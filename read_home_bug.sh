echo "=== home.py 740-790（崩溃点附近）==="
sed -n '740,790p' /home/zynq/ui/home.py | cat -n | awk '{printf "  %3d: %s\n", $1+739, substr($0, index($0,$2))}'
echo
echo "=== self.static 在哪里赋值 ==="
grep -n "static" /home/zynq/ui/home.py | head -20 | sed 's/^/  /'
echo
echo "=== box 是怎么算的 ==="
grep -n "box" /home/zynq/ui/home.py | sed -n '1,20p' | sed 's/^/  /'