#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""board.py —— 通过 SSH 在 Zynq 板子上执行命令

用法:
    python board.py "命令"
    python board.py -f script.sh          # 上传本地脚本到 /tmp 并执行
    python board.py -p 本地文件 远端路径   # 上传
    python board.py -g 远端文件 本地路径   # 下载
    python board.py --find                # 只找板子, 打印 IP

板子 IP 自动探测顺序:
    1. 环境变量 BOARD_IP
    2. 已知历史 IP
    3. 扫描本机所在网段的 22 端口, 用 zynq/123456 试登录
"""
import sys
import os
import socket
import uuid
import concurrent.futures

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import paramiko

USER = "zynq"
PASS = "123456"

# 历史出现过的板子 IP
KNOWN = [
    "192.168.10.34",
    "192.168.0.38",       # 家里路由器 (2026-10-03) ★ 最新 —— PC 现在是 192.168.0.39
    "192.168.110.144",    # 家里 13A02 (2026-10-01) ★ 注意: WiFi 不稳, IP 可能变
    "192.168.110.202",    # 家里 13A02 (历史)
    "192.168.10.23",      # CMCC-Y2Ss (2026-09-29 重启后的 IP)
    "192.168.10.18",      # CMCC-Y2Ss (历史)
    "192.168.10.13",      # CMCC-Y2Ss (历史)
    "192.168.43.210",     # 手机热点 001
]


def _probe(ip, t=1.5):
    """端口 22 是否开"""
    try:
        s = socket.create_connection((ip, 22), timeout=t)
        s.close()
        return True
    except Exception:
        return False


def _auth_ok(ip, t=4):
    """用板子账号能否登录"""
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        c.connect(ip, username=USER, password=PASS, timeout=t,
                  banner_timeout=t, auth_timeout=t,
                  look_for_keys=False, allow_agent=False)
        return True
    except Exception:
        return False
    finally:
        try:
            c.close()
        except Exception:
            pass


def local_ips():
    """本机所有非环回/非自分配 IPv4"""
    out = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            out.append(info[4][0])
    except Exception:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))       # 只用来问路由表, 不发包
        out.append(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    return [i for i in dict.fromkeys(out)
            if not i.startswith("127.") and not i.startswith("169.254.")]


def scan(subnet, workers=128):
    """扫描一个 /24 网段里所有开 22 端口的主机"""
    ips = [subnet + str(i) for i in range(1, 255)]
    hit = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        for ip, ok in zip(ips, ex.map(_probe, ips)):
            if ok:
                hit.append(ip)
    return hit


def find_host(verbose=True):
    for ip in [os.environ.get("BOARD_IP", "")] + KNOWN:
        if ip and _probe(ip):
            if verbose:
                print("[board] 已知 IP 命中: %s" % ip)
            return ip
    for ip in local_ips():
        subnet = ip.rsplit(".", 1)[0] + "."
        if verbose:
            print("[board] 已知 IP 都不通, 扫描 %s ..." % subnet)
        for h in scan(subnet):
            if _auth_ok(h):
                if verbose:
                    print("[board] 扫描命中: %s" % h)
                return h
    if verbose:
        print("[board] ⚠ 没找到板子 (没上电 / WiFi 掉线 / 不在同一网段?)")
    return None


HOST = find_host()


def conn():
    if not HOST:
        raise SystemExit("[board] 找不到板子, 中止")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, password=PASS, timeout=20,
              look_for_keys=False, allow_agent=False)
    return c


def run(cmd, timeout=180, quiet=False):
    c = conn()
    try:
        i, o, e = c.exec_command(cmd, timeout=timeout, get_pty=False)
        out = o.read().decode(errors="replace")
        err = e.read().decode(errors="replace")
    finally:
        c.close()
    if not quiet:
        if out:
            sys.stdout.write(out)
        if err.strip():
            sys.stderr.write("--- stderr ---\n" + err)
    return out, err


def put(local, remote):
    c = conn()
    try:
        sftp = c.open_sftp()
        sftp.put(local, remote)
        sftp.close()
    finally:
        c.close()
    print("上传: %s -> %s" % (local, remote))


def get(remote, local):
    c = conn()
    try:
        sftp = c.open_sftp()
        sftp.get(remote, local)
        sftp.close()
    finally:
        c.close()
    print("下载: %s -> %s" % (remote, local))


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "-f":
        local = sys.argv[2]
        # ★★★ 2026-10-03 修：原来固定上传到 /tmp/_s.sh
        # ────────────────────────────────────────────────────────────
        # 问题是【并发】时会互相踩：两个进程同时跑 -f，
        # 后一个把 /tmp/_s.sh 覆盖掉，前一个写一半的脚本被执行
        # ⇒ 报莫名其妙的语法错，或者执行了别人的半截脚本。
        # 实测：多智能体同时在板子上干活时踩到过（脚本被截断）。
        # ⇒ 改成【按本地文件名 + 随机后缀】生成独立路径，互不干扰。
        #   （跑完顺手删掉，不给板子留垃圾）
        # ────────────────────────────────────────────────────────────
        base = os.path.basename(local).replace(" ", "_") or "run"
        base = "".join(ch for ch in base if ch.isalnum() or ch in "._-")
        remote = "/tmp/_run_%s_%s.sh" % (base, uuid.uuid4().hex[:8])
        put(local, remote)
        run("chmod +x %s && bash %s; rc=$?; rm -f %s; exit $rc"
            % (remote, remote, remote))
    elif len(sys.argv) >= 3 and sys.argv[1] == "-p":
        put(sys.argv[2], sys.argv[3])
    elif len(sys.argv) >= 3 and sys.argv[1] == "-g":
        get(sys.argv[2], sys.argv[3])
    elif len(sys.argv) >= 2 and sys.argv[1] == "--find":
        print(HOST or "(无)")
    else:
        run(sys.argv[1] if len(sys.argv) > 1 else "echo hi")
