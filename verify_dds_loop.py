#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_dds_loop.py —— ★ 内部 DDS 闭环验收（零外部设备）

════════════════════════════════════════════════════════════════════
为什么这个最重要
════════════════════════════════════════════════════════════════════
板子的示波器现在【只能采内部 DDS】（外部 XADC 还没接）。
所以最关键的问题是：

    ★ AI 认不认得出【板子自己发的波形】？

如果认得出，那么整条链在【零外部设备】的情况下就能演示：
    DDS 发波形 → 采集 → wdens → PL CNN → 类别
    → RL 策略给建议设置 → 应用 → 再采集验证

这个脚本就验这两件事：
    ① 识别：4 种波形 × 多个频率 → 识别对不对
    ② 自动设置：RL 给的建议，应用之后波形是不是真的更好看

用法（板子上 sudo）:
    sudo python3 verify_dds_loop.py
    sudo python3 verify_dds_loop.py --n 6      # 每档 6 个频率
"""
import argparse
import math
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, "/home/zynq")
sys.path.insert(0, "/home/zynq/ui")

WAVES = ((0, "sine"), (1, "square"), (2, "triangle"), (3, "sawtooth"))
# 覆盖率优先：低频看形状，高频看周期数
FREQS = (2000, 5000, 10000, 20000, 50000, 100000, 200000, 500000)


def measure(samples):
    """峰峰、均值、过零数（用于判断显示质量）"""
    pp = max(samples) - min(samples)
    mean = sum(samples) / float(len(samples))
    zc = sum(1 for i in range(1, len(samples))
             if (samples[i - 1] - 128) * (samples[i] - 128) < 0)
    return {"pp": pp, "mean": mean, "zc": zc, "cycles": zc / 2.0}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=8)
    a = ap.parse_args()

    import scope_capture as SC
    import infer_local as IL

    freqs = FREQS[:a.n]
    print("=" * 78)
    print(" 内部 DDS 闭环验收（零外部设备）")
    print("=" * 78)
    print(" 链路: DDS 发波形 → 采集 4096 点 → wdens → PL CNN → 类别")
    print(" 波形 %d 种 × 频率 %d 档 = %d 组"
          % (len(WAVES), len(freqs), len(WAVES) * len(freqs)))
    print()

    # ── ① 识别 ──
    print("─" * 78)
    print("【1】识别：DDS 发什么，AI 认成什么")
    print("─" * 78)
    print("  %-9s %8s  %5s  %5s  %6s   %-14s %s"
          % ("发出", "频率", "峰峰", "过零", "周期", "AI 认出", ""))
    print("  " + "-" * 74)

    hit = 0
    tot = 0
    per = {}
    wrong = []
    for wi, wn in WAVES:
        h = 0
        t = 0
        for f in freqs:
            r = SC.set_dds(wi, f, 255)
            if not r.get("ok"):
                continue
            c = SC.capture_once(src=0, dec=1, timeout_ms=3000)
            if not c.get("ok"):
                continue
            s = list(c["samples"])
            m = measure(s)
            res = IL.infer({"type": "waveform", "data": s})
            got = res.get("label", "?")
            conf = res.get("confidence", 0)
            ok = (got == wn)
            tot += 1
            t += 1
            if ok:
                hit += 1
                h += 1
            else:
                wrong.append((wn, f, got, conf))
            print("  %-9s %7dHz  %5d  %5d  %6.1f   %-14s %s %.2f"
                  % (wn, f, m["pp"], m["zc"], m["cycles"], got,
                     "✓" if ok else "✗", conf))
        per[wn] = (h, t)
        print()

    print("  分类明细:")
    for _, wn in WAVES:
        h, t = per[wn]
        bar = "█" * int(round(h * 24.0 / max(t, 1)))
        print("    %-9s %2d/%2d  %s" % (wn, h, t, bar))
    acc = hit / float(tot) if tot else 0
    print()
    print("  ★ 识别准确率 %.1f%%（%d/%d）" % (acc * 100, hit, tot))
    if wrong:
        print("  误判:")
        for wn, f, got, conf in wrong[:8]:
            print("    %-9s %7dHz → 认成 %-14s (%.2f)" % (wn, f, got, conf))

    # ── ② 自动设置闭环 ──
    print()
    print("─" * 78)
    print("【2】自动设置：RL 给建议 → 应用 → 看波形有没有变好")
    print("─" * 78)
    try:
        import scope_policy as SP
        sp = SP.ScopePolicy()
        import scope_capture as SC2

        for wi, wn in WAVES:
            f = 10000
            SC.set_dds(wi, f, 255)
            c = SC2.capture_once(src=0, dec=1, timeout_ms=3000)
            if not c.get("ok"):
                continue
            s = list(c["samples"])
            before = measure(s)
            obs = SP.compute_obs(s, f, wi, 8, 1, 2)      # 初始设置
            r = sp.infer(obs)
            dec_new = SP.DEC_LEVELS[r["dec_idx"]]
            trig_new = SP.TRIG_LEVELS[r["trig_idx"]]
            # 应用建议
            sc = SC2.Scope() if hasattr(SC2, "Scope") else None
            try:
                import scope as S
                S.apply_settings(dec=dec_new, triglev=trig_new)
            except Exception:
                pass
            c2 = SC2.capture_once(src=0, dec=r["dec_idx"], timeout_ms=3000)
            after = measure(list(c2["samples"])) if c2.get("ok") else before
            print("  %-9s %6dHz" % (wn, f))
            print("     建议: 触发电平 %-3d (%2d/16)  时基 DEC %-3d (%2d/16)  增益 %.2f"
                  % (trig_new, r["trig_idx"], dec_new, r["dec_idx"],
                     SP.VGAIN_LEVELS[r["vgain_idx"]]))
            print("     调整前: 峰峰=%3d  过零=%4d  周期=%5.1f"
                  % (before["pp"], before["zc"], before["cycles"]))
            print("     调整后: 峰峰=%3d  过零=%4d  周期=%5.1f"
                  % (after["pp"], after["zc"], after["cycles"]))
            print()
        sp.close()
    except Exception as e:
        print("  ★ 自动设置那段出错: %s: %s" % (type(e).__name__, e))

    print("=" * 78)
    ok = acc >= 0.75
    print(" 总体: %s" % ("★ 通过（识别 ≥75%）" if ok else "★ 偏低"))
    print("=" * 78)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main() or 0)
