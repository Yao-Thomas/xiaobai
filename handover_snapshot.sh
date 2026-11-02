#!/bin/bash
echo "=== 交接状态快照 $(date '+%F %T') ==="
echo
echo "【服务】"
for s in zynq-agent zynq-audio zynq-desktop; do
  printf "  %-16s %s\n" "$s" "$(systemctl is-active $s 2>/dev/null)"
done
echo
echo "【静音状态】"
echo -n "  /etc/zynq-silent : "; [ -f /etc/zynq-silent ] && echo 存在 || echo 无
echo -n "  音频单元文件     : "; [ -f /etc/systemd/system/zynq-audio.service ] && echo 原位 || echo 已移走
echo
echo "【codec / I2S】"
sudo python3 - <<'PY'
import sys
sys.path.insert(0, "/home/zynq/ui")
try:
    from audio_pl import I2C, Mem, I2S_BASE, I2S_RX_BASE, I2S_CORE_CTRL
    i = I2C()
    print("  DAC 数字音量 0x1A/0x1B = 0x%02X/0x%02X  %s"
          % (i.rd(0x1A), i.rd(0x1B),
             "静音" if i.rd(0x1A) == 0xC0 else "可出声"))
    print("  输出音量 0x2E          = %d" % (i.rd(0x2E) & 0x3F))
    i.close()
    m = Mem()
    print("  I2S TX/RX CORE_CTRL    = %d / %d"
          % (m.rd(I2S_BASE, I2S_CORE_CTRL), m.rd(I2S_RX_BASE, I2S_CORE_CTRL)))
    m.close()
except Exception as e:
    print("  读取失败:", e)
PY
echo
echo "【关键文件在不在】"
for f in /home/zynq/ui/audio_pl.py /home/zynq/ui/audio_svc.py \
         /home/zynq/ui/rec_big.py /home/zynq/ui/matrix_vol.py \
         /home/zynq/ui/pitch_check2.py /home/zynq/ui/silent_play_test.py \
         /home/zynq/agent/main.py /home/zynq/agent/policy.py \
         /home/zynq/agent/tools.py /home/zynq/agent/asr.py \
         /home/zynq/agent/tts.py; do
  if [ -f "$f" ]; then printf "  OK   %-42s %6d\n" "$f" "$(stat -c%s $f)"
  else printf "  缺失 %s\n" "$f"; fi
done
echo
echo "【/tmp 里的运行器（会被清，注意）】"
ls /tmp/*.sh /tmp/*.py 2>/dev/null | head -12 | sed 's/^/  /'
echo
echo "【Agent 接口数 / 权限层】"
curl -s --max-time 10 http://127.0.0.1:8765/ 2>/dev/null | python3 -c "
import json,sys
try: print('  接口数:', len(json.load(sys.stdin).get('endpoints',[])))
except Exception as e: print('  读不到:', e)
"