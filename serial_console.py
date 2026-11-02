# -*- coding: utf-8 -*-
"""serial_console.py —— Zynq 板子串口控制台

用法:
    python serial_console.py            # 探测波特率并读一段
    python serial_console.py "命令"     # 发命令并读回结果
    python serial_console.py --login    # 确保已登录(必要时输账号密码)

板子串口通常是 115200 8N1。
"""
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import serial

PORT = "COM6"
BAUDS = [115200, 1500000, 57600, 9600]

USER = "zynq"
PASS = "123456"

# 已探测到的波特率会存到这里, 下次直接用
BAUD_FILE = "D:\\ubuntu_iso\\.serial_baud"


def open_port(baud):
    s = serial.Serial(PORT, baud, timeout=0.4, write_timeout=1.0)
    s.reset_input_buffer()
    return s


def detect(verbose=True):
    """探测波特率: 敲几个回车, 看哪个能收到可读文本"""
    for baud in BAUDS:
        try:
            s = open_port(baud)
        except Exception as e:
            if verbose:
                print("  %-8d 打不开: %s" % (baud, e))
            continue
        try:
            s.write(b"\r\n\r\n")
            time.sleep(0.8)
            data = s.read(600)
        finally:
            s.close()
        txt = data.decode("utf-8", "replace")
        printable = sum(1 for c in txt if 32 <= ord(c) < 127 or c in "\r\n\t")
        if data and printable > len(txt) * 0.7:
            if verbose:
                print("  ✅ %d 波特率有响应" % baud)
                for line in txt.replace("\r", "").splitlines()[-8:]:
                    print("      " + line)
            try:
                open(BAUD_FILE, "w").write(str(baud))
            except Exception:
                pass
            return baud
        elif data and verbose:
            print("  %-8d 收到 %d 字节但是乱码" % (baud, len(data)))
    return None


def get_baud():
    try:
        return int(open(BAUD_FILE).read().strip())
    except Exception:
        return None


def send(cmd, baud=None, wait=3.0, quiet=False):
    """发一条命令, 返回收到的文本"""
    baud = baud or get_baud() or 115200
    s = open_port(baud)
    try:
        s.write(b"\r\n")
        time.sleep(0.3)
        s.reset_input_buffer()
        s.write(cmd.encode() + b"\r\n")
        t0 = time.time()
        buf = b""
        while time.time() - t0 < wait:
            chunk = s.read(4096)
            if chunk:
                buf += chunk
                t0 = time.time()          # 有数据就继续等
        return buf.decode("utf-8", "replace")
    finally:
        s.close()


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        b = get_baud() or detect()
        if not b:
            print("❌ 探测不到波特率, 检查线/TX-RX 是否交叉/板子是否在输出")
            sys.exit(1)
        s = open_port(b)
        try:
            s.write(b"\r\n")
            time.sleep(1.0)
            data = s.read(4000)
            print("--- 串口输出 (%d) ---" % b)
            print(data.decode("utf-8", "replace"))
        finally:
            s.close()
    else:
        out = send(" ".join(args))
        print(out)
