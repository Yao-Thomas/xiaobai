# -*- coding: utf-8 -*-
"""capture_boot.py —— 用串口抓完整启动日志 (含 u-boot), 同时触发重启

用法: python capture_boot.py [抓取秒数]
      python capture_boot.py 120 --no-reboot    # 只抓, 不主动重启
"""
import os
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import serial

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PORT = os.environ.get("BOARD_COM", "COM7")
BAUD = 115200


def main(dur=120, do_reboot=True):
    s = serial.Serial(PORT, BAUD, timeout=0.2, write_timeout=1.0)
    s.reset_input_buffer()

    if do_reboot:
        import board
        print("[capture] 通过 SSH 触发重启 ...")
        try:
            board.run("echo %s | sudo -S -p '' bash -c 'sync; (sleep 3; reboot) >/dev/null 2>&1 &'"
                      % board.PASS, timeout=20, quiet=True)
        except Exception as e:
            print("[capture] 触发重启失败:", e)
        print("[capture] 开始抓串口 %d 秒 ..." % dur)

    t0 = time.time()
    buf = b""
    try:
        while time.time() - t0 < dur:
            chunk = s.read(4096)
            if chunk:
                buf += chunk
                sys.stdout.write(chunk.decode("utf-8", "replace"))
                sys.stdout.flush()
    except KeyboardInterrupt:
        pass
    finally:
        s.close()

    log = buf.decode("utf-8", "replace").replace("\r", "")
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "boot_log.txt")
    with open(out, "w", encoding="utf-8") as f:
        f.write(log)
    print("\n\n[capture] 完整日志已存: %s (%d 字节)" % (out, len(log)))

    # 挑出跟 FPGA 有关的行
    print("\n" + "=" * 56)
    print("跟 FPGA / PL 加载有关的行:")
    print("=" * 56)
    keys = ("fpga", "FPGA", "bitstream", "Bitstream", "loadb", "devcfg",
            "system.bit", "PCAP", "zynq_pl", "pl_load")
    hit = [ln for ln in log.splitlines() if any(k in ln for k in keys)]
    if hit:
        for ln in hit:
            print("  " + ln)
    else:
        print("  (一条都没有 —— 说明 boot.scr 的条件判断没进去, 或者日志没抓到)")
    print("=" * 56)


if __name__ == "__main__":
    dur = 120
    do_reboot = "--no-reboot" not in sys.argv
    for a in sys.argv[1:]:
        if a.isdigit():
            dur = int(a)
    main(dur, do_reboot)
