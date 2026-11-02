#!/usr/bin/env bash
echo "=== 1) 看服务的 __init__ 是否调 set_volume ==="
sed -n '18,45p' /home/zynq/ui/audio_alsa_svc.py
echo
echo "=== 2) 备份并改默认音量 24 -> 33 ==="
sudo cp /home/zynq/ui/audio_alsa_svc.py /home/zynq/ui/audio_alsa_svc.py.bak_vol33_$(date +%Y%m%d_%H%M%S)
python3 - <<'PY'
import io
p = "/home/zynq/ui/audio_alsa_svc.py"
s = io.open(p, encoding="utf-8").read()
n = s.count("self.volume = 24")
s2 = s.replace("self.volume = 24", "self.volume = 33")
# /volume 接口的默认值也一起改
s2 = s2.replace('args.get("v", 24)', 'args.get("v", 33)')
io.open(p, "w", encoding="utf-8").write(s2)
print("  替换 self.volume = 24 -> 33 : %d 处" % n)
print("  替换 /volume 默认值        : %d 处" % s.count('args.get("v", 24)'))
PY
echo
echo "=== 3) 确认改动 ==="
grep -nE "self.volume|args.get\(\"v\"" /home/zynq/ui/audio_alsa_svc.py
echo
echo "=== 4) 重启服务验证 ==="
sudo systemctl restart zynq-audio
sleep 4
echo -n "  zynq-audio: "; systemctl is-active zynq-audio
curl -s --max-time 8 http://127.0.0.1:8767/state; echo
echo
echo "   实际混音器:"
amixer -c 0 sget 'Output 1' 2>/dev/null | grep -E "Front Left"
amixer -c 0 sget 'Output 2' 2>/dev/null | grep -E "Front Left"
amixer -c 0 sget 'Playback' 2>/dev/null | grep -E "Front Left"
