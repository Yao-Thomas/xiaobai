#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bg_mvol.py —— 在板子上**分离后台**跑 ③ 频谱自证，PC 侧只轮询

为什么不能直接 board.py -f run_mvol.sh：
    实验要停掉 zynq-audio（matrix_vol 直接用 RawCap 独占设备），
    跑 2~4 分钟。挂 SSH 前台的话，SSH 一断脚本被杀，
    服务停在 stop 状态 —— 这个教训已经让我们掉过一次板子。

★ 会出声。所以：
    1) run_mvol.sh 内部有静音锁检查，锁着会直接拒绝（退出码 3）
    2) 这里在启动前先问一次（--yes 跳过），避免手滑
    3) 启动后确认它没有被静音锁拒绝

用法:
    python bg_mvol.py            # 会先要求确认
    python bg_mvol.py --yes      # 不再确认（脚本内仍有静音锁兜底）
    python bg_mvol.py --tail     # 只看当前日志
    python bg_mvol.py --check    # 只看静音锁状态，不跑
"""
import re
import sys
import time

import board

LOG = "/tmp/mvol.log"
TIMEOUT_S = 900


def main():
    if "--tail" in sys.argv:
        print(board.run("tail -70 %s 2>/dev/null || echo '(还没跑过)'" % LOG,
                        timeout=60, quiet=True)[0])
        return

    if "--check" in sys.argv:
        out, _ = board.run(
            "echo -n '静音锁: '; [ -f /etc/zynq-silent ] && echo 生效 || echo 无; "
            "echo -n 'zynq-audio: '; systemctl is-active zynq-audio; "
            "echo -n '单元文件: '; [ -f /etc/systemd/system/zynq-audio.service ] "
            "&& echo 在原位 || echo 已移走",
            timeout=40, quiet=True)
        print(out)
        return

    print("=" * 74)
    print("③ 频谱自证（matrix_vol.py 4 阶段）")
    print("=" * 74)
    print("  ★★ 这个实验会从喇叭放多个纯音，持续 2~4 分钟。")
    print("      请先确认用户已明确同意，并且旁边没有人会被吵到。")
    print()

    if "--yes" not in sys.argv:
        try:
            a = input("确认要跑吗？输入 yes 继续: ").strip().lower()
        except EOFError:
            a = ""
        if a != "yes":
            print("已取消。")
            return

    print("\n[1] 上传运行器")
    try:
        board.put("run_mvol.sh", "/tmp/run_mvol.sh")
    except Exception as e:
        print("  上传失败:", e)
        return

    print("\n[2] 探测板子")
    print("  " + board.run("uptime; systemctl is-active zynq-audio",
                           timeout=40, quiet=True)[0].replace("\n", " | "))

    print("\n[3] 分离启动")
    board.run("chmod +x /tmp/run_mvol.sh; rm -f %s; "
              "setsid nohup bash /tmp/run_mvol.sh > /tmp/mvol_wrap.log 2>&1 & "
              "sleep 3; echo started" % LOG, timeout=60, quiet=True)

    # 先看有没有被静音锁拒绝
    time.sleep(4)
    head, _ = board.run("head -3 %s 2>/dev/null" % LOG, timeout=40, quiet=True)
    if "静音锁" in head or "REFUSED" in head:
        print("\n  ★ 被静音锁拒绝了（这脚本没出声）。日志：")
        print(head)
        return

    print("\n[4] 轮询（最多 %d 秒，PC 侧不挂长连接）" % TIMEOUT_S)
    t0 = time.time()
    last = 0
    while time.time() - t0 < TIMEOUT_S:
        time.sleep(15)
        n = 0
        try:
            t, _ = board.run("wc -c < %s 2>/dev/null || echo 0" % LOG,
                             timeout=45, quiet=True)
            n = int(re.sub(r"\D", "", t) or 0)
        except Exception:
            pass
        if n != last:
            print("   [%3ds] 日志 %d 字节" % (int(time.time() - t0), n))
            last = n
        d, _ = board.run("grep -c ALLDONE %s 2>/dev/null || echo 0" % LOG,
                         timeout=45, quiet=True)
        if re.sub(r"\D", "", d) not in ("", "0"):
            print("   [%3ds] ★ 结束" % int(time.time() - t0))
            break
    else:
        print("   超时（实验可能还在跑，用 --tail 看）")

    print("\n[5] 结果")
    print(board.run("cat %s" % LOG, timeout=90, quiet=True)[0][:6000])
    print("\n[6] 服务状态（trap 应该已恢复）")
    print(board.run("systemctl is-active zynq-audio", timeout=40,
                    quiet=True)[0])


if __name__ == "__main__":
    main()
