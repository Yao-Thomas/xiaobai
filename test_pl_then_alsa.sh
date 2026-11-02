#!/bin/sh
# test_pl_then_alsa.sh —— 验证假设：先让 PL 工具配好 I2S RX，ALSA 采集就能用
#
# 之前的观察：
#   · 直接 ALSA 采集          -> -137 dBFS（数字静音）
#   · 跑过 rec_big.py 之后再采 -> -50 ~ -68 dBFS（有信号）
#
# 如果这个假设成立，说明：
#   audio_alsa_svc.py（纯 ALSA 播放）从来不配置 PL 的 I2S RX，
#   而 audio_svc.py（PL 独占版）会配。
#   换服务之后没人配 PL，采集就成了静音。
#
# 做法：
#   1. 先测 ALSA 采集（对照）
#   2. 跑 rec_big.py 配置 PL（它会配 I2S 收发 + formatter）
#   3. 再测 ALSA 采集（实验组）
#   4. 对比

echo "======================================================"
echo " 验证：PL 配置好之后，ALSA 采集能不能用"
echo "======================================================"
echo

echo "【1】对照组：直接 ALSA 采集 2 秒"
sudo arecord -D hw:0,1 -f S24_LE -r 44100 -c 2 -d 2 -t raw /tmp/alsa_before.raw 2>&1 | head -2
ls -la /tmp/alsa_before.raw 2>/dev/null | awk '{print "  文件:", $5, "字节"}'
sudo python3 /home/zynq/analyze_wav.py /tmp/alsa_before.raw 2>/dev/null | grep -E "声道 0|RMS=|恒定|极低" | head -3
echo

echo "【2】跑 PL 工具配置 I2S 收发（rec_big.py，约 30 秒）"
echo "   ★ 注意：它自己会放音（ON/OFF/ON 三次对照）"
cd /home/zynq/ui
sudo systemctl stop zynq-audio 2>/dev/null
sleep 1
sudo timeout 120 python3 rec_big.py --secs 0.4 2>&1 | tail -22
echo

echo "【3】实验组：PL 配好之后再 ALSA 采集 2 秒"
sudo arecord -D hw:0,1 -f S24_LE -r 44100 -c 2 -d 2 -t raw /tmp/alsa_after.raw 2>&1 | head -2
ls -la /tmp/alsa_after.raw 2>/dev/null | awk '{print "  文件:", $5, "字节"}'
sudo python3 /home/zynq/analyze_wav.py /tmp/alsa_after.raw 2>/dev/null | grep -E "声道 0|RMS=|恒定|极低|正常" | head -3
echo

echo "【4】起回音频服务"
sudo systemctl start zynq-audio
sleep 4
echo "  zynq-audio: $(systemctl is-active zynq-audio)"
echo
echo "=== 结论判读 ==="
echo "  对照组 -137 + 实验组 > -100  -> ★ 假设成立：PL 没配好就是静音"
echo "  两组都 -137                 -> PL 配置不是根因，另有原因"
