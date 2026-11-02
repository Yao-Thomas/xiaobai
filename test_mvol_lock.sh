#!/bin/bash
echo "=== 直接跑运行器（静音锁生效，应该拒绝且不出声）==="
rm -f /tmp/mvol.log
bash /tmp/run_mvol.sh
echo "退出码: $?"
echo
echo "--- 日志内容 ---"
cat /tmp/mvol.log
echo
echo "--- 关键：音频服务有没有被动过 ---"
echo -n "  zynq-audio: "; systemctl is-active zynq-audio
echo -n "  单元文件  : "; [ -f /etc/systemd/system/zynq-audio.service ] && echo 在原位 || echo 仍被移走