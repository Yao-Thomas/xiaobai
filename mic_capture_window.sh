#!/bin/bash
# mic_capture_window.sh —— 开一个录音窗口，让用户随时说话
#
# ★ 为什么这么做：用户不在板子边上，没法卡准时间。
#   所以后台连续录 4 秒一段、录 2 分钟，每段算 RMS/峰值，
#   把最响的那段单独存出来。用户在这 2 分钟里随便什么时候说话都行。
#
# 日志: /tmp/micwin.log   最响段: /tmp/mic_best.wav
set -u
LOG=/tmp/micwin.log
OUT=/tmp/mic_chunks
mkdir -p $OUT
rm -f $OUT/*.wav
echo "===== 录音窗口开始 $(date '+%T') =====" > $LOG

python3 - <<'PY' >> $LOG 2>&1
import io, json, math, os, struct, sys, time, urllib.request, wave
AUDIO = "http://127.0.0.1:8767"
OUT = "/tmp/mic_chunks"
SECS = 4.0
ROUNDS = 30                 # 30 x 4s = 120 秒

def rec(secs, rate=16000):
    req = urllib.request.Request(
        AUDIO + "/record",
        data=json.dumps({"secs": secs, "rate": rate, "mono": True}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return r.read()

best = (0.0, None, 0)
print("  每段 %.0f 秒，共 %d 段（%.0f 秒窗口）" % (SECS, ROUNDS, SECS*ROUNDS))
print("  %-6s %-10s %-9s %-9s %s" % ("段", "RMS", "峰值", "非零%", "说明"))
for i in range(1, ROUNDS + 1):
    try:
        b = rec(SECS)
    except Exception as e:
        print("  %-6d 采集失败: %s" % (i, e))
        time.sleep(0.5)
        continue
    try:
        w = wave.open(io.BytesIO(b), "rb")
        n = w.getnframes()
        d = w.readframes(n)
        v = struct.unpack("<%dh" % (len(d)//2), d)
    except Exception as e:
        print("  %-6d 解析失败: %s" % (i, e))
        continue
    if not v:
        continue
    rms = math.sqrt(sum(float(x)*x for x in v)/len(v))
    pk = max(abs(x) for x in v)
    nz = sum(1 for x in v if abs(x) > 6) / float(len(v))
    note = ""
    if rms > best[0]:
        best = (rms, b, i)
        note = "★ 目前最响"
    if rms > 2000:
        note += "  <<< 有声音!"
    print("  %-6d %-10.1f %-9d %-8.1f%% %s" % (i, rms, pk, nz*100, note),
          flush=True)
    # 每段都存下来，方便事后挑
    with open(os.path.join(OUT, "c%02d_rms%05d.wav" % (i, int(rms))), "wb") as f:
        f.write(b)

if best[1]:
    with open("/tmp/mic_best.wav", "wb") as f:
        f.write(best[1])
    print()
    print("  最响的一段: 第 %d 段  RMS=%.1f  ->  /tmp/mic_best.wav"
          % (best[2], best[0]))
else:
    print("  没采到任何数据")
PY
echo "===== 录音窗口结束 $(date '+%T') =====" >> $LOG
# 恢复服务（保险）
systemctl start zynq-audio 2>/dev/null
