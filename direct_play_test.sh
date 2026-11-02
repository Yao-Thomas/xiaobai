#!/bin/bash
# 绕过服务，用底层直接放音（区分"服务路径坏"还是"硬件问题"）
echo "=== 1) 停服务（要独占设备）==="
sudo systemctl stop zynq-audio
sleep 2
echo -n "  zynq-audio: "; systemctl is-active zynq-audio
echo
echo "=== 2) 底层直接播 03_小星星.wav（3 秒）==="
sudo python3 - <<'PY' 2>&1 | grep -vE "^\[dma\]|^\[fmt\]|^\[codec\]|^\[i2s\]"
import sys, time, wave, struct
sys.path.insert(0, "/home/zynq/ui")
from audio_pl import AudioOut, es8388_set_vol, make_sine

ao = AudioOut()
ao.codec_up()
ao.fmt_config()
es8388_set_vol(ao.i2c, 33, 0)
print("  codec: 0x1A=0x%02X 0x2E=%d 0x30=%d"
      % (ao.i2c.rd(0x1A), ao.i2c.rd(0x2E) & 0x3F, ao.i2c.rd(0x30) & 0x3F))

# 读 WAV，取前 3 秒
p = "/home/zynq/Music/03_小星星.wav"
w = wave.open(p, "rb")
print("  %s: %d Hz %d声道 %d帧" % (p, w.getframerate(), w.getnchannels(),
                                    w.getnframes()))
n = min(w.getnframes(), int(3.0 * w.getframerate()))
raw = w.readframes(n)
ch, sw = w.getnchannels(), w.getsampwidth()
w.close()

samples = struct.unpack("<%dh" % (len(raw) // 2), raw)
if ch == 2:
    samples = [(samples[i] + samples[i + 1]) // 2
               for i in range(0, len(samples) - 1, 2)]

# 打包成 8 字节/帧（2ch x 32bit 容器），和 make_sine 同格式
frames = max(64, ao.period_bytes // 8)
buf = bytearray()
for k in range(min(len(samples), frames)):
    v = (samples[k] * 256) & 0xFFFFFF
    b = v.to_bytes(4, "little")
    buf += b + b

ring = (bytes(buf) * (ao.ring // max(1, len(buf)) + 1))[:ao.ring]
ao.buf.write(0, ring)
print("  已灌入播放环 %d 字节（前 3 秒循环）" % len(ring))
print("  I2S: TX=%d RX=%d" % (0, 0))
time.sleep(3.0)
ao.buf.write(0, b"\x00" * ao.ring)
time.sleep(0.3)
ao.close()
print("  放完了")
PY
echo
echo "=== 3) 恢复服务 ==="
sudo systemctl start zynq-audio
sleep 3
echo -n "  zynq-audio: "; systemctl is-active zynq-audio
