#!/bin/sh
# load_cnn_now.sh —— 把带 CNN 的 bitstream 在线加载进 PL
#
# ★ 背景（这是根因，记下来）：
#     u-boot 从 /mnt/boot/system.bit 加载 PL（那个是【带 CNN】的，md5 d4574dce）
#     然后 zynq-gpu-loader.service 跑 /usr/local/bin/gpu-load.sh，
#     用 /lib/firmware/gpu.bin（9月20日的老 bit，md5 5528e498）【又覆盖了一遍】
#     ⇒ 结果：开机后 PL 里【没有 CNN】，CNN IP 的 m_axi 写全部丢失
#
#     症状特别好认：
#       · 寄存器读写全对（因为 AXI-Lite 通）
#       · ap_ctrl 显示 IP 跑完了（done=1）
#       · 但输出缓冲一个字节都没变
#       · conv 层"部分对"（其实是别的 IP/残留数据）
#
# ★ 内核支持 CONFIG_FPGA_MGR_ZYNQ_FPGA=y
#   加载方式：文件放 /lib/firmware/，然后 echo 文件名 > .../firmware

set -e
MGR=/sys/class/fpga_manager/fpga0
SRC=/home/zynq/cnn_new.bit
WANT=d4574dce0b8506251aca7afbbdc45e7d

echo "======================================================"
echo " 在线加载带 CNN 的 bitstream"
echo "======================================================"
echo

echo "① 校验源文件"
GOT=$(md5sum $SRC | cut -d' ' -f1)
echo "   期望 $WANT"
echo "   实得 $GOT"
if [ "$GOT" != "$WANT" ]; then
    echo "   ★ md5 不符，中止"
    exit 1
fi
echo "   ✓ md5 对"
echo

echo "② 备份当前的 /lib/firmware/gpu.bin"
if [ -f /lib/firmware/gpu.bin ]; then
    BAK=/lib/firmware/gpu.bin.bak_$(date +%Y%m%d_%H%M%S)
    cp -f /lib/firmware/gpu.bin "$BAK"
    echo "   ✓ 备份到 $BAK ($(stat -c %s $BAK) 字节)"
    echo "     md5 $(md5sum $BAK | cut -d' ' -f1)"
fi
echo

echo "③ 复制新 bit 到 /lib/firmware/"
cp -f $SRC /lib/firmware/cnn.bin
echo "   ✓ /lib/firmware/cnn.bin  $(stat -c %s /lib/firmware/cnn.bin) 字节"
echo

echo "④ 加载前的状态"
echo "   FPGA Manager: $(cat $MGR/state)"
echo "   CNN cp  ap_ctrl: $(python3 -c "
import mmap,os,struct
fd=os.open('/dev/mem',os.O_RDONLY|os.O_SYNC)
m=mmap.mmap(fd,4096,mmap.MAP_SHARED,mmap.PROT_READ,offset=0x43CD0000)
print('0x%08X'%struct.unpack_from('<I',m,0)[0]); m.close(); os.close(fd)" 2>/dev/null || echo '读不到')"
echo

echo "⑤ ★ 加载（桌面可能会闪一下，GPU 加速会短暂中断）"
if echo cnn.bin > $MGR/firmware 2>/dev/null; then
    echo "   写入 firmware 成功"
else
    echo "   ★ 写入 firmware 失败"
    exit 1
fi
sleep 3
ST=$(cat $MGR/state)
echo "   FPGA Manager 状态: $ST"
if [ "$ST" != "operating" ]; then
    echo "   ★ 加载失败！把备份的 gpu.bin 装回去"
    echo gpu.bin > $MGR/firmware 2>/dev/null || true
    exit 1
fi
echo

echo "⑥ 验证各 IP"
sudo python3 -c "
import mmap, os, struct
def rd(b,o):
    try:
        fd=os.open('/dev/mem', os.O_RDONLY|os.O_SYNC)
        m=mmap.mmap(fd,4096,mmap.MAP_SHARED,mmap.PROT_READ,offset=b)
        v=struct.unpack_from('<I',m,o)[0]; m.close(); os.close(fd); return v
    except Exception: return None
for nm,b,want in (('scope_0',0x43CC0000,0x53434F50),('gpu_0',0x43CB0000,0xDEADBEEF)):
    v=rd(b,0x34)
    print('   %-14s @0x%08X(0x34) = %s  %s' % (nm,b,'0x%08X'%v if v is not None else '读不到',
          '✓' if v==want else '(期望 0x%08X)'%want))
for nm,b in (('cnn_conv_pool',0x43CD0000),('cnn_fc',0x43CE0000)):
    v=rd(b,0x00)
    print('   %-14s @0x%08X(0x00) = %s  %s' % (nm,b,'0x%08X'%v if v is not None else '读不到',
          '✓ idle' if v==4 else '★ 不是 idle'))
"
echo
echo "⑦ 更新 gpu.bin（让下次开机也加载带 CNN 的 —— ★ 这才是根治）"
cp -f $SRC /lib/firmware/gpu.bin
echo "   ✓ /lib/firmware/gpu.bin 已换成带 CNN 的版本"
echo "     md5 $(md5sum /lib/firmware/gpu.bin | cut -d' ' -f1)"
echo
echo "======================================================"
echo " 完成。现在可以跑 verify_wave_onboard.py 了。"
echo "======================================================"
