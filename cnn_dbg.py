#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cnn_dbg.py —— 分步排查 CNN 数据通路

思路：把每一层单独跑，然后把输出缓冲读回来看。
     ★ 注意：这个脚本会读中间缓冲（会污染 cache），
       所以**只能用来排查，不能用来做正式推理**。

排查顺序：
  1. 寄存器写进去没有（读回确认）
  2. conv1 有没有往 fb1 写东西（对比跑之前/之后）
  3. 如果 fb1 是空的 -> m_axi 通路问题
  4. 如果 fb1 有数据 -> 继续查 conv2 / fc
"""
import ctypes
import os
import struct
import sys
import time

sys.path.insert(0, "/home/zynq")
import cnn_linux as C


def hexdump(buf, n=32, label=""):
    data = buf.as_u8(min(n, buf.size))
    neg = [b - 256 if b > 127 else b for b in data]
    print("  %s 前%d字节(u8): %s" % (label, min(n, buf.size),
                                     " ".join("%3d" % b for b in data[:n])))
    print("  %s 前%d字节(i8): %s" % (label, min(n, buf.size),
                                     " ".join("%4d" % b for b in neg[:n])))


def main():
    print("=" * 70)
    print(" CNN 数据通路排查")
    print("=" * 70)

    blob = open("/home/zynq/mnist_test.bin", "rb").read()
    cnn = C.Cnn(verbose=False)
    try:
        label, img_u8, W1, W2, WF = cnn.load(blob)
        print("\n真实标签 = %d" % label)

        print("\n--- 1) 输入/权重缓冲内容确认（CPU 视角）---")
        print("  img  前 16 字节: %s" % cnn.img.as_u8(16))
        print("  W1   前 16 字节: %s" % cnn.w1.as_i8()[:16])
        nonzero_img = sum(1 for b in cnn.img.as_u8() if b != 0)
        nonzero_w1 = sum(1 for b in cnn.w1.as_i8() if b != 0)
        print("  img  非零字节数: %d / %d" % (nonzero_img, cnn.img.size))
        print("  W1   非零字节数: %d / %d" % (nonzero_w1, cnn.w1.size))

        print("\n--- 2) 寄存器写回确认 ---")
        cnn.cpq.w64(C.R_IMG, cnn.img.paddr)
        cnn.cpq.w64(C.R_W, cnn.w1.paddr)
        cnn.cpq.w64(C.R_OUT, cnn.fb1.paddr)
        cnn.cpq.w(C.R_IH, 28); cnn.cpq.w(C.R_IW, 28)
        cnn.cpq.w(C.R_INC, 1); cnn.cpq.w(C.R_OUTC, 8)
        cnn.cpq.w(C.R_KH, 3); cnn.cpq.w(C.R_KW, 3)
        cnn.cpq.w(C.R_P, 2); cnn.cpq.w(C.R_MFQ, 119)
        time.sleep(0.05)
        print("  期望 paddr: img=%#x w=%#x out=%#x" %
              (cnn.img.paddr, cnn.w1.paddr, cnn.fb1.paddr))
        print("  读回 R_IMG  = %#x  (lo=%#x hi=%#x)" %
              (cnn.cpq.r(C.R_IMG), cnn.cpq.r(C.R_IMG), cnn.cpq.r(C.R_IMG + 4)))
        print("  读回 R_W    = %#x  (lo=%#x hi=%#x)" %
              (cnn.cpq.r(C.R_W), cnn.cpq.r(C.R_W), cnn.cpq.r(C.R_W + 4)))
        print("  读回 R_OUT  = %#x  (lo=%#x hi=%#x)" %
              (cnn.cpq.r(C.R_OUT), cnn.cpq.r(C.R_OUT), cnn.cpq.r(C.R_OUT + 4)))
        print("  读回 R_IH=%d IW=%d INC=%d OUTC=%d KH=%d KW=%d P=%d MFQ=%d" %
              (cnn.cpq.r(C.R_IH), cnn.cpq.r(C.R_IW), cnn.cpq.r(C.R_INC),
               cnn.cpq.r(C.R_OUTC), cnn.cpq.r(C.R_KH), cnn.cpq.r(C.R_KW),
               cnn.cpq.r(C.R_P), cnn.cpq.r(C.R_MFQ)))

        print("\n--- 3) 跑 conv1，前后对比 fb1 ---")
        before = cnn.fb1.as_u8(32)
        print("  跑之前 fb1 前 32 字节: %s" % before)
        # ★ 明确 invalidate fb1，确保之后读到的是 DDR 真值
        cnn.fb1.invalidate()
        before = cnn.fb1.as_u8(32)

        t0 = time.time()
        cnn.cpq.w(C.R_AP, 1)
        while not (cnn.cpq.r(C.R_AP) & 2):
            if time.time() - t0 > 5:
                print("  !! conv1 超时")
                break
            time.sleep(0.0002)
        dt = time.time() - t0
        print("  conv1 耗时 %.2f ms" % (dt * 1000))

        time.sleep(0.05)
        cnn.fb1.invalidate()
        after = cnn.fb1.as_u8(32)
        print("  跑之后 fb1 前 32 字节: %s" % after)
        print("  变化: %s" % ("有变化 ✓" if before != after else "★ 没变 —— 加速器没往这里写"))

        nz = sum(1 for b in cnn.fb1.as_u8() if b != 0)
        print("  fb1 非零字节数: %d / %d" % (nz, cnn.fb1.size))

        if nz:
            print("\n  --- fb1 前 32 字节(有符号) ---")
            print("  %s" % cnn.fb1.as_i8()[:32])
            print("  --- 期望（CPU 参考第一通道开头）---")

        print("\n--- 4) 结论 ---")
        if before == after and nz == 0:
            print("  ★ fb1 完全没被写 -> m_axi 数据通路问题")
            print("     可能原因：")
            print("       a) HP3 上没有给这个 m_axi 主控分配地址段")
            print("       b) 缓存没刷（CPU 写的数据加速器看不到）")
            print("       c) AXI 互联配置问题")
        else:
            print("  fb1 有数据 -> 数据通路是通的，问题在后面的层或精度")

    finally:
        cnn.close()


if __name__ == "__main__":
    if os.geteuid() != 0:
        sys.exit("需要 root: sudo python3 %s" % os.path.basename(__file__))
    main()
