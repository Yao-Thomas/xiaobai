echo "=== 1) ADC_IN 字典（620-645）==="
sed -n '620,645p' /home/zynq/ui/audio_pl.py
echo
echo "=== 2) AudioIn 的 i2s_config / fmt_config / start ==="
sed -n '735,800p' /home/zynq/ui/audio_pl.py
echo
echo "=== 3) 关键常量（I2S 寄存器地址等）==="
grep -nE "^I2S_RX_BASE|^I2S_BASE|^I2S_CORE_CTRL|^I2S_I2STIM|^I2S_CH0|^I2S_DIV|^FMT_BASE|^CTRL_|^R2_|^BIT_DEPTH|^CHANNELS|^MCLK_RATIO|^ADC_IN|^DEFAULT_DW|^FS" /home/zynq/ui/audio_pl.py | head -40