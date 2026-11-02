#!/usr/bin/env bash
# 用静音文件实测「删除」按钮（两次点击确认）
echo "=== 1) 造一个静音测试文件 ==="
python3 -c "
import wave, struct
w = wave.open('/home/zynq/Music/zz_删除测试.wav','wb')
w.setnchannels(2); w.setsampwidth(2); w.setframerate(44100)
w.writeframes(struct.pack('<%dh' % (44100*2), *([0]*(44100*2))))
w.close()
print('  已造 1 秒静音: zz_删除测试.wav')
"
ls -l /home/zynq/Music/*.wav | awk '{printf "  %8.0f KB  %s\n", $5/1024, $9}'
echo
echo "=== 2) 等到它排序在最前（scan 按 mtime 倒序）==="
sleep 1
echo "  现在列表第一个应该就是它（静态分析）"
echo
echo "=== 3) 点第 1 行选中它（会播 1 秒静音，不会出声）==="
echo "400,131" | sudo tee /tmp/ui_tap > /dev/null
sleep 2.5
echo
echo "=== 4) 点「删除」（第一次，应该只提示）==="
echo "383,84" | sudo tee /tmp/ui_tap > /dev/null
sleep 2
echo
echo "=== 5) 截图看提示 ==="
sudo python3 /home/zynq/ui/shot_fb.py /tmp/st1.raw 2>/dev/null
echo "  已抓图 1"
echo
echo "=== 6) 再点「删除」（第二次，应该真删）==="
echo "383,84" | sudo tee /tmp/ui_tap > /dev/null
sleep 2.5
echo
echo "=== 7) 文件还在不在 ==="
if [ -f "/home/zynq/Music/zz_删除测试.wav" ]; then
  echo "  ✗ 还在 —— 删除没生效"
else
  echo "  ✓ 已被删除 —— 删除功能正常"
fi
echo
echo "=== 8) 剩下的文件 ==="
ls -l /home/zynq/Music/*.wav 2>/dev/null | awk '{printf "  %8.0f KB  %s\n", $5/1024, $9}'
echo
echo "=== 9) 桌面日志尾部 ==="
sudo tail -5 /var/log/zynq-desktop.log 2>/dev/null | sed 's/^/  /'
echo
sudo python3 /home/zynq/ui/shot_fb.py /tmp/st2.raw 2>/dev/null
echo "  已抓图 2"
