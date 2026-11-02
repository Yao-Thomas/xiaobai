echo "########## 1) fbui.Touch 的 API（能不能拿笔画）##########"
grep -nE "class Touch|def poll|def read|def _load_inject|drag|down|move|up|pts|stroke" /home/zynq/ui/fbui.py | head -30
echo
echo "########## 2) zinnia 的 Python 绑定 ##########"
timeout 20 apt-cache search zinnia 2>/dev/null
echo "  --- pip 里有吗 ---"
timeout 25 pip3 download zinnia --no-deps -d /tmp/_z 2>&1 | tail -3
echo
echo "########## 3) 触摸是否支持多点（正确查法）##########"
sudo python3 - <<'PYEOF'
import struct, fcntl, os
# 直接读 input1 的能力位图
try:
    EVIOCGBIT = lambda ev, ln: fcntl.ioctl(fd, 0x80000000 + (0x20 + ev) * 0x100 + (ln - 1) * 0x100, b'\0'*ln)
    fd = os.open('/dev/input/event1', os.O_RDONLY)
    buf = EVIOCGBIT(3, 8)   # EV_ABS
    bits = int.from_bytes(buf, 'little')
    print("  EV_ABS 支持: 0x%x" % bits)
    names = {0x00:"ABS_X",0x01:"ABS_Y",0x2f:"ABS_MT_SLOT",0x35:"ABS_MT_POSITION_X",
             0x36:"ABS_MT_POSITION_Y",0x3a:"ABS_MT_PRESSURE",0x39:"ABS_MT_TRACKING_ID"}
    for b, n in names.items():
        print("    %-22s %s" % (n, "✓" if bits & (1 << b) else "✗"))
    os.close(fd)
except Exception as e:
    print("  查询失败:", e)
PYEOF