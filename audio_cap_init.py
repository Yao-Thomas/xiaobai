#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audio_cap_init.py —— 让 ALSA 采集能用的最小初始化

════════════════════════════════════════════════════════════════════
要解决的问题
════════════════════════════════════════════════════════════════════
实测：
    · 直接 ALSA 采集（arecord -D hw:0,1）  -> -137 dBFS  数字静音
    · 跑过 rec_big.py（PL 工具）之后再采    -> -60 dBFS   有真实信号 ✓

根因：这块板子的音频链路是**全用户态 PL 驱动**（见 audio_pl.py 的说明）：
    ES8388 ADC → AXI I2S 接收器(0x43C60000) → audio formatter S2MM → DDR

  · `audio_svc.py`（PL 独占版，09-28 用的）会配置这一整套 —— 所以那时能录音
  · `audio_alsa_svc.py`（纯 ALSA 播放，现在跑的）**从不碰 PL 寄存器**
  ⇒ 换服务之后，PL 的 I2S 收发和 ES8388 的 ADC 都没人配 → 采集永远是静音

另外两个关键点（从 audio_pl.py 抄来的，有注释说明）：
  1. **I2S 接收器既是录音数据源，又是 BCLK 和 codec LRCK 的来源**
     ⇒ 录音本来就得把它打开
  2. **ES8388 的 0x0A 寄存器选输入**：
       0x00 = LIN1/RIN1 = 板载麦克风   ★ 要的是这个
       0x50 = LIN2/RIN2 = LINE_IN 插孔（厂家默认值，没插东西就没信号）

════════════════════════════════════════════════════════════════════
这个脚本干什么
════════════════════════════════════════════════════════════════════
只做两件事，不碰 DMA、不放音、不占声卡：
  ① 打开 I2S 收发器的时钟（写 CORE_CTRL = 1）
  ② 配好 ES8388 的 ADC 那半边（上电 + 选麦克风输入 + PGA + 数字音量）

做完之后 ALSA 的 arecord 就能采到信号了。

用法:
    sudo python3 audio_cap_init.py            # 初始化
    sudo python3 audio_cap_init.py --check    # 只看当前寄存器状态
    sudo python3 audio_cap_init.py --test     # 初始化 + 录 2 秒验证
"""
import argparse
import array
import fcntl
import math
import mmap
import os
import struct
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ---- PL 地址 ----
FMT_BASE = 0x43C50000          # audio formatter
I2S_RX_BASE = 0x43C60000       # ★ AXI I2S 接收器
I2S_BASE = 0x43C70000          # AXI I2S 发送器
I2S_CORE_CTRL = 0x08           # bit0 = 启动

# ---- I2C ----
I2C_SLAVE_FORCE = 0x0706
I2C_BUS = 1
I2C_ADDR = 0x10

# ---- ES8388 的 ADC 配置 ----
# ★ 这些值是照着 audio_pl.py 的 AudioIn.codec_adc_up() 抄的，
#   不是猜的。那个版本是 09-28 验证过能录音的。
ADC_IN_MIC = 0x00     # LIN1/RIN1 = 板载麦克风
ADC_IN_LINE = 0x50    # LIN2/RIN2 = LINE_IN 插孔

ADC_REGS = [
    (0x08, 0x00, "从机模式"),
    (0x00, 0x06, "参考 500K"),
    (0x01, 0x50, "模拟电源开"),
    (0x02, 0x00, "全部上电"),
    (0x03, 0x59, "★ ADC 上电（含 mic bias）"),
    (0x09, 0x66, "ADC PGA +18dB"),
    (0x0A, ADC_IN_MIC, "★ ADC 输入 = LIN1/RIN1（板载麦克风）"),
    (0x0B, 0x02, "ADC 高通/去直流"),
    (0x0C, 0x00, "ADC 数据格式 = I2S 24bit"),
    (0x0D, 0x0C, "ADC MCLK/fs"),
    (0x10, 0x00, "★ ADC 数字音量 L（反的：0 = 0dB 最大）"),
    (0x11, 0x00, "★ ADC 数字音量 R"),
]


class Codec(object):
    def __init__(self, bus=I2C_BUS, addr=I2C_ADDR):
        self.fd = os.open("/dev/i2c-%d" % bus, os.O_RDWR)
        fcntl.ioctl(self.fd, I2C_SLAVE_FORCE, addr)

    def rd(self, reg):
        os.write(self.fd, bytes([reg & 0xFF]))
        return os.read(self.fd, 1)[0]

    def wr(self, reg, val):
        os.write(self.fd, bytes([reg & 0xFF, val & 0xFF]))

    def close(self):
        try:
            os.close(self.fd)
        except Exception:
            pass


def pl_write(base, off, val):
    """写一个 PL 寄存器

    ★ 必须开子进程做 —— 直接在本进程 mmap 一个没映射的 PL 地址，
      第一次访问就是 SIGBUS，整个脚本直接死（"Bus error"）。
      hw_tools.py 那边也是同样的处理。
    """
    code = (
        "import mmap,os,struct,sys\n"
        "fd=os.open('/dev/mem', os.O_RDWR|os.O_SYNC)\n"
        "m=mmap.mmap(fd, 4096, mmap.MAP_SHARED,"
        " mmap.PROT_READ|mmap.PROT_WRITE, offset=%d)\n"
        "struct.pack_into('<I', m, %d, %d)\n"
        "print('OK')\n" % (base, off, val & 0xFFFFFFFF))
    p = subprocess.run(["python3", "-c", code], stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, timeout=10)
    return p.returncode == 0 and b"OK" in p.stdout


def pl_read(base, off):
    """读一个 PL 寄存器。★ 同样开子进程，读到空地址不会打死本进程。"""
    code = (
        "import mmap,os,struct,sys\n"
        "fd=os.open('/dev/mem', os.O_RDONLY|os.O_SYNC)\n"
        "m=mmap.mmap(fd, 4096, mmap.MAP_SHARED, mmap.PROT_READ, offset=%d)\n"
        "print(struct.unpack_from('<I', m, %d)[0])\n" % (base, off))
    p = subprocess.run(["python3", "-c", code], stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, timeout=10)
    if p.returncode != 0:
        return None
    try:
        return int(p.stdout.decode().strip().split("\n")[-1])
    except Exception:
        return None


def show_state(codec, tag):
    print("  --- %s ---" % tag)
    print("    PL: I2S_RX CORE_CTRL = 0x%08X   I2S_TX CORE_CTRL = 0x%08X"
          % (pl_read(I2S_RX_BASE, I2S_CORE_CTRL),
             pl_read(I2S_BASE, I2S_CORE_CTRL)))
    for r, _, desc in ADC_REGS:
        if r in (0x03, 0x09, 0x0A, 0x10, 0x11):
            print("    ES8388 0x%02X = 0x%02X   %s" % (r, codec.rd(r), desc))


def init_pl():
    """★ 第一步：打开 I2S 收发器的时钟

    为什么收发都要开：
      · 接收器（0x43C60000）是录音的数据源
      · 而且它同时提供 BCLK 和 codec 的 LRCK —— 不开它，ADC 就没时钟
    """
    print("【1】打开 I2S 收发器时钟")
    before_rx = pl_read(I2S_RX_BASE, I2S_CORE_CTRL)
    before_tx = pl_read(I2S_BASE, I2S_CORE_CTRL)
    print("    之前: RX=0x%08X TX=0x%08X" % (before_rx, before_tx))

    pl_write(I2S_RX_BASE, I2S_CORE_CTRL, 1)
    pl_write(I2S_BASE, I2S_CORE_CTRL, 1)

    after_rx = pl_read(I2S_RX_BASE, I2S_CORE_CTRL)
    after_tx = pl_read(I2S_BASE, I2S_CORE_CTRL)
    print("    之后: RX=0x%08X TX=0x%08X" % (after_rx, after_tx))
    ok = (after_rx & 1) and (after_tx & 1)
    print("    %s" % ("✓ 都起来了" if ok else "✗ 没起来"))
    return ok


def init_codec(codec, adc_in=ADC_IN_MIC):
    """★ 第二步：配 ES8388 的 ADC 那半边"""
    print("【2】配置 ES8388 的 ADC（输入 = %s）"
          % ("LIN1/RIN1 板载麦克风" if adc_in == ADC_IN_MIC else "LINE_IN"))
    for r, v, desc in ADC_REGS:
        if r == 0x0A:
            v = adc_in
        old = codec.rd(r)
        codec.wr(r, v)
        now = codec.rd(r)
        flag = "✓" if now == v else "★ 读回 0x%02X" % now
        print("    0x%02X: 0x%02X -> 0x%02X  %-40s %s" % (r, old, now, desc, flag))
    return True


def capture_test(secs=2.0):
    """录一段，返回 (L_dBFS, R_dBFS, L_peak)"""
    dur = int(math.ceil(secs))
    p = subprocess.run(
        ["arecord", "-q", "-D", "hw:0,1", "-f", "S24_LE", "-c", "2",
         "-r", "44100", "-d", str(dur), "-t", "raw"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=dur + 15)
    if p.returncode != 0:
        return None, p.stderr.decode(errors="replace")[:150]
    raw = p.stdout[:int(secs * 44100) * 8]
    a = array.array("i")
    a.frombytes(raw[:len(raw) & ~3])
    for i in range(len(a)):
        if a[i] >= 0x800000:
            a[i] -= 0x1000000
    L = a[0::2]
    R = a[1::2]
    out = []
    for xs in (L, R):
        if not xs:
            out.append(-999.0)
            continue
        rms = math.sqrt(sum(float(x) * x for x in xs) / len(xs))
        out.append(20 * math.log10(rms / 8388608.0) if rms > 0 else -999.0)
    pk = max(abs(x) for x in L) if L else 0
    return (out[0], out[1], pk), None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只看状态，不改")
    ap.add_argument("--test", action="store_true", help="初始化 + 录 2 秒验证")
    ap.add_argument("--line", action="store_true", help="选 LINE_IN 而不是麦克风")
    a = ap.parse_args()

    if os.geteuid() != 0:
        sys.exit("需要 root: sudo python3 %s" % os.path.basename(__file__))

    print("=" * 74)
    print(" 音频采集初始化（让 ALSA 采集能用）")
    print("=" * 74)

    codec = Codec()
    try:
        if a.check:
            show_state(codec, "当前状态")
            return 0

        show_state(codec, "初始化前")

        print()
        init_pl()

        print()
        init_codec(codec, ADC_IN_LINE if a.line else ADC_IN_MIC)

        print()
        show_state(codec, "初始化后")

        if a.test:
            print()
            print("【3】录 2 秒验证")
            r, err = capture_test(2.0)
            if r is None:
                print("    ★ 录音失败: %s" % err)
                return 1
            L, R, pk = r
            print("    L = %.1f dBFS    R = %.1f dBFS    峰值 = %d" % (L, R, pk))
            if L > -100:
                print("    ★★★ 有信号！采集通路打通了")
            else:
                print("    ★ 还是静音 —— 检查耳机/麦克风是不是真的接上了")

        print()
        print("=" * 74)
        print(" 完成。现在 ALSA 的 arecord 应该能采到信号了。")
        print("=" * 74)
        return 0
    finally:
        codec.close()


if __name__ == "__main__":
    sys.exit(main() or 0)
