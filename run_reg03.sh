#!/bin/bash
# run_reg03.sh —— 在板子上跑 0x03 逐位隔离实验（安全版）
#
# ★ 为什么写成这样（血的教训）：
#   之前把 >180 秒的实验挂在 SSH 前台跑，SSH 一断，板上脚本被杀，
#   音频服务停在 stop 状态、PL 处于坏状态，最后只能人工断电重启。
#   所以这里：
#     1) setsid + nohup 完全脱离终端
#     2) trap 保证无论实验成功还是失败，最后一定把 zynq-audio 拉起来
#     3) PC 侧只轮询日志，不挂长连接
#
# 用法（PC 侧）: python board.py -f run_reg03.sh
# 日志:        /tmp/reg03.log

set -u
LOG=/tmp/reg03.log
TRIALS="${1:-8}"

echo "===== run_reg03 开始 $(date '+%F %T') =====" > "$LOG"

restore() {
    echo "" >> "$LOG"
    echo "--- 收尾：恢复音频服务 ---" >> "$LOG"
    systemctl start zynq-audio >> "$LOG" 2>&1
    sleep 4
    echo "zynq-audio: $(systemctl is-active zynq-audio)" >> "$LOG"
    curl -s --max-time 8 http://127.0.0.1:8767/state >> "$LOG" 2>&1
    echo "" >> "$LOG"
    echo "===== run_reg03 结束 $(date '+%F %T') =====" >> "$LOG"
}
# 无论中途怎么退出（正常/异常/被杀）都要恢复服务
trap restore EXIT INT TERM

echo "--- 1) 停音频服务（它独占设备）---" >> "$LOG"
systemctl stop zynq-audio >> "$LOG" 2>&1
sleep 2
echo "zynq-audio: $(systemctl is-active zynq-audio)" >> "$LOG"

echo "--- 2) 确认板子上的脚本存在 ---" >> "$LOG"
ls -l /home/zynq/ui/reg03_bit_isolation.py >> "$LOG" 2>&1
ls -l /home/zynq/ui/rec_big.py /home/zynq/ui/audio_pl.py >> "$LOG" 2>&1

echo "" >> "$LOG"
echo "--- 3) 跑实验（$TRIALS 次/配置）---" >> "$LOG"
cd /home/zynq/ui
python3 -u reg03_bit_isolation.py --trials "$TRIALS" >> "$LOG" 2>&1
echo "[实验退出码 $?]" >> "$LOG"
