# -*- coding: utf-8 -*-
"""
bench_latency.py —— 延迟基准脚本，输出 p50/p95/max，验证 < 3 s（契约验收）

两种模式：
    --local  直接压后端（不经 HTTP，开发机无 fastapi 也能跑，验证模型前向延迟）
    --url    经 HTTP 压真实服务（板子视角的端到端延迟，验收 < 3 s）

用法：
    python src/serve/bench_latency.py --local --n 200
    python src/serve/bench_latency.py --url http://127.0.0.1:8000 --n 200 --type waveform
"""
import argparse
import math
import os
import random
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (_HERE, os.path.dirname(_HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import client  # noqa: E402
import config  # noqa: E402
import model_backend  # noqa: E402


def make_samples(kind="square", n=4096):
    rng = random.Random(42)
    out = []
    period = 340
    for i in range(n):
        if kind == "square":
            v = 200 if ((i % period) < period // 2) else 56
        elif kind == "sine":
            v = 128 + 100 * math.sin(2 * math.pi * i / period)
        elif kind == "triangle":
            ph = (i % period) / float(period)
            v = 56 + (200 - 56) * (2 * ph if ph < 0.5 else 2 * (1 - ph))
        elif kind == "noise":
            v = 128 + rng.gauss(0, 40)
        else:
            v = 128
        out.append(max(0, min(255, int(round(v)))))
    return out


def percentile(sorted_vals, p):
    if not sorted_vals:
        return 0.0
    k = (len(sorted_vals) - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_vals[int(k)]
    d0 = sorted_vals[int(f)] * (c - k)
    d1 = sorted_vals[int(c)] * (k - f)
    return d0 + d1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="", help="压真实服务，如 http://127.0.0.1:8000")
    ap.add_argument("--local", action="store_true", help="直接压后端（不经 HTTP）")
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--type", default="waveform")
    args = ap.parse_args()

    if not args.url and not args.local:
        args.local = True
        print("未指定 --url，默认使用 --local 模式压后端。")

    lat = []
    backend = None
    cli = None
    if args.local:
        backend = model_backend.get_backend(args.type)
        print("模式  : 本地后端直压（backend=%s, n=%d, type=%s）"
              % (getattr(backend, "name", "?"), args.n, args.type))
    else:
        cli = client.InferClient(args.url, timeout=config.CLOUD_TIMEOUT_S, retries=0)
        print("模式  : HTTP 压测（url=%s, n=%d, type=%s）" % (args.url, args.n, args.type))

    kinds = ["square", "sine", "triangle", "noise"]
    ok_count = 0
    for i in range(args.n):
        data = make_samples(kinds[i % len(kinds)])
        t0 = time.perf_counter()
        if args.local:
            r = backend.predict(data) if backend else {"ok": False}
        else:
            r = cli.infer(args.type, data)
        ms = (time.perf_counter() - t0) * 1000.0
        lat.append(ms)
        if r.get("ok"):
            ok_count += 1

    lat.sort()
    p50 = percentile(lat, 50)
    p95 = percentile(lat, 95)
    mx = lat[-1] if lat else 0.0
    print("-" * 60)
    print("样本数   : %d（成功 %d）" % (len(lat), ok_count))
    print("p50      : %8.1f ms" % p50)
    print("p95      : %8.1f ms" % p95)
    print("max      : %8.1f ms" % mx)
    print("-" * 60)
    verdict = "PASS" if mx < 3000.0 else "FAIL"
    print("验收(< 3 s) : %s  (max=%.1f ms)" % (verdict, mx))
    return 0 if mx < 3000.0 else 1


if __name__ == "__main__":
    sys.exit(main())
