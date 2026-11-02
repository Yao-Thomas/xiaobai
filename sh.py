# -*- coding: utf-8 -*-
"""sh.py —— 通过串口在板子上跑 shell 命令（简洁可靠版）

用法:
    python sh.py "hostname -I"
    python sh.py "cmd1" "cmd2"

要点: 命令保持短, 发完读干净为止。板子已在 shell 里(zynq@zynq-board:~$)。
"""
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import serial

PORT = "COM6"
BAUD = 115200


def run(cmds, settle=1.2, max_wait=25.0):
    s = serial.Serial(PORT, BAUD, timeout=0.4, write_timeout=2.0)
    try:
        s.reset_input_buffer()
        time.sleep(0.2)

        # 先确认处于 shell；若在 login 提示则登录
        s.write(b"\r\n")
        time.sleep(0.7)
        probe = s.read(2000).decode("utf-8", "replace")
        if "login:" in probe:
            s.write(b"zynq\r\n"); time.sleep(1.0); s.read(500)
            s.write(b"123456\r\n"); time.sleep(1.2); s.read(500)

        s.reset_input_buffer()
        time.sleep(0.2)

        payload = " ; ".join(cmds)
        s.write((payload + "\r\n").encode())

        # 读到安静为止
        buf = ""
        t0 = time.time()
        last = time.time()
        while time.time() - t0 < max_wait:
            c = s.read(4096).decode("utf-8", "replace")
            if c:
                buf += c
                last = time.time()
            else:
                if buf and (time.time() - last) > settle:
                    break
                time.sleep(0.05)
        return buf
    finally:
        s.close()


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(0)
    out = run(args)
    # 去掉第一行(命令回显)和末尾的空提示符
    lines = out.replace("\r", "").split("\n")
    if lines and args[0].split()[0] in lines[0]:
        lines = lines[1:]
    txt = "\n".join(lines).strip()
    # 去掉结尾的提示符
    for tail in ("zynq@zynq-board:~$", "zynq@zynq-board:/$"):
        while txt.endswith(tail):
            txt = txt[:-len(tail)].strip()
    print(txt)
