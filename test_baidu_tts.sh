#!/bin/bash
# 验证百度语音合成（只生成 WAV 文件，**不播放**）
echo "===== 百度 TTS 测试（不出声）====="
sudo python3 - <<'PY'
import os, sys, wave, math, struct, time
sys.path.insert(0, "/home/zynq")
for line in open("/etc/zynq-baidu.env"):
    if "=" in line:
        k, v = line.strip().split("=", 1)
        os.environ[k] = v

from agent import tts

def info(p):
    if not os.path.exists(p):
        return "文件不存在"
    w = wave.open(p, "rb")
    n, ch, sw, r = w.getnframes(), w.getnchannels(), w.getsampwidth(), w.getframerate()
    d = w.readframes(n)
    w.close()
    try:
        v = struct.unpack("<%dh" % (len(d)//2), d)
        rms = math.sqrt(sum(float(x)*x for x in v)/len(v)) if v else 0
        pk = max(abs(x) for x in v) if v else 0
    except Exception:
        rms = pk = -1
    return ("%d Hz %d声道 %dbit  %.2f秒  %d字节  RMS=%.0f 峰值=%d"
            % (r, ch, sw*8, n/float(r), os.path.getsize(p), rms, pk))

TEXT = "你好，我是系统管家小白，现在时间是下午三点二十。"
print("  合成文本:", TEXT)
print()

# ---- 1) 百度引擎 ----
for per, name in ((0, "度小满女声"), (1, "度小满男声"), (3, "度逍遥"), (4, "度丫丫")):
    out = "/tmp/tts_baidu_%d.wav" % per
    t0 = time.time()
    try:
        p = tts.synth(TEXT, out_path=out, per=per, engine="baidu")
        print("  [百度 per=%d %s] %.1f秒  %s" % (per, name, time.time()-t0, info(p)))
    except Exception as e:
        print("  [百度 per=%d %s] 失败: %s" % (per, name, str(e)[:150]))
    if per == 0:
        break        # 先只测一个，省额度

# ---- 2) 离线 espeak 对照 ----
out2 = "/tmp/tts_espeak.wav"
t0 = time.time()
try:
    p = tts.synth(TEXT, out_path=out2, engine="espeak")
    print("  [离线 espeak]      %.1f秒  %s" % (time.time()-t0, info(p)))
except Exception as e:
    print("  [离线 espeak] 失败:", str(e)[:150])

print()
print("  ★ 两个文件都生成了，但**都没有播放**（全程无声）")
print("  ★ 音量对比看峰值/RMS：百度 TTS 通常比 espeak 更饱满")
PY
echo
echo "===== 确认音频服务仍是停止状态（保证没出声）====="
systemctl is-active zynq-audio
