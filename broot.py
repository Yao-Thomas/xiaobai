#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""broot.py —— 以 root 身份在板子上跑命令 (SSH 用户是 zynq, 需要 sudo)

board.run 走的是 exec_command 且不喂 stdin, 而 `sudo -S` 要从 stdin 读密码,
所以这里自己开一个 channel, 把密码写进去。
"""
import shlex
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import paramiko

import board as _b

PASS = "123456"


def srun(cmd, timeout=300, quiet=False, use_sudo=True):
    """以 root 执行 cmd, 返回 (out, err)"""
    host = _b.HOST
    if not host:
        raise SystemExit("[broot] 找不到板子")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(host, username=_b.USER, password=_b.PASS, timeout=20,
              look_for_keys=False, allow_agent=False)
    try:
        if use_sudo:
            full = "sudo -S -p '' /bin/bash -c " + shlex.quote(cmd)
        else:
            full = "/bin/bash -c " + shlex.quote(cmd)
        i, o, e = c.exec_command(full, timeout=timeout, get_pty=False)
        if use_sudo:
            i.write(PASS + "\n")
            i.flush()
        out = o.read().decode(errors="replace")
        err = e.read().decode(errors="replace")
    finally:
        c.close()
    if not quiet:
        if out:
            sys.stdout.write(out)
        if err.strip():
            sys.stderr.write("--- stderr ---\n" + err + "\n")
    return out, err


def put_root(local, remote, mode=None):
    """先传到 /tmp, 再 sudo 搬到目标位置"""
    tmp = "/tmp/_up_" + remote.strip("/").replace("/", "_")
    _b.put(local, tmp)
    cmd = "install -m %s %s %s" % (mode or "0644", shlex.quote(tmp), shlex.quote(remote))
    out, err = srun(cmd)
    srun("rm -f " + shlex.quote(tmp), quiet=True)
    return out, err


if __name__ == "__main__":
    _b.HOST = _b.find_host(verbose=False)
    print("HOST =", _b.HOST)
    srun("id; sudo -n true 2>&1; echo sudo_nopass_rc=$?")
    srun("ls -ld /mnt/boot /usr/local/bin")
