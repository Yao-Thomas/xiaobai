#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""reg03_bit_isolation.py —— 逐位隔离 0x03，判定"PdnMICB 到底有没有用"

════════════════════════════════════════════════════════════════════
要解决什么
════════════════════════════════════════════════════════════════════
交接文档第 287 行写着"麦克风偏置被厂家配置关掉了，这是采集不稳的根因"，
依据是 0x03 从 0x59 改成 0x51 后变稳（两位只差 bit3 = PdnMICB）。

查证结果：
  * 官方手册第 14 页确认 bit3 **确实**是 PdnMICB（0=开/1=关）—— 位名没错
  * 但原理图上 ES8388 **没有独立 MICBIAS 引脚**（只有 LIN1/RIN1/LIN2/RIN2/
    VMID/ADCVREF/VREF），VMID 只挂 3×10µF 到 AGND；麦克风偏置网络是
    R36(2K)+C34/C36/C38/C92+R37(680R)，而 R36 另一端在现有截图上出了画面
  * ⇒ **"改 bit3 见效"没有可解释的物理路径**，很可能是假相关

所以做逐位隔离：把 0x03 每一位单独翻，用**能区分纯音与噪声的判据**来判定。

判据（PC 离线测试台 test_audio_math.py 标定的）：
    纯音 990.5 Hz -> 平坦度 765,452
    白噪声        -> 平坦度 1.70
    斜坡伪数据    -> 平坦度 2.01
  ⇒ **平坦度 > 100 才算采到真信号**（早期用的 >1.8 形同虚设）

════════════════════════════════════════════════════════════════════
0x03 逐位表（手册第 14 页）
════════════════════════════════════════════════════════════════════
  bit6 PdnAINR        1 = 右模拟输入断电
  bit5 PdnADCL        0 = 左 ADC 上电   <- 麦克风走 LIN1，必须 0
  bit4 PdnADCR        0 = 右 ADC 上电
  bit3 PdnMICB        0 = 麦克风偏置开  <- ★ 本次要判定的
  bit2 PdnADCBiasgen  0 = 正常
  bit1 flashLP        0 = 正常
  bit0 int1LP

★ 用法（必须先停音频服务，它是独占设备的）:
    sudo systemctl stop zynq-audio
    sudo python3 /home/zynq/ui/reg03_bit_isolation.py --trials 8
    sudo systemctl start zynq-audio          # 实验完记得恢复
"""
import argparse
import json
import math
import sys
import time

sys.path.insert(0, "/home/zynq/ui")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import audio_pl as A                                          # noqa: E402
from audio_pl import AudioOut, make_sine, es8388_set_vol      # noqa: E402
from rec_big import RawCap, s24                               # noqa: E402

FS = A.FS
BIG = 8388607.0

# 除 0x03 外，其余按"已知可用配置"写死
BASE_REGS = [
    (0x08, 0x00), (0x00, 0x06), (0x01, 0x50), (0x02, 0x00),
    (0x09, 0x66), (0x0A, 0x00), (0x0B, 0x02), (0x0C, 0x00), (0x0D, 0x02),
    (0x10, 0x00), (0x11, 0x00), (0x18, 0x03), (0x2B, 0x80),
    (0x1A, 0x00), (0x1B, 0x00), (0x27, 0xF8), (0x2A, 0xF8),
]

# 0x03 的候选值（都保证 bit5 PdnADCL = 0，即左 ADC 上电）
CASES = [
    (0x51, "基准: ADCL开 MICB开 ADCBiasgen正常"),
    (0x59, "★只翻 bit3: MICB 关（文档说的'厂家值'）"),
    (0x55, "只翻 bit2: ADCBiasgen 断电"),
    (0x71, "只翻 bit4: 右 ADC 也上电"),
    (0x11, "只翻 bit6: 右模拟输入上电"),
    (0x41, "翻 bit3+bit2: MICB关 + ADCBiasgen断电"),
    (0x50, "MICB开, 但 bit0 int1LP=0"),
    (0x00, "全 0（所有模块上电）—— 最宽松对照"),
]


def rms(v):
    return 0.0 if not v else math.sqrt(sum(float(x) * x for x in v) / len(v))


def left_of(d):
    """按 8 字节/帧取左声道 24bit 样本"""
    return [s24(int.from_bytes(d[8 * i:8 * i + 4], "little"))
            for i in range(len(d) // 8)]


def goe(v, f, rate=FS):
    """加窗 Goertzel 能量"""
    n = len(v)
    if n < 32:
        return 0.0
    w = 2.0 * math.pi * f / rate
    c = 2.0 * math.cos(w)
    s0 = s1 = s2 = 0.0
    for i, x in enumerate(v):
        win = 0.5 - 0.5 * math.cos(2.0 * math.pi * i / (n - 1))
        s0 = x * win + c * s1 - s2
        s2 = s1
        s1 = s0
    return s1 * s1 + s2 * s2 - c * s1 * s2


def flatness(vals):
    if not vals:
        return 0.0
    s = sorted(vals)
    med = s[len(s) // 2]
    if med <= 0:
        return 1e9 if max(s) > 0 else 0.0
    return max(s) / med


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=8)
    ap.add_argument("--freq", type=float, default=990.53)
    ap.add_argument("--secs", type=float, default=0.5)
    ap.add_argument("--amp", type=float, default=0.9)
    ap.add_argument("--out", default="/tmp/reg03_result.json")
    a = ap.parse_args()

    print("=" * 80)
    print("0x03 逐位隔离实验  |  纯音 %.2f Hz  |  每配置 %d 次" % (a.freq, a.trials))
    print("判据: 平坦度 > 100 才算'采到真信号'（PC 测试台标定）")
    print("=" * 80)

    cap = RawCap(verbose=False)
    ao = AudioOut()
    ao.codec_up()
    ao.fmt_config()
    es8388_set_vol(ao.i2c, 30, 0)

    i2c = cap.i2c
    for r, v in BASE_REGS:
        i2c.wr(r, v)
    i2c.wr(0x03, 0x51)
    time.sleep(0.3)

    # 两个 I2S 都要开：BCLK = AND(tx_sclk, rx_sclk)，codec 的 LRCK 来自接收器
    mem = cap.mem
    mem.wr(A.I2S_RX_BASE, A.I2S_CORE_CTRL, 1)
    mem.wr(A.I2S_BASE, A.I2S_CORE_CTRL, 1)

    # ---- 把播放环填满纯音：它会一直循环播，整个实验期间都在响 ----
    frames = ao.period_bytes // A.BYTES_PER_FRAME
    tone = make_sine(a.freq, frames=frames, amp=a.amp, pack=ao.pack)
    ao.buf.write(0, (tone * 8)[:ao.ring])
    print("播放环已填满 %.2f Hz 纯音（loop 播放，实验期间持续响）\n"
          % a.freq)

    def grab(secs):
        """★ 先 cfg 复位，再采；第一次采完丢一次（寄存器变更瞬态）"""
        cap.cfg()
        cap.grab(min(secs, 0.8 * cap.ring / 352800.0))
        cap.cfg()
        d, _ = cap.grab(min(secs, 0.8 * cap.ring / 352800.0))
        return left_of(d)

    print("%-10s %-8s %-11s %-12s %-8s %s"
          % ("0x03", "RMS中位", "峰值中位", "平坦度中位", "抖动", "活/总"))
    print("-" * 80)

    results = {}
    for val, desc in CASES:
        i2c.wr(0x03, val)
        time.sleep(0.35)
        grab(a.secs)                    # 丢弃瞬态
        rl, pl, fl = [], [], []
        for t in range(a.trials):
            v = grab(a.secs)
            if not v:
                continue
            rl.append(rms(v))
            pl.append(max(abs(x) for x in v))
            fl.append(flatness([goe(v, a.freq * k) for k in (1, 2, 3)]))
            time.sleep(0.06)
        if not rl:
            print("%-10s  (没采到数据)" % ("0x%02X" % val))
            continue
        rl_s, fl_s = sorted(rl), sorted(fl)
        jit = (max(rl) - min(rl)) / max(1e-9, rl_s[len(rl) // 2])
        alive = sum(1 for f in fl if f > 100)
        results["0x%02X" % val] = {
            "desc": desc, "n": len(rl),
            "rms_med": rl_s[len(rl) // 2], "rms_min": min(rl), "rms_max": max(rl),
            "peak_med": sorted(pl)[len(pl) // 2],
            "flat_med": fl_s[len(fl) // 2], "flat_max": max(fl),
            "jitter": jit, "alive": alive,
        }
        print("%-10s %-8.0f %-11.0f %-12.1f %-8.2f %d/%d"
              % ("0x%02X" % val, rl_s[len(rl) // 2],
                 sorted(pl)[len(pl) // 2], fl_s[len(fl) // 2], jit,
                 alive, len(fl)))

    # 收尾：停音、恢复
    ao.buf.write(0, b"\x00" * ao.ring)
    i2c.wr(0x03, 0x51)
    ao.close()
    cap.close()

    print("-" * 80)
    base, off = results.get("0x51"), results.get("0x59")
    if base and off:
        b, m = max(base["flat_med"], 1e-9), max(off["flat_med"], 1e-9)
        ratio = m / b
        print()
        print("★ 关键对比：0x51(MICB开)  vs  0x59(MICB关)")
        print("   平坦度中位 %.1f  vs  %.1f   比值 %.2f" % (base["flat_med"],
                                                          off["flat_med"], ratio))
        print("   RMS中位    %.0f  vs  %.0f" % (base["rms_med"], off["rms_med"]))
        if ratio > 3 or ratio < 0.33:
            print("   => 差异显著: PdnMICB **确实**影响采集，文档结论成立")
        else:
            print("   => 差异不显著: 当初的'0x59 是根因'是**假相关**，"
                  "文档那句话应作废")
    else:
        print("\n[!] 缺少 0x51 或 0x59 的数据，无法做关键对比")

    with open(a.out, "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print("\n结果已存: %s" % a.out)
    print("别忘了: sudo systemctl start zynq-audio")
    return 0


if __name__ == "__main__":
    sys.exit(main())
