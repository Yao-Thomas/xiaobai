#!/bin/bash
#=====================================================================
#  runtime_gpu_test.sh —— 用 FPGA Manager 加载 GPU, 然后命令行测
#  故意不写 .gpu_addr -> 桌面保持软件渲染, 不会 SIGBUS 崩溃
#=====================================================================
set -u
BASE=0x43CB0000

echo "=== [1] 加载前: 记录当前屏幕特征 (对比用) ==="
python3 -c "
import mmap, os, collections
fd=os.open('/dev/fb0', os.O_RDONLY)
mm=mmap.mmap(fd,3072*600,mmap.MAP_SHARED,mmap.PROT_READ)
c=collections.Counter()
for y in range(0,600,29):
    for x in range(0,1024,31):
        o=y*3072+x*3
        c[(mm[o+2],mm[o+1],mm[o])]+=1
mm.close(); os.close(fd)
print('  最常见 3 色:', ['#%02X%02X%02X'%k for k,_ in c.most_common(3)])
"

echo ""
echo "=== [2] 用 FPGA Manager 加载 GPU bitstream ==="
cp -f /home/zynq/gpu_final.bit.bin /lib/firmware/gpu.bin 2>/dev/null || cp -f /home/zynq/gpu_system_swapped.bit.bin /lib/firmware/gpu.bin
ls -la /lib/firmware/gpu.bin | awk '{print "  文件:", $5, "字节"}'
echo gpu.bin > /sys/class/fpga_manager/fpga0/firmware
sleep 3
echo -n "  FPGA Manager 状态: "; cat /sys/class/fpga_manager/fpga0/state

echo ""
echo "=== [3] 立刻检查屏幕还在不在 (显示通路是否被破坏) ==="
sleep 2
python3 -c "
import mmap, os, collections
fd=os.open('/dev/fb0', os.O_RDONLY)
mm=mmap.mmap(fd,3072*600,mmap.MAP_SHARED,mmap.PROT_READ)
c=collections.Counter()
for y in range(0,600,29):
    for x in range(0,1024,31):
        o=y*3072+x*3
        c[(mm[o+2],mm[o+1],mm[o])]+=1
mm.close(); os.close(fd)
print('  最常见 3 色:', ['#%02X%02X%02X'%k for k,_ in c.most_common(3)])
"

echo ""
echo "=== [4] 探测 GPU ==="
python3 -c "
import sys
sys.path.insert(0,'/home/zynq/ui')
from gpu import GPU
g=GPU(0x43CB0000, verbose=False)
ok=g.probe()
print('  GPU:', '存在 ✅' if ok else '无响应')
g.close()
sys.exit(0 if ok else 1)
" 2>/dev/null
GPU_OK=$?

echo ""
echo "=== [5] 用 GPU 画一个测试图案 (整屏刷青色, 一眼就能看出) ==="
if [ $GPU_OK -eq 0 ]; then
python3 -c "
import sys, time
sys.path.insert(0,'/home/zynq/ui')
from gpu import GPU
import mmap, os, ctypes, fcntl

# 取显存物理地址
class FBFix(ctypes.Structure):
    _fields_=[('id',ctypes.c_char*16),('smem_start',ctypes.c_ulong),('smem_len',ctypes.c_uint32),
              ('type',ctypes.c_uint32),('type_aux',ctypes.c_uint32),('visual',ctypes.c_uint32),
              ('xpanstep',ctypes.c_uint16),('ypanstep',ctypes.c_uint16),('ywrapstep',ctypes.c_uint16),
              ('__pad',ctypes.c_uint16),('line_length',ctypes.c_uint32)]
fd=os.open('/dev/fb0',os.O_RDWR); fix=FBFix(); fcntl.ioctl(fd,0x4602,fix); os.close(fd)
phys=fix.smem_start
if not phys:
    try: phys=int(open('/home/zynq/.fb_phys').read().strip(),0)
    except Exception: phys=0
print('  显存物理地址: 0x%08X' % phys)
if not phys:
    print('  ❌ 拿不到物理地址, 跳过'); sys.exit(0)

g=GPU(0x43CB0000, verbose=False)
g.clear_error()
g.wr(0x08, phys); g.wr(0x0C, 3072)
g.wr(0x10, (0<<16)|0); g.wr(0x14, (1023<<16)|599)
g.wr(0x18, 0xFFC000)     # RGB 青蓝色
g.wr(0x04, 0); g.wr(0x00, 1)
t0=time.time()
while time.time()-t0 < 3:
    if g.rd(0x1C) >= 614400: break
    time.sleep(0.005)
print('  GPU 报告写入 %d 像素, 耗时 %.1f ms' % (g.rd(0x1C), (time.time()-t0)*1000))
# 在中间画一条红线
g.clear_error()
g.wr(0x10, (0<<16)|300); g.wr(0x14, (1023<<16)|300)
g.wr(0x18, 0xFF0000); g.wr(0x04, 1); g.wr(0x00, 1)
time.sleep(0.3)
print('  GPU 画线 %d 像素' % g.rd(0x1C))
g.close()
print('  ✅ 已用 GPU 把屏幕刷成青色 + 红色横线')
" 2>/dev/null
else
  echo "  GPU 不可用, 跳过"
fi

echo ""
echo "=== [6] 读回屏幕验证 ==="
python3 -c "
import mmap, os
fd=os.open('/dev/fb0',os.O_RDONLY)
mm=mmap.mmap(fd,3072*600,mmap.MAP_SHARED,mmap.PROT_READ)
for (x,y,n) in ((512,100,'上半屏'),(512,300,'红线处'),(512,500,'下半屏')):
    o=y*3072+x*3
    print('  %-8s = #%02X%02X%02X' % (n, mm[o+2],mm[o+1],mm[o]))
mm.close(); os.close(fd)
"
echo ""
echo "  ⚠️ 请看在板子屏幕上: 显示的是青色吗? 还是桌面/黑屏?"
echo DONE-RUNTIME
