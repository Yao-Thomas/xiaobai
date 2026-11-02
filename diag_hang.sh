#!/usr/bin/env bash
pid=$(systemctl show -p MainPID --value zynq-desktop)
echo "=== 桌面 PID=$pid ==="
echo
echo "=== 1) CPU 时间是否在涨（涨=在循环；不涨=卡住）==="
t1=$(awk '{print $14+$15}' /proc/$pid/stat 2>/dev/null)
sleep 5
t2=$(awk '{print $14+$15}' /proc/$pid/stat 2>/dev/null)
echo "  5 秒前 ticks=$t1   现在 ticks=$t2   差=$((t2-t1))"
[ $((t2-t1)) -gt 50 ] && echo "  -> 在跑（约 $(( (t2-t1)/5/100 ))% CPU）" || echo "  -> 几乎不动"
echo
echo "=== 2) 进程状态与线程 ==="
grep -E "^(State|Threads|VmRSS)" /proc/$pid/status 2>/dev/null | sed 's/^/  /'
echo
echo "=== 3) stdout/stderr 指向哪里（管道满了会阻塞 print）==="
ls -l /proc/$pid/fd/1 /proc/$pid/fd/2 2>/dev/null | sed 's/^/  /'
echo
echo "=== 4) 打开的文件里有没有 fb ==="
ls -l /proc/$pid/fd/ 2>/dev/null | grep -iE "fb|snd|input" | sed 's/^/  /'
echo
echo "=== 5) 服务有没有设 StandardOutput ==="
systemctl cat zynq-desktop 2>/dev/null | grep -iE "Standard|Exec|Restart"
echo
echo "=== 6) 桌面最近输出（journal）==="
sudo journalctl -u zynq-desktop -n 15 --no-pager 2>/dev/null | tail -8 | sed 's/^/  /'
echo
echo "=== 7) 内存够吗（OOM 会让它卡）==="
free -m | sed 's/^/  /'
echo
echo "=== 8) 系统整体负载 ==="
uptime
