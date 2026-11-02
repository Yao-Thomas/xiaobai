#!/bin/sh
# mem_sample.sh —— 采样长跑进程的内存/线程/句柄，用于判断 2 小时长跑是否退化
# 用法: sh mem_sample.sh

echo "time: $(date '+%Y-%m-%d %H:%M:%S')"
# 取 python3 那个进程：排除 sudo / setsid 外壳行
PID=$(ps -ef | grep 'soak_v4.py' | grep -v grep | grep -v sudo | grep -v setsid | awk '{print $2}' | head -1)
echo "uptime:$(cat /proc/uptime | cut -d' ' -f1)秒"

# 取 python3 那个进程（跳过 sudo 外壳）
if [ -z "$PID" ]; then
    echo "soak 进程未找到"
else
    echo "soak pid=$PID"
    awk '/VmRSS|VmSize|Threads/{print "  " $0}' /proc/$PID/status 2>/dev/null
    echo "  fds=$(ls /proc/$PID/fd 2>/dev/null | wc -l)"
    echo "  cpu_ticks=$(awk '{print $14+$15}' /proc/$PID/stat 2>/dev/null)"
fi

# 桌面与管家小白进程也看一下
for name in desktop.py agent; do
    P=$(ps -ef | grep "[/]$name" | awk '{print $2}' | head -1)
    if [ -n "$P" ]; then
        R=$(awk '/VmRSS/{print $2}' /proc/$P/status 2>/dev/null)
        echo "  $name pid=$P RSS=${R}kB"
    fi
done

echo "--- 系统内存 (MB) ---"
free -m | sed -n '2p'
echo "--- 负载 ---"
cat /proc/loadavg
echo "--- 采样的最后一行日志 ---"
tail -1 /tmp/soak2h.log
echo "MEM_SAMPLE_DONE"
