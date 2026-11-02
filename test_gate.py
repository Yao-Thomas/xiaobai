import sys, os
sys.path.insert(0, 'D:/ubuntu_iso')
import agent.policy as P
P.silent = lambda: True
import agent.tools as T
for cmd in ("ls /home/zynq",
            "sudo systemctl start zynq-audio",
            "systemctl restart zynq-audio",
            "python3 loopback_proof.py",
            "cat /proc/meminfo"):
    r = T._policy_gate("shell", cmd)
    print("  %-38s -> %s" % (cmd, (r or "放行").split(chr(10))[0][:60]))