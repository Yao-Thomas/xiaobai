#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次性连续录音 —— 最不容易出错的采集方式。

做法:
  * S2MM 用大环形 (period 32768 x 16 = 512KB)，录 0.5s 只写 ~176KB -> 绝不回绕
  * 停止 DMA **之后**再从缓冲偏移 0 线性读出来 —— 顺序天然正确，不需要按写指针旋转
  * 因此不存在"读到正在被覆盖的区域"和"旋转算错"这两类假数据

用法:
    sudo python3 rec_big.py                # 放音ON / OFF / ON 三次对照
    sudo python3 rec_big.py --freq 1000 --secs 0.5
"""
import sys
import time
import math

sys.path.insert(0, "/home/zynq/ui")
import audio_pl as A                                          # noqa: E402
from audio_pl import (Mem, I2C, DmaBuffer, AudioOut, make_sine,   # noqa: E402
                      es8388_set_vol, FMT_BASE, R2_CTRL, R2_STS, R2_FS_MULT,
                      R2_PERIOD, R2_BUF_LSB, R2_BUF_MSB, R2_XFER,
                      R2_BYTES_PER_CH, CTRL_RESET, CTRL_DW_SHIFT,
                      CTRL_CH_SHIFT, CTRL_DMA_EN, CTRL_IOC_IRQ,
                      CTRL_TOUT_IRQ, BIT_DEPTH, CHANNELS, MCLK_RATIO,
                      STS_IOC, STS_CH_STS, I2S_RX_BASE, I2S_BASE,
                      I2S_CORE_CTRL, I2S_I2STIM, I2S_CH0, I2S_DIV)


def arg(name, default=None, cast=str):
    if name in sys.argv:
        i = sys.argv.index(name)
        if i + 1 < len(sys.argv):
            return cast(sys.argv[i + 1])
    return default


def s24(w):
    w &= 0xFFFFFF
    return w - 0x1000000 if w & 0x800000 else w


class RawCap(object):
    """一次性连续录音，停 DMA 后线性读。"""

    def __init__(self, ring_kb=2048, verbose=True):
        self.verbose = verbose
        self.mem = Mem()
        self.i2c = I2C()
        # 连续内存碎片化会让大块分配失败 -> 从大到小重试
        self.buf = None
        for kb in (ring_kb, 1536, 1024, 768, 512, 384, 256, 192, 128):
            kb = min(kb, ring_kb)
            try:
                self.buf = DmaBuffer(kb << 10, verbose=False)
                if verbose:
                    print("[dma] 拿到 %d KB 连续缓冲 @ 0x%08X"
                          % (self.buf.avail // 1024, self.buf.phys))
                break
            except Exception as e:
                if verbose:
                    print("[dma] %d KB 失败(%s)，退一档" % (kb, e))
        if self.buf is None:
            raise RuntimeError("连 128KB 连续内存都拿不到，重启板子再试")
        self.period_bytes = 32768
        self.periods = max(1, min(16, (self.buf.avail // self.period_bytes)))
        self.ring = self.period_bytes * self.periods
        assert self.ring <= self.buf.avail

    def cfg(self):
        m = self.mem
        m.wr(FMT_BASE, R2_CTRL, m.rd(FMT_BASE, R2_CTRL) | CTRL_RESET)
        for _ in range(200):
            if not (m.rd(FMT_BASE, R2_CTRL) & CTRL_RESET):
                break
            time.sleep(0.001)
        ctrl = m.rd(FMT_BASE, R2_CTRL)
        ctrl &= ~(0x7 << CTRL_DW_SHIFT)
        ctrl |= BIT_DEPTH[32] << CTRL_DW_SHIFT      # 32bit: 旁路 aes_dec
        ctrl &= ~(0xF << CTRL_CH_SHIFT)
        ctrl |= CHANNELS << CTRL_CH_SHIFT
        ctrl &= ~(CTRL_DMA_EN | CTRL_IOC_IRQ | CTRL_TOUT_IRQ)
        m.wr(FMT_BASE, R2_CTRL, ctrl)
        m.wr(FMT_BASE, R2_FS_MULT, MCLK_RATIO)
        m.wr(FMT_BASE, R2_PERIOD, (self.periods << 16) | self.period_bytes)
        m.wr(FMT_BASE, R2_BYTES_PER_CH, self.period_bytes // CHANNELS)
        m.wr(FMT_BASE, R2_BUF_LSB, self.buf.phys & 0xFFFFFFFF)
        m.wr(FMT_BASE, R2_BUF_MSB, (self.buf.phys >> 32) & 0xFFFFFFFF)
        m.wr(FMT_BASE, R2_STS, STS_IOC | STS_CH_STS)
        if self.verbose:
            print("[cap] ring=%d B (%d x %d) @ 0x%08X  位宽字段=%d"
                  % (self.ring, self.periods, self.period_bytes, self.buf.phys,
                     (ctrl >> CTRL_DW_SHIFT) & 0x7))

    def grab(self, secs):
        """录 secs 秒，返回 (字节串, 实测速率 B/s)"""
        m = self.mem
        m.wr(FMT_BASE, R2_STS, STS_IOC | STS_CH_STS)
        m.wr(FMT_BASE, R2_CTRL, m.rd(FMT_BASE, R2_CTRL) | CTRL_DMA_EN)
        x0 = m.rd(FMT_BASE, R2_XFER)
        time.sleep(secs)
        x1 = m.rd(FMT_BASE, R2_XFER)
        m.wr(FMT_BASE, R2_CTRL, m.rd(FMT_BASE, R2_CTRL) & ~CTRL_DMA_EN)
        n = x1 - x0
        if n < 0:
            n += self.ring
        assert n < self.ring, "回绕了，减少 --secs 或加大 ring"
        return self.buf.read(0, n), n / secs

    def close(self):
        for fn in (self.i2c.close, self.buf.close, self.mem.close):
            try:
                fn()
            except Exception:
                pass


def analyze(d, freq, tag):
    ls, rs = [], []
    for i in range(len(d) // 8):
        ls.append(s24(int.from_bytes(d[8 * i:8 * i + 4], "little")))
        rs.append(s24(int.from_bytes(d[8 * i + 4:8 * i + 8], "little")))
    if not ls:
        print("%s  空" % tag)
        return None
    rl = math.sqrt(sum(float(x) * x for x in ls) / len(ls))
    rr = math.sqrt(sum(float(x) * x for x in rs) / len(rs))
    ml = sum(ls) / len(ls)

    def goe(v, f):
        w = 2.0 * math.pi * f / A.FS
        c = 2.0 * math.cos(w)
        s1 = s2 = 0.0
        for x in v:
            s0 = x + c * s1 - s2
            s2, s1 = s1, s0
        return math.sqrt(max(0.0, s1 * s1 + s2 * s2 - c * s1 * s2)) / (len(v) / 2.0)

    g = goe(ls, freq)
    # 粗扫峰值
    best, bf = -1.0, 0
    f = 200
    while f <= 5000:
        v = goe(ls, f)
        if v > best:
            best, bf = v, f
        f += 100
    uniq_l = len(set(ls))
    print("%s  样本=%d  L_RMS=%.1f R_RMS=%.1f  均值L=%.1f  L唯一值=%d"
          % (tag, len(ls), rl, rr, ml, uniq_l))
    print("        @%.0fHz=%.1f  峰值=%dHz(%.1f)  前6帧=%s"
          % (freq, g, bf, best,
             " ".join("(%d,%d)" % (ls[i], rs[i]) for i in range(min(6, len(ls))))))
    return rl, g, bf


def main():
    freq = arg("--freq", 1000.0, float)
    secs = arg("--secs", 0.5, float)
    amp = arg("--amp", 0.9, float)
    vol = arg("--vol", 30, int)

    # ---- 播放侧（顺带把 codec 初始化好）----
    ao = AudioOut()
    ao.codec_up()
    ao.i2s_config()
    ao.fmt_config()
    es8388_set_vol(ao.i2c, vol, 0)

    cap = RawCap()
    cap.cfg()
    # 录音时长不能超过环形的 90%，否则 DMA 回绕，线性读就不成立了
    lim = 0.9 * cap.ring / 352800.0
    if secs > lim:
        print("[warn] ring 只有 %d B，%.2fs 会回绕 -> 收到 %.2fs"
              % (cap.ring, secs, lim))
        secs = lim
    # ADC 那一半
    i2c = cap.i2c
    i2c.wr(0x08, 0x00)
    i2c.wr(0x00, 0x06)
    i2c.wr(0x01, 0x50)
    i2c.wr(0x02, 0x00)
    i2c.wr(0x03, 0x59)
    i2c.wr(0x09, 0x66)
    i2c.wr(0x0A, 0x00)          # LIN1/RIN1 = MIC_P/MIC_N
    i2c.wr(0x0B, 0x02)
    i2c.wr(0x0C, 0x00)
    i2c.wr(0x0D, 0x0C)
    i2c.wr(0x10, 0x00)
    i2c.wr(0x11, 0x00)

    frames = max(64, ao.period_bytes // A.BYTES_PER_FRAME)
    tone = make_sine(freq, frames=frames, amp=amp, pack=ao.pack)
    tone_bytes = (tone * 8)[:ao.ring]
    sil_bytes = b"\x00" * ao.ring

    cap.mem.wr(I2S_RX_BASE, I2S_CORE_CTRL, 1)
    cap.mem.wr(I2S_BASE, I2S_CORE_CTRL, 1)
    ao.buf.write(0, sil_bytes)
    ao.start()
    time.sleep(0.25)            # 让静音铺满播放环形

    print("[cfg] 0x03=0x%02X 0x09=0x%02X 0x0A=0x%02X 0x0D=0x%02X "
          "0x18=0x%02X 0x2B=0x%02X 放音%.0fHz amp%.2f vol%d"
          % (i2c.rd(0x03), i2c.rd(0x09), i2c.rd(0x0A), i2c.rd(0x0D),
             i2c.rd(0x18), i2c.rd(0x2B), freq, amp, vol))

    trials = [("静音", sil_bytes), ("放音", tone_bytes),
              ("静音", sil_bytes), ("放音", tone_bytes)]
    out = {}
    for i, (tag, content) in enumerate(trials):
        ao.buf.write(0, content)
        time.sleep(0.30)        # 等播放环形整圈换掉
        d, rate = cap.grab(secs)
        print("\n--- 第%d次: %s  实测 %.0f B/s (%.1f 帧/s) ---"
              % (i, tag, rate, rate / A.BYTES_PER_FRAME))
        r = analyze(d, freq, "   ")
        if r:
            out.setdefault(tag, []).append(r)

    print("\n================ 汇总 ================")
    for tag in ("静音", "放音"):
        v = out.get(tag, [])
        if v:
            print("  %s: L_RMS=%s  @%.0fHz=%s" %
                  (tag, ["%.1f" % x[0] for x in v], freq,
                   ["%.1f" % x[1] for x in v]))
    if out.get("静音") and out.get("放音"):
        go = sum(x[1] for x in out["放音"]) / len(out["放音"])
        gf = sum(x[1] for x in out["静音"]) / len(out["静音"])
        db = 20 * math.log10(max(1e-9, go) / max(1e-9, gf))
        print("  => @%.0fHz 放音/静音 = %.2fx (%+.1f dB)  %s"
              % (freq, go / max(1e-9, gf), db,
                 "★★ 麦克风听到放音了" if db > 6 else
                 "（没听到：ADC 通路或麦克风有问题）"))
        ro = sum(x[0] for x in out["放音"]) / len(out["放音"])
        rf = sum(x[0] for x in out["静音"]) / len(out["静音"])
        print("  => L_RMS  放音/静音 = %.2fx" % (ro / max(1e-9, rf)))

    ao.buf.write(0, sil_bytes)
    time.sleep(0.1)
    ao.stop()
    ao.close()
    cap.close()


if __name__ == "__main__":
    main()
