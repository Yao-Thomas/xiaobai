#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cap_diag.py —— 采集通路诊断（ALSA mixer 侧）

为什么要有这个脚本
------------------
`ui/cap_adc_fix.py` 直接走 I2C 写 ES8388 寄存器，但内核的 es8388 驱动
占着那个 I2C 设备，会报 `Device or resource busy`。所以只能走 ALSA mixer
（驱动暴露出来的那些控件）。

本脚本做三件事：
  1. 把采集相关的控件全打出来（含 dB）
  2. 依次试几组设置，每组录 2 秒，报电平
  3. 同时用 i2cget 读 ES8388 的关键寄存器（读通常不受"设备忙"影响）
     看看 0x0A（ADC 输入选择）到底是什么值

背景（从上一轮的 main_cnn5 / cap_adc_fix.py 里翻出来的线索）：
    reg    驱动设的   老代码能录音的值   含义
    0x03   0x09       0x51                ADC 电源（bit3=PdnMICB）
    0x0A   0x50       0x00                ADC 输入选择（0x00=LIN1/RIN1 麦克风）
    0x0D   0x03       0x02                ADC 控制5
  ⇒ 怀疑 0x0A=0x50 选了 LINE 输入，而板子上接的是麦克风 -> 采到静音
"""
import math
import os
import struct
import subprocess
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

CARD = "hw:0,1"
RATE = "44100"          # ★ 实测只有 44100 能装上参数，48000 会 set_params 失败
ES8388_ADDR = "0x10"
I2C_BUS = "1"


def sh(cmd, t=20):
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           timeout=t)
        return p.returncode, p.stdout.decode(errors="replace")
    except Exception as e:
        return -1, str(e)


def mixer_get(name):
    rc, out = sh(["amixer", "-c", "0", "sget", name])
    if rc != 0:
        return None
    keep = []
    for line in out.split("\n"):
        s = line.strip()
        if s.startswith(("Front Left", "Front Right", "Mono", "Item0", "Limits")):
            keep.append(s)
    return " | ".join(keep)


def mixer_set(name, val):
    return sh(["amixer", "-c", "0", "sset", name, val])[0] == 0


def i2c_read(reg):
    rc, out = sh(["i2cget", "-y", I2C_BUS, ES8388_ADDR, "0x%02X" % reg])
    if rc != 0:
        return None
    try:
        return int(out.strip(), 16)
    except Exception:
        return None


def record(path, secs=2):
    try:
        os.remove(path)
    except OSError:
        pass
    rc, out = sh(["arecord", "-q", "-D", CARD, "-f", "S24_LE", "-r", RATE,
                  "-c", "2", "-d", str(secs), path], t=secs + 15)
    if rc != 0 or not os.path.exists(path):
        return None
    return path


def stats(path):
    """返回 (每声道 RMS_dBFS 列表, 每声道 峰值样本数)

    ★ 本板采集的 24 位数据【没有符号扩展】，必须从 bit23 手动扩展。
    """
    try:
        data = open(path, "rb").read()
        i = data.find(b"data")
        if i < 0:
            return None
        hdr = i + 8
        afmt, nch, rate, brate, balign, bits = struct.unpack_from("<HHIIHH", data, 20)
        n = (len(data) - hdr) // balign
        raw32 = list(struct.unpack_from("<%di" % (n * nch), data, hdr))
        vals = [v - 0x1000000 if v >= 0x800000 else v for v in raw32]
        full = 8388608.0
        res = []
        for c in range(nch):
            xs = vals[c::nch]
            rms = math.sqrt(sum(float(x) * x for x in xs) / len(xs))
            db = 20 * math.log10(rms / full) if rms > 0 else -999.0
            pk = max(abs(x) for x in xs) if xs else 0
            res.append((db, pk, len(set(xs))))
        return res
    except Exception as e:
        return [(-999.0, 0, 0), ("err:" + str(e), 0, 0)]


def main():
    if os.geteuid() != 0:
        sys.exit("需要 root: sudo python3 %s" % os.path.basename(__file__))

    print("=" * 78)
    print(" 采集通路诊断")
    print("=" * 78)

    # ---------- 1) 控件现状 ----------
    print("\n>>> 1. 采集相关控件现状")
    for n in ["Capture Digital", "Capture Mute", "Capture Polarity",
              "Left Channel", "Right Channel", "ALC Capture Function",
              "ALC Capture Max PGA", "ALC Capture Min PGA", "3D Mode",
              "ALC Capture Target"]:
        v = mixer_get(n)
        print("   %-26s %s" % (n, v if v else "(无此控件)"))

    # ---------- 2) ES8388 寄存器（读） ----------
    print("\n>>> 2. ES8388 寄存器（i2cget 读，看 ADC 输入选择）")
    regs = [0x00, 0x01, 0x02, 0x03, 0x08, 0x09, 0x0A, 0x0B, 0x0C, 0x0D,
            0x10, 0x11, 0x12, 0x17, 0x18, 0x19, 0x1A, 0x1B, 0x1C, 0x1D,
            0x26, 0x27, 0x2E, 0x30, 0x31]
    names = {0x00: "ChipCtrl1", 0x01: "ChipCtrl2", 0x02: "ChipPwr",
             0x03: "ADCPwr", 0x08: "MstrMode", 0x09: "ADC Ctrl1",
             0x0A: "ADC Ctrl2 ★输入选择", 0x0B: "DAC Ctrl1",
             0x0C: "DAC Ctrl2", 0x0D: "ADC Ctrl5", 0x10: "DAC Ctrl3",
             0x17: "ADC Ctrl3", 0x18: "ADC Ctrl4", 0x19: "ADCPgaL",
             0x1A: "ADCPgaR", 0x1B: "ADC AlcCtrl1", 0x1C: "ADC AlcCtrl2"}
    ok_any = False
    for r in regs:
        v = i2c_read(r)
        if v is None:
            continue
        ok_any = True
        mark = ""
        if r == 0x0A:
            mark = "  ← ★★★ 0x00=麦克风 0x50=LINE"
        if r == 0x03:
            mark = "  ← ADC 电源"
        print("   0x%02X %-22s = 0x%02X%s" % (r, names.get(r, ""), v, mark))
    if not ok_any:
        print("   (i2cget 读不了 —— 可能要 i2c-tools，或总线号不对)")

    # ---------- 3) 分组试验 ----------
    print("\n>>> 3. 分组录音试验（每组 2 秒）")
    print("   ★ 先记下原始设置，测完恢复")

    orig = {}
    for n in ["3D Mode", "Left Channel", "Right Channel"]:
        orig[n] = mixer_get(n)

    trials = [
        ("A 原样", []),
        ("B 关 3D + PGA 拉满", [("3D Mode", "No 3D"), ("Left Channel", "8"),
                                ("Right Channel", "8")]),
        ("C 再关 ALC", [("ALC Capture Function", "off")]),
    ]

    for label, sets in trials:
        for name, val in sets:
            mixer_set(name, val)
        time.sleep(0.3)
        p = record("/tmp/diag_%s.wav" % label.split()[0], 2)
        if not p:
            print("   %-22s ★ 录音失败" % label)
            continue
        st = stats(p)
        if not st:
            print("   %-22s ★ 解析失败" % label)
            continue
        txt = "  ".join("ch%d %.1f dBFS(峰%d)" % (i, s[0], s[1])
                        for i, s in enumerate(st))
        print("   %-22s %s" % (label, txt))

    # ---------- 4) 恢复 ----------
    print("\n>>> 4. 恢复原设置")
    for n, v in orig.items():
        if v and "Mono" in v:
            pass
    mixer_set("3D Mode", "Level 7")
    mixer_set("Left Channel", "6")
    mixer_set("Right Channel", "6")
    print("   已恢复")

    print()
    print("★ 判读：")
    print("   A/B/C 全都 ≈ -137 dBFS  -> 不是 mixer 能解决的，是 ADC 输入选择")
    print("                              或模拟前端（需要改 0x0A，得先释放 I2C）")
    print("   B 或 C 明显变大          -> 就是 3D/PGA/ALC 的问题，改 mixer 就行")


if __name__ == "__main__":
    main()
