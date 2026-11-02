#!/bin/bash
echo "=== [1] 前台运行扫雷(最多6秒，看报错) ==="
timeout 6 sudo python3 -u /home/zynq/mines.py
echo "退出码: $?"
echo ""
echo "=== [2] python3 版本 / 模块 ==="
python3 --version
python3 -c "import mmap,struct,fcntl,ctypes; print('模块 OK')"
echo ""
echo "=== [3] 文件是否完整 ==="
ls -l /home/zynq/mines.py
tail -3 /home/zynq/mines.py
