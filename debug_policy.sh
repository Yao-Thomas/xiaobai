#!/bin/bash
# 直接调试 policy 的批准匹配
sudo python3 - <<'PY'
import sys
sys.path.insert(0, "/home/zynq")
from agent import policy as P

cmd = "touch /tmp/demo_approval"
print("  测试命令:", repr(cmd))
print("  classify:", P.classify_shell(cmd))
print("  is_approved:", P.is_approved("shell", cmd))
print()
print("  当前 _pending:")
for it in P._pending:
    print("    id=%s key=%s payload=%r" % (it["id"], it["key"], it["payload"]))
print("  当前 _approved:")
import time
for k, v in P._approved.items():
    print("    key=%s 还有 %.0f 秒" % (k, v - time.time()))
print()
print("  手动算一下 key:")
print("    request 时的 key :", P._key("shell", cmd))
print("    队列里的 key     :", [it["key"] for it in P._pending if it["payload"] == cmd])
PY
