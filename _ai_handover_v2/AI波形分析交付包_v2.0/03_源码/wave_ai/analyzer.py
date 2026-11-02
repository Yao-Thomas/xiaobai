"""
analyzer.py —— 单帧完整分析流水线（服务层只负责 HTTP，不碰算法）

    samples(4096) + fs/dec
        ├─ 96×96×3 视觉输入 ──┐
        ├─ 59 维特征 ─────────┤→ 融合网络 → 16 类概率
        ├─ 端侧 8 类概率 ─────┘
        ├─ 原始采样 → 质量评估（方向 2）
        ├─ 嵌入 + 特征 → 未知异常检测（方向 3）
        └─ 结构化事实 → 中文一句话（≤70 字，TTS 友好）

设计要点：
  · 所有失败都变成 {"ok": false, "error": "..."}，绝不把异常抛给 HTTP 层；
  · 端侧概率是"参考输入"不是真值，缺失/不合法时自动降级（lp_available=0）；
  · 时间戳/耗时全部记录，便于验收时看"哪一步慢"。
"""
from __future__ import annotations

import os
import time

import numpy as np
import torch

from . import config, explain
from .anomaly import Detector, load_stats
from .config import CAP_LEN, CLASSES, CN, ENGINE, N_CLASSES, VERSION
from .features import FEATURE_NAMES, extract_features
from .model import WaveFusionNet
from .quality import analyze_quality
from .representation import to_images, to_model_input

_EPS = 1e-9


class InputError(ValueError):
    pass


def _as_int_samples(samples):
    """校验并规范化 samples（4096 点、0~1023、int）"""
    if samples is None:
        raise InputError("缺少 samples 字段")
    a = np.asarray(samples)
    if a.ndim != 1:
        raise InputError("samples 必须是一维数组")
    if a.size != CAP_LEN:
        raise InputError("samples 长度必须为 %d，收到 %d" % (CAP_LEN, a.size))
    if not np.all(np.isfinite(a.astype(np.float64))):
        raise InputError("samples 含 NaN/Inf")
    lo, hi = float(a.min()), float(a.max())
    if hi < 0 or lo > 1023:
        raise InputError("samples 超出 10 bit 范围（0~1023），收到 [%g, %g]" % (lo, hi))
    clipped = bool(lo < 0 or hi > 1023)
    return np.clip(np.rint(a.astype(np.float64)), 0, 1023).astype(np.uint16), clipped


def _parse_local_cnn(local):
    """把端侧 8 类结果映射到本模型的 16 类顺序（缺的补 0）"""
    if not isinstance(local, dict):
        return None, None
    classes = local.get("classes")
    probs = local.get("probs")
    if not isinstance(probs, (list, tuple)) or len(probs) == 0:
        return None, None
    p = np.asarray(probs, dtype=np.float64).reshape(-1)
    if classes is None or len(classes) != len(p):
        classes = config.CLASSES_8 if len(p) == 8 else CLASSES[:len(p)]
    out = np.zeros(N_CLASSES, dtype=np.float64)
    for name, v in zip(classes, p):
        if name in CLASSES:
            out[CLASSES.index(name)] = max(0.0, float(np.nan_to_num(v, nan=0.0)))
    s = out.sum()
    if s > 0:
        out /= s
    label = local.get("label")
    conf = local.get("confidence")
    return out, {"label": label, "confidence": float(conf or (out.max() if s > 0 else 0.0))}


class Analyzer:
    def __init__(self, bundle_path, anomaly_stats_path=None, threads=4):
        t0 = time.time()
        if not os.path.exists(bundle_path):
            raise FileNotFoundError("模型文件不存在: %s" % bundle_path)
        bundle = torch.load(bundle_path, map_location="cpu", weights_only=False)
        self.classes = list(bundle.get("classes") or CLASSES)
        self.n_classes = len(self.classes)
        self.mean = np.asarray(bundle["feat_mean"], dtype=np.float32)
        self.std = np.asarray(bundle["feat_std"], dtype=np.float32)
        self.temperature = float(bundle.get("temperature", 1.0) or 1.0)
        self.model = WaveFusionNet(n_classes=self.n_classes)
        self.model.load_state_dict(bundle["state_dict"])
        self.model.eval()
        try:
            torch.set_num_threads(int(threads))
        except Exception:
            pass
        self.bundle = bundle
        self.anomaly = Detector()
        self.anomaly_stats_path = anomaly_stats_path
        if anomaly_stats_path and os.path.exists(anomaly_stats_path):
            self.anomaly = Detector(load_stats(anomaly_stats_path))
        self.load_s = round((time.time() - t0) * 1000, 1)
        self._warmup()

    # -----------------------------------------------------------------
    def _warmup(self):
        """预热**整条 analyze 流水线**（不只是推理）。

        ★ 只预热 infer 的话，第一次真实请求还要现加载 scipy 的 welch/lstsq 路径，
          实测冷启动单帧 495 ms（预算 800 ms，很险）；预热完整链路后首帧 ~40 ms。
        """
        rng = np.random.default_rng(0)
        t = np.arange(CAP_LEN) / float(CAP_LEN)
        frames = []
        frames.append(511.5 + 300 * np.sin(2 * np.pi * 4 * t))
        frames.append(511.5 + 300 * np.where(np.mod(4 * t, 1.0) < 0.5, 1.0, -1.0))
        frames.append(np.full(CAP_LEN, 511.5))
        for f in frames:
            try:
                self.analyze({"samples": np.clip(np.rint(f), 0, 1023).astype(int).tolist(),
                              "fs": 20000000, "dec": 10,
                              "options": {"want_quality": True, "want_anomaly": True}})
            except Exception:
                pass

    # -----------------------------------------------------------------
    @torch.inference_mode()
    def infer(self, raw, fs, dec, local_probs=None, want_embed=True):
        t0 = time.perf_counter()
        fs_eff = float(fs) / max(float(dec), 1.0)
        feat, info = extract_features(raw, fs_eff, local_probs)
        t1 = time.perf_counter()
        img = to_model_input(to_images(raw[None, :]))
        fn = (feat - self.mean) / self.std
        x_img = torch.from_numpy(img)
        x_feat = torch.from_numpy(fn[None, :].astype(np.float32))
        logits = self.model(x_img, x_feat)
        embed = None
        if want_embed:
            embed = self.model.embedding(x_img, x_feat)[0].numpy()
        t2 = time.perf_counter()
        z = logits[0].numpy().astype(np.float64) / max(self.temperature, 1e-6)
        z -= z.max()
        p = np.exp(z)
        p /= max(float(p.sum()), _EPS)
        label = self.classes[int(np.argmax(p))]
        return {
            "label": label,
            "probs": p,
            "confidence": float(p.max()),
            "info": info,
            "feat": feat,
            "embed": embed,
            "timing": {"features_ms": round((t1 - t0) * 1000, 2),
                       "vision_ms": round((t2 - t1) * 1000, 2)},
        }

    # -----------------------------------------------------------------
    def analyze(self, payload: dict) -> dict:
        t_all = time.perf_counter()
        try:
            return self._analyze(payload, t_all)
        except InputError as e:
            return {"ok": False, "engine": ENGINE, "error": str(e),
                    "elapsed_ms": int((time.perf_counter() - t_all) * 1000)}
        except Exception as e:  # pragma: no cover - 兜底
            return {"ok": False, "engine": ENGINE,
                    "error": "%s: %s" % (type(e).__name__, str(e)[:180]),
                    "elapsed_ms": int((time.perf_counter() - t_all) * 1000)}

    def _analyze(self, payload, t_all):
        opts = payload.get("options") or {}
        max_chars = int(opts.get("max_chars") or 70)
        for_voice = bool(opts.get("for_voice", True))
        want_q = bool(opts.get("want_quality", True))
        want_a = bool(opts.get("want_anomaly", True))
        lang = opts.get("language") or "zh-CN"

        raw, clipped = _as_int_samples(payload.get("samples"))
        fs = float(payload.get("fs") or config.FS_BASE)
        dec = int(payload.get("dec") or 10)
        if dec < 1 or dec > 4096:
            raise InputError("dec 必须在 1~4096 之间")

        lp, local_meta = _parse_local_cnn(payload.get("local_cnn") or payload.get("hint"))
        out = self.infer(raw, fs, dec, lp)

        q = {}
        if want_q:
            tq = time.perf_counter()
            q = analyze_quality(raw, dec=dec, fs_base=fs, label=out["label"])
            q.pop("harmonics", None)
            q["eval_ms"] = round((time.perf_counter() - tq) * 1000, 2)
        else:
            q = {"applicable": False, "skipped": True, "score": None,
                 "notes": ["未请求质量评估"]}

        fd = {n: float(v) for n, v in zip(FEATURE_NAMES, out["feat"].tolist())}
        if want_a:
            an = self.anomaly.detect(out["embed"], out["probs"], out["label"],
                                     fd, q, out["info"])
        else:
            an = {"is_anomaly": False, "score": None, "features": [],
                  "suggestion": "", "skipped": True}

        tt = time.perf_counter()
        # 用质量模块的精确占空比覆盖特征里的"整窗占比"（后者在非整数周期下有偏）
        if want_q and q.get("duty_pct") is not None:
            out["info"]["duty_pct"] = float(q["duty_pct"])
        txt = explain.make_text(out["label"], CN.get(out["label"], out["label"]),
                                out["confidence"], out["info"], q, an,
                                max_chars=max_chars, for_voice=for_voice,
                                want_quality=want_q)
        text_ms = round((time.perf_counter() - tt) * 1000, 2)

        probs = [round(float(v), 6) for v in out["probs"]]
        fusion = self._fusion(local_meta, out["label"], out["confidence"])
        notes = []
        if clipped:
            notes.append("输入有超出 0~1023 的采样，已按 10 bit 限幅")
        if local_meta and not fusion["agree"]:
            notes.append("端侧判为 %s，多模态判为 %s，以多模态为准"
                         % (local_meta.get("label"), out["label"]))
        if q.get("period_source") == "spectrum":
            notes.append("周期由谱峰估计（过零点不足），时间类指标精度略降")

        elapsed = int(round((time.perf_counter() - t_all) * 1000))
        resp = {
            "ok": True,
            "engine": ENGINE,
            "elapsed_ms": elapsed,
            "label": out["label"],
            "label_cn": CN.get(out["label"], out["label"]),
            "confidence": round(out["confidence"], 6),
            "classes": list(self.classes),
            "probs": probs,
            "text": txt["text"],
            "quality": self._quality_contract(q),
            "anomaly": {
                "is_anomaly": bool(an.get("is_anomaly")),
                "score": an.get("score"),
                "features": an.get("features") or [],
                "suggestion": an.get("suggestion") or "",
                "reason": an.get("reason") or "",
            },
            "extra": {
                "version": VERSION,
                "text_source": txt["source"],
                "text_chars": txt["chars"],
                "tts_ready": txt["tts_ready"],
                "language": lang,
                "fusion": fusion,
                "measurements": out["info"],
                "timing": dict(out["timing"], text_ms=text_ms,
                               total_ms=elapsed),
                "quality_detail": {
                    "coverage": q.get("coverage"),
                    "components": q.get("components"),
                    "period_source": q.get("period_source"),
                    "period_cycles": q.get("period_cycles"),
                    "shape_fidelity": q.get("shape_fidelity"),
                    "rail_frac": q.get("rail_frac"),
                    "flat_frac": q.get("flat_frac"),
                    "fs_eff_hz": q.get("fs_eff_hz"),
                    "n_periods": q.get("n_periods"),
                },
                "anomaly_detail": an.get("details") or [],
                "anomaly_distance": an.get("distance"),
                "notes": "；".join(notes),
            },
        }
        return resp

    # -----------------------------------------------------------------
    def _fusion(self, local_meta, label, conf):
        if not local_meta:
            return {"local_cnn": None,
                    "vision_model": {"label": label, "confidence": round(conf, 6)},
                    "agree": None, "final_source": "multimodal_v1"}
        agree = bool(local_meta.get("label") == label)
        return {
            "local_cnn": {"label": local_meta.get("label"),
                          "confidence": round(float(local_meta.get("confidence") or 0), 6)},
            "vision_model": {"label": label, "confidence": round(conf, 6)},
            "agree": agree,
            "final_source": "multimodal_v1",
            "weight_local": 0.4 if agree else 0.0,
            "weight_vision": 0.6 if agree else 1.0,
        }

    @staticmethod
    def _quality_contract(q):
        """只暴露契约 §3.1 的字段 + 必要的解释字段，保证 JSON 干净"""
        keys = ("score", "rise_us", "fall_us", "overshoot_pct", "undershoot_pct",
                "snr_db", "jitter_ns", "thd_pct", "duty_stability_pct")
        out = {k: (None if q.get(k) is None else
                   (int(round(q[k])) if k == "score" else round(float(q[k]), 3)))
               for k in keys}
        out["applicable"] = bool(q.get("applicable", True))
        out["coverage"] = q.get("coverage")
        out["notes"] = q.get("notes") or []
        return out

    # -----------------------------------------------------------------
    def classify(self, payload: dict) -> dict:
        """契约 §2.3：只要视觉模型结果"""
        t0 = time.perf_counter()
        try:
            raw, clipped = _as_int_samples(payload.get("samples"))
            fs = float(payload.get("fs") or config.FS_BASE)
            dec = int(payload.get("dec") or 10)
            lp, local_meta = _parse_local_cnn(payload.get("hint")
                                              or payload.get("local_cnn"))
            out = self.infer(raw, fs, dec, lp, want_embed=False)
            q = analyze_quality(raw, dec=dec, fs_base=fs, label=out["label"])
            txt = explain.make_text(out["label"], CN.get(out["label"], out["label"]),
                                    out["confidence"], out["info"], q,
                                    {"is_anomaly": False, "features": []})
            return {
                "ok": True,
                "engine": config.ENGINE_VISION,
                "elapsed_ms": int(round((time.perf_counter() - t0) * 1000)),
                "label": out["label"],
                "label_cn": CN.get(out["label"], out["label"]),
                "confidence": round(out["confidence"], 6),
                "classes": list(self.classes),
                "probs": [round(float(v), 6) for v in out["probs"]],
                "extra": {
                    "notes": txt["text"],
                    "measurements": out["info"],
                    "quality_score": q.get("score"),
                    "clipped_input": clipped,
                    "local_cnn": local_meta,
                    "timing": out["timing"],
                },
            }
        except InputError as e:
            return {"ok": False, "engine": config.ENGINE_VISION, "error": str(e)}
        except Exception as e:  # pragma: no cover
            return {"ok": False, "engine": config.ENGINE_VISION,
                    "error": "%s: %s" % (type(e).__name__, str(e)[:180])}

    def explain(self, payload: dict) -> dict:
        t0 = time.perf_counter()
        try:
            style = payload.get("style") or {}
            r = payload.get("result")
            if not isinstance(r, dict):
                raise InputError("缺少 result 字段（融合结果 R）")
            t = explain.explain_result(payload, style)
            return {"ok": True, "engine": config.ENGINE_LLM,
                    "elapsed_ms": int(round((time.perf_counter() - t0) * 1000)),
                    "text": t["text"], "confidence": t["confidence"],
                    "tts_ready": True,
                    "extra": {"chars": t["chars"], "source": t["source"]}}
        except InputError as e:
            return {"ok": False, "engine": config.ENGINE_LLM, "error": str(e)}
        except Exception as e:  # pragma: no cover
            return {"ok": False, "engine": config.ENGINE_LLM,
                    "error": "%s: %s" % (type(e).__name__, str(e)[:180])}

    # -----------------------------------------------------------------
    def health(self):
        return {
            "ok": True,
            "engine": ENGINE,
            "version": VERSION,
            "classes": list(self.classes),
            "n_classes": self.n_classes,
            "input": "samples",
            "input_shape": [CAP_LEN],
            "input_dtype": "uint16 0~1023",
            "img_shape": [3, 96, 96],
            "feat_dim": int(self.mean.size),
            "temperature": self.temperature,
            "metrics": self.bundle.get("metrics", {}),
            "anomaly": bool(self.anomaly.stats),
            "load_ms": self.load_s,
            "endpoints": ["/health", "/waveform/analyze", "/waveform/classify",
                          "/waveform/explain"],
        }
