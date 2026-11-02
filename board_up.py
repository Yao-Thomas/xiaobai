#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""board_up.py —— 板子一上电就按顺序做完这些（PC 侧一条命令）

顺序：
  0) 探测在线
  1) 健康检查：三个服务 + 音频服务 state + ADC 存活（_ensure_alive 自检）
  2) 同步代码：把 PC 上已修正的 matrix_vol.py / audio_svc.py 传上去
     （★ 必须校验板上那份也带着"平坦度 > 100"的判据，
        否则 ③ 会又变成"白噪声也能通过"）
  3) ③ 频谱自证复跑（走常驻服务的 /matrix，稳定、随时可复现）
  4) 需要的话跑 0x03 逐位隔离实验（长实验，分离后台）

用法:
    python board_up.py            # 1~3 步
    python board_up.py --reg03    # 额外跑第 4 步
"""
import re
import sys

import board

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def route(cmd, timeout=180):
    """board.run 返回 (out, err) 元组；这里只要 stdout 字符串。"""
    out, _ = route(cmd, timeout=timeout, quiet=True)
    return out


def hr(t):
    print("\n" + "=" * 74)
    print(t)
    print("=" * 74)


def main():
    do_reg03 = "--reg03" in sys.argv

    hr("0) 探测板子")
    try:
        print("  " + route("uptime; hostname; hostname -I", timeout=40)
              .replace("\n", " | "))
    except Exception as e:
        print("  ✗ 板子不在线: %s" % e)
        return 1

    hr("1) 健康检查")
    print(route(
        "echo '--- 服务 ---'; "
        "systemctl is-active zynq-audio zynq-agent zynq-desktop; "
        "echo '--- 音频服务 state ---'; "
        "curl -s --max-time 8 http://127.0.0.1:8767/state; echo; "
        "echo '--- Agent health ---'; "
        "curl -s --max-time 8 http://127.0.0.1:8765/health | head -c 300; echo; "
        "echo '--- 温度 ---'; cat /sys/class/thermal/thermal_zone0/temp "
        "2>/dev/null; echo; "
        "echo '--- 音乐目录 ---'; ls /home/zynq/Music/*.wav 2>/dev/null | head -5",
        timeout=90))

    hr("2) 同步代码 + 校验板上判据")
    for loc, rem in (("ui/matrix_vol.py", "/home/zynq/ui/matrix_vol.py"),
                     ("ui/audio_svc.py", "/home/zynq/ui/audio_svc.py"),
                     ("ui/reg03_bit_isolation.py",
                      "/home/zynq/ui/reg03_bit_isolation.py")):
        try:
            board.put(loc, rem)
            print("  上传 %s" % rem)
        except Exception as e:
            print("  [!] %s 上传失败: %s" % (rem, e))

    # ★ 关键校验：板上那份必须真的用 >100
    chk = route(
        "grep -n 'minflat > 100\\|min_flatness\\|flatness' "
        "/home/zynq/ui/audio_svc.py | head -6", timeout=60)
    print("  板上 audio_svc.py 的判据行:")
    for ln in chk.splitlines():
        print("    " + ln.strip())
    if "100" not in chk:
        print("  ⚠️ 板上没找到 >100 的判据 —— 先别跑 ③，否则结果是假的")

    route("sudo systemctl restart zynq-audio; sleep 8; "
              "systemctl is-active zynq-audio", timeout=90)

    hr("3) ③ 频谱自证复跑（走常驻服务 /matrix）")
    print("  这一步会从喇叭放 6 个候选频率，用麦克风回录，")
    print("  判据：对角线命中 >= 5/6 且 最小平坦度 > 100")
    print("  ★ 会出声（纯音，不是蜂鸣器）\n")
    out = route("bash /tmp/run_matrix.sh 2>&1 || "
                    "curl -s --max-time 300 -X POST "
                    "-H 'Content-Type: application/json' "
                    "-d '{\"secs\":0.5,\"amp\":0.9}' "
                    "http://127.0.0.1:8767/matrix", timeout=420)
    print(out[:4000])

    if do_reg03:
        hr("4) 0x03 逐位隔离实验（长实验，分离后台）")
        import subprocess
        r = subprocess.run([sys.executable, "bg_reg03.py", "8"],
                           timeout=1200)
        print("  bg_reg03 退出码", r.returncode)

    hr("完成")
    print(route("systemctl is-active zynq-audio zynq-agent zynq-desktop",
                    timeout=60))
    return 0


if __name__ == "__main__":
    sys.exit(main())
