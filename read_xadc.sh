#!/bin/bash
# 读 XADC 的温度换算参数
D=/sys/devices/soc0/amba/f8007100.adc/iio:device0
echo "=== IIO 属性 ==="
for f in in_temp0_raw in_temp0_offset in_temp0_scale; do
  echo -n "  $f = "; cat $D/$f 2>/dev/null
done
echo
echo "=== 按标准 IIO 公式换算 ==="
python3 - <<'PY'
D = "/sys/devices/soc0/amba/f8007100.adc/iio:device0"
try:
    r = float(open(D + "/in_temp0_raw").read())
    o = float(open(D + "/in_temp0_offset").read())
    s = float(open(D + "/in_temp0_scale").read())
    print("  raw=%.0f offset=%.0f scale=%.6f" % (r, o, s))
    print("  温度 = (raw + offset) * scale = %.1f C" % ((r + o) * s))
except Exception as e:
    print("  失败:", e)
# 对照：我原来那个错误公式
r = float(open(D + "/in_temp0_raw").read())
print()
print("  我原来的错误公式（raw > 2000 就 /1000）: %.1f  <- 这就是那个 2.9" % (r / 1000.0))
print("  Zynq XADC 通用公式 raw*503.975/4096-273.15: %.1f C"
      % (r * 503.975 / 4096.0 - 273.15))
PY
