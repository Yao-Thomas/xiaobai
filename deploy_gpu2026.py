#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""deploy_gpu2026.py —— 把自研 GPU 的 bitstream 部署到板子并验证

子命令:
  check             板子状态 / boot.scr 是否支持 system.bit / 当前 SD 上有什么
  install <格式>     上传并写成 SD 启动分区的 system.bit
                    格式: fullbit(默认, 唯一实测可用) / bootgen / swapped / raw
  reboot            重启板子并等它回来
  verify            截图 + 探测 0x43CB0000 上的 GPU 寄存器
  auto              自动轮询各种格式: 装 -> 重启 -> 探测, 成功就停
  enable            确认 GPU 正常后, 写 .gpu_addr 标记并重启桌面 + 测加速比
  revert            恢复备份的 system.bit 并重启
  status            只看服务状态

=== 核心结论 (2026-09-24 实测) ===

u-boot 的 `fpga loadb` 要的是【带 ASCII 文本头的完整 .bit 文件】,
不是去掉头的 .bin! u-boot 会自己解析 .bit 头部、自己做 DMA 对齐和字节交换。
成功时它会打印:
    design filename = "system_wrapper;...Version=2026.1;..."
    part number = "7z020clg400"
    bytes in bitstream = 4045564
    zynq_align_dma_buffer: Align buffer at ... to ... (swap 1)

实测五种格式只有完整 .bit 能用:
    完整 .bit (00 09 0f f0 ...)          OK
    去头 + 字节交换 (bb 00 00 00 ...)     FAIL: Command 'loadb' failed: Error 1
    去头 raw       (00 00 00 bb ...)     FAIL: 同上
    bootgen 输出   (ff ff ff ff ...)     FAIL: 同上
    .bit 用 fpga load (不带 b)           FAIL: Bitstream is not validated yet

注意: Linux 的 FPGA Manager 要的偏偏是【去头 + 字节交换】的 .bin (两者正好相反)。
      它也能用, 但【运行中重配 PL 会打断 DRM 显示驱动 -> 整机内核卡死】,
      千万不要走那条路 (实测踩过, 只能断电重启)。

板子上的服务名是 zynq-desktop / zynq-screen-guard (带 zynq- 前缀)。
所有涉及挂载/服务的操作都要 root, 所以统一走 sudo。
"""
import os
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import board  # noqa: E402

IMPL = r"D:\ubuntu_iso\atk2026\Navigator_7020\Navigator_7020.runs\impl_1"

BIT = {
    # 正确的那个: 带文本头的完整 .bit —— u-boot 的 fpga loadb 就认这个
    "fullbit": os.path.join(IMPL, "system_wrapper.bit"),
    # 下面三个是错误格式, 只留作对照 / 给 Linux FPGA Manager 用
    "bootgen": os.path.join(HERE, "gpu2026_bootgen.bin"),
    "swapped": os.path.join(HERE, "gpu2026_swapped.bit"),
    "raw":     os.path.join(HERE, "gpu2026_raw.bit"),
}
# fullbit 排第一: 实测只有它能被 u-boot 接受
ORDER = ["fullbit", "bootgen", "swapped", "raw"]

PROBE_LOCAL = os.path.join(HERE, "gpu_probe.py")
PROBE_REMOTE = "/home/zynq/ui/gpu_probe.py"

SVC = "zynq-desktop zynq-screen-guard wifi-connect ssh"


# ---------------------------------------------------------------- 基础

def sh(cmd, timeout=180, quiet=False):
    """以 zynq 用户执行"""
    return board.run(cmd, timeout=timeout, quiet=quiet)


def root_run(script, timeout=300, quiet=False, tag="step"):
    """以 root 执行一段脚本 (上传成文件再用 sudo bash 跑, 避免引号地狱)"""
    local = os.path.join(HERE, "_tmp_%s.sh" % tag)
    with open(local, "w", encoding="utf-8", newline="\n") as f:
        f.write("#!/bin/bash\n" + script)
    remote = "/tmp/_%s.sh" % tag
    board.put(local, remote)
    cmd = "echo %s | sudo -S -p '' bash %s" % (board.PASS, remote)
    return board.run(cmd, timeout=timeout, quiet=quiet)


def svc_state():
    return "for s in %s; do printf '%%-20s %%s\\n' \"$s\" " \
           "\"$(systemctl is-active $s 2>/dev/null)\"; done" % SVC


def wait_ssh(limit=240):
    t0 = time.time()
    while time.time() - t0 < limit:
        board.HOST = board.find_host(verbose=False)
        if board.HOST:
            try:
                out, _ = board.run("echo alive", timeout=10, quiet=True)
                if "alive" in out:
                    print("  板子已回来: %s  (等待 %.0f 秒)"
                          % (board.HOST, time.time() - t0))
                    return True
            except Exception:
                pass
        time.sleep(5)
        print("  等待中 ... %.0fs" % (time.time() - t0), end="\r")
    print()
    return False


# ---------------------------------------------------------------- check

CHECK_SCRIPT = r'''
echo "=== 主机 ==="; hostname; uptime
echo
echo "=== 网卡 ==="; ip -4 addr show | grep -E "^[0-9]+:|inet "
echo
echo "=== SD 分区 ==="; lsblk -o NAME,SIZE,FSTYPE,LABEL,MOUNTPOINT | grep -E "NAME|mmcblk"
echo
echo "=== 挂载启动分区 ==="
mkdir -p /mnt/boot
mountpoint -q /mnt/boot || mount /dev/mmcblk0p1 /mnt/boot
ls -l /mnt/boot/ | head -30
echo
echo "=== boot.scr 里跟 PL 加载相关的内容 ==="
if [ -f /mnt/boot/boot.scr ]; then
    grep -a -o -E ".{0,60}(system\.bit|fpga [a-z]+).{0,60}" /mnt/boot/boot.scr \
        || echo "(没有 system.bit / fpga 相关内容!)"
else
    echo "(没有 boot.scr)"
fi
echo
echo "=== 现有 system.bit (头部决定能不能被 u-boot 接受) ==="
if [ -f /mnt/boot/system.bit ]; then
    ls -l /mnt/boot/system.bit
    echo -n "  头部 8 字节: "; od -An -tx1 -N8 /mnt/boot/system.bit
    case "$(od -An -tx1 -N4 /mnt/boot/system.bit | tr -d ' ')" in
        00090ff0) echo "  ==> 完整 .bit (带文本头)  ★ 正确格式" ;;
        bb000000) echo "  ==> 去头 + 字节交换 .bin  ✗ u-boot 会加载失败!" ;;
        000000bb) echo "  ==> 去头 raw .bin          ✗ u-boot 会加载失败!" ;;
        ffffffff) echo "  ==> bootgen 输出 .bin      ✗ u-boot 会加载失败!" ;;
        *)        echo "  ==> 未知格式" ;;
    esac
fi
umount /mnt/boot
echo
echo "=== 桌面渲染模式 ==="
if [ -f /home/zynq/.gpu_addr ]; then
    echo -n "有 .gpu_addr: "; cat /home/zynq/.gpu_addr
else
    echo "(无 .gpu_addr → 软件渲染)"
fi
echo
echo "=== 服务状态 ==="
__SVC__
echo
echo "=== GPU 探测 (需要 root 才能开 /dev/mem) ==="
cd /home/zynq/ui && python3 gpu_probe.py 2>&1 | head -14
echo
echo "=== 看门狗暂停标记 ==="
ls -l /home/zynq/.guard_pause 2>/dev/null || echo "(未暂停)"
'''.replace("__SVC__", svc_state())


def cmd_check():
    board.put(PROBE_LOCAL, PROBE_REMOTE)
    root_run(CHECK_SCRIPT, timeout=180, tag="check")


# ---------------------------------------------------------------- install

INSTALL_SCRIPT = r'''
set -e
SRC=__SRC__
mkdir -p /mnt/boot
mountpoint -q /mnt/boot || mount /dev/mmcblk0p1 /mnt/boot
if [ ! -f /mnt/boot/BOOT.BIN ]; then
    echo "!! /mnt/boot 里没有 BOOT.BIN, 这不像启动分区, 中止"
    umount /mnt/boot
    exit 1
fi
echo "--- 安装前 ---"
ls -l /mnt/boot/system.bit* 2>/dev/null || echo "(SD 上原本没有 system.bit)"
if [ -f /mnt/boot/system.bit ] && [ ! -f /mnt/boot/system.bit.bak_before_gpu ]; then
    cp /mnt/boot/system.bit /mnt/boot/system.bit.bak_before_gpu
    echo "OK 已备份原始 system.bit -> system.bit.bak_before_gpu"
fi
cp -f "$SRC" /mnt/boot/system.bit
sync
echo "--- 安装后 ---"
ls -l /mnt/boot/system.bit
md5sum "$SRC" /mnt/boot/system.bit
echo -n "--- 头部 8 字节: "; od -An -tx1 -N8 /mnt/boot/system.bit
case "$(od -An -tx1 -N4 /mnt/boot/system.bit | tr -d ' ')" in
    00090ff0) echo "OK 这是完整 .bit, u-boot 能加载 (__FMT__)" ;;
    *)        echo "!! 警告: 这看起来不是完整 .bit, u-boot 的 fpga loadb 可能会失败!" ;;
esac
umount /mnt/boot
echo "OK 安装完成 (__FMT__)"
'''


def install(fmt):
    src = BIT.get(fmt)
    if not src or not os.path.exists(src):
        raise SystemExit(
            "找不到 %s\n  可用的: %s" % (src, ", ".join(BIT.keys())))
    remote = "/home/zynq/gpu2026_%s.bit" % fmt
    print("  上传 %s (%.1f MB)" % (os.path.basename(src), os.path.getsize(src) / 1e6))
    board.put(src, remote)
    root_run(INSTALL_SCRIPT.replace("__SRC__", remote).replace("__FMT__", fmt),
             timeout=300, tag="install")


def cmd_install(fmt):
    pause_guard(True)
    install(fmt)


# ---------------------------------------------------------------- guard

def pause_guard(on=True):
    if on:
        sh("touch /home/zynq/.guard_pause", quiet=True)
        print("  看门狗已暂停")
    else:
        sh("rm -f /home/zynq/.guard_pause", quiet=True)
        print("  看门狗已恢复")


# ---------------------------------------------------------------- revert

REVERT_SCRIPT = r'''
set -e
mkdir -p /mnt/boot
mountpoint -q /mnt/boot || mount /dev/mmcblk0p1 /mnt/boot
FOUND=""
for b in system.bit.bak_before_gpu system.bit.origbak system.bit.binbak system.bit.bak_orig; do
    if [ -f /mnt/boot/$b ]; then
        cp -f /mnt/boot/$b /mnt/boot/system.bit
        sync
        echo "OK 已从 $b 恢复 system.bit"
        FOUND=$b
        break
    fi
done
if [ -z "$FOUND" ]; then
    echo "i  没有任何备份, 保持原样"
fi
ls -l /mnt/boot/system.bit 2>/dev/null
umount /mnt/boot
rm -f /home/zynq/.gpu_addr
echo "OK 已清掉 .gpu_addr (回到软件渲染)"
'''


def cmd_revert():
    pause_guard(True)
    root_run(REVERT_SCRIPT, timeout=180, tag="revert")
    print("现在可以 reboot 了")


# ---------------------------------------------------------------- reboot

def cmd_reboot():
    print("  重启板子 ...")
    root_run("sync; (sleep 2; reboot) >/dev/null 2>&1 &", timeout=20,
             quiet=True, tag="reboot")
    time.sleep(10)
    if wait_ssh():
        sh("uptime")


# ---------------------------------------------------------------- verify

def probe_gpu():
    board.put(PROBE_LOCAL, PROBE_REMOTE)
    # 必须用 root: /dev/mem 普通用户打不开, 否则会误报"没解码"
    out, _ = root_run("cd /home/zynq/ui && python3 gpu_probe.py; echo RC=$?",
                      timeout=60, quiet=True, tag="probe")
    ok = ("RC=0" in out) and ("已解码" in out)
    return ok, out


def grab_shot(tag):
    remote = "/home/zynq/shot_%s.png" % tag
    root_run("cd /home/zynq/ui && python3 shot_board.py %s; echo RC=$?" % remote,
             timeout=150, quiet=True, tag="shot")
    local = os.path.join(HERE, "shot_%s.png" % tag)
    try:
        board.get(remote, local)
    except Exception as e:
        return None, "下载截图失败: %s" % e
    return local, ""


def analyze_shot(path):
    try:
        from PIL import Image
    except ImportError:
        return None, None
    im = Image.open(path).convert("RGB").resize((128, 75))
    px = list(im.getdata())
    dark = sum(1 for r, g, b in px if r + g + b < 24)
    return dark / float(len(px)), len(set(px))


def verify_once(tag="t"):
    print("  [1/2] 探测 GPU 寄存器 0x43CB0000 ...")
    gpu_ok, out = probe_gpu()
    print("        " + out.strip().replace("\n", "\n        "))

    print("  [2/2] 抓屏 (只看 DDR 帧缓冲, 不能证明 LCD 真的亮)")
    shot, msg = grab_shot(tag)
    lcd_ok, note = None, ""
    if shot:
        ratio, colors = analyze_shot(shot)
        if ratio is None:
            note = "截图已存 %s" % shot
        else:
            lcd_ok = (ratio < 0.85)
            note = "黑屏比例 %.0f%%, 颜色数 %d -> %s  (%s)" % (
                ratio * 100, colors, "画面有内容" if lcd_ok else "全黑!", shot)
    else:
        note = msg
    print("        " + note)
    return gpu_ok, lcd_ok, note


def cmd_verify():
    if not board.HOST and not wait_ssh(60):
        return
    sh("uptime")
    sh(svc_state())
    gpu_ok, lcd_ok, _ = verify_once(time.strftime("%m%d_%H%M%S"))
    print("=" * 54)
    if gpu_ok:
        print("GPU 正常! 下一步: python deploy_gpu2026.py enable")
    elif lcd_ok is False:
        print("画面全黑 -> 立刻 revert")
    else:
        print("GPU 不可用 -> 检查 SD 上 system.bit 是不是【完整 .bit】")
    print("=" * 54)


# ---------------------------------------------------------------- auto

def cmd_auto():
    pause_guard(True)
    good = None
    for fmt in ORDER:
        print("\n" + "=" * 54)
        print(">>> 试 %s 格式" % fmt)
        print("=" * 54)
        try:
            install(fmt)
        except Exception as e:
            print("  安装失败, 跳过: %s" % e)
            continue
        cmd_reboot()
        if not board.HOST:
            print("  板子没回来, 停止")
            break
        gpu_ok, lcd_ok, _ = verify_once(fmt)
        if gpu_ok:
            print("\n  OK %s 格式成功!" % fmt)
            good = fmt
            break
        print("\n  -- %s 格式没让 GPU 出现, 试下一种" % fmt)

    print("\n" + "=" * 54)
    if good:
        print("结论: 用 %s 格式" % good)
        print("下一步: python deploy_gpu2026.py enable")
    else:
        print("结论: 所有格式都没成功")
    print("=" * 54)


# ---------------------------------------------------------------- enable

def cmd_enable():
    print("写 .gpu_addr 标记并重启桌面 ...")
    sh("echo 0x43CB0000 > /home/zynq/.gpu_addr; cat /home/zynq/.gpu_addr")
    pause_guard(False)
    root_run("systemctl restart zynq-desktop; sleep 8; systemctl is-active zynq-desktop",
             timeout=120, tag="enable")
    print("\n--- 桌面日志 ---")
    root_run("journalctl -u zynq-desktop -n 60 --no-pager | "
             "grep -iE 'gpu|GPU|挂载|桌面' | tail -12", timeout=60, tag="log")
    print("\n--- 真实加速比 (gpu_demo.py) ---")
    root_run("cd /home/zynq/ui && python3 gpu_demo.py 2>&1 | tail -32",
             timeout=300, tag="demo")
    print("\n--- 抓屏确认 ---")
    verify_once("gpu_on")


def cmd_status():
    sh(svc_state())
    sh("ls -l /home/zynq/.gpu_addr 2>/dev/null || echo '(无 .gpu_addr)'; "
       "ls -l /home/zynq/.guard_pause 2>/dev/null || echo '(guard 未暂停)'")


DISPATCH = {
    "check": cmd_check,
    "revert": cmd_revert,
    "reboot": cmd_reboot,
    "verify": cmd_verify,
    "auto": cmd_auto,
    "enable": cmd_enable,
    "status": cmd_status,
}

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(1)
    a = sys.argv[1]
    if a == "install":
        cmd_install(sys.argv[2] if len(sys.argv) > 2 else "fullbit")
    elif a in DISPATCH:
        DISPATCH[a]()
    else:
        print(__doc__)
