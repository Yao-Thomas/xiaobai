echo "=== apps_music.py 的 record() ==="
sed -n '150,215p' /home/zynq/ui/apps_music.py
echo
echo "=== 它调的 HTTP 接口是什么 ==="
grep -nE "8767|8768|localhost|127.0.0.1|/rec|/play|http" /home/zynq/ui/apps_music.py | head -20