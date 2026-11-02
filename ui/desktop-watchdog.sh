#!/bin/sh
# desktop-watchdog.sh —— 桌面"画面冻结"看门狗
#
# 为什么需要:
#   zynq-screen-guard 只会救【黑屏】。桌面主循环一旦被阻塞（比如某个读网络的
#   调用卡住），画面会停在最后一帧 —— 看着正常，但点哪都没反应。
#   那个守护进程看不出这种"活着的死机"。
#
# 做法:
#   桌面每一轮循环往 /run/desktop_beat 写一个时间戳；本脚本定时检查，
#   超过 STALE 秒没更新就重启桌面服务。

BEAT=/run/desktop_beat
STALE=25

[ -f "$BEAT" ] || exit 0          # 桌面还没起来，不管

now=$(date +%s)
beat=$(cut -d. -f1 "$BEAT" 2>/dev/null)
[ -n "$beat" ] || exit 0

age=$((now - beat))
if [ "$age" -gt "$STALE" ]; then
    logger -t desktop-watchdog "桌面心跳停了 ${age}s，重启 zynq-desktop"
    echo "desktop stalled ${age}s -> restart"
    systemctl restart zynq-desktop
    # 刚重启的桌面要几秒才会写第一次心跳，先把时间戳顶掉，
    # 免得下一个 20s 周期里又被判成"卡死"来回重启
    date +%s > "$BEAT"
else
    echo "ok (${age}s)"
fi
