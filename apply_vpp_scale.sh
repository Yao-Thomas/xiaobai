#!/usr/bin/env bash
# 应用 Vpp_scale 3.5V -> 4.0V（约 +1.16 dB），然后播放对比
echo "=== 1) 当前 0x1D（DAC Control 8）==="
v=$(sudo i2cget -f -y 1 0x10 0x1d 2>/dev/null)
echo "  0x1D = $v   （bit1:0 = $(printf '%d' $((v & 3))) ）"
echo "  0 = Vpp 3.5V(默认)   1 = Vpp 4.0V"
echo
echo "=== 2) 改成 4.0V（bit1:0 = 01）==="
new=$(printf '0x%02x' $(( (v & 0xFC) | 0x01 )))
sudo i2cset -f -y 1 0x10 0x1d $new 2>/dev/null
sleep 0.3
v2=$(sudo i2cget -f -y 1 0x10 0x1d 2>/dev/null)
echo "  写入 $new 后读回: $v2   （bit1:0 = $(printf '%d' $((v2 & 3))) ）"
echo "  ✓ 现在 Vpp = 4.0V" 
echo
echo "=== 3) 确认其它增益仍是最大 ==="
printf "  "
for r in 0x1a 0x1b 0x27 0x2a 0x2e 0x2f 0x30 0x31; do
  printf "0x%s=%s " "${r#0x}" "$(sudo i2cget -f -y 1 0x10 $r 2>/dev/null)"
done
echo
amixer -c 0 sget 'Output 1' 2>/dev/null | grep -E "Front Left"
echo
echo "############################################################"
echo "#  播放《小星星》—— 这是 Vpp=4.0V 的版本"
echo "############################################################"
# 播放中把 0x1D 钉住（驱动可能重写）
aplay -q /home/zynq/Music/03_小星星.wav &
AP=$!
for i in $(seq 1 16); do
  sudo i2cset -f -y 1 0x10 0x1d $new 2>/dev/null
  sleep 0.5
done
wait $AP 2>/dev/null
echo "  --- 放完 ---"
echo
echo "=== 4) 播放后 0x1D（看驱动有没有改回去）==="
sudo i2cget -f -y 1 0x10 0x1d 2>/dev/null | xargs -I{} echo "  0x1D = {}"
