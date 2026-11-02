#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""beep.py —— 板载【有源蜂鸣器】测试

★ 蜂鸣器和音频链路**一点关系都没有**，别混：
    蜂鸣器 : PL 的 GPIO  ->  Linux `gpio-beeper` 驱动 -> /dev/input/eventX (EV_SND)
             内核设备树节点 /proc/device-tree/beep
             /proc/bus/input/devices 里名字就叫 "beep"，能力 EV=40001 SND=2
    ES8388 : DDR -> audio formatter -> AXI I2S -> ES8388 -> 耳机(LOUT1/ROUT1)
                                                       -> MD8002A 功放 -> 喇叭(LOUT2/ROUT2)

所以：
  蜂鸣器响  ≠  音频链路通
  音频链路通 = 能听出 500/1000/2000/4000 Hz 这些**音高**

用法：
    python3 beep.py            响 1 次（200ms）
    python3 beep.py 3          响 3 次
    python3 beep.py 1 500      响 1 次，500ms
    python3 beep.py --bell     用 SND_BELL（有源蜂鸣器一般用这个）
    python3 beep.py --list     只列出蜂鸣器设备
"""
import os
import struct
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

EV_SYN, EV_SND = 0x00, 0x12
SND_BELL, SND_TONE = 0x01, 0x02
EVSZ = struct.calcsize("llHHi")          # 32 位 ARM 上是 16 字节


def find_beeper():
    """从 /proc/bus/input/devices 里找名字叫 beep / buzzer 的那个 eventX"""
    try:
        txt = open("/proc/bus/input/devices").read()
    except Exception:
        return None
    blocks = txt.split("\n\n")
    for b in blocks:
        if "beep" in b.lower() or "buzzer" in b.lower():
            for ln in b.splitlines():
                if ln.startswith("H:"):
                    for t in ln.split():
                        if t.startswith("event"):
                            return "/dev/input/" + t
    return None


def send(fd, etype, code, value):
    os.write(fd, struct.pack("llHHi", 0, 0, etype, code, value))
    os.write(fd, struct.pack("llHHi", 0, 0, EV_SYN, 0, 0))


def open_beeper():
    """打开蜂鸣器设备；没有就返回 None"""
    path = find_beeper()
    if not path:
        return None
    try:
        return os.open(path, os.O_WRONLY)
    except Exception:
        return None


def beep(n=1, ms=200, fd=None, use_bell=False, gap=0.18):
    """嘀 n 声。给别的脚本复用（比如 audio_pl.py 用它报"第几组"）。

    返回 True/False（有没有蜂鸣器）。fd 传进来就复用，不关。
    """
    own = fd is None
    if own:
        fd = open_beeper()
        if fd is None:
            return False
    code = SND_BELL if use_bell else SND_TONE
    on = 1 if use_bell else 1000
    try:
        for i in range(n):
            send(fd, EV_SND, code, on)
            time.sleep(ms / 1000.0)
            send(fd, EV_SND, code, 0)
            if i < n - 1:
                time.sleep(gap)
        return True
    except Exception:
        return False
    finally:
        if own:
            try:
                os.close(fd)
            except Exception:
                pass


def main(argv):
    list_only = "--list" in argv
    use_bell = "--bell" in argv
    nums = [a for a in argv if not a.startswith("--")]
    n = int(nums[0]) if nums else 1
    dur = int(nums[1]) if len(nums) > 1 else 200

    path = find_beeper()
    print("蜂鸣器设备:", path or "(没找到)")
    if list_only:
        try:
            print(open("/proc/bus/input/devices").read())
        except Exception:
            pass
        return
    if not path:
        print("没找到蜂鸣器设备。看看 /proc/bus/input/devices 里有没有名字带 beep 的。")
        return

    fd = os.open(path, os.O_WRONLY)
    try:
        for i in range(n):
            print("  第 %d/%d 次" % (i + 1, n))
            if use_bell:
                send(fd, EV_SND, SND_BELL, 1)
                time.sleep(dur / 1000.0)
                send(fd, EV_SND, SND_BELL, 0)
            else:
                send(fd, EV_SND, SND_TONE, 1000)      # 有源蜂鸣器会忽略频率
                time.sleep(dur / 1000.0)
                send(fd, EV_SND, SND_TONE, 0)
            time.sleep(0.25)
    finally:
        os.close(fd)
    print("完事。听到「嘀」说明蜂鸣器是好的 —— 但**这不代表音频链路通**。")


if __name__ == "__main__":
    main(sys.argv[1:])
