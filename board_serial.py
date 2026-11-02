# -*- coding: utf-8 -*-
"""board_serial.py —— 通过串口登录板子并执行命令 (SSH 不通时的备用通道)

用法:
    python board_serial.py "命令"         # 登录后执行命令
    python board_serial.py -f 脚本.sh     # 登录后执行本地脚本内容
    python board_serial.py --peek         # 只看串口现在在输出什么
    python board_serial.py --interactive  # 手动交互 (Ctrl+C 退出)

板子: COM7 @115200, 用户 zynq / 123456
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
USER = "zynq"
PASS = "123456"


class Term:
    def __init__(self, port=PORT, baud=BAUD):
        self.s = serial.Serial(port, baud, timeout=0.3, write_timeout=1.5)
        self.s.reset_input_buffer()

    def close(self):
        try:
            self.s.close()
        except Exception:
            pass

    def wr(self, data):
        if isinstance(data, str):
            data = data.encode()
        self.s.write(data)

    def read_for(self, sec=2.0, stop=None):
        """读 sec 秒 (或直到出现 stop 里的某个字节串)"""
        t0 = time.time()
        buf = b""
        while time.time() - t0 < sec:
            chunk = self.s.read(4096)
            if chunk:
                buf += chunk
                if stop and any(p in buf for p in stop):
                    break
                t0 = time.time()
        return buf.decode("utf-8", "replace")

    def login(self, verbose=True):
        """确保已经登录, 返回最后看到的提示符"""
        self.wr(b"\r")
        time.sleep(0.6)
        out = self.read_for(1.5)
        for _ in range(3):
            if "login:" in out:
                self.wr(USER + "\r")
                time.sleep(1.2)
                out += self.read_for(1.5)
            if "assword:" in out:
                self.wr(PASS + "\r")
                time.sleep(1.8)
                out += self.read_for(2.0)
            if "$" in out or "#" in out:
                break
            self.wr(b"\r")
            time.sleep(0.5)
            out += self.read_for(1.2)
        if verbose:
            txt = out.replace("\r", "")
            if txt.strip():
                print("[串口]", txt.strip()[-400:])
        return out

    def cmd(self, c, wait=2.5, settle=0.7):
        """执行命令并读回输出"""
        # 先敲一个回车确保在提示符上
        self.wr(b"\r")
        time.sleep(0.3)
        self.s.reset_input_buffer()
        self.wr(c.encode() + b"\r")
        t0 = time.time()
        buf = b""
        while time.time() - t0 < wait:
            chunk = self.s.read(4096)
            if chunk:
                buf += chunk
                t0 = time.time()
        time.sleep(settle)
        chunk = self.s.read(8192)
        if chunk:
            buf += chunk
        return buf.decode("utf-8", "replace")


def clean(txt):
    return txt.replace("\r", "")


if __name__ == "__main__":
    args = sys.argv[1:]
    t = Term()
    try:
        if not args:
            print(clean(t.read_for(2.0)))
        elif args[0] == "--peek":
            t.wr(b"\r")
            print(clean(t.read_for(3.0)))
        elif args[0] == "--interactive":
            t.login()
            print(">>> 交互模式, 输入命令 (Ctrl+C 退出)")
            while True:
                line = input("serial> ")
                print(clean(t.cmd(line, wait=3.0)))
        elif args[0] == "-f":
            t.login()
            with open(args[1], "r", encoding="utf-8") as f:
                script = f.read()
            # 逐行发, 每行等一会儿
            for line in script.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                out = clean(t.cmd(line, wait=3.0))
                print("$ " + line)
                print(out)
                print("-" * 50)
        else:
            t.login(verbose=False)
            out = clean(t.cmd(" ".join(args), wait=4.0))
            print(out)
    finally:
        t.close()
