#!/bin/bash
# run_mvol.sh —— ③ 频谱自证（matrix_vol.py 的 4 阶段流水线）安全运行器
#
# ══════════════════════════════════════════════════════════════════
#  ★★ 这个脚本会出声！跑之前必须得到用户明确同意。
# ══════════════════════════════════════════════════════════════════
#
# 前身（run_mvol.sh / start_mvol.sh / bg_mvol.sh）有三个问题：
#   1) 没有静音锁检查 —— 会不问自放，正是 2026-09-28 事故的性质
#   2) run_mvol.sh 挂在前台 —— SSH 一断就被杀，服务停在 stop 状态
#      （这个教训已经让我们掉过一次板子，只能人工断电）
#   3) start_mvol.sh 不留 trap —— 实验崩了音频服务一直停着
#
# 这个版本：
#   1) /etc/zynq-silent 存在就**拒绝运行**（除非显式 --force）
#   2) 必须由 PC 侧 setsid nohup 分离启动
#   3) trap 保证无论成败都恢复音频服务
#   4) 单元文件被移走时自动放回（因为实验需要服务能起来）
#
# 用法:
#    PC 侧:  python bg_mvol.py          （推荐，自动分离启动+轮询）
#    板上:   setsid nohup bash /tmp/run_mvol.sh > /dev/null 2>&1 &
#    日志:   /tmp/mvol.log

set -u
LOG=/tmp/mvol.log
FLAG="${1:-}"

# ─────────────── 静音锁：最重要的一道闸 ───────────────
if [ -f /etc/zynq-silent ] && [ "$FLAG" != "--force" ]; then
  cat > $LOG <<EOF
【静音锁生效 · 拒绝运行】$(date '+%F %T')

用户明确要求：在他本人同意之前，不许发出任何声音。
matrix_vol.py 会从喇叭放多个纯音（4 个阶段，约 2~4 分钟），
所以这里直接拒绝，不执行任何放音动作。

如果用户已经同意（当面确认过），执行：
    sudo rm -f /etc/zynq-silent
然后重新跑本脚本。
EOF
  echo "REFUSED_BY_SILENT_LOCK" >> $LOG
  echo "SILENT_LOCK_REFUSED"
  exit 3
fi

# ─────────────── 单元文件被移走时放回（实验需要服务能起）───────────────
if [ ! -f /etc/systemd/system/zynq-audio.service ] && \
   [ -f /root/zynq-audio.service.disabled ]; then
  sudo mv /root/zynq-audio.service.disabled \
          /etc/systemd/system/zynq-audio.service
  sudo systemctl daemon-reload
  sleep 1
fi

# ─────────────── 无论成败都要恢复服务 ───────────────
restore() {
  echo "" >> $LOG
  echo "--- 收尾：恢复音频服务 ---" >> $LOG
  sudo systemctl start zynq-audio >> $LOG 2>&1
  sleep 6
  echo "SERVICE=$(systemctl is-active zynq-audio)" >> $LOG
  echo "ALLDONE" >> $LOG
  echo "--- $(date '+%T') 结束 ---" >> $LOG
}
trap restore EXIT INT TERM

# ─────────────── 停服务（matrix_vol 要独占设备）───────────────
sudo pkill -f matrix_vol.py 2>/dev/null
sleep 1
sudo systemctl stop zynq-audio 2>/dev/null
sleep 2

: > $LOG
{
  echo "===== ③ 频谱自证 $(date '+%F %T') ====="
  echo "  脚本: /home/zynq/ui/matrix_vol.py"
  echo "  4 个阶段: 扫放音电平 -> 扫 ADC PGA -> 3 次可复现 -> 半双工对比"
  echo "  判据: 平坦度 > 100（白噪声约 1.7；旧值 1.8 已废弃）"
  echo "  音量: 从低到高逐级，遇到第一个线性区就停"
  echo ""
} >> $LOG

cd /home/zynq/ui || exit 1
python3 -u matrix_vol.py >> $LOG 2>&1
echo "" >> $LOG
echo "[matrix_vol 退出码 $?]" >> $LOG
