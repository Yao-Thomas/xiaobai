#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fpga_loop_check.py —— 一条命令检查「agent 改 FPGA」闭环通不通

════════════════════════════════════════════════════════════════════
为什么要有这个（演示前必跑）
────────────────────────────────────────────────────────────────────
「agent 改 FPGA」这条链有 5 段，任何一段断了都会表现成
"agent 说提交成功，然后就没有然后了"：

    ① PC 侧守护进程在跑吗？          ← ★ 最常见：忘了开
    ② 板子 SSH 通吗？                ← 守护靠 SSH 读任务
    ③ Vivado 在吗？                  ← 路径对不对
    ④ 板子侧 agent 服务在吗？
    ⑤ fpga_jobs 目录权限对吗？        ← 踩过：root 建的目录，zynq 写不进去

用法:
    python fpga_loop_check.py               # 只检查（不上真任务）
    python fpga_loop_check.py --live        # 顺手提交一个真任务跑一遍
"""
import argparse
import io
import json
import os
import socket
import subprocess
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))


def _board_ip():
    """板子地址 —— 优先从 PC 客户端配置读，读不到再用兜底

    ★ 2026-10-03 改：原来这里是写死的 "192.168.110.144"。
      但板子的 IP 会变（DHCP）：192.168.110.144 → 192.168.0.38，
      写死之后体检一直报"板子不可达"，其实是地址过时了。
      ⇒ 优先读 ~/.xiaobai_chat.json（客户端设置里填的那个），
        其次扫一遍历史 IP（和 board.py 的 KNOWN 一致）。
    """
    p = os.path.join(os.path.expanduser("~"), ".xiaobai_chat.json")
    try:
        import json as _j
        with open(p, encoding="utf-8-sig") as f:
            ip = (_j.load(f) or {}).get("host")
        if ip:
            return ip.strip()
    except Exception:
        pass
    for ip in ("192.168.0.38", "192.168.110.144"):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.8)
            ok = (s.connect_ex((ip, 22)) == 0)
            s.close()
            if ok:
                return ip
        except Exception:
            continue
    return "192.168.0.38"


BOARD_IP = _board_ip()
VIVADO = r"D:\Xilinx\2026.1\Vivado\bin\vivado.bat"
PROJ = r"D:\ubuntu_iso\atk2026\Navigator_7020\Navigator_7020.xpr"

OK = "\u2713"
NO = "\u2717"


def board_run(cmd, timeout=60):
    """通过 board.py 在板子上跑命令"""
    p = subprocess.run([sys.executable, os.path.join(HERE, "board.py"), cmd],
                       capture_output=True, text=True, timeout=timeout,
                       encoding="utf-8", errors="replace")
    out = [ln for ln in (p.stdout or "").split("\n")
           if not ln.startswith("[board]")]
    return "\n".join(out).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true",
                    help="提交一个真的构建任务并等结果")
    a = ap.parse_args()

    print("=" * 70)
    print(" 「agent 改 FPGA」闭环体检")
    print("=" * 70)
    bad = []

    # ── ① PC 侧守护在跑吗 ──
    # ★ 检测方式（踩过）：第一版用 wmic 查进程命令行，
    #   但 wmic 在较新的 Windows 上【已经被移除】
    #   ⇒ 守护明明在跑（PID 10424），这里却报"没在跑"。
    #   现在改成读守护自己写的心跳文件（见 fpga_build_daemon.heartbeat）。
    print("\n【1】PC 侧构建守护")
    hb_path = os.path.join(HERE, ".fpga_daemon_heartbeat.json")
    hb = None
    if os.path.exists(hb_path):
        try:
            hb = json.load(open(hb_path, encoding="utf-8"))
        except Exception:
            hb = None
    if hb:
        age = time.time() - float(hb.get("ts") or 0)
        fresh = age < max(60.0, float(hb.get("interval") or 10) * 4)
        print("   %s 心跳: %s  pid=%s  最后活跃 %.0f 秒前"
              % (OK if fresh else NO, hb.get("iso"), hb.get("pid"), age))
        if fresh:
            print("   %s 守护进程在跑" % OK)
        else:
            print("   %s ★ 心跳过期（>%d 秒）—— 守护可能已经挂了"
                  % (NO, int(max(60.0, float(hb.get("interval") or 10) * 4))))
            bad.append("PC 守护进程（心跳过期）")
    else:
        print("   %s ★ 没有心跳文件 —— 守护从没启动过，" % NO)
        print("      双击 start_fpga_daemon.bat 启动")
        bad.append("PC 守护进程")

    # ── ② 板子 SSH ──
    print("\n【2】板子连通（SSH）")
    up = board_run("echo BOARD_OK", timeout=60)
    if "BOARD_OK" in up:
        print("   %s %s 可达" % (OK, BOARD_IP))
    else:
        print("   %s 连不上：%s" % (NO, up[:120]))
        bad.append("板子 SSH")
        print("\n（后面几项跳过）")
        return report(bad)

    # ── ③ Vivado ──
    print("\n【3】PC 侧 Vivado")
    if os.path.exists(VIVADO):
        print("   %s %s" % (OK, VIVADO))
    else:
        print("   %s ★ 找不到 %s" % (NO, VIVADO))
        bad.append("Vivado")
    if os.path.exists(PROJ):
        print("   %s 工程 %s" % (OK, os.path.basename(PROJ)))
    else:
        print("   %s ★ 找不到工程 %s" % (NO, PROJ))
        bad.append("Vivado 工程")

    # ── ④ 板载 agent ──
    print("\n【4】板载 agent 服务")
    h = board_run("curl -s --max-time 8 http://127.0.0.1:8765/health",
                  timeout=40)
    if '"ok"' in h or "ok" in h[:40]:
        print("   %s agent 在线" % OK)
    else:
        print("   %s ★ 不在线：%s" % (NO, h[:120]))
        bad.append("板载 agent")

    # ── ⑤ fpga_jobs 权限 ──
    print("\n【5】fpga_jobs 目录权限")
    ls = board_run("ls -ld /home/zynq/fpga_jobs 2>&1", timeout=40)
    print("   %s" % ls)
    if "zynq" in ls and "rwx" in ls:
        print("   %s zynq 可写（agent 用 zynq 身份跑）" % OK)
    else:
        print("   %s ★ 属主不对，agent 写不进去。" % NO)
        print("      修：sudo chown -R zynq:zynq /home/zynq/fpga_jobs")
        bad.append("fpga_jobs 权限")

    # ── ⑥（可选）真跑一个任务 ──
    if a.live and not bad:
        print("\n【6】★ 真跑一个任务（提交 + 等结果）")
        before = board_run("ls -1 /home/zynq/fpga_jobs/*.result.json "
                           "2>/dev/null | wc -l", timeout=40)
        sub = board_run(
            "curl -s --max-time 40 -X POST -H 'Content-Type: application/json'"
            " -d '{\"name\":\"hw_fpga_build\",\"args\":"
            "{\"preset\":\"check\",\"desc\":\"闭环体检\",\"wait\":false}}'"
            " http://127.0.0.1:8765/tool", timeout=60)
        print("   提交返回: %s" % sub[:200])
        if "需要用户批准" in sub:
            print("   \u2192 ★ 被安全门禁拦住了（这是设计如此）")
            print("     到板子界面上点「同意」，或调 /approve 批准")
        else:
            print("   等结果（最多 180 秒）...")
            for _ in range(36):
                time.sleep(5)
                after = board_run("ls -1 /home/zynq/fpga_jobs/*.result.json "
                                  "2>/dev/null | wc -l", timeout=40)
                if after != before:
                    print("   %s 结果出来了" % OK)
                    break
            else:
                print("   %s 180 秒还没结果 —— 看守护进程窗口" % NO)
                bad.append("构建执行")

    return report(bad)


def report(bad):
    print()
    print("=" * 70)
    if bad:
        print(" %s 有 %d 项不通：%s" % (NO, len(bad), "、".join(bad)))
        print(" 按上面提示修，再跑一次本脚本。")
    else:
        print(" %s 全部通过 —— 「agent 改 FPGA」闭环是通的" % OK)
    print("=" * 70)
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
