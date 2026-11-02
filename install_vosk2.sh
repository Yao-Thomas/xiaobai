#!/bin/bash
echo "=== 停掉源码编译 cffi ==="
sudo pkill -f "pip install" 2>/dev/null
sudo pkill -f "cffi" 2>/dev/null
sleep 1

echo "=== 装预编译的 python3-cffi (armhf) ==="
sudo apt-get install -y --no-install-recommends python3-cffi python3-cffi-backend 2>&1 | tail -5
python3 -c "import cffi; print('cffi OK', cffi.__version__)" 2>&1 | tail -1

echo
echo "=== 只装 vosk 本体（不拉依赖）==="
sudo python3 -m pip install --no-cache-dir --no-deps vosk 2>&1 | tail -6

echo
echo "=== 验证 ==="
python3 -c "import vosk; print('VOSK OK', vosk.__file__)" 2>&1 | tail -2
