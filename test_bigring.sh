#!/bin/bash
sudo systemctl stop zynq-audio
sleep 2
cd /home/zynq/ui || exit 1
sudo python3 - <<'PY' 2>&1 | grep -vE "^\[codec\]"
import sys, time
sys.path.insert(0, "/home/zynq/ui")
from audio_pl import AudioOut, es8388_set_vol
ao = AudioOut()
ao.codec_up(); ao.i2s_config(); ao.fmt_config()
es8388_set_vol(ao.i2c, 0, 0xC0)      # 静音，不出声
ao.start()
es8388_set_vol(ao.i2c, 0, 0xC0)
print("  ring = %d 字节 = %d 帧 = %.3f 秒"
      % (ao.ring, ao.ring//8, ao.ring/352800.0))
print("  buf.avail = %d 字节 (%.1f MB)" % (ao.buf.avail, ao.buf.avail/1048576.0))
print("  period_bytes = %d" % ao.period_bytes)
ao.buf.write(0, b"\x00"*ao.ring)
time.sleep(0.2); ao.close()
PY
echo
sudo systemctl start zynq-audio
sleep 4
echo -n "  zynq-audio: "; systemctl is-active zynq-audio
curl -s --max-time 10 http://127.0.0.1:8767/state; echo