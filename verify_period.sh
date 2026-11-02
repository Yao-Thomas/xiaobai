#!/bin/bash
# 静默验证：环变大且 R_PERIOD 不再是溢出值
cd /home/zynq/ui || exit 1
sudo python3 - <<'PY' 2>&1 | grep -vE "^\[codec\]|^\[dma\] 第"
import sys, time
sys.path.insert(0, "/home/zynq/ui")
from audio_pl import AudioOut, es8388_set_vol, Mem, FMT_BASE, R_PERIOD
ao = AudioOut()
ao.codec_up(); ao.i2s_config(); ao.fmt_config()
es8388_set_vol(ao.i2c, 0, 0xC0)
ao.start()
es8388_set_vol(ao.i2c, 0, 0xC0)
print("  ring          = %d 字节 = %.2f 秒" % (ao.ring, ao.ring/352800.0))
print("  period_bytes  = %d   (必须 <= 16384)" % ao.period_bytes)
print("  periods       = %d" % ao.periods)
m = Mem()
pr = m.rd(FMT_BASE, R_PERIOD)
print("  R_PERIOD 读回 = 0x%08X" % pr)
print("     高16位 periods     = %d" % ((pr >> 16) & 0xFFFF))
print("     低16位 period_bytes= %d  %s"
      % (pr & 0xFFFF, "OK" if (pr & 0xFFFF) == ao.period_bytes else "★还是不匹配！"))
ao.buf.write(0, b"\x00"*ao.ring)
time.sleep(0.2); ao.close()
PY