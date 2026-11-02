"""
make_fixtures.py —— 生成验收夹具（≥20 条真实格式的请求 + 一份融合结果 R）

    python scripts/make_fixtures.py --out deliverables/fixtures

产物：
    test_wave_<label>_<i>.json   契约 §2.2 的请求体（含 samples/fs/dec/local_cnn/options）
    test_result_R.json           契约 §3.2 的融合结果（供 /waveform/explain 用）
    fixtures_manifest.json       每条夹具的真值标签 / 仿真参数 / 用途
    real_format_demo.jsonl       与采集工具完全同格式的 JSONL（给板端核对格式）

★ 这些是**仿真真实链路**数据（source=sim_hw_10bit），不是板卡实测；
  板端实测数据到了之后，用同样格式替换即可，服务不需要改。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wave_ai.config import CLASSES, CLASSES_8  # noqa: E402
from wave_ai.hw_sim import synth  # noqa: E402


def fake_local(label, rng):
    probs = [0.0] * 8
    if label in CLASSES_8:
        probs[CLASSES_8.index(label)] = float(rng.uniform(0.55, 0.95))
    else:
        probs[int(rng.integers(0, 8))] = float(rng.uniform(0.35, 0.75))
    rest = 1.0 - sum(probs)
    probs[int(rng.integers(0, 8))] += rest
    return {"label": CLASSES_8[int(np.argmax(probs))],
            "confidence": round(float(max(probs)), 3),
            "classes": CLASSES_8, "probs": [round(p, 4) for p in probs]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="deliverables/fixtures")
    ap.add_argument("--per-class", type=int, default=2)
    ap.add_argument("--seed", type=int, default=20261021)
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    rng = np.random.default_rng(args.seed)

    manifest = []
    lines = []
    for label in CLASSES:
        raw, par = synth(label, args.per_class, rng, domain="train")
        for i in range(args.per_class):
            dec = int(par["dec"][i])
            s = [int(v) for v in raw[i].tolist()]
            local = fake_local(label, rng)
            body = {
                "type": "waveform_analysis",
                "samples": s,
                "fs": 20000000,
                "dec": dec,
                "local_cnn": local,
                "measurements": {
                    "freq_hz": round(float(par["k"][i] * 20e6 / dec / 4096), 2)
                    if np.isfinite(par["k"][i]) else None,
                    "vpp_v": round(float(par["vpp_lsb"][i]) * 10.0 / 1024.0, 4),
                },
                "options": {"max_chars": 70, "language": "zh-CN", "for_voice": True,
                            "want_quality": True, "want_anomaly": True},
            }
            name = "test_wave_%s_%d.json" % (label, i)
            with open(os.path.join(args.out, name), "w", encoding="utf-8") as f:
                json.dump(body, f, ensure_ascii=False)
            manifest.append({
                "file": name, "true_label": label, "dec": dec,
                "freq_hz": body["measurements"]["freq_hz"],
                "vpp_v": body["measurements"]["vpp_v"],
                "source": "sim_hw_10bit", "purpose": "契约结构 + 准确率",
            })
            lines.append(json.dumps({
                "samples": s, "label": label, "ch": 0, "fs": 20000000, "dec": dec,
                "meta": {"vpp_lsb": round(float(par["vpp_lsb"][i]), 1),
                         "freq_hz": body["measurements"]["freq_hz"],
                         "triggered": True, "stale": False},
                "ts": 1761000000.123, "aug": False,
            }, separators=(",", ":"), ensure_ascii=False))

    # 融合结果 R（给 /waveform/explain 用）
    R = {
        "type": "waveform_analysis",
        "result": {
            "label": "square", "label_cn": "方波", "confidence": 0.973,
            "fusion": {
                "local_cnn": {"label": "square", "confidence": 0.731},
                "vision_model": {"label": "square", "confidence": 0.973},
                "agree": True, "final_source": "vision_model",
            },
            "measurements": {
                "freq_hz": 998.5, "vpp_v": 1.008, "vmax_v": 0.42, "vmin_v": -0.577,
                "duty_pct": 49.9, "offset_v": -0.078, "rise_us": 1.2, "fall_us": 1.1,
            },
            "quality": {"score": 87, "snr_db": 42.0, "thd_pct": 1.5,
                        "jitter_ns": 3.0, "overshoot_pct": 8.0},
            "channel": 0, "ts": 1761000000.123,
        },
        "style": {"max_chars": 70, "language": "zh-CN", "tone": "concise",
                  "for_voice": True},
    }
    with open(os.path.join(args.out, "test_result_R.json"), "w", encoding="utf-8") as f:
        json.dump(R, f, ensure_ascii=False, indent=2)

    with open(os.path.join(args.out, "fixtures_manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"n": len(manifest), "items": manifest,
                   "note": "source=sim_hw_10bit，板端实测数据请按同格式替换"},
                  f, ensure_ascii=False, indent=2)
    with open(os.path.join(args.out, "real_format_demo.jsonl"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print("夹具 -> %s" % os.path.abspath(args.out))
    print("  %d 条请求 + 1 条融合结果 + 1 份 JSONL（%d 行）" % (len(manifest), len(lines)))


if __name__ == "__main__":
    main()
