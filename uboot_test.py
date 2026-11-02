#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""uboot_test.py —— 串口进 u-boot 命令行, 现场测试 bitstream 格式

改进: 从触发重启【之前】就一直敲回车, 一直到看见 u-boot 提示符,
     这样 2 秒的 autoboot 倒计时窗口不会错过。
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

CANDIDATES = [
    ("t_sw.bin",  4045532),
    ("t_raw.bin", 4045532),
    ("t_bg.bin",  4045568),
]

PROMPTS = (b"Zynq>", b"=> ", b"U-Boot>", b"zynq>")


def enter_uboot(s, log):
    """一边猛敲回车一边读, 直到出现 u-boot 提示符

    注意: 必须先清空串口缓冲! 否则会读到上一次残留的 "zynq-board login:",
          脚本会误以为已经进了 Linux 而立刻退出 (踩过这个坑)。
    """
    import board

    # ★ 先清干净串口里残留的东西
    s.reset_input_buffer()
    time.sleep(0.5)
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

    t0 = time.time()
    buf = b""
    got = False
    saw_uboot = False
    while time.time() - t0 < 100:
        c = s.read(4096)
        if c:
            buf += c
            log.append(c)
            if b"U-Boot 20" in buf or b"Hit any key" in buf:
                saw_uboot = True
            if any(p in buf for p in PROMPTS):
                got = True
                break
        else:
            time.sleep(0.02)
        # 只有在【没见过 u-boot 输出】时才把 login 当作"错过了"
        if saw_uboot and b"login:" in buf[-4000:]:
            break

    stop.set()
    th.join(timeout=2)
    time.sleep(0.3)
    s.reset_input_buffer()
    return got, buf


def enter_uboot_retry(s, log, tries=3):
    last = b""
    for i in range(tries):
        print("\n########## 第 %d 次尝试进 u-boot ##########" % (i + 1))
        got, buf = enter_uboot(s, log)
        last = buf
        if got:
            return True, buf
        print("[uboot] 这次没进去, 等 20 秒重试 ...")
        time.sleep(20)
    return False, last


def read_until(s, patterns, timeout=25, log=None, echo=True):
    t0 = time.time()
    buf = b""
    while time.time() - t0 < timeout:
        c = s.read(4096)
        if c:
            buf += c
            if log is not None:
                log.append(c)
            if echo:
                sys.stdout.write(c.decode("utf-8", "replace"))
                sys.stdout.flush()
            if any(p in buf for p in patterns):
                break
        else:
            time.sleep(0.02)
    return buf


def cmd(s, c, timeout=25, log=None):
    print("\n>>> " + c)
    s.reset_input_buffer()
    s.write(c.encode() + b"\r")
    out = read_until(s, PROMPTS, timeout=timeout, log=log)
    text = out.decode("utf-8", "replace")
    low = text.lower()
    bad = any(k in low for k in ("failed", "error", "unknown command",
                                 "not found", "bad ", "no partition"))
    print("    [%s]" % ("成功" if not bad else "★ 有报错"))
    return out


def main():
    s = serial.Serial(PORT, BAUD, timeout=0.2, write_timeout=1.5)
    log = []
    try:
        got, buf = enter_uboot_retry(s, log)
        if not got:
            print("\n[uboot] ❌ 还是没进去。最后看到的内容:")
            print(buf.decode("utf-8", "replace")[-1500:])
            return
        print("[uboot] ✅ 已进入 u-boot 命令行")

        cmd(s, "", timeout=5, log=log)
        cmd(s, "version", timeout=10, log=log)
        cmd(s, "mmc dev 0", timeout=10, log=log)

        results = {}
        for name, size in CANDIDATES:
            print("\n" + "=" * 58)
            print("测试 %s  (%d 字节)" % (name, size))
            print("=" * 58)
            cmd(s, "fatload mmc 0:1 0x08000000 %s" % name, timeout=30, log=log)
            out = cmd(s, "fpga loadb 0 0x08000000 0x%X" % size, timeout=30, log=log)
            results[name] = out.decode("utf-8", "replace")

        print("\n" + "=" * 58)
        print("汇总")
        print("=" * 58)
        for name, _ in CANDIDATES:
            t = results.get(name, "")
            low = t.lower()
            bad = any(k in low for k in ("failed", "error", "bad ", "not found"))
            print("  %-12s %s" % (name, "★ 失败" if bad else "看起来成功"))
            tail = [l for l in t.splitlines() if l.strip()][-3:]
            for l in tail:
                print("        " + l.strip()[:100])

        print("\n继续启动 Linux ...")
        cmd(s, "boot", timeout=15, log=log)
        try:
            with open("uboot_session.log", "wb") as f:
                f.write(b"".join(log))
            print("\n[uboot] 完整串口日志 -> uboot_session.log")
        except Exception:
            pass
    finally:
        s.close()


if __name__ == "__main__":
    main()
