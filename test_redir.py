import sys
sys.path.insert(0, 'D:/ubuntu_iso')
import agent.policy as P
P.silent = lambda: False
SYS = "uptime; echo ---; free -m | head -3; echo ---; df -h / | tail -1; echo ---; cat /sys/class/thermal/thermal_zone0/temp 2>/dev/null; cat /proc/loadavg"
cases = [
  (SYS, "system 工具的命令 -> 期望 allow"),
  ("cat /proc/meminfo 2>/dev/null", "无害 stderr 重定向 -> 期望 allow"),
  ("echo hi > /etc/foo", "写到 /etc -> 期望 confirm"),
  ("echo hi > /tmp/x", "写到 /tmp -> 期望 confirm"),
  ("echo hi >/dev/null", "丢到 /dev/null -> 期望 allow"),
  ("ls > /dev/null 2>&1", "全丢 -> 期望 allow"),
  ("ls $(pwd)", "命令替换 -> 期望 confirm"),
  ("ls; rm -rf /tmp/x", "夹带写 -> 期望 confirm"),
  ("rm -rf /", "危险 -> 期望 deny"),
]
for c, note in cases:
    d, r = P.classify_shell(c)
    print("  %-8s %-56s %s" % (d, c[:56], note))