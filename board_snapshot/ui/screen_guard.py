#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""screen_guard.py —— 黑屏检测 + 自动恢复 (安全网)

为什么需要:
  之前踩过的坑 —— GPU 标记文件过期导致桌面 SIGBUS 崩溃循环, 屏幕全黑,
  看起来像"板子坏了"。这个守护进程会自动发现并抢救。

判定逻辑:
  每 INTERVAL 秒采样 /dev/fb0 的 200+ 个点
  某点 RGB 通道和 < DARK_SUM(24) 视为"黑点"
  黑点占比 > DARK_RATIO(0.85)  -> 记为一次黑屏
  连续 BAD_NEED(3) 次            -> 判定异常, 开始抢救

抢救阶梯 (逐级升级):
  ① 存证: 把当前画面存成 PNG + 记录状态到日志
  ② 杀掉桌面进程, 删掉 /home/zynq/.gpu_addr (GPU 标记)
  ③ 重启 zynq-desktop
  ④ 等 60 秒仍黑 -> 重启系统 (每个开机周期最多 2 次)

暂停:
  touch /home/zynq/.guard_pause   -> 停止干预(只记录不抢救)
  rm    /home/zynq/.guard_pause   -> 恢复
"""
import os, sys, time, mmap, subprocess, datetime

FB = "/dev/fb0"
LOG = "/var/log/zynq-screen-guard.log"
SHOTDIR = "/home/zynq/guard_shots"
PAUSE = "/home/zynq/.guard_pause"
GPU_MARK = "/home/zynq/.gpu_addr"

W, H, STRIDE = 1024, 600, 3072
INTERVAL = 10           # 采样间隔(秒)
DARK_SUM = 24           # RGB 和低于此值算黑点
DARK_RATIO = 0.85       # 黑点占比超过此值算一次黑屏
BAD_NEED = 3            # 连续几次算异常 (3*10=30秒)
RECOVER_COOLDOWN = 300  # 抢救成功后冷却(秒)
MAX_REBOOTS = 2         # 每个开机周期最多重启系统几次


def log(msg):
    line = "%s  %s" % (datetime.datetime.now().strftime("%m-%d %H:%M:%S"), msg)
    try:
        with open(LOG, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass
    # 只在交互终端打印 (服务里由日志文件记录, 避免重复)
    if sys.stdout.isatty():
        print(line, flush=True)


def sh(cmd, t=20):
    try:
        return subprocess.check_output(cmd, shell=True,
                                       stderr=subprocess.STDOUT,
                                       timeout=t).decode(errors="replace")
    except Exception as e:
        return str(e)


def sample():
    """采样 framebuffer, 返回 (黑点占比, 总采样数, 平均亮度)"""
    try:
        fd = os.open(FB, os.O_RDONLY)
        mm = mmap.mmap(fd, STRIDE * H, mmap.MAP_SHARED, mmap.PROT_READ)
        dark = 0
        n = 0
        tot = 0
        for y in range(5, H, 23):
            for x in range(5, W, 29):
                o = y * STRIDE + x * 3
                b, g, r = mm[o], mm[o + 1], mm[o + 2]
                s = b + g + r
                tot += s
                if s < DARK_SUM:
                    dark += 1
                n += 1
        mm.close()
        os.close(fd)
        return (dark / float(n), n, tot / float(n))
    except Exception as e:
        return (-1.0, 0, 0)


def save_shot(tag):
    """存证: 把当前画面存成 PNG"""
    try:
        os.makedirs(SHOTDIR, exist_ok=True)
        ts = datetime.datetime.now().strftime("%m%d_%H%M%S")
        out = os.path.join(SHOTDIR, "%s_%s.png" % (ts, tag))
        fd = os.open(FB, os.O_RDONLY)
        mm = mmap.mmap(fd, STRIDE * H, mmap.MAP_SHARED, mmap.PROT_READ)
        raw = mm[:]
        mm.close()
        os.close(fd)
        try:
            from PIL import Image
            img = Image.frombytes("RGB", (W, H), raw, "raw", "BGR", STRIDE)
            img.save(out)
        except Exception:
            with open(out.replace(".png", ".raw"), "wb") as f:
                f.write(raw)
            out = out.replace(".png", ".raw")
        return out
    except Exception as e:
        return "(存图失败: %s)" % e


def desktop_state():
    a = sh("systemctl is-active zynq-desktop").strip()
    n = sh("pgrep -c -f '[d]esktop.py'").strip()
    return a, n


def recover(level, reason, reboot_count):
    """抢救。level: 1=清标记重启桌面  2=重启系统"""
    log("!! 触发抢救 level=%d  原因: %s" % (level, reason))
    shot = save_shot("bad")
    a, n = desktop_state()
    log("   存证: %s   桌面状态: %s 进程 %s" % (shot, a, n))
    log("   日志尾部: %s" % sh("tail -5 /var/log/zynq-desktop.log 2>/dev/null").replace("\n", " | ")[:300])

    if os.path.exists(PAUSE):
        log("   (暂停开关存在, 只记录不干预)")
        return

    # ---- level 1: 清标记 + 重启桌面 ----
    if os.path.exists(GPU_MARK):
        os.remove(GPU_MARK)
        log("   已删除 GPU 标记 %s" % GPU_MARK)
    log("   重启桌面...")
    sh("systemctl restart zynq-desktop")
    time.sleep(20)
    ratio, cnt, avg = sample()
    if ratio >= 0 and ratio < DARK_RATIO:
        log("   ✅ 抢救成功! 现在黑点占比 %.1f%% (亮度均值 %.0f)" % (ratio * 100, avg))
        return True

    # ---- level 2: 重启系统 (限次) ----
    if level >= 2 and reboot_count < MAX_REBOOTS:
        log("   ⚠️ 桌面重启无效, 重启系统 (第 %d 次)" % (reboot_count + 1))
        with open("/home/zynq/.guard_reboot_count", "w") as f:
            f.write(str(reboot_count + 1))
        sh("systemctl reboot")
    else:
        log("   ⚠️ 已达重启上限或 level=1, 不再升级 (等人工处理)")
    return False


def main():
    log("=" * 60)
    log("黑屏安全网启动  (阈值: RGB和<%d, 黑点>%.0f%%, 连续%d次)"
        % (DARK_SUM, DARK_RATIO * 100, BAD_NEED))

    # 读重启计数
    try:
        reboot_count = int(open("/home/zynq/.guard_reboot_count").read().strip())
    except Exception:
        reboot_count = 0
    log("本次开机周期已重启系统 %d 次" % reboot_count)

    # 开机后先等系统稳定
    time.sleep(45)

    bad = 0
    paused_logged = False
    while True:
        try:
            paused = os.path.exists(PAUSE)
            ratio, cnt, avg = sample()
            if ratio < 0:
                log("采样失败(fb 打不开), 跳过")
            else:
                a, n = desktop_state()
                if ratio >= DARK_RATIO:
                    bad += 1
                    log("黑屏计数 %d/%d  (黑点 %.0f%%, 亮度 %.0f, 桌面=%s/%s)"
                        % (bad, BAD_NEED, ratio * 100, avg, a, n))
                else:
                    if bad > 0:
                        log("已恢复正常 (黑点 %.0f%%, 亮度 %.0f)" % (ratio * 100, avg))
                    bad = 0
                    paused_logged = False

                # 桌面在崩溃循环也要救 (即使屏幕还没全黑)
                crash_loop = (a in ("activating", "failed", "deactivating")) and n == "0"
                if crash_loop:
                    log("检测到桌面崩溃循环 (state=%s, 进程=%s), 直接抢救" % (a, n))
                    recover(1, "桌面崩溃循环", reboot_count)
                    bad = 0
                    time.sleep(RECOVER_COOLDOWN)
                    continue

                if bad >= BAD_NEED:
                    lvl = 2 if bad >= BAD_NEED + 3 else 1
                    recover(lvl, "连续 %d 次黑屏" % bad, reboot_count)
                    bad = 0
                    time.sleep(RECOVER_COOLDOWN)

            if paused and not paused_logged:
                log("⏸  暂停开关存在, 只监视不干预")
                paused_logged = True

        except Exception as e:
            log("异常: %s" % e)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
