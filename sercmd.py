# -*- coding: utf-8 -*-
"""sercmd.py —— 通过串口登录板子并执行命令

板子: 领航者 Zynq7020, UART 走 CH340 -> COM6 @115200
用法:
    python sercmd.py "命令"                 # 执行一条命令
    python sercmd.py "cmd1" "cmd2" ...      # 多条(会用 ; 连起来)
    python sercmd.py --raw "命令"           # 不清洗输出
    python sercmd.py --no-login "命令"      # 不尝试登录(已经登录过)

设计要点:
  · 自动识别 login: / Password: 提示并登录
  · 用唯一分隔符包住命令输出, 精确截取
  · 每次执行前 reset_input_buffer, 避免读到上次残留
"""
import re
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import serial

PORT = "COM6"
BAUD = 115200
USER = "zynq"
PASS = "123456"

BEGIN = "__SC_BEGIN__"
END = "__SC_END__"


def read_for(s, secs=1.0, quiet=0.3):
    """读 secs 秒, 或 quiet 秒无数据就返回"""
    buf = b""
    t_end = time.time() + secs
    last = time.time()
    while time.time() < t_end:
        try:
            n = s.in_waiting
            if n:
                buf += s.read(n)
                last = time.time()
            else:
                if buf and (time.time() - last) > quiet:
                    break
                time.sleep(0.05)
        except Exception:
            break
    return buf.decode("utf-8", "replace")


def ensure_login(s, verbose=True):
    """确保处于已登录的 shell"""
    s.reset_input_buffer()
    s.write(b"\r\n")
    time.sleep(0.6)
    txt = read_for(s, 1.5)

    # 已经在 shell 里(看到提示符)就直接返回
    if re.search(r"[#$]\s*$", txt.strip()) and "login:" not in txt:
        if verbose:
            print("[已在 shell 里]")
        return True, txt

    # 需要登录
    if "login:" in txt or "Password:" in txt or not txt.strip():
        if verbose:
            print("[检测到登录提示, 正在登录]")
        # 可能已经停在 login: 也可能停在 Password:
        if "Password:" in txt:
            s.write(PASS.encode() + b"\r\n")
        else:
            s.write(USER.encode() + b"\r\n")
            time.sleep(0.8)
            t2 = read_for(s, 1.5)
            if verbose:
                print("   " + t2.strip()[:80])
            if "Password:" in t2 or "password" in t2.lower():
                s.write(PASS.encode() + b"\r\n")
            else:
                # 也许已经进去了
                pass
        time.sleep(1.2)
        t3 = read_for(s, 2.0)
        ok = bool(re.search(r"[#$]", t3))
        if verbose:
            print("[登录%s]" % ("成功" if ok else "可能失败"))
            if not ok:
                print("   回显: " + t3.strip()[:200])
        return ok, t3

    return True, txt


def run(cmds, do_login=True, verbose=True):
    s = serial.Serial(PORT, BAUD, timeout=0.3, write_timeout=2.0)
    try:
        if do_login:
            ensure_login(s, verbose=verbose)

        # 拼命令: 用 echo 包住, 便于精确截取
        joined = "; ".join(cmds)
        payload = "echo %s; %s; echo %s\r\n" % (BEGIN, joined, END)

        s.reset_input_buffer()
        time.sleep(0.15)
        s.write(payload.encode())

        t_end = time.time() + 20
        buf = ""
        while time.time() < t_end:
            chunk = read_for(s, 0.6, quiet=0.35)
            if chunk:
                buf += chunk
            if END in buf:
                time.sleep(0.4)
                buf += read_for(s, 0.6)
                break

        # 截取 BEGIN..END 之间的内容
        m = re.search(re.escape(BEGIN) + r"(.*?)" + re.escape(END), buf, re.S)
        if m:
            return m.group(1)
        return buf
    finally:
        s.close()


if __name__ == "__main__":
    args = [a for a in sys.argv[1:]]
    do_login = "--no-login" not in args
    raw = "--raw" in args
    args = [a for a in args if not a.startswith("--")]

    if not args:
        print(__doc__)
        sys.exit(0)

    out = run(args, do_login=do_login)
    if raw:
        print(out)
    else:
        # 去掉命令回显那几行
        lines = out.replace("\r", "").split("\n")
        cleaned = []
        for ln in lines:
            t = ln.strip()
            if not t:
                continue
            if BEGIN in t or END in t:
                continue
            if t.startswith("echo ") or t == ";":
                continue
            cleaned.append(ln.rstrip())
        print("\n".join(cleaned))
