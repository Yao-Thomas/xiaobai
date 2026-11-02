#!/bin/sh
# his-trial-guard.sh —— "试用他的系统"那一跳的自愈 + 取证
#
# 只在我们自己内核以外的那一跳里干活:
#   · 把这一跳的完整现场 (dmesg / modprobe 结果 / PL 设备 / 显示) 存到 /root/his_trial/
#   · 等最多 4 分钟, 只要有网 (能 ping 通网关, 或有无线口拿到正常 IPv4) 就放行
#   · 没网 -> 重启。u-boot 里的 use_ours.flag 已经写好了, 于是必然回到我们自己的系统
#
# 配合 boot.scr 的 panic=10, 他内核 panic 也能自动退回来。

OUR_UTS='#1 SMP PREEMPT Thu Sep 14 08:39:17 UTC 2023'
GATEWAY=192.168.10.1
WAIT_LOOPS=48          # 48 x 5s = 240s
D=/root/his_trial

cur=$(uname -v)
if [ "$cur" = "$OUR_UTS" ]; then
    exit 0             # 是我们自己的内核, 什么都不做
fi

mkdir -p "$D"
R="$D/report_$(date +%Y%m%d_%H%M%S).txt"

{
    echo "##### his-trial boot $(date)"
    echo "--- uname ---"
    uname -a
    echo "--- cmdline ---"
    cat /proc/cmdline
    echo "--- boot-time dmesg ---"
    dmesg
    echo "--- lsmod (before) ---"
    lsmod
    echo "--- modinfo aic8800_fdrv ---"
    modinfo aic8800_fdrv 2>&1
    echo "--- modprobe aic8800_fdrv ---"
    modprobe -v aic8800_fdrv 2>&1
    echo "modprobe_rc=$?"
    echo "--- dmesg (after modprobe, tail 60) ---"
    dmesg | tail -60
    echo "--- lsmod (after) ---"
    lsmod
    echo "--- /proc/fb ---"
    cat /proc/fb 2>&1
    echo "--- ls /dev/fb* /dev/dri/* ---"
    ls -l /dev/fb* /dev/dri/ 2>&1
    echo "--- fb0 参数 ---"
    for f in name virtual_size bits_per_pixel stride smem_len; do
        printf "%s=" "$f"
        cat /sys/class/graphics/fb0/$f 2>&1
    done
    echo "--- PL 平台设备 (43c*) ---"
    ls /sys/bus/platform/devices/ 2>/dev/null | grep -i 43c
    echo "--- dmesg 关键子系统 ---"
    dmesg | grep -iE 'xilinx|drm|fb0|v4l|i2c|ov5640|dma|snd|clk_wiz|v_tc|frmbuf|audio|i2s' | head -80
    echo "--- /proc/interrupts ---"
    cat /proc/interrupts 2>&1
    echo "--- ip link ---"
    ip -br link 2>&1
} > "$R" 2>&1

ok=0
i=0
while [ "$i" -lt "$WAIT_LOOPS" ]; do
    if ping -c 1 -W 2 "$GATEWAY" >/dev/null 2>&1; then
        ok=1
        break
    fi
    if ip -4 -o addr show 2>/dev/null | awk '$2 ~ /^wl/ {print $4}' | grep -qv '^169\.254'; then
        ok=1
        break
    fi
    i=$((i + 1))
    sleep 5
done

{
    echo "--- waited $((i * 5))s, net_ok=$ok ---"
    echo "--- ip addr (final) ---"
    ip -br addr 2>&1
    echo "--- ip route (final) ---"
    ip route 2>&1
    echo "--- dmesg tail 40 (final) ---"
    dmesg | tail -40
} >> "$R" 2>&1

# 抓一帧屏幕当证据 (万一他的显示设计是好的, 这就是唯一的画面记录)
if [ -e /dev/fb0 ]; then
    timeout 20 dd if=/dev/fb0 of="$D/fb0.raw" bs=1M count=2 >>"$R" 2>&1
    ls -l "$D/fb0.raw" >> "$R" 2>&1
fi

if [ "$ok" = "1" ]; then
    echo "NETWORK OK -> 留在他的系统, 不重启" >> "$R"
    exit 0
fi

echo "NO NETWORK -> 重启退回我们自己的系统 (use_ours.flag 已置位)" >> "$R"
sync
sleep 2
reboot -f
