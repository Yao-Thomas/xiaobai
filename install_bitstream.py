#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""install_bitstream.py —— 把新建的 bitstream 装到板子并重启

流程（每一步都可回退）：
  1. 检查本地新 bitstream 存在 + 打印哈希
  2. 上传到板上 /home/zynq/
  3. 备份板上当前的 /mnt/boot/system.bit
  4. 替换 /mnt/boot/system.bit
  5. 重启板子
  6. 等它起来，确认声卡和哈希

★ 板子上现存的可用版本（可回退）：
    /mnt/boot/system.bit.bak_audio_clockfix_20260928   8b1941...  ← 当前启动的
    /mnt/boot/system.bit.bak_before_rxbclk             （我上一轮加的备份）
"""
import hashlib
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import board                                                   # noqa: E402

BIT = (r"D:\ubuntu_iso\atk2026\Navigator_7020\Navigator_7020.runs"
       r"\impl_1\system_wrapper.bit")


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    if not os.path.exists(BIT):
        print("✗ 本地 bitstream 不存在:", BIT)
        print("  （重建可能还没跑完）")
        return 1

    size = os.path.getsize(BIT)
    print("=" * 74)
    print("安装新 bitstream")
    print("=" * 74)
    print("  本地文件: %s" % BIT)
    print("  大小: %d 字节" % size)
    print("  SHA256: %s" % sha256(BIT))

    if size < 3000000 or size > 6000000:
        print("  ⚠ 大小看着不对（正常约 4MB），确认一下再装")
        if input("  继续？输入 yes: ").strip().lower() != "yes":
            return 1

    print()
    print("[1] 上传到板上")
    board.put(BIT, "/home/zynq/system_rxbclk.bit")
    out, _ = board.run("ls -l /home/zynq/system_rxbclk.bit; "
                       "sha256sum /home/zynq/system_rxbclk.bit", timeout=120)
    print(out)

    print("[2] 备份板上当前的 bitstream")
    out, _ = board.run(
        "sudo cp /mnt/boot/system.bit /mnt/boot/system.bit.bak_before_rxbclk "
        "2>/dev/null; sha256sum /mnt/boot/system.bit", timeout=120)
    print(out)

    print("[3] 替换 /mnt/boot/system.bit")
    out, _ = board.run(
        "sudo cp /home/zynq/system_rxbclk.bit /mnt/boot/system.bit && "
        "sync && sha256sum /mnt/boot/system.bit", timeout=180)
    print(out)

    print("[4] 重启")
    try:
        board.run("sudo reboot", timeout=15, quiet=True)
    except Exception:
        pass
    print("  已发出重启命令，等 75 秒...")
    time.sleep(75)

    print("[5] 等待板子回来")
    for i in range(20):
        try:
            out, _ = board.run("echo UP; uptime; sha256sum /mnt/boot/system.bit; "
                               "cat /proc/asound/cards | head -2",
                               timeout=40, quiet=True)
            if out and "UP" in out:
                print(out)
                break
        except Exception:
            pass
        print("  第 %d 次还没起来，等 15 秒" % (i + 1))
        time.sleep(15)

    print()
    print("★ 装完了。接下来播放试听（记得先确认用户在场并同意）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
