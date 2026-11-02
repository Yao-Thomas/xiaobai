"""
client.py —— 板端/PC 端调用示例（也用于联调）

    # 1) 用仿真波形演示（不需要数据文件）
    python -m wave_ai.client --url http://127.0.0.1:8000 --demo square

    # 2) 用采集工具导出的 JSONL 里的第一条
    python -m wave_ai.client --url http://127.0.0.1:8000 --jsonl /home/zynq/real_ds/square.jsonl

    # 3) 用契约请求文件（test_wave_square_0.json）
    python -m wave_ai.client --url http://127.0.0.1:8000 --file test_wave_square_0.json

    # 4) 只做健康检查
    python -m wave_ai.client --url http://127.0.0.1:8000 --health
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request

import numpy as np

from .config import CAP_LEN, CLASSES, CLASSES_8


def post(url, obj, timeout=30):
    body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def get(url, timeout=10):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def demo_frame(label="square", seed=1):
    from .hw_sim import synth
    rng = np.random.default_rng(seed)
    raw, par = synth(label, 1, rng)
    return raw[0], int(par["dec"][0])


def make_payload(samples, dec=10, fs=20000000, local=None, max_chars=70):
    return {
        "type": "waveform_analysis",
        "samples": [int(v) for v in samples],
        "fs": int(fs),
        "dec": int(dec),
        "local_cnn": local,
        "options": {"max_chars": max_chars, "language": "zh-CN",
                    "for_voice": True, "want_quality": True, "want_anomaly": True},
    }


def fake_local(label, conf=0.72):
    """模拟端侧 8 类输出（联调用；真实部署时由板端 PL CNN 填）"""
    probs = [0.0] * 8
    if label in CLASSES_8:
        probs[CLASSES_8.index(label)] = conf
    else:
        probs[0] = conf
    probs[(CLASSES_8.index(label) + 1) % 8 if label in CLASSES_8 else 2] = 1.0 - conf
    return {"label": CLASSES_8[int(np.argmax(probs))], "confidence": conf,
            "classes": CLASSES_8, "probs": probs}


def show(resp, title="响应"):
    print("\n=== %s ===" % title)
    if not resp.get("ok"):
        print("  ok=false:", resp.get("error"))
        return
    print("  类别   : %s (%s)  置信度 %.3f"
          % (resp.get("label"), resp.get("label_cn"), resp.get("confidence", 0)))
    print("  文本   : %s  [%s 字]" % (resp.get("text"), len(resp.get("text") or "")))
    q = resp.get("quality") or {}
    print("  质量   : score=%s snr=%s rise=%s thd=%s cov=%s"
          % (q.get("score"), q.get("snr_db"), q.get("rise_us"), q.get("thd_pct"),
             q.get("coverage")))
    a = resp.get("anomaly") or {}
    print("  异常   : %s %s %s" % (a.get("is_anomaly"), a.get("features"),
                                   a.get("suggestion")))
    ex = resp.get("extra") or {}
    print("  融合   : %s" % (ex.get("fusion") or {}).get("agree"))
    print("  耗时   : %s ms（服务端 %s ms）" % (resp.get("elapsed_ms"),
                                                resp.get("server_ms")))
    print("  时间   : %s" % ex.get("timing"))
    if ex.get("notes"):
        print("  备注   : %s" % ex["notes"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--health", action="store_true")
    ap.add_argument("--demo", default=None,
                    help="用仿真波形演示：%s" % ",".join(CLASSES))
    ap.add_argument("--jsonl", default=None, help="采集工具导出的 JSONL 文件")
    ap.add_argument("--file", default=None, help="契约请求 JSON 文件")
    ap.add_argument("--explain", default=None, help="对一份融合结果 R 调 /waveform/explain")
    args = ap.parse_args()

    base = args.url.rstrip("/")
    if args.health or (not args.demo and not args.jsonl and not args.file):
        h = get(base + "/health")
        print(json.dumps(h, ensure_ascii=False, indent=2)[:1200])
        return

    if args.demo:
        raw, dec = demo_frame(args.demo)
        label = args.demo
        payload = make_payload(raw, dec=dec, local=fake_local(label))
    elif args.jsonl:
        with open(args.jsonl, encoding="utf-8") as f:
            rec = json.loads(f.readline())
        payload = make_payload(rec["samples"], dec=rec.get("dec", 10),
                               local=fake_local(rec.get("label", "square")))
    else:
        with open(args.file, encoding="utf-8") as f:
            payload = json.load(f)

    t = time.perf_counter()
    resp = post(base + "/waveform/analyze", payload)
    show(resp, "POST /waveform/analyze")
    print("  总耗时 : %.0f ms（含网络）" % ((time.perf_counter() - t) * 1000))

    if args.explain:
        with open(args.explain, encoding="utf-8") as f:
            r = json.load(f)
        e = post(base + "/waveform/explain", r)
        print("\n=== POST /waveform/explain ===")
        print("  text:", e.get("text"))
        print("  tts_ready:", e.get("tts_ready"), " 耗时:", e.get("elapsed_ms"), "ms")


if __name__ == "__main__":
    main()
