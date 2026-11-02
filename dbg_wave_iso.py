#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dbg_wave_iso.py —— 把波形模型的问题隔离到"输入/权重/输出"哪一环

════════════════════════════════════════════════════════════════════
已经知道的事实（别重复验证）
════════════════════════════════════════════════════════════════════
✓ MNIST 路径能跑通：logits 10/10 与 CPU 一致  ⇒ 加速器通路是好的
✓ AXI-Lite 寄存器读写正确（MFQ 读回 201/371/1390）
✓ 输入缓冲写进去了（CPU 读回一致）
✗ 波形模型 logits 全 0
✗ fb1/fb2 的 CPU 读回是脏的（缓存）—— 不能作为依据

所以问题只可能在：
    A. 波形的输入数据没被加速器读到
    B. 波形的 fc 权重没被读到
    C. MFQ 太大导致累加器溢出/截断
    D. 波形的权重/输入本身有问题

这个脚本一次改一个变量，只比对【logits】（8 字节，读回可靠）：

    组 1: 波形输入 + 波形权重（正常）        → 基线
    组 2: 波形输入 + fc 权重换成全 1        → 权重变了 logits 变吗
    组 3: MNIST 输入 + MNIST 权重           → 对照（应该非零）
    组 4: MNIST 输入 + 波形权重             → 输入形态一样时呢
    组 5: 全 0 输入 + 波形权重              → 应该是 0
    组 6: 波形输入 + MFQ 改成 119           → MFQ 是原因吗

用法:
    sudo python3 dbg_wave_iso.py
"""
import os
import struct
import sys

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
    rout = open(os.path.join(W, "wave_reference_out.bin"), "rb").read()

    W1 = wb[0x0000:0x0000 + 72]
    W2 = wb[0x0080:0x0080 + 1152]
    WF = wb[0x0500:0x0500 + 3200]

    c = CL.Cnn(verbose=False)

    def setup(w1b, w2b, wfb):
        c.w1.write(w1b + b"\x00" * (128 - len(w1b)))
        c.w2.write(w2b + b"\x00" * (1152 - len(w2b)))
        c.wf.write(wfb + b"\x00" * (4032 - len(wfb)))
        c.w1.flush(); c.w2.flush(); c.wf.flush()

    def run(img784, mfq1=CL.MFQ_C1, mfq2=CL.MFQ_C2, mfqc=CL.MFQ_FC, out=8):
        c.img.write(img784 + b"\x00" * (832 - len(img784)))
        c.img.flush()
        c.run_cpq(28, 28, 1, CL.CB1, c.img, c.w1, c.fb1, mfq=mfq1)
        c.run_cpq(13, 13, CL.CB1, CL.CB2, c.fb1, c.w2, c.fb2, mfq=mfq2)
        c.run_fc(c.fb2, c.wf, c.lg, CL.FCI, out, mfq=mfqc)
        c.lg.invalidate()
        return b2i(c.lg.read(out))

    def cpu(img784, W1b, W2b, WFb, mfq1, mfq2, mfqc, out=8):
        i8 = b2i(img784)
        w1 = b2i(W1b); w2 = b2i(W2b); wf = b2i(WFb)
        _, _, lg = CL.cpu_reference(i8, w1, w2, wf,
                                    mfq1=mfq1, mfq2=mfq2, mfqfc=mfqc, fco=out)
        return lg

    img_wave = rin[0:784]
    want = b2i(rout[0:8])

    print("=" * 74)
    print(" 波形模型问题隔离")
    print("=" * 74)
    print(" 参考 logits（第 0 组）: %s" % want)
    print()

    tests = []

    # 组 1：正常
    setup(W1, W2, WF)
    hw = run(img_wave)
    cp = cpu(img_wave, W1, W2, WF, CL.MFQ_C1, CL.MFQ_C2, CL.MFQ_FC)
    tests.append(("1 波形输入+波形权重（正常）", hw, cp))

    # 组 2：fc 权重全 1
    setup(W1, W2, bytes([1]) * 3200)
    hw = run(img_wave)
    cp = cpu(img_wave, W1, W2, bytes([1]) * 3200,
             CL.MFQ_C1, CL.MFQ_C2, CL.MFQ_FC)
    tests.append(("2 波形输入 + fc 权重全1", hw, cp))

    # 组 3：MNIST 数据
    try:
        mb = open(os.path.join(W, "mnist_test.bin"), "rb").read()
        m_img = bytes(((b - 128) & 0xFF) for b in mb[0:784])
        m_w1 = mb[784:784 + 72]
        m_w2 = mb[856:856 + 1152]
        m_wf = mb[2008:2008 + 4000]
        setup(m_w1, m_w2, m_wf)
        hw = run(m_img, 119, 119, 119, 10)
        cp = cpu(m_img, m_w1, m_w2, m_wf, 119, 119, 119, 10)
        tests.append(("3 MNIST输入+MNIST权重(对照)", hw, cp))
    except Exception as e:
        print(" 组3 跳过: %s" % e)

    # 组 4：MNIST 输入 + 波形权重
    try:
        setup(W1, W2, WF)
        hw = run(m_img)
        cp = cpu(m_img, W1, W2, WF, CL.MFQ_C1, CL.MFQ_C2, CL.MFQ_FC)
        tests.append(("4 MNIST输入 + 波形权重", hw, cp))
    except Exception:
        pass

    # 组 5：全 0 输入
    setup(W1, W2, WF)
    hw = run(bytes([0]) * 784)
    cp = cpu(bytes([0]) * 784, W1, W2, WF, CL.MFQ_C1, CL.MFQ_C2, CL.MFQ_FC)
    tests.append(("5 全0输入 + 波形权重", hw, cp))

    # 组 6：MFQ 全改成 119
    setup(W1, W2, WF)
    hw = run(img_wave, 119, 119, 119)
    cp = cpu(img_wave, W1, W2, WF, 119, 119, 119)
    tests.append(("6 波形输入+波形权重,MFQ=119", hw, cp))

    print("%-34s %-28s %-28s %s" % ("测试", "硬件 logits", "CPU logits", "判"))
    print("-" * 100)
    for name, hw, cp in tests:
        mark = "✓" if hw == cp else "✗"
        print("%-34s %-28s %-28s %s" % (name, hw, cp, mark))

    print()
    print("=" * 74)
    print(" 怎么读这张表：")
    print("  组 3 必须 ✓（MNIST 是对照，之前验过）")
    print("  组 1 ✗  → 波形这条路有问题")
    print("  组 1 和组 2 结果一样 → fc 权重根本没被读到")
    print("  组 5 不是全 0 → 输入通路有问题")
    print("  组 6 变好 → MFQ 就是原因")
    print("=" * 74)

    c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
