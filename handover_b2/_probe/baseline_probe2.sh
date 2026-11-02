#!/bin/sh
echo "===== C. PL IP magic readback (read-only) ====="
for a in 43CC0034 43CB0034 43C50000 43C60000 43C30034; do
  n=$((0x$a))
  off=$((n / 4))
  printf "0x%s = " "$a"
  sudo -n dd if=/dev/mem bs=4 count=1 skip=$off 2>/dev/null | od -An -tx4 | tr -d '\n'
  echo
done
echo
echo "===== D. hard indicators ====="
for f in mode modes virtual_size bits_per_pixel stride; do
  printf "fb0/%-14s = %s\n" "$f" "$(cat /sys/class/graphics/fb0/$f 2>/dev/null | tr '\n' ' ')"
done
echo "--- asound cards ---"; cat /proc/asound/cards 2>/dev/null
echo "--- asound pcm ---"; cat /proc/asound/pcm 2>/dev/null
echo "--- input names ---"
for e in /sys/class/input/event*; do printf "%s = %s\n" "$e" "$(cat $e/device/name 2>/dev/null)"; done
echo "--- i2c devices ---"; ls /sys/bus/i2c/devices/ 2>/dev/null | tr '\n' ' '; echo
echo "--- zynq-audio.service ---"
systemctl is-active zynq-audio 2>&1
systemctl is-enabled zynq-audio 2>&1
echo
echo "===== E. toolchain ====="
python3 -V 2>&1
gcc --version 2>&1 | head -1
for t in gcc fdtput fdtget devmem2 gpiodetect; do printf "%-10s -> %s\n" "$t" "$(which $t 2>/dev/null || echo MISSING)"; done
python3 -c "import PIL;print('PIL',PIL.__version__)" 2>&1
python3 -c "import numpy;print('numpy',numpy.__version__)" 2>&1
echo
echo "===== F. running services ====="
systemctl list-units --type=service --state=running --no-pager --no-legend 2>/dev/null | awk '{print $1}' | sort
echo
echo "===== G. desktop app discovery ====="
grep -n 'apps_\|/home/zynq/ui\|import_module\|APPS' /home/zynq/ui/desktop.py 2>/dev/null | head -25
echo
echo "===== H. dual-scope files present? ====="
ls -l /home/zynq/ui/scope_dual* /home/zynq/ui/apps_scope_dual* /home/zynq/ui/libscopedual* /home/zynq/ui/scope_model* /home/zynq/ui/scope_processing* 2>&1
echo
echo "===== I. scope_cap_axi register peek (ours, read-only) ====="
for a in 43CC0034 43CC0038 43CC003C 43CC0000; do
  n=$((0x$a)); off=$((n / 4))
  printf "0x%s = " "$a"
  sudo -n dd if=/dev/mem bs=4 count=1 skip=$off 2>/dev/null | od -An -tx4 | tr -d '\n'
  echo
done
echo "===== J. rootfs free + python site ====="
df -h / | tail -1
python3 -c "import sys;print(sys.version)" 2>&1
echo "PROBE2_DONE"
