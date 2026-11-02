#!/bin/bash
# ⚠️ 这个脚本已作废（2026-09-28）
#
# 原因：它会**不问自放**（没有静音锁检查），而且不留 trap
#       —— 实验崩了音频服务就一直停着。
#       2026-09-28 的"Agent 自行放音"事故就是这类问题的性质。
#
# 请改用：
#     PC 侧:  python bg_mvol.py        （分离启动 + 轮询 + 静音锁兜底）
#     板上:   bash /tmp/run_mvol.sh    （内部有静音锁检查，锁着会拒绝）
#
cat <<'EOF'
⚠️ 本脚本已作废。

它没有静音锁检查，会不问自放。
请用:  python bg_mvol.py        (PC 侧)
   或  bash /tmp/run_mvol.sh    (板上；内部有静音锁)
EOF
exit 1