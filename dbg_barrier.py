#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dbg_barrier.py —— 验证"层间需要写同步"这个假设

════════════════════════════════════════════════════════════════════
推理链
════════════════════════════════════════════════════════════════════
1. conv1 的输出 f1，CPU 读回来与 CPU 参考 100% 一致
2. 把【CPU 算的 f1】灌进 fb1 再跑 conv2 → 400/400 全对
3. 但 conv1 直接接 conv2 → 只有 70%

⇒ conv1 写 DDR 的结果，"晚一点"是对的；紧接着启动的 conv2 读到的
  却是还没落盘/还没到一致性点的中间数据。

Zynq 的 HP 口经 L2 缓存控制器。加速器写完之后，L2 里可能还是脏的/
没更新的，另一个 master（或者同一个 IP 的下一次启动）去读就可能读到旧值。
CPU 从【不可缓存映射】读一下，相当于强制 L2 把那条线拿最新 —— 之后就一致了。

要验证的就是：层与层之间插一个"CPU 读一下"（读屏障），conv2/fc 会不会就对了。

对照方案：
    A. 什么都不加（现状）          → 期望 ~70%
    B. 加 time.sleep(0.001)        → 时间够不够
    C. 加 time.sleep(0.01)
    D. CPU 读 fb1 头 64 字节（读屏障）→ 期望变好
    E. CPU 读 fb1 整块 1408 字节
    F. 读头 64 字节 + sleep(0.0001)

用法:
    sudo python3 dbg_barrier.py
"""
import os
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, "/home/zynq")
W = "/home/zynq"


def b2i(b):
    return [x - 256 if x >= 128 else x for x in b]


def main():
    import cnn_linux as CL

    wb = open(os.path.join(W, "wave_weights.bin"), "rb").read()
    rin = open(os.path.join(W, "wave_reference_in.bin"), "rb").read()
    W1b = wb[0x0000:0x0000 + 72]
    W2b = wb[0x0080:0x0080 + 1152]
    WFb = wb[0x0500:0x0500 + 3200]

    img_i8 = b2i(rin[0:784])
    f1_cpu, f2_cpu, lg_cpu = CL.cpu_reference(
        img_i8, b2i(W1b), b2i(W2b), b2i(WFb),
        mfq1=CL.MFQ_C1, mfq2=CL.MFQ_C2, mfqfc=CL.MFQ_FC, fco=8)

    print("=" * 74)
    print(" 层间写同步验证")
    print("=" * 74)
    print("  CPU f1 max=%d   f2 max=%d   logits=%s"
          % (max(f1_cpu), max(f2_cpu), lg_cpu))
    print()

    c = CL.Cnn(verbose=False)
    c.w1.write(W1b + b"\x00" * (128 - 72))
    c.w2.write(W2b)
    c.wf.write(WFb + b"\x00" * (4032 - 3200))
    c.w1.flush(); c.w2.flush(); c.wf.flush()

    def run_case(name, barrier):
        """跑 conv1 → [barrier] → conv2，返回 f2 的一致度"""
        c.img.write(rin[0:784] + b"\x00" * (832 - 784))
        c.img.flush()
        c.run_cpq(28, 28, 1, CL.CB1, c.img, c.w1, c.fb1, mfq=CL.MFQ_C1)
        if barrier:
            barrier()
        c.run_cpq(13, 13, CL.CB1, CL.CB2, c.fb1, c.w2, c.fb2, mfq=CL.MFQ_C2)
        c.fb2.invalidate()
        hw = b2i(c.fb2.read(400))
        same = sum(1 for i in range(400) if hw[i] == f2_cpu[i])
        print("  %-34s %3d/400 (%.1f%%)  max=%d  %s"
              % (name, same, same * 100.0 / 400, max(hw),
                 "★ 全对" if same == 400 else ""))
        return same

    results = {}
    results["A 不加"] = run_case("A 不加任何同步（现状）", None)
    results["B sleep 1ms"] = run_case(
        "B time.sleep(0.001)", lambda: time.sleep(0.001))
    results["C sleep 10ms"] = run_case(
        "C time.sleep(0.010)", lambda: time.sleep(0.010))
    results["D 读头 64B"] = run_case(
        "D CPU 读 fb1 头 64 字节", lambda: c.fb1.read(64))
    results["E 读整块"] = run_case(
        "E CPU 读 fb1 整块 1408", lambda: c.fb1.read(1408))
    results["F 读64B+sleep"] = run_case(
        "F 读 64B + sleep(0.0001)",
        lambda: (c.fb1.read(64), time.sleep(0.0001)))

    print()
    print("─" * 74)
    print(" 如果 D/E/F 明显变好 → 就是写同步问题，层间要加读屏障")
    print(" 如果 B/C 变好 → 单纯是时间不够")
    print()

    # ── 顺手看：fc 也一样吗 ──
    print("─" * 74)
    print(" fc 层间同步")
    for name, barrier in (("不加", None),
                          ("读 fb2 64B", lambda: c.fb2.read(64)),
                          ("读 fb2 整块", lambda: c.fb2.read(448)),
                          ("sleep 10ms", lambda: time.sleep(0.010))):
        c.img.write(rin[0:784] + b"\x00" * (832 - 784))
        c.img.flush()
        c.run_cpq(28, 28, 1, CL.CB1, c.img, c.w1, c.fb1, mfq=CL.MFQ_C1)
        c.fb1.read(1408)                      # 这一层先加屏障，隔离出 fc 的问题
        c.run_cpq(13, 13, CL.CB1, CL.CB2, c.fb1, c.w2, c.fb2, mfq=CL.MFQ_C2)
        if barrier:
            barrier()
        c.run_fc(c.fb2, c.wf, c.lg, CL.FCI, 8, mfq=CL.MFQ_FC)
        c.lg.invalidate()
        hw = b2i(c.lg.read(8))
        same = sum(1 for i in range(8) if hw[i] == lg_cpu[i])
        print("  %-16s 硬件 %s   CPU %s   %d/8"
              % (name, hw, lg_cpu, same))

    c.close()
    print()
    print("=" * 74)
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
