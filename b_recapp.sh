echo "=== 1) 哪个 App 做录音 ==="
grep -rln "arecord\|录音" /home/zynq/ui/*.py 2>/dev/null | head -8
echo
echo "=== 2) 录音 App 怎么录的 ==="
for f in /home/zynq/ui/apps_music.py /home/zynq/ui/apps_recorder.py; do
  [ -f "$f" ] || continue
  echo "--- $f ---"
  grep -nE "arecord|rec_big|audio_pl|AudioIn|subprocess|def rec" "$f" | head -12
done
echo
echo "=== 3) 找所有提到录音的 App ==="
ls /home/zynq/ui/apps_*.py 2>/dev/null
echo
echo "=== 4) audio_svc.py 还在吗，它有没有录音 ==="
ls -la /home/zynq/ui/audio_svc.py
grep -nE "def .*rec|AudioIn|S2MM|capture" /home/zynq/ui/audio_svc.py | head -10