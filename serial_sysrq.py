# -*- coding: utf-8 -*-
"""serial_sysrq.py —— 通过串口 BREAK 触发内核 SysRq 抢救卡死的板子

用法:
    python serial_sysrq.py            # 先试普通回车, 不行就 SysRq 同步+重启
    python serial_sysrq.py peek       # 只读
    python serial_sysrq.py sync       # 只同步
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


def read(s, sec):
    t0 = time.time()
    buf = b""
    while time.time() - t0 < sec:
        c = s.read(4096)
        if c:
            buf += c
            t0 = time.time()
    return buf


def sysrq(s, key, wait=3.0):
    """发 BREAK 再发一个字符 -> 内核 SysRq"""
    print("[sysrq] 发送 BREAK + '%s'" % key)
    s.send_break(duration=0.35)
    time.sleep(0.3)
    s.write(key.encode())
    time.sleep(wait)
    out = read(s, 2.0)
    if out:
        print(out.decode("utf-8", "replace"))
    return out


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    s = serial.Serial(PORT, BAUD, timeout=0.3, write_timeout=2.0)
    try:
        s.reset_input_buffer()

        if mode == "peek":
            s.write(b"\r\n")
            print(read(s, 3.0).decode("utf-8", "replace"))
            return

        # 先试探: 敲几个回车看有没有反应
        print("[probe] 敲回车试探 ...")
        s.write(b"\r\n\r\n")
        out = read(s, 3.0)
        if out.strip():
            print("[probe] 有反应, 板子还活着:")
            print(out.decode("utf-8", "replace"))
            if mode == "all":
                return

        print("[probe] 没反应, 上 SysRq")

        # SysRq 开关: 有些内核默认关着, 先试着开
        sysrq(s, "w", wait=1.0)      # 显示阻塞任务 (纯信息)

        if mode in ("all", "sync"):
            sysrq(s, "s", wait=3.0)      # 同步磁盘

        if mode == "all":
            sysrq(s, "b", wait=5.0)      # 立即重启
            print("[sysrq] 已发送重启, 等待 ...")
            t0 = time.time()
            buf = b""
            while time.time() - t0 < 60:
                c = s.read(4096)
                if c:
                    buf += c
                    if b"U-Boot" in buf or b"login:" in buf:
                        break
            txt = buf.decode("utf-8", "replace")
            print(txt[-2000:] if txt else "(还是没输出)")
    finally:
        s.close()


if __name__ == "__main__":
    main()
