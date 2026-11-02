echo "=== 1) 文件里有没有『幽灵』 ==="
grep -n "幽灵" /home/zynq/ui/desktop.py | sed 's/^/  /'
echo
echo "=== 2) 两处『开始』判定现在长什么样 ==="
grep -n "600 - TB_H + 10, 116, 600 - 10" /home/zynq/ui/desktop.py | sed 's/^/  /'
echo
echo "=== 3) 带上前后文 ==="
for ln in $(grep -n "600 - TB_H + 10, 116, 600 - 10" /home/zynq/ui/desktop.py | cut -d: -f1); do
  echo "  --- 第 $ln 行附近 ---"
  sed -n "$((ln-4)),$((ln+2))p" /home/zynq/ui/desktop.py | sed 's/^/    /'
done
echo
echo "=== 4) 备份文件列表 ==="
ls -lt /home/zynq/ui/desktop.py.bak_* 2>/dev/null | head -4 | awk '{print "  "$6" "$7" "$8"  "$9}'