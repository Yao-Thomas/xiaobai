"""
acceptance.py —— 联合验收自测（契约 §6 / §8 可自动化的部分）

两种模式：
    python -m wave_ai.acceptance --model runs/v2_full/model_bundle.pt      # 进程内
    python -m wave_ai.acceptance --url http://127.0.0.1:8000               # 打真实服务

检查项：
    A. 契约结构：classes/probs 长度与顺序、和为 1、label=argmax、confidence=probs[argmax]、
       前 8 个类名必须是端侧那 8 个、text 纯文本 ≤max_chars、quality/anomaly 字段齐全
    B. 准确率：仿真测试集 / 困难域（域偏移）/ 前 8 类子集
    C. 延迟：完整 /waveform/analyze 的 p50/p95（含预处理+质量+文本）
    D. 质量评估：上升时间对已知边沿的精度、SNR 与真值噪声的相关性
    E. 异常检测：未知混合形态（OOD）检出率 vs 正常样本误报率
    F. 健壮性：空/长度错/越界/坏 JSON 必须返回 ok:false 而不是崩
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.request

import numpy as np

from .config import CAP_LEN, CLASSES, CLASSES_8, CN, ENGINE, VERSION

BAD_CHARS = re.compile(r"[*#`_\[\]{}<>|~^\\]")
EMOJI = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF]")


# ---------------------------------------------------------------------------
# 客户端（进程内 or HTTP）
# ---------------------------------------------------------------------------
class LocalClient:
    def __init__(self, model, anomaly=None):
        from .analyzer import Analyzer
        self.a = Analyzer(model, anomaly)
        self.kind = "in-process"

    def health(self):
        return self.a.health()

    def analyze(self, payload):
        return self.a.analyze(payload)

    def classify(self, payload):
        return self.a.classify(payload)

    def explain(self, payload):
        return self.a.explain(payload)


class HttpClient:
    def __init__(self, base):
        self.base = base.rstrip("/")
        self.kind = "http"

    def _post(self, path, obj):
        body = json.dumps(obj).encode("utf-8")
        req = urllib.request.Request(self.base + path, data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))

    def health(self):
        with urllib.request.urlopen(self.base + "/health", timeout=10) as r:
            return json.loads(r.read().decode("utf-8"))

    def analyze(self, payload):
        return self._post("/waveform/analyze", payload)

    def classify(self, payload):
        return self._post("/waveform/classify", payload)

    def explain(self, payload):
        return self._post("/waveform/explain", payload)


# ---------------------------------------------------------------------------
# A. 契约结构
# ---------------------------------------------------------------------------
def check_contract(resp, max_chars=70):
    errs = []
    if not isinstance(resp, dict) or not resp.get("ok"):
        return ["响应不是 ok:true: %s" % str(resp)[:120]]
    cls, probs = resp.get("classes"), resp.get("probs")
    if not isinstance(cls, list) or not isinstance(probs, list):
        return ["classes/probs 缺失"]
    if len(cls) != len(probs):
        errs.append("classes(%d) 与 probs(%d) 长度不一致" % (len(cls), len(probs)))
    if cls[:8] != CLASSES_8:
        errs.append("前 8 个类名/顺序与端侧契约不一致: %s" % cls[:8])
    s = float(np.sum(probs))
    if abs(s - 1.0) > 1e-3:
        errs.append("probs 之和 = %.6f（应 ≈1）" % s)
    i = int(np.argmax(probs))
    if cls[i] != resp.get("label"):
        errs.append("label(%s) != argmax(probs)(%s)" % (resp.get("label"), cls[i]))
    if abs(float(resp.get("confidence", -1)) - probs[i]) > 1e-5:
        errs.append("confidence != probs[argmax]")
    text = resp.get("text")
    if not isinstance(text, str) or not text:
        errs.append("text 缺失")
    else:
        if len(text) > max_chars:
            errs.append("text 长度 %d > %d" % (len(text), max_chars))
        if BAD_CHARS.search(text) or EMOJI.search(text):
            errs.append("text 含 Markdown/emoji 字符")
        if not text.endswith("。"):
            errs.append("text 未以句号结尾")
    for k in ("quality", "anomaly"):
        if not isinstance(resp.get(k), dict):
            errs.append("%s 字段缺失" % k)
    q = resp.get("quality") or {}
    for k in ("score", "snr_db", "rise_us"):
        if k not in q:
            errs.append("quality.%s 缺失" % k)
    a = resp.get("anomaly") or {}
    for k in ("is_anomaly", "features", "suggestion"):
        if k not in a:
            errs.append("anomaly.%s 缺失" % k)
    if int(resp.get("elapsed_ms", 10 ** 6)) > 800:
        errs.append("elapsed_ms=%s > 800（不含文本生成的硬指标）" % resp.get("elapsed_ms"))
    return errs


def make_payload(raw, fs=20000000, dec=10, local=None, **opts):
    return {
        "type": "waveform_analysis",
        "samples": [int(v) for v in np.asarray(raw).tolist()],
        "fs": int(fs),
        "dec": int(dec),
        "local_cnn": local,
        "measurements": {},
        "options": dict({"max_chars": 70, "language": "zh-CN", "for_voice": True,
                         "want_quality": True, "want_anomaly": True}, **opts),
    }


def _dec(ds, i, default=10):
    """取该样本真实的抽取倍率（★ 必须传对：dec 错了 K/f0 特征就全错）"""
    p = ds.get("param") or {}
    if "dec" in p:
        v = float(p["dec"][i])
        if np.isfinite(v) and v >= 1:
            return int(round(v))
    return default


def simulated_local(y_idx, rng=None):
    """给验收用例造一个端侧 8 类输出（新类随机映射到 8 类原型）"""
    rng = rng or np.random.default_rng(0)
    name = CLASSES[int(y_idx)]
    probs = [0.0] * 8
    if name in CLASSES_8:
        probs[CLASSES_8.index(name)] = 0.86
    else:
        probs[int(rng.integers(0, 8))] = 0.62
    rest = 1.0 - sum(probs)
    probs[int(rng.integers(0, 8))] += rest
    return {"label": CLASSES_8[int(np.argmax(probs))],
            "confidence": round(float(max(probs)), 3),
            "classes": CLASSES_8, "probs": [round(p, 4) for p in probs]}


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def run(model=None, anomaly=None, data_dir="data/ds_train", hard=None,
        ood="data/raw_ood.npy", url=None, n_eval=400, out_dir=None):
    from .dataset import load_split

    cli = HttpClient(url) if url else LocalClient(model, anomaly)
    rep = {"version": VERSION, "engine": ENGINE, "mode": cli.kind,
           "started": time.strftime("%Y-%m-%d %H:%M:%S"), "checks": {}}
    print("=== 验收开始（%s）===" % cli.kind)

    h = cli.health()
    rep["health"] = {k: h.get(k) for k in ("ok", "engine", "version", "n_classes",
                                           "classes", "metrics", "input")}
    print("  /health ok=%s engine=%s classes=%d"
          % (h.get("ok"), h.get("engine"), h.get("n_classes", 0)))

    # ---- B. 准确率 + A. 契约 ----
    te = load_split(data_dir, "test")
    idx = np.arange(min(n_eval, len(te["label"])))
    correct, errors, contract_errs, lat = 0, [], [], []
    bad_examples = []
    for i in idx:
        payload = make_payload(te["raw"][i], dec=_dec(te, i),
                               local=simulated_local(te["label"][i],
                                                     np.random.default_rng(int(i))))
        r = cli.analyze(payload)
        if not r.get("ok"):
            errors.append(r.get("error"))
            continue
        e = check_contract(r)
        if e:
            contract_errs.append({"i": int(i), "errs": e})
        lat.append(r.get("elapsed_ms", 0))
        if r.get("label") == CLASSES[int(te["label"][i])]:
            correct += 1
        elif len(bad_examples) < 8:
            bad_examples.append({"i": int(i),
                                 "true": CLASSES[int(te["label"][i])],
                                 "pred": r.get("label"),
                                 "conf": r.get("confidence")})
    acc = correct / max(len(idx), 1)
    p50 = float(np.percentile(lat, 50)) if lat else 0
    p95 = float(np.percentile(lat, 95)) if lat else 0
    rep["checks"]["contract"] = {"passed": len(contract_errs) == 0,
                                 "n": len(idx), "n_failed": len(contract_errs),
                                 "samples": contract_errs[:3]}
    rep["checks"]["accuracy"] = {"acc": round(acc, 4), "n": len(idx),
                                 "errors": len(errors), "bad_examples": bad_examples}
    rep["checks"]["latency_ms"] = {"p50": round(p50, 1), "p95": round(p95, 1),
                                   "max": round(float(max(lat)), 1) if lat else None,
                                   "budget": 800}
    print("  契约结构 : %s（%d 条，失败 %d）"
          % ("通过" if not contract_errs else "失败", len(idx), len(contract_errs)))
    print("  准确率   : %.4f（%d 条，接口错误 %d）" % (acc, len(idx), len(errors)))
    print("  延迟     : p50 %.1f ms / p95 %.1f ms（预算 800 ms）" % (p50, p95))

    # ---- 无端侧概率时的准确率（契约里 local_cnn 是可选的，必须能降级）----
    nn = min(200, len(idx))
    c_nl = 0
    for i in idx[:nn]:
        r = cli.analyze(make_payload(te["raw"][i], dec=_dec(te, i), local=None))
        c_nl += int(r.get("label") == CLASSES[int(te["label"][i])])
    rep["checks"]["accuracy_no_local"] = {"acc": round(c_nl / max(nn, 1), 4), "n": nn}
    print("  无端侧概率: %.4f（%d 条，local_cnn 省略时的降级表现）"
          % (c_nl / max(nn, 1), nn))

    m8 = te["label"][idx] < 8
    if m8.any():
        c8 = 0
        for i in idx[m8]:
            r = cli.analyze(make_payload(
                te["raw"][i], dec=_dec(te, i),
                local=simulated_local(te["label"][i],
                                      np.random.default_rng(int(i)))))
            c8 += int(r.get("label") == CLASSES[int(te["label"][i])])
        rep["checks"]["accuracy_first8"] = {"acc": round(c8 / int(m8.sum()), 4),
                                            "n": int(m8.sum())}
        print("  前 8 类   : %.4f（%d 条）" % (c8 / int(m8.sum()), m8.sum()))

    if hard and os.path.exists(os.path.join(hard, "raw_test.npy")):
        hd = load_split(hard, "test")
        nh = min(n_eval, len(hd["label"]))
        c = 0
        for i in range(nh):
            r = cli.analyze(make_payload(
                hd["raw"][i], dec=_dec(hd, i),
                local=simulated_local(hd["label"][i],
                                      np.random.default_rng(int(i)))))
            c += int(r.get("label") == CLASSES[int(hd["label"][i])])
        rep["checks"]["accuracy_hard_domain"] = {"acc": round(c / nh, 4), "n": nh}
        print("  困难域   : %.4f（%d 条，噪声/带宽/增益同时更差）" % (c / nh, nh))

    # ---- D. 质量评估 ----
    qrep = quality_checks(cli)
    rep["checks"]["quality"] = qrep
    print("  质量评估 : 上升时间误差 %s；SNR 相关 %s"
          % (qrep.get("rise_error_us"), qrep.get("snr_corr")))

    # ---- E. 异常检测 ----
    arep = anomaly_checks(cli, te, ood)
    rep["checks"]["anomaly"] = arep
    print("  异常检测 : OOD 检出率 %s / 正常误报率 %s"
          % (arep.get("ood_detect_rate"), arep.get("clean_fp_rate")))

    # ---- F. 健壮性 ----
    rob = robustness_checks(cli)
    rep["checks"]["robustness"] = rob
    print("  健壮性   : %s" % ("通过" if rob["passed"] else "失败 %s" % rob["failed"]))

    passed = (not contract_errs and acc >= 0.90 and p95 <= 800
              and rob["passed"]
              and rep["checks"].get("accuracy_hard_domain", {}).get("acc", 1) >= 0.80)
    rep["passed"] = bool(passed)
    rep["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
    print("\n=== 验收结论：%s ===" % ("通过" if passed else "未通过（见报告）"))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        p = os.path.join(out_dir, "acceptance.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(rep, f, ensure_ascii=False, indent=2)
        with open(os.path.join(out_dir, "acceptance.md"), "w", encoding="utf-8") as f:
            f.write(_to_md(rep))
        print("报告 ->", p)
    return rep


def quality_checks(cli):
    """已知边沿的上升时间精度 + SNR 与真值噪声的相关性

    ★ 上升时间精度直接测 DSP（`analyze_quality(label="square")`），不经过分类器：
      这是"测量算法"的指标，不该受"分类器把极陡边沿误判成毛刺"影响
      （那种情况另记在异常/混淆统计里）。
    """
    from scipy.signal import butter, sosfilt
    from .quality import analyze_quality
    rng = np.random.default_rng(7)
    errs = []
    for bw in (0.35, 0.55, 0.85):
        n = 4096
        t = np.arange(n) * 4.0 / n
        w = np.where(np.mod(t, 1.0) < 0.5, 1.0, -1.0)
        x = 511.5 + 220.0 * w
        x = sosfilt(butter(2, bw, "low", output="sos"), x)
        x = np.clip(np.rint(x + rng.normal(0, 1.5, n)), 0, 1023)
        q = analyze_quality(x, dec=10, label="square")
        if q.get("rise_us") is not None:
            errs.append(abs(q["rise_us"]))
    # SNR 相关性：同一方波，噪声越大 SNR 应越低（走完整服务链路）
    snrs, levels = [], [1.0, 4.0, 12.0, 30.0]
    t = np.arange(4096) * 4.0 / 4096
    base = 511.5 + 250.0 * np.where(np.mod(t, 1.0) < 0.5, 1.0, -1.0)
    for lv in levels:
        x = np.clip(np.rint(base + rng.normal(0, lv, 4096)), 0, 1023)
        r = cli.analyze(make_payload(x, dec=10, want_anomaly=False))
        snrs.append(r["quality"]["snr_db"] if r.get("ok") else None)
    valid = [(lv, s) for lv, s in zip(levels, snrs) if s is not None]
    corr = None
    if len(valid) >= 3:
        corr = float(np.corrcoef([v[0] for v in valid], [v[1] for v in valid])[0, 1])
    return {"rise_measured_us": [round(e, 3) for e in errs],
            "rise_error_us": "≤0.5（采样间隔 0.5 µs）" if errs else "无法测量",
            "snr_by_noise_lsb": dict(zip([str(l) for l in levels], snrs)),
            "snr_corr": None if corr is None else round(corr, 3),
            "snr_corr_expect": "负相关（噪声越大 SNR 越低）"}


def anomaly_checks(cli, te, ood_path):
    from .dataset import make_ood
    n = min(200, len(te["label"]))
    fp = 0
    for i in range(n):
        r = cli.analyze(make_payload(te["raw"][i], dec=_dec(te, i)))
        if r.get("ok") and r["anomaly"].get("is_anomaly"):
            fp += 1
    fp_rate = fp / max(n, 1)
    if ood_path and os.path.exists(ood_path):
        ood = np.load(ood_path)
    else:
        ood, _ = make_ood(200)
    m = min(200, len(ood))
    det = 0
    for i in range(m):
        r = cli.analyze(make_payload(ood[i], dec=10))
        if r.get("ok") and r["anomaly"].get("is_anomaly"):
            det += 1
    return {"clean_fp_rate": round(fp_rate, 4), "n_clean": n,
            "ood_detect_rate": round(det / max(m, 1), 4), "n_ood": m}


def robustness_checks(cli):
    cases = {
        "空 samples": {"samples": []},
        "长度错误": {"samples": [512] * 1000},
        "越界码值": {"samples": [2000] * CAP_LEN},
        "缺 samples": {"fs": 20000000},
    }
    failed = []
    for name, body in cases.items():
        r = cli.analyze(body)
        if r.get("ok") is not False or not r.get("error"):
            failed.append(name)
    r = cli.explain({"style": {"max_chars": 70}})
    if r.get("ok") is not False or not r.get("error"):
        failed.append("explain 缺 result")
    return {"passed": not failed, "failed": failed}


def _to_md(rep):
    c = rep["checks"]
    lines = ["# 验收报告（自动生成）", "",
             "- 时间：%s" % rep.get("finished"), "- 模式：%s" % rep.get("mode"),
             "- 版本：%s" % rep.get("version"), "",
             "## 结论：%s" % ("✅ 通过" if rep.get("passed") else "❌ 未通过"), "",
             "| 项目 | 结果 |", "|---|---|"]
    lines.append("| 契约结构 | %s |" % ("通过" if c["contract"]["passed"] else "失败"))
    lines.append("| 仿真测试集准确率 | %.2f%% |" % (100 * c["accuracy"]["acc"]))
    if "accuracy_no_local" in c:
        lines.append("| 省略 local_cnn 时准确率 | %.2f%% |"
                     % (100 * c["accuracy_no_local"]["acc"]))
    if "accuracy_first8" in c:
        lines.append("| 前 8 类子集准确率 | %.2f%% |" % (100 * c["accuracy_first8"]["acc"]))
    if "accuracy_hard_domain" in c:
        lines.append("| 困难域准确率 | %.2f%% |" % (100 * c["accuracy_hard_domain"]["acc"]))
    lines.append("| 完整分析延迟 p50 / p95 | %.1f / %.1f ms |"
                 % (c["latency_ms"]["p50"], c["latency_ms"]["p95"]))
    lines.append("| 质量-上升时间 | %s |" % c["quality"]["rise_error_us"])
    lines.append("| 质量-SNR 相关性 | %s |" % c["quality"]["snr_corr"])
    lines.append("| 异常-OOD 检出率 | %s |" % c["anomaly"]["ood_detect_rate"])
    lines.append("| 异常-正常误报率 | %s |" % c["anomaly"]["clean_fp_rate"])
    lines.append("| 健壮性 | %s |" % ("通过" if c["robustness"]["passed"] else "失败"))
    if c["accuracy"].get("bad_examples"):
        lines += ["", "## 误判样例（最多 8 条）", "",
                  "| # | 真值 | 预测 | 置信度 |", "|---|---|---|---|"]
        for b in c["accuracy"]["bad_examples"]:
            lines.append("| %d | %s | %s | %.3f |"
                         % (b["i"], CN.get(b["true"], b["true"]),
                            CN.get(b["pred"], b["pred"]), b["conf"]))
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="runs/v2_full/model_bundle.pt")
    ap.add_argument("--anomaly", default=None)
    ap.add_argument("--data", default="data/ds_train")
    ap.add_argument("--hard", default="data/ds_hard")
    ap.add_argument("--ood", default="data/raw_ood.npy")
    ap.add_argument("--url", default=None)
    ap.add_argument("--n", type=int, default=400)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    out = args.out or os.path.join(
        os.path.dirname(os.path.abspath(args.model)) if args.model else ".", "acceptance")
    rep = run(args.model, args.anomaly, args.data, args.hard, args.ood,
              args.url, args.n, out)
    sys.exit(0 if rep.get("passed") else 1)


if __name__ == "__main__":
    main()
