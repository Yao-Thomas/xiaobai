#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""uboot_fpga.py —— 在 u-boot 里把 fpga 命令试个遍, 找出能用的那个

安全说明: 全程只在 u-boot 命令行操作, 不动任何文件, 不碰内核。
         最坏情况就是命令报错, 然后 boot 继续启动 Linux。

用法: python uboot_fpga.py
"""
import os
import sys
import threading
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import serial

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PORT = os.environ.get("BOARD_COM", "COM7")
BAUD = 115200
PROMPTS = (b"Zynq>", b"=> ", b"U-Boot>")

# 候选: (文件, 用哪个 fpga 子命令)
TESTS = [
    ("t_gpu.bit", "fpga load  0 0x08000000 ${filesize}", "完整 .bit (带文本头)"),
    ("t_sw.bin",  "fpga loadb 0 0x08000000 ${filesize}", "字节交换 .bin"),
    ("t_raw.bin", "fpga loadb 0 0x08000000 ${filesize}", "未交换 raw"),
    ("t_bg.bin",  "fpga loadb 0 0x08000000 ${filesize}", "bootgen 官方 .bin"),
    ("t_gpu.bit", "fpga loadb 0 0x08000000 ${filesize}", ".bit 当 bin 试"),
]


def read_until(s, pats, timeout=25, echo=True):
    t0 = time.time()
    buf = b""
    while time.time() - t0 < timeout:
        c = s.read(4096)
        if c:
            buf += c
            if echo:
                sys.stdout.write(c.decode("utf-8", "replace"))
                sys.stdout.flush()
            if any(p in buf for p in pats):
                break
        else:
            time.sleep(0.02)
    return buf


def enter_uboot(s):
    import board
    s.reset_input_buffer()
    time.sleep(0.4)
    s.reset_input_buffer()
    stop = threading.Event()

    def spam():
        while not stop.is_set():
            try:
                s.write(b"\r")
            except Exception:
                return
            time.sleep(0.06)

    th = threading.Thread(target=spam, daemon=True)
    th.start()
    time.sleep(0.5)
    print("[uboot] 触发重启 ...")
    try:
        board.run("echo %s | sudo -S -p '' bash -c 'sync; (sleep 2; reboot) >/dev/null 2>&1 &'"
                  % board.PASS, timeout=20, quiet=True)
    except Exception as e:
        print("[uboot] 触发失败:", e)

    buf = b""
    got = False
    saw = False
    t0 = time.time()
    while time.time() - t0 < 100:
        c = s.read(4096)
        if c:
            buf += c
            if b"Hit any key" in buf or b"U-Boot 20" in buf:
                saw = True
            if any(p in buf for p in PROMPTS):
                got = True
                break
        else:
            time.sleep(0.02)
        if saw and b"login:" in buf[-3000:]:
            break
    stop.set()
    th.join(timeout=2)
    time.sleep(0.3)
    s.reset_input_buffer()
    return got


def cmd(s, c, timeout=30):
    print("\n>>> " + c)
    s.reset_input_buffer()
    s.write(c.encode() + b"\r")
    out = read_until(s, PROMPTS, timeout=timeout)
    t = out.decode("utf-8", "replace")
    low = t.lower()
    bad = any(k in low for k in ("failed", "error", "unknown command",
                                 "not found", "bad ", "wrong", "cannot",
                                 "invalid"))
    print("    ==> %s" % ("★ 失败" if bad else "✅ 成功"))
    return t, bad


def main():
    s = serial.Serial(PORT, BAUD, timeout=0.25, write_timeout=2.0)
    log = []
    try:
        if not enter_uboot(s):
            print("[uboot] ❌ 没进 u-boot")
            return
        print("[uboot] ✅ 进了 u-boot\n")

        cmd(s, "", timeout=5)
        cmd(s, "version", timeout=10)
        cmd(s, "fpga", timeout=10)            # 打印用法
        cmd(s, "fpga info 0", timeout=10)
        cmd(s, "mmc dev 0", timeout=10)

        results = []
        for fname, fcmd, desc in TESTS:
            print("\n" + "=" * 58)
            print("试: %s  [%s]" % (desc, fname))
            print("=" * 58)
            _, b1 = cmd(s, "fatload mmc 0:1 0x08000000 %s" % fname, timeout=30)
            txt, b2 = cmd(s, fcmd, timeout=30)
            results.append((desc, fname, fcmd, b1 or b2, txt))

        print("\n" + "=" * 58)
        print("汇总")
        print("=" * 58)
        for desc, fname, fcmd, bad, txt in results:
            print("  %-24s %-14s %s" % (desc, fname, "★ 失败" if bad else "✅ 成功"))
        print("=" * 58)

        print("\n继续启动 Linux ...")
        cmd(s, "boot", timeout=20)
    finally:
        s.close()


if __name__ == "__main__":
    main()
