import sys, os
sys.path.insert(0, 'D:/ubuntu_iso')
os.environ['PATH'] = os.environ['PATH']
import agent.policy as P
# 假装静音锁存在
P.silent = lambda: True
print("  (模拟静音锁生效)")
for c in ("systemctl start zynq-audio", "systemctl status zynq-audio",
          "python3 loopback_proof.py", "curl -X POST http://127.0.0.1:8767/play",
          "ls /home/zynq", "cat /proc/meminfo"):
    d, r = P.classify_shell(c)
    print("  %-6s %-46s %s" % (d, c, r[:60]))