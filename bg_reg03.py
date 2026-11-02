#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bg_reg03.py —— 在板子上**分离后台**跑 0x03 逐位隔离实验，PC 侧只轮询

为什么不能直接 board.py -f run_reg03.sh：
    实验要先把 zynq-audio 停掉（它独占 DMA/I2C），跑几分钟。
    如果挂在 SSH 前台，SSH 一断，板上脚本被杀，服务就停在 stop 状态
    —— 上次就是这么把板子搞到需要人工断电的。

所以：上传 -> setsid nohup 分离启动 -> PC 只读日志。

用法:
    python bg_reg03.py              # 默认 8 次/配置
    python bg_reg03.py 12           # 12 次/配置
    python bg_reg03.py --tail       # 只看当前日志
"""
import re
import sys
import time

import board

LOG = "/tmp/reg03.log"


def upload(local, remote):
    print("  上传 %s -> %s" % (local, remote))
    try:
        board.put(local, remote)
        return True
    except Exception as e:
        print("    [!] 上传失败: %s" % e)
        return False


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    trials = args[0] if args else "8"
    tail_only = "--tail" in sys.argv
    timeout_s = 900

    print("=" * 74)
    print("0x03 逐位隔离实验（板子 %s）" % board.HOST)
    print("=" * 74)

    if tail_only:
        print(board.run("cat %s 2>/dev/null | tail -60" % LOG, timeout=60))
        return

    # ---- 1) 上传 ----
    print("\n[1] 上传脚本")
    upload("ui/reg03_bit_isolation.py", "/home/zynq/ui/reg03_bit_isolation.py")
    upload("run_reg03.sh", "/tmp/run_reg03.sh")

    # ---- 2) 探测在线 ----
    print("\n[2] 探测板子")
    up = board.run("uptime; systemctl is-active zynq-audio", timeout=40)
    print("   " + up.replace("\n", " | "))

    # ---- 3) 分离启动 ----
    print("\n[3] 分离启动（setsid + nohup，脱离 SSH）")
    board.run(
        "chmod +x /tmp/run_reg03.sh; "
        "rm -f %s; "
        "setsid nohup bash /tmp/run_reg03.sh %s > /tmp/reg03_wrap.log 2>&1 & "
        "sleep 2; echo started; pgrep -f reg03_bit_isolation | head -3"
        % (LOG, trials),
        timeout=60)
    print("   已启动")

    # ---- 4) 轮询 ----
    print("\n[4] 轮询日志（最多 %d 秒，PC 侧不挂长连接）" % timeout_s)
    t0 = time.time()
    last_len = 0
    while time.time() - t0 < timeout_s:
        time.sleep(15)
        try:
            txt = board.run("wc -c < %s 2>/dev/null || echo 0" % LOG,
                            timeout=45).strip()
            n = int(re.sub(r"\D", "", txt) or 0)
        except Exception as e:
            print("   轮询异常: %s" % e)
            continue
        el = int(time.time() - t0)
        if n != last_len:
            print("   [%3ds] 日志 %d 字节（还在跑）" % (el, n))
            last_len = n
        # 完成标志
        try:
            done = board.run("grep -c 'run_reg03 结束' %s 2>/dev/null || echo 0"
                             % LOG, timeout=45).strip()
        except Exception:
            done = "0"
        if re.sub(r"\D", "", done) not in ("", "0"):
            print("   [%3ds] ★ 实验结束" % el)
            break
    else:
        print("   超时（实验可能还在跑，用 --tail 看日志）")

    # ---- 5) 打印结果 ----
    print("\n[5] 日志尾部")
    out = board.run("tail -75 %s" % LOG, timeout=90)
    print(out)
    print("\n[6] 服务状态（脚本的 trap 应该已经恢复它）")
    print(board.run("systemctl is-active zynq-audio; "
                    "curl -s --max-time 8 http://127.0.0.1:8767/state",
                    timeout=60))


if __name__ == "__main__":
    main()
