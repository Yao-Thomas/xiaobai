#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rate_silent.py —— **静默**精确测放音速率（DAC 数字静音，不出声）

═══ 为什么要静默测 ═══
用户对"未经同意就出声"很敏感。而速率这个量**不需要听**，
只要密集采样 formatter 的传输计数（R_XFER）就能算出来。

═══ 为什么之前的测量不可信 ═══
之前用 poll_pos() 两次采样，结果出现**负值**（说明计数器回绕），
而且单位不明确（字节？帧？）。这次：
  * 用 R_XFER（AUD_XFER_COUNT），**每 50 ms 采一次，采 2 秒（40 个点）**
  * 用**差分的中位数**估速率，回绕点自动识别并剔除
  * 同时读 R_STS 看有没有错误位

═══ 要回答的问题 ═══
放音速率到底是多少？以及 I2STIM 分频改变时它怎么变？
    * 若 I2STIM 变小、速率成比例变大  -> 分频有效，调到合适值即可
    * 若怎么调都远低于 44100          -> MCLK 源本身慢，要动 FPGA 时钟

★ 全程 DAC 数字静音（0x1A/0x1B = 0xC0 = -96dB），一点声都没有。
"""
import statistics
import sys
import time

sys.path.insert(0, "/home/zynq/ui")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import audio_pl as A                                          # noqa: E402
from audio_pl import AudioOut, es8388_set_vol                 # noqa: E402

MUTE = 0xC0
R_CTRL = A.MM2S + 0x10
R_STS = A.MM2S + 0x14
R_XFER = A.MM2S + 0x28


def main():
    print("=" * 84)
    print("静默测放音速率（DAC 数字静音，不出声）")
    print("=" * 84)

    ao = AudioOut()
    ao.codec_up()
    ao.i2s_config()
    ao.fmt_config()
    # ★ 压静音：输出音量 0 + DAC 数字 -96dB
    es8388_set_vol(ao.i2c, 0, MUTE)
    if ao.i2c.rd(0x1A) != MUTE:
        print("  ✗ 静音没设上，中止")
        return 2
    ao.start()
    # start() 之后 codec 可能被重设，再压一次
    es8388_set_vol(ao.i2c, 0, MUTE)
    mem = ao.mem
    print("  DAC 已静音: 0x1A=0x%02X 0x1B=0x%02X  输出音量=%d"
          % (ao.i2c.rd(0x1A), ao.i2c.rd(0x1B), ao.i2c.rd(0x2E) & 0x3F))
    print("  播放环 = %d 字节 = %d 帧 = %.4f 秒（标称）"
          % (ao.ring, ao.ring // 8, ao.ring / 352800.0))
    print()

    def sample(span=2.0, dt=0.05):
        """密集采样 R_XFER，返回 (速率单位/秒, 原始点列表)"""
        pts = []
        t0 = time.time()
        while time.time() - t0 < span:
            pts.append((time.time() - t0, mem.rd(A.FMT_BASE, R_XFER)))
            time.sleep(dt)
        # 差分，剔除负值（回绕）
        diffs = []
        for i in range(1, len(pts)):
            d = pts[i][1] - pts[i - 1][1]
            if d < 0:
                continue                    # 回绕，跳过
            dtt = pts[i][0] - pts[i - 1][0]
            if dtt > 0:
                diffs.append(d / dtt)
        if not diffs:
            return 0.0, pts
        return statistics.median(diffs), pts

    print("--- 1) 不碰 I2STIM（保持默认 %d）---" % A.I2S_DIV)
    r, pts = sample()
    print("  R_XFER 首末: %s -> %s" % (pts[0][1], pts[-1][1]))
    print("  速率(中位数) = %.0f 单位/秒" % r)
    if r > 0:
        print("    若单位=字节: %.0f 帧/秒 = %.0f Hz 有效采样率"
              % (r / 8, r / 8))
        print("    期望        : 352800 字节/秒 = 44100 帧/秒")
        print("    比值(实测/期望, 按字节) = %.4f" % (r / 352800.0))
    st = mem.rd(A.FMT_BASE, R_STS)
    ctrl = mem.rd(A.FMT_BASE, R_CTRL)
    print("  R_STS=0x%08X  R_CTRL=0x%08X (DMA_EN=%d)"
          % (st, ctrl, ctrl & 1))
    print()

    print("--- 2) 扫 I2STIM，看速率怎么变 ---")
    print("  %-8s %-14s %-14s %s" % ("I2STIM", "速率(单位/秒)", "折算帧/秒", "相对默认"))
    print("  " + "-" * 60)
    base = None
    results = {}
    for div in (4, 2, 1, 3, 8, 16):
        ao._i2s_w(A.I2S_I2STIM, div)
        ao._rx_w(A.I2S_I2STIM, div)
        ao._rx_w(A.I2S_CORE_CTRL, 1)
        ao._i2s_w(A.I2S_CORE_CTRL, 1)
        es8388_set_vol(ao.i2c, 0, MUTE)         # 每轮都确保静音
        time.sleep(0.25)
        r, _ = sample(span=1.4)
        results[div] = r
        if div == 4:
            base = r
        rel = ("%.2fx" % (r / base)) if (base and base > 0) else "-"
        print("  %-8d %-14.0f %-14.0f %s"
              % (div, r, r / 8, rel))
        # 确认写进去了
        txv = mem.rd(A.I2S_BASE, A.I2S_I2STIM)
        rxv = mem.rd(A.I2S_RX_BASE, A.I2S_I2STIM)
        if txv != div or rxv != div:
            print("        ⚠ 读回 TX=%s RX=%s（写入没生效？）" % (txv, rxv))

    # 恢复
    ao._i2s_w(A.I2S_I2STIM, A.I2S_DIV)
    ao._rx_w(A.I2S_I2STIM, A.I2S_DIV)
    ao.buf.write(0, b"\x00" * ao.ring)
    time.sleep(0.2)
    try:
        ao.close()
    except Exception:
        pass

    print()
    print("=" * 84)
    print("判读")
    print("=" * 84)
    if base and base > 0:
        d1 = results.get(1, 0)
        print("  I2STIM=4 -> %.0f 单位/秒" % base)
        print("  I2STIM=1 -> %.0f 单位/秒  (%.2fx)" % (d1, d1 / base))
        if d1 > base * 1.5:
            print("  ★ 分频有效：变小 -> 速率变大")
            need = 352800.0 / (d1 / 8) if d1 else 0
            print("    即使 I2STIM=1，折算帧率 %.0f，还需再快 %.1f 倍"
                  % (d1 / 8, need))
            print("    => 光靠分频**调不到 44100**，源时钟本身慢")
        else:
            print("  ⚠ 改分频几乎没影响 -> 速率不由 I2STIM 决定")
            print("    => 要查 formatter 的周期/中断配置")
        print()
        print("  若折算帧率远小于 44100，且调分频救不回来，")
        print("  下一步就是查 MCLK 的来源（FPGA 时钟树 / 板载晶振）。")
    print()
    print("  ★ 全程 DAC 数字静音（0x%02X），没有发出任何声音。" % MUTE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
