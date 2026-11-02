cd /home/zynq
echo "=== 1) 先测小文件（刚才那段采集）==="
sudo python3 analyze_wav.py /tmp/cap44.wav 2>&1 | tail -18
echo
echo "=== 2) 再测大文件（半岛铁盒，55MB —— 上一版就是这里卡死的）==="
time sudo python3 analyze_wav.py "/home/zynq/Music/02_半岛铁盒.wav" 2>&1 | tail -22