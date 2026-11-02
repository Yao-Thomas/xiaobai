#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_mic.py —— 找出这台机器上【能录音】的方法

════════════════════════════════════════════════════════════════════
背景
════════════════════════════════════════════════════════════════════
用 MCI 录音时报：
    "未安装可按当前格式记录文件的波形设备" (rc=328)

原因可能有好几个，得一个个排除：
    ① 我指定的 16kHz/mono/16bit 声卡不支持
    ② MCI 的 waveaudio 设备用"系统默认录音格式"，而那个格式是坏的
    ③ 这台机器装了 Nahimic 音效软件，把录音设备接管了
    ④ 根本没有可用的录音设备

这个脚本把几种可能都试一遍，看哪个能成。

用法:
    python probe_mic.py
"""
import ctypes
import os
import sys
import tempfile
import time
import wave

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

TMP = tempfile.gettempdir()


def mci_send(cmd, want_ret=False):
    winmm = ctypes.WinDLL("winmm.dll")
    winmm.mciSendStringW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p,
                                     ctypes.c_uint, ctypes.c_void_p]
    winmm.mciSendStringW.restype = ctypes.c_uint
    winmm.mciGetErrorStringW.argtypes = [ctypes.c_uint, ctypes.c_wchar_p,
                                         ctypes.c_uint]
    buf = ctypes.create_unicode_buffer(512) if want_ret else None
    rc = winmm.mciSendStringW(cmd, buf, 512 if buf else 0, None)
    if rc != 0:
        e = ctypes.create_unicode_buffer(512)
        winmm.mciGetErrorStringW(rc, e, 512)
        return rc, e.value
    return 0, (buf.value if buf else "")


def try_mci(tag, setup_cmds, secs=2.0):
    """试一种 MCI 配置"""
    alias = "pm" + str(abs(hash(tag)) % 10000)
    out = os.path.join(TMP, "probe_%s.wav" % alias)
    try:
        os.remove(out)
    except Exception:
        pass
    try:
        mci_send("close %s" % alias)
    except Exception:
        pass
    rc, err = mci_send("open new type waveaudio alias %s" % alias)
    if rc:
        print("   ✗ open 就失败: %s" % err)
        return False, None
    for c in setup_cmds:
        rc, err = mci_send(c % alias)
        if rc:
            print("   ! 设置失败（继续）: %s -> %s" % (c.split()[1], err))
    rc, err = mci_send("record %s" % alias)
    if rc:
        print("   ✗ record 失败: %s" % err)
        try:
            mci_send("close %s" % alias)
        except Exception:
            pass
        return False, None
    time.sleep(secs)
    mci_send("stop %s" % alias)
    rc, err = mci_send('save %s "%s"' % (alias, out))
    if rc:
        print("   ✗ save 失败: %s" % err)
        try:
            mci_send("close %s" % alias)
        except Exception:
            pass
        return False, None
    mci_send("close %s" % alias)
    # 检查
    if not os.path.exists(out) or os.path.getsize(out) < 100:
        print("   ✗ 文件没生成或太小")
        return False, None
    try:
        with wave.open(out, "rb") as w:
            n, rate, ch, sw = (w.getnframes(), w.getframerate(),
                               w.getnchannels(), w.getsampwidth())
        print("   ✓ 成功！%d Hz / %d ch / %d bit / %.2f 秒 / %d 字节"
              % (rate, ch, sw * 8, n / float(rate), os.path.getsize(out)))
        return True, out
    except Exception as e:
        print("   ✗ 文件不是合法 wav: %s" % e)
        return False, None


def main():
    print("=" * 72)
    print(" 录音方式探测")
    print("=" * 72)

    print()
    print("【0】系统里的录音设备（waveIn API）")
    try:
        winmm = ctypes.WinDLL("winmm.dll")
        n = winmm.waveInGetNumDevs()
        print("   waveInGetNumDevs() = %d" % n)
        if n == 0:
            print("   ✗ ★ 系统报告【0 个录音设备】—— 没有麦克风或驱动没装")
        else:
            class WICAPS(ctypes.Structure):
                _fields_ = [
                    ("wMid", ctypes.c_ushort), ("wPid", ctypes.c_ushort),
                    ("vDriverVersion", ctypes.c_uint),
                    ("szPname", ctypes.c_wchar * 32),
                    ("dwFormats", ctypes.c_uint),
                    ("wChannels", ctypes.c_ushort),
                    ("wReserved1", ctypes.c_ushort)]
            for i in range(n):
                c = WICAPS()
                rc = winmm.waveInGetDevCapsW(i, ctypes.byref(c),
                                             ctypes.sizeof(c))
                if rc == 0:
                    print("   [%d] %s   声道=%d  格式掩码=0x%X"
                          % (i, c.szPname, c.wChannels, c.dwFormats))
    except Exception as e:
        print("   探测失败: %s" % e)

    print()
    print("【1】MCI 用【指定格式】16kHz/mono/16bit")
    ok1, _ = try_mci("16k", [
        "set %s time format milliseconds",
        "set %s channels 1",
        "set %s samplespersec 16000",
        "set %s bitspersample 16"])

    print()
    print("【2】MCI 用【系统默认格式】（什么都不设）")
    ok2, _ = try_mci("default", [])

    print()
    print("【3】MCI 用 44.1kHz/mono/16bit")
    ok3, _ = try_mci("44100", [
        "set %s channels 1",
        "set %s samplespersec 44100",
        "set %s bitspersample 16"])

    print()
    print("【4】MCI 用 8kHz/mono/8bit（最保守）")
    ok4, _ = try_mci("8k8", [
        "set %s channels 1",
        "set %s samplespersec 8000",
        "set %s bitspersample 8"])

    print()
    print("【5】MCI 显式指定设备类型（不用 new）")
    try:
        r = mci_send("open waveaudio alias pmx")
        if r[0] == 0:
            rc, err = mci_send("record pmx")
            print("   open waveaudio: %s" % ("record OK" if rc == 0
                                             else "record 失败: " + err))
            mci_send("close pmx")
        else:
            print("   ✗ open waveaudio 失败: %s" % r[1])
    except Exception as e:
        print("   失败: %s" % e)

    print()
    print("=" * 72)
    if any((ok1, ok2, ok3, ok4)):
        print(" 结论: ★ MCI 能录 —— 用上面成功的那种配置")
        print("       首选【方案 1（16k）】，不成退【方案 2（默认格式）】")
    else:
        print(" 结论: ★ MCI 全都不行")
        print("       ⇒ 需要换方案：pip install sounddevice（带 portaudio）")
        print("         或者检查系统默认录音设备（控制面板 → 声音 → 录制）")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
