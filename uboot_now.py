# -*- coding: utf-8 -*-
"""uboot_now.py —— 在已经停在 u-boot 提示符的板子上直接发命令

用法:
    python uboot_now.py "命令1" "命令2" ...
    python uboot_now.py --peek            # 只看当前提示符
"""
import os
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import serial

PORT = os.environ.get("BOARD_COM", "COM7")
BAUD = 115200
PROMPT = b"Zynq>"


def open_s():
    s = serial.Serial(PORT, BAUD, timeout=0.3, write_timeout=2.0)
    s.reset_input_buffer()
    return s


def wait_prompt(s, timeout=30, echo=True):
    t0 = time.time()
    buf = b""
    while time.time() - t0 < timeout:
        c = s.read(4096)
        if c:
            buf += c
            if echo:
                sys.stdout.write(c.decode("utf-8", "replace"))
                sys.stdout.flush()
            if PROMPT in buf:
                return buf, True
        else:
            time.sleep(0.02)
    return buf, False


def run(s, c, timeout=30):
    print("\n$ " + c)
    s.reset_input_buffer()
    s.write(c.encode() + b"\r")
    buf, ok = wait_prompt(s, timeout=timeout)
    text = buf.decode("utf-8", "replace")
    low = text.lower()
    bad = any(k in low for k in ("failed", "error", "unknown command",
                                 "not found", "bad ", "wrong", "cannot"))
    print("   ==> %s" % ("★ 报错了" if bad else "OK"))
    return text, bad


if __name__ == "__main__":
    args = sys.argv[1:]
    s = open_s()
    try:
        if args and args[0] == "--peek":
            s.write(b"\r")
            wait_prompt(s, timeout=5)
            sys.exit(0)

        run(s, "", timeout=5)

        TESTS = [
            ("t_sw.bin",  "字节交换 (system.bit 现在就是这个)"),
            ("t_raw.bin", "不交换 raw"),
            ("t_bg.bin",  "bootgen 官方输出"),
        ]
        summary = []
        for name, desc in TESTS:
            print("\n" + "=" * 56)
            print("测试 %s —— %s" % (name, desc))
            print("=" * 56)
            txt1, bad1 = run(s, "fatload mmc 0:1 0x08000000 %s" % name, timeout=30)
            txt2, bad2 = run(s, "fpga loadb 0 0x08000000 ${filesize}", timeout=30)
            summary.append((name, desc, bad1 or bad2, txt2))

        print("\n" + "=" * 56)
        print("汇总")
        print("=" * 56)
        for name, desc, bad, txt in summary:
            print("  %-12s %-34s %s" % (name, desc, "★ 失败" if bad else "✅ 成功"))
            for line in [l.strip() for l in txt.splitlines() if l.strip()][-3:]:
                print("        " + line[:90])

        print("\n" + "=" * 56)
        print("启动 Linux")
        print("=" * 56)
        run(s, "boot", timeout=20)
    finally:
        s.close()
