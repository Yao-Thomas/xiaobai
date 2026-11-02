#!/bin/bash
# 尝试装离线语音识别 vosk（armv7l）+ 中文小模型
echo "=== python3 / pip 情况 ==="
python3 -V
python3 -m pip --version 2>&1 | head -2 || echo "没有 pip"
echo
echo "=== 装 pip（如果需要）==="
if ! python3 -m pip --version >/dev/null 2>&1; then
  sudo apt-get install -y --no-install-recommends python3-pip 2>&1 | tail -3
fi
python3 -m pip --version 2>&1 | head -1
echo
echo "=== 装 vosk ==="
sudo python3 -m pip install --no-cache-dir vosk 2>&1 | tail -6
echo
echo "=== 验证 ==="
python3 -c "import vosk, sys; print('vosk OK', vosk.__file__)" 2>&1 | tail -3
echo
echo "=== 下载中文小模型 (~42MB) ==="
cd /home/zynq
if [ -d /home/zynq/vosk-model-small-cn-0.22 ]; then
  echo "模型已存在"
else
  sudo curl -L --max-time 900 -o /tmp/cn.zip \
    https://alphacephei.com/vosk/models/vosk-model-small-cn-0.22.zip 2>&1 | tail -2
  ls -l /tmp/cn.zip
  sudo unzip -q -o /tmp/cn.zip -d /home/zynq/ && sudo rm -f /tmp/cn.zip
fi
ls -d /home/zynq/vosk-model* 2>&1
du -sh /home/zynq/vosk-model* 2>/dev/null
