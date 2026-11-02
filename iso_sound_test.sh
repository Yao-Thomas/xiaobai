#!/usr/bin/env bash
echo "=== 1) 哪些文件被我归一化过 / 哪些没动 ==="
echo "  备份目录（=被我改过的）:"
ls -1 /home/zynq/Music/_原始备份/ 2>/dev/null | sed 's/^/    /'
echo "  没被我动过的: 02_语音测试.wav  提示音.wav  录音_0928_144954.wav"
echo
echo "=== 2) 当前服务/混音器状态 ==="
curl -s --max-time 8 http://127.0.0.1:8767/state; echo
amixer -c 0 sget 'Playback' 2>/dev/null | grep -E "Front Left"
amixer -c 0 sget 'Output 1' 2>/dev/null | grep -E "Front Left"
echo
echo "=== 3) 现在还有没有 aplay 残留 ==="
ps aux | grep "[a]play" | head -3
echo
echo "=== 4) 三个音源逐个放，每个 2.5 秒，中间停 1 秒 ==="
echo "--- A) 纯音（服务现场合成，不依赖任何文件）---"
curl -s --max-time 30 -X POST -H 'Content-Type: application/json' \
  -d '{"tone":1000,"secs":2.5,"amp":0.4}' http://127.0.0.1:8767/play; echo
sleep 1
echo "--- B) 没被我动过的文件（提示音.wav）---"
curl -s --max-time 30 -X POST -H 'Content-Type: application/json' \
  -d '{"file":"/home/zynq/Music/提示音.wav"}' http://127.0.0.1:8767/play; echo
sleep 1
echo "--- C) 我归一化过的文件（03_小星星.wav）---"
curl -s --max-time 30 -X POST -H 'Content-Type: application/json' \
  -d '{"file":"/home/zynq/Music/03_小星星.wav"}' http://127.0.0.1:8767/play; echo
sleep 1
echo "--- D) 归一化的原始备份（改动前的 03_小星星）---"
curl -s --max-time 30 -X POST -H 'Content-Type: application/json' \
  -d '{"file":"/home/zynq/Music/_原始备份/03_小星星.wav"}' http://127.0.0.1:8767/play; echo
echo
echo "=== 5) 期间有没有报错 ==="
curl -s --max-time 8 http://127.0.0.1:8767/state; echo
echo
echo "=== 6) 三个文件的实际数据（确认文件本身有内容）==="
python3 - <<'PY'
import wave, struct, math
for p in ("/home/zynq/Music/提示音.wav",
          "/home/zynq/Music/03_小星星.wav",
          "/home/zynq/Music/_原始备份/03_小星星.wav"):
    try:
        w = wave.open(p, "rb")
        n, sw, ch, r = w.getnframes(), w.getsampwidth(), w.getnchannels(), w.getframerate()
        raw = w.readframes(n); w.close()
        v = list(struct.unpack("<%dh" % (len(raw)//2), raw))
        rms = math.sqrt(sum(float(x)*x for x in v)/len(v))
        pk = max(abs(x) for x in v)
        print("  %-46s %dHz %dch %dbit %.2fs 峰值=%5d(%.1fdBFS) RMS=%.0f"
              % (p.replace("/home/zynq/Music/", ""), r, ch, sw*8, n/float(r),
                 pk, 20*math.log10(max(1e-9,pk/32767.0)), rms))
    except Exception as e:
        print("  %-46s 读失败 %s" % (p, e))
PY
