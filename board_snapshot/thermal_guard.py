#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""thermal_guard.py —— 板子温度守护 + 过热自动降温

════════════════════════════════════════════════════════════════════
为什么需要它
════════════════════════════════════════════════════════════════════
这块 Zynq-7020 的实际情况（实测）：
  · ★ 没有任何风扇，也没有 PWM 控制
  · ★ 内核没有 cpufreq —— 连降频都做不到
  · 空载（load 0.5）就已经 70°C 上下，而且在缓慢爬升

所以唯一能降温的手段就是【让它少干活 / 停活】。

════════════════════════════════════════════════════════════════════
分级策略（带滞回，避免在阈值附近来回抖）
════════════════════════════════════════════════════════════════════
  等级   触发温度   动作
  ────  ────────  ──────────────────────────────────────────────
  OK      < 72°C   什么都不做
  WARN    ≥ 75°C   记日志 + 写状态文件（给 agent / 桌面读）
  COOL    ≥ 80°C   ★ 降载：停桌面动画类应用、停音频、停 GPU 演示
  STOP    ≥ 85°C   ★ 停桌面 + 停音频，只留 agent（还要能汇报）
  EMERG   ≥ 90°C   ★ 停一切可停的，只留最小系统（agent 仍在跑）

  降级恢复：温度回落到 (触发值 - 5°C) 以下才恢复上一级，避免抖动。

════════════════════════════════════════════════════════════════════
温度来源
════════════════════════════════════════════════════════════════════
  /sys/bus/iio/devices/iio:device0/in_temp0_raw     (XADC 片上温度)
  in_temp0_scale = 123.040771484   (millidegree / LSB)
  in_temp0_offset = -2219
  温度(°C) = (raw + offset) * scale / 1000

用法:
    sudo python3 thermal_guard.py              # 前台跑（调试用）
    sudo python3 thermal_guard.py --once       # 只读一次温度
    sudo python3 thermal_guard.py --status     # 打印当前状态
    sudo python3 thermal_guard.py --no-action  # 只监控不动作（安全模式）
    sudo python3 thermal_guard.py --test 88    # 假装 88°C，演练动作（不改真实状态）
"""
import argparse
import json
import os
import subprocess
import sys
import time
import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

IIO = "/sys/bus/iio/devices/iio:device0"
RAW = IIO + "/in_temp0_raw"
SCALE = IIO + "/in_temp0_scale"
OFFSET = IIO + "/in_temp0_offset"

STATE_DIR = "/run/thermal"
STATE_FILE = STATE_DIR + "/state.json"
LOG_FILE = "/var/log/thermal_guard.log"
HIST_FILE = STATE_DIR + "/history.txt"

# 分级阈值（摄氏度）
#
# ★★★ 2026-10-01 按实测重新标定 ★★★
#   实测结论（很关键）：
#     · 这块板子【空载、桌面停了、音频停了】仍然稳定在 86°C
#     · 停桌面 / 降背光 对温度几乎没有影响（+0.9°C 的波动）
#     · XADC 读数经数据手册公式交叉验证，是准的
#     · 没有风扇、没有 cpufreq，软件能省的电上限只有约 40%
#       （PS 自身的 1.488W 是关不掉的）
#   ⇒ 这是【结构性散热问题】，不是软件负载问题。
#     所以阈值必须按实测平衡点来定，否则守护会一直卡在"停机"状态，
#     把板子弄得不能用，却一点也没降温。
#
#   商业级 Tj 上限 = 85°C。板子实测平衡点已经在那之上，
#   标定后的策略是：不追求"降到安全区"（做不到），
#   而是在【继续超标】时逐级停掉非必要负载。
#
# ★★★★ 2026-10-01 第二次修正（很重要，血的教训）★★★★
#   我一开始在 EMERG 级用 `poweroff`。结果：
#     · poweroff 在这块 Zynq 板子上是【halt】，不是断电
#     · 板子电源还在（用户说得对：没按板上按键不可能真断电）
#     · 但 PS 停了、kernel 挂了、getty 没了 ⇒ 串口完全静默
#     · ★ 而 RTC 闹钟【无法从 poweroff/halt 唤醒它】（实测：闹钟到点没反应，
#       等了 5 分钟、20 次 ping 全不通，串口 0 字节）
#     · 我也试了 10 种 DTR/RTS 序列想从串口复位 —— 全没用（复位脚没接到串口）
#   ⇒ 结论：在这块板子上，**poweroff 是单向操作**，只能人工按按键/重新上电。
#     所以守护【绝对不能用 poweroff】，否则一超标板子就"死"到你回家。
#
#   ★ 改用 `systemctl reboot`：
#     · reboot 走的是 PS 复位路径，板子【能自己起来】—— 这是关键
#     · 缺点：只停 40 秒左右，降温效果有限
#     · 补偿：在启动早期加一段"冷却暂停"（见 cooldown 相关逻辑），
#       那段时间只有最小系统在跑
T_WARN = 88.0              # 记日志（实测平衡点之上）
T_COOL = 90.0              # 停音频
T_STOP = 92.0              # 停桌面
T_EMERG = 96.0             # ★ 重启（不是关机！）
HYST = 3.0                 # 滞回（实测波动约 ±1°C，3 度够）
REBOOT_ON_EMERG = True     # ★ 到达 EMERG 时是否重启（务必保持 True，别改回 poweroff）
COOLDOWN_MINS = 5          # ★ 重启后冷却暂停多少分钟
POLL_SECS = 5.0
HIST_MAX = 720             # 历史保留条数
# 启停标志：重启前写它，开机时由 cooldown 脚本读走并删除
# ★ 必须放【持久】路径 —— /run 是 tmpfs，重启就没了，标志传不过去
COOLDOWN_FLAG = "/var/lib/thermal/cool_down"
COOLDOWN_STATE_DIR = "/var/lib/thermal"

# 各级要停的服务（恢复时会再起回来）
STOP_SERVICES = {
    "COOL": ["zynq-audio"],                      # 音频（功放也发热）
    "STOP": ["zynq-desktop", "zynq-audio"],      # 桌面最耗（持续刷屏）
    "EMERG": ["zynq-desktop", "zynq-audio"],
}
# ★ agent 永远不停 —— 它要负责汇报和让用户远程处理
PROTECTED = {"zynq-agent"}

# 降载时要杀掉的应用进程（桌面里的耗电大户，按需加）
HEAVY_APPS = ["apps_gpu.py", "apps_gpuperf.py", "apps_scope.py",
              "apps_mines.py", "apps_fight.py"]


def log(msg):
    line = "[%s] %s" % (datetime.datetime.now().strftime("%H:%M:%S"), msg)
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except OSError:
        pass


def read_temp():
    """读 XADC 片上温度，返回摄氏度（读不到返回 None）"""
    try:
        raw = int(open(RAW).read().strip())
        scale = float(open(SCALE).read().strip())
        off = float(open(OFFSET).read().strip())
        return (raw + off) * scale / 1000.0
    except Exception:
        return None


def sh(cmd, t=20):
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, timeout=t)
        return p.returncode, p.stdout.decode(errors="replace").strip()
    except Exception as e:
        return -1, str(e)


def svc_active(name):
    rc, out = sh(["systemctl", "is-active", name], 5)
    return out.strip() == "active"


def which_stopped_services(needed):
    """找出【本来在跑、但现在被我们停了】的服务

    ★ 只恢复我们停掉的 —— 别把用户自己关掉的服务给起回来。
    """
    stopped = []
    for s in needed:
        if s in PROTECTED:
            continue
        if not svc_active(s):
            stopped.append(s)
    return stopped


def take_action(level, stopped):
    """执行降载动作；stopped 是累积的'被我们停掉的服务'集合"""
    if level in ("OK", "WARN"):
        return stopped
    need = STOP_SERVICES.get(level, [])
    for s in need:
        if s in PROTECTED:
            continue
        if svc_active(s):
            sh(["systemctl", "stop", s], 30)
            if not svc_active(s):
                stopped.add(s)
                log("  ★ 已停服务 %s（降温）" % s)
    # 杀重负载应用
    rc, out = sh(["pgrep", "-f", "--", "desktop.py"], 5)
    if out:
        for app in HEAVY_APPS:
            rc2, ids = sh(["pgrep", "-f", "--", app], 5)
            if ids:
                for pid in ids.split():
                    sh(["kill", "-TERM", pid], 5)
                    log("  ★ 已停应用 %s (pid %s)" % (app, pid))
    return stopped


def reboot_board(temp):
    """★ 最后手段：重启（不是关机！）

    ★★★ 为什么必须是 reboot 而不是 poweroff ★★★
      实测：这块板子 poweroff 之后是 halt 状态 —— 电源还在、串口静默、
      RTC 闹钟唤不醒、DTR/RTS 也复位不了。也就是说 **poweroff 是单向的**，
      一旦执行，板子就"死"在那里直到有人按键/重新上电。

      reboot 走 PS 复位路径，板子能自己起来 —— 这是唯一安全的自动手段。

      降温靠的是"重启后的冷却暂停"（见 cool_down.py / cooldown 标志），
      不是靠重启本身。
    """
    sentinel = STATE_DIR + "/rebooted"
    if os.path.exists(sentinel):
        return
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        # ★ 冷却标志要写到【持久】目录：/run 是 tmpfs，重启就丢了
        os.makedirs(COOLDOWN_STATE_DIR, exist_ok=True)
        with open(COOLDOWN_FLAG, "w", encoding="utf-8") as f:
            f.write("%d\n%.1f\n" % (COOLDOWN_MINS, temp))
        with open(sentinel, "w", encoding="utf-8") as f:
            f.write("%.1f %s\n" % (temp,
                                   datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    except OSError:
        pass
    log("=" * 60)
    log("★★★ 温度 %.1f°C 达到紧急阈值 %.1f°C —— 重启并冷却 %d 分钟 ★★★"
        % (temp, T_EMERG, COOLDOWN_MINS))
    log("   （★ 用 reboot 不用 poweroff：这块板子 poweroff 后醒不过来）")
    log("=" * 60)
    for s in ("zynq-desktop", "zynq-audio"):
        try:
            sh(["systemctl", "stop", s], 15)
        except Exception:
            pass
    sh(["sync"], 20)
    sh(["systemctl", "reboot"], 20)


def restore(stopped):
    """温度下来了，把之前停掉的服务起回来"""
    for s in list(stopped):
        if svc_active(s):
            stopped.discard(s)
            continue
        sh(["systemctl", "start", s], 30)
        if svc_active(s):
            stopped.discard(s)
            log("  ✓ 已恢复服务 %s" % s)
    return stopped


def decide(temp, stopped):
    """根据温度决定等级"""
    if temp >= T_EMERG:
        return "EMERG"
    if temp >= T_STOP:
        return "STOP"
    if temp >= T_COOL:
        return "COOL"
    if temp >= T_WARN:
        return "WARN"
    # 滞回：已经降过载，要低于 (阈值 - HYST) 才算真降温
    if stopped:
        if temp >= T_COOL - HYST:
            return "COOL"
    return "OK"


def write_state(d):
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        os.replace(tmp, STATE_FILE)          # 原子替换
    except OSError:
        pass


def append_hist(line):
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        lines = []
        if os.path.exists(HIST_FILE):
            with open(HIST_FILE) as f:
                lines = f.read().splitlines()
        lines.append(line)
        if len(lines) > HIST_MAX:
            lines = lines[-HIST_MAX:]
        with open(HIST_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except OSError:
        pass


def read_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="只读一次温度")
    ap.add_argument("--status", action="store_true", help="打印当前状态")
    ap.add_argument("--no-action", action="store_true", help="只监控不动作")
    ap.add_argument("--test", type=float, default=None,
                    help="假装这个温度走一遍决策（不真的动服务）")
    ap.add_argument("--interval", type=float, default=POLL_SECS)
    a = ap.parse_args()

    if a.status:
        st = read_state()
        print(json.dumps(st, ensure_ascii=False, indent=2))
        return 0

    if a.once:
        t = read_temp()
        print("%.1f" % t if t is not None else "读不到")
        return 0

    if a.test is not None:
        print("=== 演练：假装温度 %.1f°C ===" % a.test)
        stopped = set()
        lv = decide(a.test, stopped)
        print("  判定等级: %s" % lv)
        need = STOP_SERVICES.get(lv, [])
        print("  会停的服务: %s" % (", ".join(need) if need else "(无)"))
        print("  ★ 这是演练，没有真的停任何东西")
        return 0

    if os.geteuid() != 0:
        sys.exit("需要 root: sudo python3 %s" % os.path.basename(__file__))

    no_action = a.no_action
    if no_action:
        log("★ 安全模式：只监控、不动作")
    log("启动温度守护  阈值 WARN=%.0f COOL=%.0f STOP=%.0f EMERG=%.0f 滞回=%.0f"
        % (T_WARN, T_COOL, T_STOP, T_EMERG, HYST))

    stopped = set()
    last_level = None
    peak = 0.0
    while True:
        t = read_temp()
        if t is None:
            time.sleep(a.interval)
            continue
        if t > peak:
            peak = t
        level = decide(t, stopped)

        if level != last_level:
            log("温度 %.1f°C -> 等级 %s%s（峰值 %.1f）"
                % (t, level, "  [已降载 %d 个服务]" % len(stopped) if stopped else "",
                   peak))
            last_level = level

        if not no_action:
            if level == "EMERG":
                # ★ 最高级：重启 + 冷却暂停
                #   （★ 绝不能用 poweroff —— 实测这块板子 poweroff 后醒不过来）
                stopped = take_action(level, stopped)
                if REBOOT_ON_EMERG:
                    reboot_board(t)
                    time.sleep(60)      # 别在重启过程中反复触发
                    continue
            elif level in ("OK",):
                if stopped:
                    log("温度回落到 %.1f°C，恢复服务" % t)
                    stopped = restore(stopped)
                    peak = t          # 复位峰值
            elif level == "WARN":
                pass                  # 只记录
            else:
                stopped = take_action(level, stopped)

        write_state({
            "temp": round(t, 1),
            "peak": round(peak, 1),
            "level": level,
            "stopped": sorted(stopped),
            "thresholds": {"warn": T_WARN, "cool": T_COOL,
                           "stop": T_STOP, "emerg": T_EMERG},
            "no_action": no_action,
            "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
        append_hist("%s %.1f %s" %
                    (datetime.datetime.now().strftime("%H:%M:%S"), t, level))

        time.sleep(a.interval)


if __name__ == "__main__":
    sys.exit(main() or 0)
