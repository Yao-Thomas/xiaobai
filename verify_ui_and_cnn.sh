#!/bin/sh
# verify_ui_and_cnn.sh —— 验证变更历史 App 和 CNN
echo "======================================================"
echo " 验证：桌面 App + CNN"
echo "======================================================"
echo
echo "【1】桌面上的「变更历史」App"
echo -n "  apps_hwchange.py: "
ls -la /home/zynq/ui/apps_hwchange.py 2>/dev/null | awk '{print $5" 字节"}' || echo "不在"
echo -n "  desktop.py 注册: "
grep -c "apps_hwchange" /home/zynq/ui/desktop.py 2>/dev/null
echo -n "  备份: "
ls /home/zynq/ui/desktop.py.bak_* 2>/dev/null | tail -1 || echo "无"
echo
echo "  语法检查:"
python3 -c "import ast,io; ast.parse(io.open('/home/zynq/ui/apps_hwchange.py',encoding='utf-8').read()); print('    ✓ apps_hwchange.py 语法 OK')" 2>&1
python3 -c "import ast,io; ast.parse(io.open('/home/zynq/ui/desktop.py',encoding='utf-8').read()); print('    ✓ desktop.py 语法 OK')" 2>&1
echo
echo "  能不能 import（桌面是用 importlib 加的）:"
cd /home/zynq/ui && python3 -c "
import sys; sys.path.insert(0,'/home/zynq/ui'); sys.path.insert(0,'/home/zynq')
import importlib
try:
    m = importlib.import_module('apps_hwchange')
    print('    ✓ import 成功，有 run() =', hasattr(m, 'run'))
    print('    App 里的常量: MAX_ROWS=%s  LIST_TOP=%s' % (m.MAX_ROWS, m.LIST_TOP))
except Exception as e:
    print('    ✗', type(e).__name__, e)
" 2>&1
echo
echo "  桌面现在显示的是第几页（变更历史在第 1 页最后）:"
cat /home/zynq/.desktop_pages 2>/dev/null || echo "    (没有分页配置)"
echo
echo "【2】★ CNN 真跑一次（MNIST 测试数据）"
ls -la /home/zynq/mnist_test.bin 2>/dev/null | awk '{print "  测试数据: "$5" 字节"}'
sudo python3 /home/zynq/cnn_linux.py --check 2>&1 | tail -12
echo
echo "【3】★ CNN 跑一张真图（用 --data）"
sudo python3 /home/zynq/cnn_linux.py --data /home/zynq/mnist_test.bin 2>&1 | tail -20
echo
echo "【4】波形 AI 链 + CNN（示波器采的真实波形）"
sudo python3 -c "
import sys; sys.path.insert(0,'/home/zynq')
import scope_capture as SC, waveform_ai as W
r = SC.capture_once()
if not r.get('ok'):
    print('  ✗ 采集失败:', r.get('error')); raise SystemExit
w = [(v-128)/128.0 for v in r['samples']]
img = W.waveform_to_image(w)
s = W.image_summary(img)
print('  28x28 时频图: 均值 %.1f 非零 %d/%d' % (s['mean'], s['nonzero'], len(img)))
cls, info = W.classify_with_cnn(img, cnn_script='/home/zynq/cnn_linux.py')
print('  CNN 结果:', cls)
print('  说明:', str(info)[:150])
" 2>&1
echo
echo "【5】温度"
sudo python3 /home/zynq/thermal_guard.py --once
echo
