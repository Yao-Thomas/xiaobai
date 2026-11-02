#!/bin/sh
# board-analyst READ-ONLY baseline inventory. NOTHING IS WRITTEN.
echo "===== A. our UI dir ====="
ls -l /home/zynq/ui/ 2>&1
echo "--- md5 of key PS files (ours) ---"
md5sum /home/zynq/ui/fbui.py /home/zynq/ui/desktop.py /home/zynq/ui/apps_scope.py \
       /home/zynq/ui/scope.py /home/zynq/ui/libscope.so \
       /home/zynq/ui/apps_scope_dual.py /home/zynq/ui/scope_dual.py \
       /home/zynq/ui/scope_model.py /home/zynq/ui/scope_processing.py \
       /home/zynq/ui/libscopedual.so 2>&1
echo
echo "===== B. /mnt/boot (p1) ====="
ls -l /mnt/boot/ 2>&1
echo "--- md5 of boot artifacts ---"
md5sum /mnt/boot/system.bit /mnt/boot/system.dtb /mnt/boot/zImage /mnt/boot/BOOT.BIN 2>&1
echo "--- df ---"
df -h /mnt/boot / 2>&1
echo
echo "===== C. PL IP magic readback via /dev/mem (read-only dd) ====="
for a in 43CC0034 43CB0034 43C50000 43C60000; do
  printf "0x%s = " "$a"
  sudo -n dd if=/dev/mem bs=4 count=1 skip=$((0x$a / 4)) 2>/dev/null | od -An -tx4 | tr -d '\n'
  echo
done
echo
echo "===== D. LCD / audio / touch hard indicators ====="
for f in mode modes virtual_size bits_per_pixel stride; do
  printf "fb0/%-16s = %s\n" "$f" "$(cat /sys/class/graphics/fb0/$f 2>/dev/null | tr '\n' ' ')"
done
echo "--- asound cards ---"
cat /proc/asound/cards 2>/dev/null
echo "--- pcm devices ---"
cat /proc/asound/pcm 2>/dev/null
echo "--- event names ---"
for e in /sys/class/input/event*; do printf "%s = %s\n" "$e" "$(cat $e/device/name 2>/dev/null)"; done
echo "--- i2c-2 devices ---"
ls /sys/bus/i2c/devices/ 2>/dev/null | tr '\n' ' '; echo
echo
echo "===== E. toolchain / runtime on board ====="
python3 -V 2>&1; gcc --version 2>&1 | head -1; which gcc fdtput fdtget devmem2 2>&1
echo "--- PIL ---"
python3 -c "import PIL,sys; print('PIL', PIL.__version__)" 2>&1
echo "--- numpy ---"
python3 -c "import numpy; print('numpy', numpy.__version__)" 2>&1
echo
echo "===== F. services (ours, must stay active) ====="
systemctl list-units --type=service --state=running --no-pager --no-legend 2>/dev/null | awk '{print $1}' | sort
echo
echo "===== G. desktop entries for scope ====="
ls -l /usr/share/applications/ 2>/dev/null | grep -i -E 'scope|ui' 
grep -rl -i scope /usr/share/applications/ 2>/dev/null
echo "--- how desktop finds apps ---"
grep -n 'APPS\|apps_scope\|/home/zynq/ui' /home/zynq/ui/desktop.py 2>/dev/null | head -30
echo
echo "===== H. does our UI already have a dual-scope entry? ====="
ls -l /home/zynq/ui/scope_dual* /home/zynq/ui/apps_scope_dual* /home/zynq/ui/libscopedual* 2>&1
echo "PROBE_DONE"
