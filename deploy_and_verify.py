#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次把"点击 + 退出"这套修复全装到板子上，并跑完整回归。

装 4 个文件：
    fbui.py         全局"返回区"保险（点两次强制回桌面，修好任何应用出不来）
    desktop.py      图标页不再吃点击(B1) / 天气卡不跳WiFi(B2) / 跑应用时挂上返回区
    home.py         「最近使用」画点同源(B3)
    apps_browser.py 顶栏加「桌面」按钮（浏览器原来完全没有退出键）

然后：
    A) audit_exit_run.py  16 个应用 逐个 打开->退出->再打开
    B) fix_taps.py        图标页 12 个图标 / 天气卡 / 最近使用 4 个 / Dock 6 个
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import board                       # noqa: E402
import broot                       # noqa: E402

UI = os.path.join(HERE, "ui")
FILES = ["fbui.py", "desktop.py", "home.py", "apps_browser.py"]


def main():
    print("HOST =", board.HOST)

    print("\n=== 1) 部署")
    import hashlib
    for fn in FILES:
        local = os.path.join(UI, fn)
        tmp = "/tmp/_fix_" + fn
        board.put(local, tmp)
        broot.srun("install -o zynq -g zynq -m 0644 %s /home/zynq/ui/%s"
                   % (tmp, fn), quiet=True)
        want = hashlib.md5(open(local, "rb").read()).hexdigest()
        out, _ = broot.srun("md5sum /home/zynq/ui/%s" % fn, quiet=True)
        got = out.split()[0] if out.strip() else "?"
        print("   %-18s %s" % (fn, "OK" if got == want else "!! 不一致"))

    print("\n=== 2) 语法自检（在板子上）")
    broot.srun("cd /home/zynq/ui && for f in %s; do python3 -c "
               "\"import ast,sys; ast.parse(open(sys.argv[1],encoding='utf-8')"
               ".read())\" $f && echo \"   $f OK\"; done" % " ".join(FILES),
               use_sudo=False)

    print("\n=== 3) 重启桌面")
    broot.srun("systemctl restart zynq-desktop", quiet=True)
    import time
    time.sleep(20)
    print("   ", broot.srun("systemctl is-active zynq-desktop", quiet=True)[0].strip())

    print("\n" + "#" * 70)
    print("# A) 16 个应用：打开 -> 退出 -> 再打开")
    print("#" * 70)
    r1 = subprocess.call([sys.executable,
                          os.path.join(HERE, "audit_exit_run.py")])

    print("\n" + "#" * 70)
    print("# B) 点击回归：图标页 / 天气卡 / 最近使用 / Dock")
    print("#" * 70)
    r2 = subprocess.call([sys.executable, os.path.join(HERE, "fix_taps.py")])

    print("\n" + "=" * 70)
    print("A(退出审计) =", "通过" if r1 == 0 else "有问题",
          "   B(点击回归) =", "通过" if r2 == 0 else "有问题")
    print("=" * 70)
    return r1 or r2


if __name__ == "__main__":
    sys.exit(main())
