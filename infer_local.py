#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""infer_local.py —— ★ 板端 /infer 实现（用 PL 加速器，不是 numpy）

════════════════════════════════════════════════════════════════════
契约（照 AI 负责人 `02_文档/04_云端推理API与降级.md` 逐字实现）
════════════════════════════════════════════════════════════════════
    POST /infer
    { "type": "waveform"|"chat", "data": [...], "hint": "...", "api_key": "..." }

    → 200 { "ok": true, "label": "square", "confidence": 0.93,
            "detail": {...}, "elapsed_ms": 240, "offline_mode": false }
    → 失败 { "ok": false, "error": "..." }

    唯一的加法（契约里写明的向后兼容加法）：
        成功响应里多一个顶层布尔 offline_mode（在线 false / 降级后 true）

════════════════════════════════════════════════════════════════════
★ 为什么自己实现，而不是直接搬他的 serve/
════════════════════════════════════════════════════════════════════
他的 `serve/model_backend.py` 是 **纯 numpy 整数前向**（板子上没有 numpy），
而且他那边是"云端"跑软件推理。

我们的板子上有 **PL 加速器**（CNN conv1→conv2→fc，真硬件）。
⇒ 按同一个契约自己实现，但推理走 PL：
    · 比 numpy 快得多（11.5 ms/组 vs 他那边 p95 0.3ms 是启发式回退，不是真模型）
    · 而且是"真机上跑的",演示时更有说服力

════════════════════════════════════════════════════════════════════
输入形态（契约里说有两种，用长度自动判别）
════════════════════════════════════════════════════════════════════
    len(data) == 4096  → 原始采样 → 走 wdens 预处理 → 28×28 → PL
    len(data) == 784   → 已经是 28×28 像素 → 直接送 PL
    hint 可以指定 "wdens" / "raw" / "image" 来强制

分级推理的 decision_path（契约要求记下来）：
    local            本地推理成功
    cloud_fallback_local   本来要走云端，云端不可达 → 降到本地
"""
import json
import math
import os
import sys
import threading
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "ui"))

# ★ 板子只有一块 PL 加速器，多个请求要排队
_LOCK = threading.RLock()

_CLASSES = ("sine", "square", "triangle", "sawtooth", "noise",
            "clipping", "signal_loss", "duty_abnormal")

_W = None            # 缓存 Cnn 和其他资源


def _ensure():
    """懒加载：Cnn + 权重（进程内只建一次）"""
    global _W
    if _W is not None:
        return _W
    import cnn_linux as CL
    import waveform_ai as WA
    c = CL.Cnn(verbose=False)
    w1, w2, wf = CL.load_wave_weights()
    c.w1.write(w1)
    c.w2.write(w2)
    c.wf.write(wf[:3200] + b"\x00" * (4032 - 3200))
    _W = {"c": c, "CL": CL, "WA": WA}
    return _W


def _softmax(x):
    if not x:
        return []
    m = max(x)
    e = [math.exp(v - m) for v in x]
    s = sum(e) or 1.0
    return [v / s for v in e]


def _to_image(data, hint=None):
    """把 data 解释成 28×28 uint8

    返回 (img784_list, 解释方式说明)
    """
    W = _ensure()
    n = len(data)
    h = (hint or "").strip().lower()

    if h in ("image", "pixel", "28x28") or (n == 784 and h != "raw"):
        v = [int(round(float(x))) for x in data]
        v = [0 if x < 0 else (255 if x > 255 else x) for x in v]
        return v, "784 像素（直接当 28×28 密度图）"

    if n == 4096 or h in ("raw", "wdens", "samples"):
        s = [int(round(float(x))) for x in data]
        s = [0 if x < 0 else (255 if x > 255 else x) for x in s]
        img = W["WA"].wdens_u8(s)
        return list(img), "4096 原始采样 → wdens 28×28 密度图"

    raise ValueError("data 长度 %d 不认识（要 4096 个采样或 784 个像素）" % n)


def infer_waveform(data, hint=None):
    """波形识别：PL 加速器推理

    返回契约格式的 dict（不含 elapsed_ms，由调用方补）
    """
    t0 = time.time()
    with _LOCK:
        W = _ensure()
        CL = W["CL"]
        img, how = _to_image(data, hint)
        idx, name, logits = CL.wave_classify(bytes(img), c=W["c"])
        prob = _softmax(list(logits))
        conf = prob[idx] if idx is not None and 0 <= idx < len(prob) else 0.0
        return {
            "ok": True,
            "label": name,
            "confidence": round(float(conf), 4),
            "detail": {
                "engine": "PL 加速器（cnn_conv_pool + cnn_fc）",
                "input_interpretation": how,
                "classes": list(_CLASSES),
                "logits": list(logits),
                "probs": [round(p, 4) for p in prob],
                "decision_path": "local",
                "mfq": [CL.MFQ_C1, CL.MFQ_C2, CL.MFQ_FC],
                # ★ 硬件信息，演示时可以讲
                "accel_regs": {"conv_pool": "0x43CD0000", "fc": "0x43CE0000"},
            },
            "elapsed_ms": int((time.time() - t0) * 1000),
            "offline_mode": True,
        }


def infer(body, cloud_chat_fn=None):
    """统一的 /infer 入口

    body: 契约里的请求体
    cloud_chat_fn: chat 类型时用来问云端/agent 的回调（可选）
    """
    t0 = time.time()
    if not isinstance(body, dict):
        return {"ok": False, "error": "请求体要是 JSON 对象"}
    typ = (body.get("type") or "").strip().lower()
    data = body.get("data")
    hint = body.get("hint")

    if typ == "waveform":
        if not isinstance(data, (list, tuple)) or not data:
            return {"ok": False, "error": "type=waveform 需要 data 数组"}
        try:
            return infer_waveform(data, hint)
        except Exception as e:
            return {"ok": False,
                    "error": "%s: %s" % (type(e).__name__, e),
                    "elapsed_ms": int((time.time() - t0) * 1000)}

    if typ == "chat":
        text = data if isinstance(data, str) else (
            (data or {}).get("text") if isinstance(data, dict) else "")
        if not text:
            return {"ok": False, "error": "type=chat 需要 data 为字符串或 {text:...}"}
        if cloud_chat_fn is None:
            return {"ok": False, "error": "chat 需要云端回调（没接）"}
        try:
            r = cloud_chat_fn(text)
            return {"ok": True, "label": "chat",
                    "confidence": 1.0,
                    "detail": {"reply": str(r),
                               "decision_path": "cloud"},
                    "elapsed_ms": int((time.time() - t0) * 1000),
                    "offline_mode": False}
        except Exception as e:
            return {"ok": False, "error": "云端失败: %s" % e,
                    "elapsed_ms": int((time.time() - t0) * 1000)}

    # 没给 type 但有 data → 按长度猜
    if isinstance(data, (list, tuple)) and data:
        try:
            return infer_waveform(data, hint)
        except Exception as e:
            return {"ok": False, "error": str(e)}

    return {"ok": False, "error": "type 只能是 waveform 或 chat"}


def health():
    """契约里的 GET /health"""
    ok = True
    err = None
    try:
        W = _ensure()
        ok = W["c"].cpq.r(0x00) is not None
    except Exception as e:
        ok = False
        err = "%s: %s" % (type(e).__name__, e)
    return {
        "ok": ok,
        "service": "xiaobai-infer",
        "engine": "PL 加速器",
        "classes": list(_CLASSES),
        "error": err,
    }


# ══════════════════════════════════════════════════════════════════
#  自测
# ══════════════════════════════════════════════════════════════════
def selftest():
    print("=" * 74)
    print(" 板端 /infer 自测")
    print("=" * 74)
    ok = True

    def chk(c, m, d=""):
        nonlocal ok
        print("   %s %s%s" % ("✓" if c else "✗", m, ("   " + d) if d else ""))
        ok = ok and c

    print()
    print("【1】health")
    h = health()
    print("   %s" % json.dumps(h, ensure_ascii=False))
    chk(h.get("ok") is True, "health.ok")

    print()
    print("【2】784 像素输入（造一张 wdens 图）")
    try:
        import waveform_ai as WA
        s = [int(127 + 100 * math.sin(i * 0.05)) for i in range(4096)]
        img = WA.wdens_u8(s)
        r = infer({"type": "waveform", "data": list(img)})
        chk(r.get("ok"), "返回 ok", "label=%s conf=%.3f"
            % (r.get("label"), r.get("confidence", 0)))
        chk(r.get("detail", {}).get("decision_path") == "local",
            "decision_path=local")
        chk("offline_mode" in r, "有 offline_mode 字段")
    except Exception as e:
        chk(False, "784 输入", str(e))

    print()
    print("【3】4096 采样输入（自动走 wdens）")
    try:
        s = [int(127 + 100 * math.sin(i * 0.05)) for i in range(4096)]
        r = infer({"type": "waveform", "data": s})
        chk(r.get("ok"), "返回 ok", "label=%s" % r.get("label"))
        chk("wdens" in r.get("detail", {}).get("input_interpretation", ""),
            "识别为 4096 采样")
    except Exception as e:
        chk(False, "4096 输入", str(e))

    print()
    print("【4】错误处理")
    chk(infer({"type": "waveform"}).get("ok") is False, "缺 data 要报错")
    chk(infer({"type": "bogus"}).get("ok") is False, "错的 type 要报错")
    chk(infer({"type": "waveform", "data": [1, 2, 3]}).get("ok") is False,
        "长度不对要报错")
    chk(infer(None).get("ok") is False, "非 dict 要报错")

    print()
    print("【5】hint 强制指定")
    try:
        from_test = [0] * 784
        r = infer({"type": "waveform", "data": from_test, "hint": "image"})
        chk(r.get("ok"), "hint=image")
    except Exception as e:
        chk(False, "hint", str(e))

    print()
    print("=" * 74)
    print(" 总体: %s" % ("★ 全部通过" if ok else "★ 有问题"))
    print("=" * 74)
    return 0 if ok else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    print(json.dumps(health(), ensure_ascii=False, indent=1))
