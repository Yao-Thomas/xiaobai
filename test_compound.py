import sys
sys.path.insert(0, 'D:/ubuntu_iso')
import agent.policy as P
P.silent = lambda: False
cases = [
  ("uptime; echo ---; free -m | head -3; echo ---; df -h / | tail -1", "system 工具拼的"),
  ("ls /home/zynq", "单只读"),
  ("cat /proc/meminfo | grep Mem", "管道只读"),
  ("ls; rm -rf /tmp/x", "只读+危险写"),
  ("systemctl is-active zynq-audio && free -m", "只读复合"),
  ("echo hi > /etc/foo", "重定向到 /etc"),
  ("df -h / > /tmp/out.txt", "重定向到 /tmp"),
  ("uptime; systemctl restart zynq-audio", "只读+改服务"),
  ("ls $(pwd)", "命令替换"),
  ("rm -rf /", "危险"),
]
print("  %-8s %-52s %s" % ("判定", "命令", "原因"))
print("  " + "-"*96)
for c, note in cases:
    d, r = P.classify_shell(c)
    print("  %-8s %-52s %s" % (d, c[:52], r[:44]))
    print("  %-8s %-52s (%s)" % ("", "", note))