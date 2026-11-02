# -*- coding: utf-8 -*-
"""
model_backend.py —— 模型后端抽象 + 量化模型加载器 + 占位回退实现

职责：
    1. 把 /infer 请求里的 data 解释成 28×28 int8 图像
       （raw 4096 采样 vs 784 像素，用 hint / data 长度自动判别）
    2. 若 deliverables/quantized_model/ 存在 -> 加载 int8 权重跑【纯 numpy 整数前向】
       （与 qmodel.reference_infer_arrays 逐位一致，不依赖 torch）
    3. 若不存在 -> 用内置启发式分类器（简单统计特征），保证 API 永远能跑

★ 本模块无第三方依赖（numpy + 标准库），可在没有 fastapi/torch 的机器上单测。
★ 预处理复用冻结契约 src/common/preprocess.py（禁止修改），import 失败会优雅降级。
"""
import json
import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))      # .../src/serve
for _p in (_HERE, os.path.dirname(_HERE)):               # 把 serve 和 src 都放进 sys.path
    if _p not in sys.path:
        sys.path.insert(0, _p)

import numpy as np

# 让 Windows 控制台（cp1252 等非 UTF-8 编码）也能输出中文日志，避免 UnicodeEncodeError；
# Linux 上 stdout/stderr 本来就是 utf-8，这里是无害的 no-op。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

import config

RAW_LEN = 4096            # 一次采集的样本数（示波器固定）
IMG = 28                  # 图像边长（与 PL 加速器几何对齐）
PIX_LEN = IMG * IMG       # 784


# ===========================================================================
# 输入解释：data -> 28×28 图像
# ===========================================================================
def _load_preprocess():
    """懒加载冻结契约 src/common/preprocess.py；失败返回 (None, 原因)。"""
    try:
        from common import preprocess as pp  # noqa: E402
        return pp, None
    except Exception as e:  # noqa: BLE001
        return None, str(e)


def _safe_array(data):
    try:
        return np.asarray(data, dtype=np.float64)
    except Exception:  # noqa: BLE001
        return None


def interpret_input(data, hint=None, mode=None):
    """把请求 data 解释成 28×28 图像。

    判别规则（hint 优先，其次 data 长度）：
        · 长度 4096 -> 原始采样（0~255），经 preprocess 变 28×28
        · 长度 784  -> 已经是 28×28 像素（int8 或 uint8），直接推理
    返回 {"ok", "form", "image_u8", "image_int8", "samples", "note", "dtype_note", "mode"}
    或 {"ok": False, "error"}。
    """
    mode = mode or config.PREPROCESS_MODE
    arr = _safe_array(data)
    if arr is None:
        return {"ok": False, "error": "data 无法解析为数组"}

    n = arr.size
    hint = (hint or "").strip().lower() if isinstance(hint, str) else ""

    want_raw = any(k in hint for k in ("raw", "4096", "samples", "sample", "采样"))
    want_pix = any(k in hint for k in ("image", "784", "pixel", "像素"))

    # 判定形态：hint 优先，长度其次
    if n == PIX_LEN and not want_raw:
        form = "image"
    elif n == RAW_LEN and not want_pix:
        form = "raw"
    elif want_raw:
        form = "raw"
    elif want_pix:
        form = "image"
    else:
        return {"ok": False,
                "error": "无法判定 data 形态：长度=%d（期望 4096=原始采样 或 784=28×28 图像），hint=%r" % (n, hint)}

    if form == "raw":
        if n != RAW_LEN:
            return {"ok": False, "error": "raw 形态要求 4096 个样本，实际 %d" % n}
        pp, err = _load_preprocess()
        if pp is None:
            return {"ok": False,
                    "error": "预处理模块 src/common/preprocess.py 加载失败: %s" % err}
        try:
            img_u8 = np.asarray(pp.capture_to_image(arr.tolist(), mode), dtype=np.uint8)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": "预处理失败(mode=%s): %s" % (mode, e)}
        img_i8 = (img_u8.astype(np.int16) - 128).astype(np.int8)
        return {"ok": True, "form": "raw", "image_u8": img_u8, "image_int8": img_i8,
                "samples": arr, "note": "raw_4096_samples -> %s 28x28" % mode,
                "dtype_note": "uint8 -> int8(u8-128)", "mode": mode}

    # form == "image"
    if n != PIX_LEN:
        return {"ok": False, "error": "image 形态要求 784 个像素，实际 %d" % n}
    a = arr.reshape(IMG, IMG)
    if a.min() < 0:
        # 已含负值 -> 认为已是 int8（-128..127）
        img_i8 = np.clip(np.rint(a), -128, 127).astype(np.int8)
        img_u8 = np.clip(np.rint(a) + 128, 0, 255).astype(np.uint8)
        dtype_note = "int8(直接使用)"
    else:
        # 0..255 -> uint8，按唯一变换 int8 = u8 - 128
        img_u8 = np.clip(np.rint(a), 0, 255).astype(np.uint8)
        img_i8 = (img_u8.astype(np.int16) - 128).astype(np.int8)
        dtype_note = "uint8 -> int8(u8-128)"
    return {"ok": True, "form": "image", "image_u8": img_u8, "image_int8": img_i8,
            "samples": None, "note": "image_784_pixels (直接推理)",
            "dtype_note": dtype_note, "mode": mode}


# ===========================================================================
# ★ 纯 numpy 整数前向（与 qmodel.reference_infer_arrays 逐位一致）
# ===========================================================================
def _im2col_conv_int8(x_q, w_q):
    """x_q:(IC,H,W) int32 ; w_q:(OC,IC,K,K) int32 -> acc:(OC,OH,OW) int64"""
    IC, H, W = x_q.shape
    OC, IC2, K, _ = w_q.shape
    if IC != IC2:
        raise ValueError("通道不匹配 %r vs %r" % (IC, IC2))
    OH, OW = H - K + 1, W - K + 1
    acc = np.zeros((OC, OH, OW), dtype=np.int64)
    for ky in range(K):
        for kx in range(K):
            patch = x_q[:, ky:ky + OH, kx:kx + OW].astype(np.int64)
            wk = w_q[:, :, ky, kx].astype(np.int64)
            acc += np.tensordot(wk, patch, axes=(1, 0))
    return acc


def _wrap_int32(v):
    """模拟 HLS ap_int<32> 回绕（与 qmodel.wrap_int32 一致）"""
    v = np.asarray(v, dtype=np.int64)
    return ((v + (1 << 31)) & np.int64(0xFFFFFFFF)) - (1 << 31)


def _requant_shift(acc, mfq, relu):
    """out = (acc * MFQ) >> 16，卷积后 ReLU+饱和到 [0,127]，FC 饱和到 [-128,127]"""
    prod = _wrap_int32(acc.astype(np.int64) * int(mfq))
    q = prod >> 16
    lo, hi = (0, 127) if relu else (-128, 127)
    np.clip(q, lo, hi, out=q)
    return q.astype(np.int32)


def _maxpool2(f):
    OC, H, W = f.shape
    OH, OW = H // 2, W // 2
    v = f[:, :OH * 2, :OW * 2].reshape(OC, OH, 2, OW, 2)
    return v.max(axis=(2, 4))


# ===========================================================================
# 后端抽象
# ===========================================================================
class ModelBackend:
    """模型后端抽象基类。predict(data, hint) -> 契约响应 dict。"""
    name = "abstract"

    def predict(self, data, hint=None):
        raise NotImplementedError


# ===========================================================================
# 量化模型加载器（真实交付物）
# ===========================================================================
class QuantizedWaveformBackend(ModelBackend):
    name = "quantized"

    def __init__(self, model_dir=None):
        self.model_dir = model_dir or config.MODEL_DIR
        self.spec = None
        self.classes = list(config.CLASSES)
        self.mfq = None
        self.w1 = self.w2 = self.wf = None
        self._load()

    # ------------------------------------------------------------------
    def _load(self):
        spec_path = os.path.join(self.model_dir, "model_spec.json")
        weights_path = os.path.join(self.model_dir, "weights.bin")
        if not (os.path.isfile(spec_path) and os.path.isfile(weights_path)):
            raise FileNotFoundError("量化模型不存在: %s" % self.model_dir)

        with open(spec_path, encoding="utf-8") as f:
            self.spec = json.load(f)

        self.classes = list(self.spec.get("classes") or config.CLASSES)

        requant = self.spec.get("requant", {})
        mpl = requant.get("MFQ_per_layer")
        if mpl:
            self.mfq = [int(mpl["conv1"]), int(mpl["conv2"]), int(mpl["fc"])]
        else:
            m = int(requant.get("MFQ", 119))
            self.mfq = [m, m, m]

        blob = np.fromfile(weights_path, dtype=np.uint8)
        entries = (self.spec.get("weights_layout", {}) or {}).get("entries") or []
        by_name = {e["name"]: e for e in entries}
        if by_name:
            def grab(name):
                e = by_name[name]
                off, nb = int(e["offset"]), int(e["bytes"])
                return blob[off:off + nb].astype(np.int8).reshape(tuple(e["shape"]))
            self.w1 = grab("conv1.weight")
            self.w2 = grab("conv2.weight")
            self.wf = grab("fc.weight")
        else:
            # 缺省回退布局（顺序 conv1 -> conv2 -> fc，128 字节对齐）
            self.w1, self.w2, self.wf = self._fallback_weights(blob)

    @staticmethod
    def _fallback_weights(blob):
        parts = []
        off = 0
        for name, nbytes in (("conv1.weight", 72), ("conv2.weight", 1152),
                             ("fc.weight", 9 * 400)):
            off = (off + 63) // 64 * 64
            off = (off + 127) // 128 * 128
            parts.append(blob[off:off + nbytes].astype(np.int8))
            off += nbytes
        return (parts[0].reshape(8, 1, 3, 3), parts[1].reshape(16, 8, 3, 3),
                parts[2].reshape(9, 400))

    # ------------------------------------------------------------------
    def _infer_int8(self, img_i8):
        x_q = np.asarray(img_i8, dtype=np.int32).reshape(IMG, IMG)
        a1 = _im2col_conv_int8(x_q[None, :, :], self.w1)
        q1 = _requant_shift(a1, self.mfq[0], relu=True)
        p1 = _maxpool2(q1)
        a2 = _im2col_conv_int8(p1, self.w2)
        q2 = _requant_shift(a2, self.mfq[1], relu=True)
        p2 = _maxpool2(q2)
        xf = p2.reshape(-1).astype(np.int64)
        acc = np.asarray(self.wf, dtype=np.int64) @ xf
        logits = _requant_shift(acc, self.mfq[2], relu=False)
        return logits.astype(np.int32)

    # ------------------------------------------------------------------
    def predict(self, data, hint=None):
        interp = interpret_input(data, hint)
        if not interp.get("ok"):
            return {"ok": False, "error": interp.get("error")}
        try:
            logits = self._infer_int8(interp["image_int8"])
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": "量化模型前向失败: %s" % e}
        return _logits_to_result(logits, self.classes, self.name, interp)


# ===========================================================================
# 启发式占位回退（无交付模型时兜底，保证 API 始终能跑）
# ===========================================================================
class HeuristicWaveformBackend(ModelBackend):
    name = "heuristic"

    def predict(self, data, hint=None):
        arr = _safe_array(data)
        if arr is None:
            return {"ok": False, "error": "data 无法解析为数组"}
        # 原始 4096 采样：直接用时域统计特征，不依赖预处理模块
        if arr.size == RAW_LEN:
            label, conf, reason = _heuristic_from_samples(arr)
            detail = {
                "interpretation": "raw_4096_samples (时域统计特征)",
                "model_source": self.name,
                "reason": reason,
            }
            return {"ok": True, "label": label, "confidence": conf,
                    "detail": detail}
        # 其它：解释成图像再用图像统计特征
        interp = interpret_input(data, hint)
        if not interp.get("ok"):
            return {"ok": False, "error": interp.get("error")}
        label, conf, reason = _heuristic_from_image(interp["image_u8"])
        detail = {
            "interpretation": interp.get("note"),
            "dtype_note": interp.get("dtype_note"),
            "model_source": self.name,
            "reason": reason,
        }
        return {"ok": True, "label": label, "confidence": conf, "detail": detail}


# ===========================================================================
# chat 占位后端（模型① LLM 由本地 agent 负责，云端仅保留接口占位）
# ===========================================================================
class ChatBackend(ModelBackend):
    name = "chat_stub"

    def predict(self, data, hint=None):
        return {"ok": False,
                "error": "chat 推理后端未接入：模型①（本地 agent LLM）由本地 agent 负责，"
                         "云端仅保留接口占位；可在此接入 LLM/RAG 后返回正常结果"}


# ===========================================================================
# 工具函数
# ===========================================================================
def _logits_to_result(logits, classes, source, interp):
    """int logits -> softmax 置信度 + 契约响应。"""
    z = np.asarray(logits, dtype=np.float64)
    z = z - float(z.max())                     # 稳定性
    e = np.exp(z)
    probs = e / float(e.sum())
    idx = int(np.argmax(probs))
    label = classes[idx] if 0 <= idx < len(classes) else "unknown"
    confidence = float(probs[idx])
    detail = {
        "interpretation": interp.get("note"),
        "dtype_note": interp.get("dtype_note"),
        "preprocess_mode": interp.get("mode"),
        "model_source": source,
        "logits": [int(v) for v in np.asarray(logits)],
        "class_index": idx,
    }
    return {"ok": True, "label": label, "confidence": confidence, "detail": detail}


def _heuristic_from_samples(s):
    """4096 采样 -> (label, confidence, reason)。置信度故意压到 <0.7，触发云端复核。"""
    s = np.asarray(s, dtype=np.float64)
    mean = float(s.mean())
    std = float(s.std())
    vpp = float(s.max() - s.min())

    if std < 3.0:
        return "signal_loss", 0.90, "信号近乎平线（std=%.2f LSB）" % std

    top_frac = float((s >= 254).mean())
    bot_frac = float((s <= 1).mean())
    if top_frac > 0.05 or bot_frac > 0.05:
        return "clipping", 0.80, "顶部/底部饱和占比高（top=%.3f, bot=%.3f）" % (top_frac, bot_frac)

    zc = int(np.abs(np.diff(np.sign(s - mean))).sum()) // 2
    zcr = zc / float(len(s))
    if zcr > 0.30:
        return "noise", 0.65, "过零率极高(%.2f)，无明显周期结构" % zcr

    duty = float((s > mean).mean())
    span = max(1.0, vpp)
    near_top = float((s > mean + 0.45 * span).mean())
    near_bot = float((s < mean - 0.45 * span).mean())
    flat = near_top + near_bot

    if duty < 0.30 or duty > 0.70:
        return "duty_abnormal", 0.55, "占空比偏离 50%%（duty=%.2f）" % duty
    if flat > 0.55:
        return "square", 0.60, "平顶/平底占比高(%.2f)，疑似方波" % flat
    if duty < 0.44 or duty > 0.56:
        return "sawtooth", 0.55, "占空比轻微偏移(%.2f)，疑似锯齿" % duty

    mid_frac = float((np.abs(s - mean) < 0.25 * span).mean())
    if mid_frac > 0.30:
        return "sine", 0.55, "中间幅度占比高(%.2f)，疑似正弦" % mid_frac
    return "triangle", 0.55, "默认三角（幅度分布较均匀）"


def _heuristic_from_image(img_u8):
    """图像形态下的粗判（幅度行熵：均匀 -> 噪声，单带 -> 丢信号）。"""
    img = np.asarray(img_u8, dtype=np.float64)
    if img.size == 0 or float(img.max()) <= 0.0:
        return "signal_loss", 0.85, "图像近乎空白"
    rowsum = img.mean(axis=1)
    total = float(rowsum.sum()) + 1e-6
    p = rowsum / total
    entropy = -float((p * np.log(p + 1e-9)).sum())
    uniformity = entropy / math.log(IMG)
    if uniformity > 0.85:
        return "noise", 0.60, "幅度分布接近均匀(%.2f)，疑似噪声" % uniformity
    return "sine", 0.50, "图像形态下启发式仅作粗判，建议送云端复核"


# ===========================================================================
# 后端工厂 + 云端推理统一入口
# ===========================================================================
_WAVEFORM_BACKEND = None


def build_waveform_backend(model_dir=None):
    """优先加载量化模型；失败则回退到启发式占位分类器（不抛异常）。"""
    try:
        return QuantizedWaveformBackend(model_dir)
    except Exception as e:  # noqa: BLE001
        print("[model_backend] 量化模型不可用(%s)，回退到启发式占位分类器" % e,
              file=sys.stderr)
        return HeuristicWaveformBackend()


def get_backend(type_):
    """按请求类型返回后端实例（waveform 用单例，chat 用占位）。"""
    global _WAVEFORM_BACKEND
    if type_ == "waveform":
        if _WAVEFORM_BACKEND is None:
            _WAVEFORM_BACKEND = build_waveform_backend()
        return _WAVEFORM_BACKEND
    if type_ == "chat":
        return ChatBackend()
    return None


def run_cloud_inference(request):
    """云端 /infer 的核心：按 type 选后端并推理，返回契约响应（不含 elapsed_ms）。

    由 api.py 补 elapsed_ms；板端 router 的 cloud_predict 经 HTTP 调用本逻辑。
    """
    if not isinstance(request, dict):
        return {"ok": False, "error": "请求必须是 JSON 对象"}
    type_ = request.get("type")
    data = request.get("data")
    hint = request.get("hint")
    backend = get_backend(type_)
    if backend is None:
        return {"ok": False, "error": "未知请求类型 %r（支持 waveform/chat）" % type_}
    return backend.predict(data, hint)
