#!/bin/bash
echo "--- pip 日志 ---"
tail -6 /tmp/pipvosk.log
echo "--- vosk import ---"
python3 -c "import vosk; print('VOSK OK', vosk.__file__)" 2>&1 | tail -2
echo "--- zip ---"
ls -l /tmp/cn.zip 2>&1
echo "--- 解压模型 ---"
if [ -f /tmp/cn.zip ] && [ ! -d /home/zynq/vosk-model-small-cn-0.22 ]; then
  if ! pgrep -f "curl.*vosk-model" >/dev/null; then
    sudo unzip -q -o /tmp/cn.zip -d /home/zynq/ && echo "解压完成" || echo "解压失败"
  else
    echo "还在下载中，暂不解压"
  fi
fi
ls -d /home/zynq/vosk-model* 2>&1
du -sh /home/zynq/vosk-model* 2>/dev/null
