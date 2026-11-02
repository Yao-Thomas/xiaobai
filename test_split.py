import sys
sys.path.insert(0, 'D:/ubuntu_iso')
import agent.policy as P
P.silent = lambda: False
for c in ("ls && rm -rf /tmp/x", "ls | grep x", "ls; rm -rf /tmp/x",
          "a & b", "ls > /dev/null 2>&1", "free -m && df -h"):
    d, r = P.classify_shell(c)
    print("  %-8s %-34s %s" % (d, c, r[:46]))