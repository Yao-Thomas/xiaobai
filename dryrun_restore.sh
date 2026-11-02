#!/bin/bash
# dryrun_restore.sh —— 预演"恢复放音"这条路，**但全程 DAC 数字静音**（不出声）
#
# ══════════════════════════════════════════════════════════════════
#  为什么要做这个
# ══════════════════════════════════════════════════════════════════
# 用户说"可以放音了"之后，我要按台账四步走：
#     1) 放回单元文件 + 启动 zynq-audio
#     2) 恢复 codec 寄存器
#     3) 跑 ③ 频谱自证
#     4) 跑 ⑤ 语音闭环
#
# 如果这条路里任何一步有问题（服务起不来、端口没监听、
# 单元文件放回去但 daemon-reload 没生效、依赖没满足…），
# 用户回来的那一刻就会卡住。
#
# 所以先**空跑一遍**：真的启动服务、真的调接口、真的录音，
# 但**把 DAC 数字音量钉在 0xC0（-96dB）**，所以一点声都不会出。
#
# 注意：服务启动时 codec_up() 会把 DAC 设回 0x00，
#       所以每次操作前后都要**重新确认并重新压静音**。
set -u

MUTE=0xC0

mute() {
  sudo python3 - <<'PY'
import sys
sys.path.insert(0, "/home/zynq/ui")
from audio_pl import I2C, es8388_set_vol
i = I2C()
es8388_set_vol(i, 0, 0xC0)          # 输出音量 0(-45dB) + DAC 数字 -96dB
print("    压静音: 0x1A=0x%02X 0x1B=0x%02X 0x2E=%d"
      % (i.rd(0x1A), i.rd(0x1B), i.rd(0x2E) & 0x3F))
i.close()
PY
}

echo "=================================================================="
echo " 预演恢复放音（★ 全程 DAC 数字静音，不出声）"
echo " $(date '+%F %T')"
echo "=================================================================="
echo
echo "--- 0) 起始状态 ---"
echo -n "  zynq-audio : "; systemctl is-active zynq-audio
echo -n "  静音锁     : "; [ -f /etc/zynq-silent ] && echo 生效 || echo 无
echo -n "  单元文件   : "; [ -f /etc/systemd/system/zynq-audio.service ] \
  && echo 在原位 || echo 已移走
echo

echo "--- 1) 压静音（在启动服务之前先设一次，双保险）---"
mute
echo

echo "--- 2) 放回单元文件 ---"
if [ ! -f /etc/systemd/system/zynq-audio.service ]; then
  sudo mv /root/zynq-audio.service.disabled \
          /etc/systemd/system/zynq-audio.service \
    && echo "  已放回" || { echo "  ✗ 放回失败"; exit 1; }
  sudo systemctl daemon-reload && echo "  daemon-reload 完成"
else
  echo "  已经在原位，跳过"
fi
echo

echo "--- 3) 启动音频服务 ---"
sudo systemctl start zynq-audio
sleep 4
echo -n "  is-active: "; systemctl is-active zynq-audio
echo -n "  is-enabled: "; systemctl is-enabled zynq-audio 2>&1
echo

echo "--- 4) ★ 立刻重新压静音（服务 codec_up 会把它设回 0x00）---"
mute
echo

echo "--- 5) 服务健康检查 ---"
curl -s --max-time 15 http://127.0.0.1:8767/health | head -c 300; echo
echo -n "  端口监听: "
sudo ss -ltnp 2>/dev/null | grep -c ':8767' || echo 0
echo

echo "--- 6) /state ---"
curl -s --max-time 15 http://127.0.0.1:8767/state | head -c 300; echo
echo

echo "--- 7) 再压一次静音，然后试录音（录音不出声，可以测）---"
mute
curl -s --max-time 40 -X POST -H 'Content-Type: application/json' \
  -d '{"secs":2,"rate":16000,"mono":true}' \
  http://127.0.0.1:8767/record -o /tmp/dryrun_rec.wav
ls -l /tmp/dryrun_rec.wav 2>/dev/null | awk '{print "  录到 "$5" 字节"}'
python3 - <<'PY'
import wave, struct, math, os
p = "/tmp/dryrun_rec.wav"
if not os.path.exists(p) or os.path.getsize(p) < 1000:
    print("  ✗ 没录到数据"); raise SystemExit
w = wave.open(p, "rb"); n = w.getnframes(); r = w.getframerate()
d = w.readframes(n); w.close()
v = struct.unpack("<%dh" % (len(d) // 2), d)
rms = math.sqrt(sum(float(x) * x for x in v) / len(v))
print("  %d 帧 = %.2f 秒  RMS=%.0f 峰值=%d  %s"
      % (n, n / float(r), rms, max(abs(x) for x in v),
         "★有信号" if rms > 20 else "⚠近乎静音"))
PY
echo

echo "--- 8) 走一遍 /asr 和 /tts（都不出声）---"
echo -n "  ASR: "
curl -s --max-time 90 -X POST -H 'Content-Type: application/json' \
  -d '{"file":"/tmp/dryrun_rec.wav"}' http://127.0.0.1:8765/asr \
  | python3 -c "
import json,sys
try:
    d=json.load(sys.stdin)
    print('引擎=%s 耗时=%s 文字=%r' % (d.get('engine'),d.get('elapsed'),d.get('text')))
except Exception as e: print('(解析失败)',e)
"
echo -n "  TTS: "
curl -s --max-time 60 -X POST -H 'Content-Type: application/json' \
  -d '{"text":"恢复预演测试，不会播出来。"}' http://127.0.0.1:8765/tts \
  | python3 -c "
import json,sys
try:
    d=json.load(sys.stdin)
    print('%s  %s 字节' % (d.get('path'), d.get('bytes')) if d.get('ok') else d)
except Exception as e: print('(解析失败)',e)
"
echo

echo "--- 9) ★ 关键：确认还没出声，且现在压静音 ---"
mute
echo "  服务状态: $(systemctl is-active zynq-audio)"
echo

echo "--- 10) 收尾：停服务 + 重新封锁 + 上锁 ---"
sudo systemctl stop zynq-audio
sleep 2
sudo systemctl disable zynq-audio 2>&1 | tail -1
sudo mv /etc/systemd/system/zynq-audio.service \
        /root/zynq-audio.service.disabled 2>/dev/null \
  && echo "  单元文件已移走"
sudo rm -f /etc/systemd/system/multi-user.target.wants/zynq-audio.service
sudo systemctl daemon-reload
sleep 1
echo -n "  zynq-audio : "; systemctl is-active zynq-audio
echo -n "  start 测试 : "; sudo systemctl start zynq-audio 2>&1 | head -1
echo -n "  静音锁     : "; [ -f /etc/zynq-silent ] && echo 生效 || echo 无
echo
echo "=================================================================="
echo " 预演结束。全程 DAC 数字静音（0xC0 = -96dB）。"
echo " 结论：恢复路径可用与否见上面每一步的输出。"
echo "=================================================================="
