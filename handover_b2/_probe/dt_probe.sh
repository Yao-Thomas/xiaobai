#!/bin/sh
# board-analyst READ-ONLY device tree probe
echo "===== 1. uname / model ====="
uname -a
cat /proc/device-tree/model 2>/dev/null; echo
echo
echo "===== 2. amba_pl full listing (-l) ====="
ls -l /proc/device-tree/amba_pl/
echo
echo "===== 3. per-node status + reg (the 9 nodes) ====="
for n in clk_wiz@43c80000 clk_wiz@43c30000 v_tc@43c90000 v_tc@43c10000 \
         v_frmbuf_wr@43c40000 v_frmbuf_rd@43ca0000 v_frmbuf_rd@43c20000 \
         i2c@41600000 drm_pl_disp_hdmi atk_hdmi_drm vcap_dvp \
         drm_pl_disp_lcd atk_lcd_drm PWM@43c00000 audio_formatter@43c50000 \
         i2s_receiver@43c60000 i2s_transmitter@43c70000 \
         gpio@41200000 gpio@41210000 gpio@41220000; do
  d=/proc/device-tree/amba_pl/$n
  if [ -d "$d" ]; then
    st=$(cat $d/status 2>/dev/null)
    [ -z "$st" ] && st="(no status prop => enabled)"
    printf "PRESENT  %-26s status=%s\n" "$n" "$st"
  else
    printf "ABSENT   %-26s\n" "$n"
  fi
done
echo
echo "===== 4. reg addresses (hexdump of reg) ====="
for n in clk_wiz@43c80000 v_tc@43c90000 v_frmbuf_wr@43c40000 v_frmbuf_rd@43ca0000 i2c@41600000 vcap_dvp clk_wiz@43c30000 PWM@43c00000 audio_formatter@43c50000 i2s_receiver@43c60000 i2s_transmitter@43c70000; do
  d=/proc/device-tree/amba_pl/$n
  if [ -d "$d" ]; then
    printf "%-26s reg=" "$n"
    od -An -tx1 $d/reg 2>/dev/null | tr -d '\n'
    printf "  compatible="
    tr '\0' ' ' < $d/compatible 2>/dev/null
    printf "\n"
  fi
done
echo
echo "===== 5. i2c@41600000 subnodes (ov5640?) ====="
ls -l /proc/device-tree/amba_pl/i2c@41600000/ 2>/dev/null
echo "--- children of i2c@41600000 named * ---"
for c in /proc/device-tree/amba_pl/i2c@41600000/*/; do
  [ -d "$c" ] || continue
  echo "CHILD: $c  status=$(cat $c/status 2>/dev/null)"
  tr '\0' ' ' < $c/compatible 2>/dev/null; echo
done
echo
echo "===== 6. any scope node anywhere in DT? ====="
find /proc/device-tree -maxdepth 3 -iname '*scope*' 2>/dev/null
echo "--- grep compatible for scope ---"
grep -rl -i scope /proc/device-tree --include=compatible 2>/dev/null
echo
echo "===== 7. top-level DT dirs ====="
ls /proc/device-tree/
echo
echo "===== 8. amba (PS) vs amba_pl: scope_cap / 43cc0000 owners ====="
grep -rl "43cc0000\|43CC0000" /proc/device-tree 2>/dev/null | head -20
echo
echo "===== 9. /dev/mem owners relevant ====="
ls -l /dev/mem /dev/fb0 /dev/input/ 2>&1
echo
echo "===== 10. LCD / touch / audio status ====="
cat /sys/class/graphics/fb0/virtual_size 2>/dev/null
echo "--- i2c buses ---"
ls /sys/bus/i2c/devices/ 2>/dev/null | tr '\n' ' '; echo
echo "--- event devices ---"
for e in /sys/class/input/event*; do printf "%s: %s\n" "$e" "$(cat $e/device/name 2>/dev/null)"; done
echo "--- zynq-audio ---"
cat /proc/asound/cards 2>/dev/null
echo
echo "===== 11. modules / i2c2 bus reg ====="
cat /proc/device-tree/amba_pl/i2c@41600000/status 2>/dev/null; echo "(i2c@41600000 status above)"
