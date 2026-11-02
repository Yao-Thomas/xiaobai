#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""flash_scope.py —— 原子地把示波器比特流写进 SD 并重启

为什么要原子:
  直接用 `cp -f 新文件 /mnt/boot/system.bit` 覆盖, 如果传到一半 WiFi 断了,
  system.bit 就是个半截文件 -> 下次启动 u-boot 加载 PL 失败。
  (上次就是传到一半断的, 幸好走的是先上传到 /home 再 cp, 没写坏 SD)

  所以: 先写 system.bit.new -> 校验 md5 -> 再 mv 改名。
"""
import hashlib
import os
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import board                       # noqa: E402

BIT = (r"D:\ubuntu_iso\atk2026\Navigator_7020\Navigator_7020.runs"
       r"\impl_1\system_wrapper.bit")
REMOTE = "/home/zynq/scope.bit"

INSTALL = r'''
set -e
SRC=/home/zynq/scope.bit
WANT=__MD5__
echo "--- 校验上传的文件 ---"
GOT=$(md5sum $SRC | cut -d' ' -f1)
echo "  want=$WANT"
echo "  got =$GOT"
if [ "$GOT" != "$WANT" ]; then echo "!! 上传文件 md5 不符, 中止"; exit 1; fi

mkdir -p /mnt/boot
mountpoint -q /mnt/boot || mount /dev/mmcblk0p1 /mnt/boot
if [ ! -f /mnt/boot/BOOT.BIN ]; then
    echo "!! /mnt/boot 里没有 BOOT.BIN, 不像启动分区, 中止"
    umount /mnt/boot; exit 1
fi
echo "--- 安装前 ---"
ls -l /mnt/boot/system.bit
echo -n "  旧 md5: "; md5sum /mnt/boot/system.bit | cut -d' ' -f1

echo "--- 写 system.bit.new ---"
cp -f $SRC /mnt/boot/system.bit.new
sync
GOT2=$(md5sum /mnt/boot/system.bit.new | cut -d' ' -f1)
if [ "$GOT2" != "$WANT" ]; then echo "!! SD 上文件 md5 不符, 不动 system.bit"; rm -f /mnt/boot/system.bit.new; umount /mnt/boot; exit 1; fi
echo "  新文件 md5 OK"

echo "--- 原子替换 ---"
mv -f /mnt/boot/system.bit.new /mnt/boot/system.bit
sync
echo "--- 安装后 ---"
ls -l /mnt/boot/system.bit
echo -n "  新 md5: "; md5sum /mnt/boot/system.bit | cut -d' ' -f1
echo -n "  头部 4 字节: "; od -An -tx1 -N4 /mnt/boot/system.bit
umount /mnt/boot
echo "OK 安装完成"
'''


def md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def root_run(script, tag, timeout=600):
    local = os.path.join(HERE, "_tmp_%s.sh" % tag)
    with open(local, "w", encoding="utf-8", newline="\n") as f:
        f.write("#!/bin/bash\n" + script)
    board.put(local, "/tmp/_%s.sh" % tag)
    return board.run("echo %s | sudo -S -p '' bash /tmp/_%s.sh" % (board.PASS, tag),
                     timeout=timeout)


def wait_board(limit=420):
    t0 = time.time()
    while time.time() - t0 < limit:
        board.HOST = board.find_host(verbose=False)
        if board.HOST:
            try:
                out, _ = board.run("echo alive", timeout=10, quiet=True)
                if "alive" in out:
                    print("  板子回来了: %s (等了 %.0f 秒)" % (board.HOST, time.time() - t0))
                    return True
            except Exception:
                pass
        print("  等待中 ... %.0fs" % (time.time() - t0), end="\r")
        time.sleep(5)
    print()
    return False


def main():
    if not board.HOST:
        board.find_host(verbose=True)
    if not board.HOST:
        raise SystemExit("找不到板子")

    print("=== 1. 上传比特流 ===")
    m = md5(BIT)
    sz = os.path.getsize(BIT)
    print("  %s  %d 字节  md5=%s" % (os.path.basename(BIT), sz, m))
    t0 = time.time()
    board.put(BIT, REMOTE)
    print("  上传完成, 用了 %.0f 秒 (%.0f KB/s)"
          % (time.time() - t0, sz / 1024.0 / max(1e-6, time.time() - t0)))

    print("=== 2. 原子安装到 SD ===")
    out, _ = root_run(INSTALL.replace("__MD5__", m), "flash")
    print(out)

    print("=== 3. 重启 ===")
    root_run("sync; (sleep 2; reboot) >/dev/null 2>&1 &", "reboot", timeout=20)
    time.sleep(12)
    if not wait_board(420):
        print("!! 板子没回来 —— 请断电重上一次电, 然后跟我说一声")
        return 1
    out, _ = board.run("uptime; cat /sys/class/graphics/fb0/pan", timeout=25)
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
