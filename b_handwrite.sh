echo "########## 1) 板上有没有现成的手写识别库 ##########"
python3 -c "import zinnia; print('  zinnia 已装')" 2>&1 | head -2
apt-cache policy zinnia python3-zinnia 2>/dev/null | head -12
echo
echo "########## 2) 有没有别的识别库 ##########"
python3 -c "import tegaki; print('  tegaki')" 2>&1 | head -1
python3 -c "import PIL; print('  PIL', PIL.__version__)" 2>&1 | head -1
python3 -c "import numpy; print('  numpy', numpy.__version__)" 2>&1 | head -1
python3 -c "import cv2; print('  cv2', cv2.__version__)" 2>&1 | head -1
echo
echo "########## 3) apt 能不能装东西（有网就行）##########"
timeout 25 sudo apt-get update -qq 2>&1 | tail -3
echo "  --- 查 zinnia 包 ---"
timeout 20 apt-cache search zinnia 2>/dev/null | head -5
echo
echo "########## 4) 触摸屏类型（手写体验的关键）##########"
cat /proc/bus/input/devices 2>/dev/null | grep -A5 -iE "touch|Goodix|gt9|ft5" | head -20
echo "--- 是否支持多点 ---"
sudo evtest --query /dev/input/event1 EV_ABS ABS_MT_POSITION_X 2>/dev/null && echo "  支持多点触摸" || echo "  单点（电阻屏？）"