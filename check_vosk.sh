#!/bin/bash
echo "--- vosk 是否装上 ---"
python3 -c "import vosk; print('VOSK INSTALLED', vosk.__file__)" 2>&1 | tail -2
echo "--- 模型 zip 下载进度 ---"
ls -l /tmp/cn.zip 2>&1
echo "--- 模型目录 ---"
ls -d /home/zynq/vosk-model* 2>&1
du -sh /home/zynq/vosk-model* 2>/dev/null
echo "--- 还在下吗 ---"
pgrep -af "curl.*vosk-model" | head -3
