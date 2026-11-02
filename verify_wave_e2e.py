#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_wave_e2e.py —— ★ 波形识别的真机端到端验收（板子上 sudo 跑）

════════════════════════════════════════════════════════════════════
和 verify_wave_onboard.py 的区别
════════════════════════════════════════════════════════════════════
    verify_wave_onboard.py
        只验「参考输入 → 硬件 → 与参考输出逐点一致」
        证明的是【加速器 + 权重 + MFQ】这条链
        已经过了：512/512 点一致

    这个脚本
        验的是完整业务链：
            原始 4096 点波形 → wdens 密度图 → int8 → PL 加速器 → 类别
        证明的是【预处理 + 驱动 + 模型】整条链

    数据用 AI 交付包的 dds_sim 生成（★ 必须用他们的生成器，
    我第一版用自己的 gen_wave，分布不对，端到端只有 35%）

用法:
    sudo python3 verify_wave_e2e.py
    sudo python3 verify_wave_e2e.py --n 20     # 每类 20 个
"""
import argparse
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, "/home/zynq")
W = "/home/zynq"
CLS = ("sine", "square", "triangle", "sawtooth", "noise",
       "clipping", "signal_loss", "duty_abnormal")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=12, help="每类多少个样本")
    a = ap.parse_args()

    import cnn_linux as CL
    import waveform_ai as WA

    print("=" * 74)
    print(" 波形识别 · 真机端到端验收")
    print("=" * 74)
    print(" 链路: 4096 点波形 → wdens 28×28 → int8 → PL 加速器 → 8 类")
    print(" 每类 %d 个样本" % a.n)

    # 数据源：AI 交付包的 dds_sim（★ 必须用他们的，分布才对）
    dds_path = os.path.join(W, "ai_delivery", "03_源码")
    if not os.path.isdir(dds_path):
        # 板子上可能没放源码，退回本地生成
        print(" ⚠ 找不到 ai_delivery/03_源码，改用 waveform_ai.gen_wave")
        print("   （注意：gen_wave 的分布和交付包不一致，结果仅供参考）")
        use_dds = False
    else:
        sys.path.insert(0, dds_path)
        use_dds = True

    rng = None
    DS = None
    if use_dds:
        try:
            import numpy as np
            from common import dds_sim as DS
            rng = np.random.default_rng(20261002)
            print(" 数据源: AI 交付包 dds_sim ✓")
        except Exception as e:
            print(" ⚠ 导入 dds_sim 失败（%s），改用 gen_wave" % e)
            use_dds = False

    print()

    # 预加载一次 Cnn，反复用（省时间）
    c = CL.Cnn(verbose=False)
    w1, w2, wf = CL.load_wave_weights()
    c.w1.write(w1)
    c.w2.write(w2)
    c.wf.write(wf[:3200] + b"\x00" * (4032 - 3200))

    per = {}
    tot = 0
    hit = 0
    wrong = []

    for label in CLS:
        h = 0
        for i in range(a.n):
            if use_dds:
                samples, spec, _ = DS.make_sample(rng, label)
                samples = list(samples)
                K = float(spec.cycles)
                amp = float(spec.amp)
            else:
                K = 3.0 + i
                amp = 80.0
                wv = WA.gen_wave(label, n=4096,
                                 freq=K * 20000000.0 / 4096.0,
                                 noise=0.01, seed=1000 + i)
                samples = list(WA.quantize_8bit(wv))

            # ★ 预处理：4096 点 → 28×28 uint8 密度图
            img = WA.wdens_u8(samples)
            # ★ 送加速器（wave_classify 内部做 int8 = u8-128）
            idx, name, lg = CL.wave_classify(bytes(img), c=c)
            top = CL.WAVE_CLASSES.index(name) if name in CL.WAVE_CLASSES else -1
            top_name = CL.WAVE_CLASSES[top] if top >= 0 else "?"

            tot += 1
            if top_name == label:
                hit += 1
                h += 1
            elif len(wrong) < 10:
                wrong.append((label, K, amp, top_name, lg))
        per[label] = (h, a.n)

    print(" 分类结果:")
    for lb in CLS:
        h, n = per[lb]
        bar = "█" * int(round(h * 20.0 / n))
        print("   %-15s %2d/%2d  %s" % (lb, h, n, bar))

    acc = hit / float(tot) if tot else 0
    print()
    print(" ★ 端到端准确率 %.1f%%（%d/%d）" % (acc * 100, hit, tot))
    print("   交付包自己的测试集是 95.9%%，离线复刻 94.8%%")
    if wrong:
        print()
        print(" 误判样本（前 %d 个）:" % len(wrong))
        for lb, K, amp, top, lg in wrong:
            print("   %-14s K=%5.1f amp=%5.1f → %-14s logits=%s"
                  % (lb, K, amp, top, lg))

    c.close()

    print()
    print("=" * 74)
    ok = acc >= 0.80
    print(" 总体: %s" % ("★ 通过（≥80%）" if ok else "★ 偏低，看上面的误判"))
    print("=" * 74)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main() or 0)
