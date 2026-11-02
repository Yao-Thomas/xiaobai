#!/bin/bash
echo "=== 服务状态 ==="
for s in zynq-desktop zynq-screen-guard wifi-connect ssh; do
    printf '  %-22s %s\n' "$s" "$(systemctl is-active $s)"
done

echo ""
echo "=== GPU 相关 (应该都是关闭的) ==="
if [ -e /home/zynq/.gpu_addr ]; then
    echo "  ❌ GPU 标记还在: $(cat /home/zynq/.gpu_addr)"
else
    echo "  ✅ GPU 标记: 无 (纯软件渲染)"
fi
echo -n "  GPU 加载器: "; systemctl is-enabled zynq-gpu-loader 2>&1

echo ""
echo "=== 黑屏安全网 ==="
echo -n "  状态: "; systemctl is-active zynq-screen-guard
echo "  最近日志:"
tail -4 /var/log/zynq-screen-guard.log | sed 's/^/    /'

echo ""
echo "=== WiFi ==="
echo -n "  SSID: "; iwconfig wlx688fc92bd646 2>/dev/null | grep -oP 'ESSID:\S+'
echo -n "  IP:   "; hostname -I | awk '{print $1}'
echo -n "  信号: "; iwconfig wlx688fc92bd646 2>/dev/null | grep -oP 'Signal level=\S+'
echo "  已保存的网络:"
wpa_cli -i wlx688fc92bd646 list_networks 2>/dev/null | tail -n +2 | sed 's/^/    /'

echo ""
echo "=== 桌面日志尾 ==="
tail -4 /var/log/zynq-desktop.log | sed 's/^/    /'

echo ""
echo "=== 屏幕采样 ==="
python3 -c "
import mmap, os
fd=os.open('/dev/fb0',os.O_RDONLY)
mm=mmap.mmap(fd,3072*600,mmap.MAP_SHARED,mmap.PROT_READ)
dark=0;n=0;tot=0
for y in range(5,600,23):
    for x in range(5,1024,29):
        o=y*3072+x*3
        s=mm[o]+mm[o+1]+mm[o+2]
        tot+=s
        if s<24: dark+=1
        n+=1
mm.close(); os.close(fd)
print('  黑点 %d/%d (%.1f%%), 平均亮度 %.0f -> %s' % (dark,n,dark*100.0/n,tot*100.0/n,
      '黑屏!' if dark*1.0/n>0.85 else '正常 ✅'))
"
echo DONE-VERIFY
