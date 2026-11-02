#!/bin/bash
cd /home/zynq/ui
echo "=== 重新生成全部提示音（含 6 个更响的）==="
sudo python3 - <<'PY'
import sys, os, math
sys.path.insert(0, "/home/zynq/ui")
import chime
os.makedirs("/home/zynq/Music/提示音", exist_ok=True)
n = 22050
sine = [int(32767*math.sin(2*math.pi*1000*i/44100)) for i in range(n)]
ref = math.sqrt(sum(float(x)*x for x in sine)/len(sine))
for k in chime.STYLES:
    p = "/home/zynq/Music/提示音/%s.wav" % k
    s = chime.make_chime(k)
    chime.write_wav(s, p)
    rms = math.sqrt(sum(float(x)*x for x in s)/len(s))
    print("  %-8s %-18s 峰值=%-6d RMS=%+6.1f dB  %.2fs" % (
        k, chime.STYLE_NAMES.get(k, k), max(abs(x) for x in s),
        20*math.log10(rms/ref), len(s)/44100.0))
PY
sudo chown -R zynq:zynq /home/zynq/Music/提示音
echo
echo "=== 默认提示音也更新成 apple（保持原样）==="
sudo python3 -c "
import sys; sys.path.insert(0,'/home/zynq/ui')
import chime
chime.write_wav(chime.make_chime('apple'), '/home/zynq/Music/提示音.wav')
print('  ok')
"
sudo chown zynq:zynq /home/zynq/Music/提示音.wav
echo
echo "=== 文件数 ==="
ls /home/zynq/Music/提示音/ | wc -l
echo
echo "=== 重启桌面（提示音页要重新读列表）==="
sudo systemctl restart zynq-desktop
sleep 9
systemctl is-active zynq-desktop
curl -s --max-time 6 http://127.0.0.1:8767/state; echo
