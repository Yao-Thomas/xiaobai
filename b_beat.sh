echo "=== _beat() 实现 + 调用点 ==="
sed -n '1225,1260p' /home/zynq/ui/desktop.py
echo
echo "=== 所有 _beat 调用 ==="
grep -n "_beat\|desktop_beat\|Thread" /home/zynq/ui/desktop.py | head -20
echo
echo "=== run_app 里是不是阻塞（有没有起线程）==="
grep -n "mod.run(scr" -B3 -A3 /home/zynq/ui/desktop.py