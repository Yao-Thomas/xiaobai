#!/bin/sh
# es8388_dump.sh —— 读 ES8388 全部关键寄存器（必须 root）
#
# 为什么单独做成脚本：board.py -f 是以 zynq 用户跑的，
# i2cget 会报 "Could not open file /dev/i2c-1: Permission denied"，
# 所以脚本内部自己 sudo。

BUS=1
ADDR=0x10

echo "======================================================"
echo " ES8388 寄存器 dump  (i2c-$BUS @ $ADDR)"
echo "======================================================"
echo
printf "  reg   值    含义\n"
printf "  ----  ----  ------------------------------------------\n"

read_reg() {
    r=$1
    v=$(sudo i2cget -y $BUS $ADDR $r 2>/dev/null)
    if [ -z "$v" ]; then v="读失败"; fi
    printf "  0x%02X  %-6s %s\n" "$((r))" "$v" "$2"
}

read_reg 0x00 "Chip Control 1   (0x06=正常)"
read_reg 0x01 "Chip Control 2"
read_reg 0x02 "Chip Power Mgmt  (DAC/ADC 上电位)"
read_reg 0x03 "ADC Power Mgmt   ★ PdnMICB/PdnADCB"
read_reg 0x04 "DAC Power Mgmt"
read_reg 0x08 "Master Mode Ctrl"
read_reg 0x09 "ADC Control 1"
read_reg 0x0A "ADC Control 2    ★★ 输入选择(0x00=MIC, 0x50=LINE)"
read_reg 0x0B "DAC Control 1"
read_reg 0x0C "DAC Control 2"
read_reg 0x0D "ADC Control 5    ★"
read_reg 0x0E "ADC Control 6"
read_reg 0x10 "DAC Control 3"
read_reg 0x11 "DAC Control 4"
read_reg 0x12 "DAC Control 5"
read_reg 0x17 "ADC Control 3    ★ PGA/增益"
read_reg 0x18 "ADC Control 4"
read_reg 0x19 "ADC PGA L        ★ 左 PGA 增益"
read_reg 0x1A "ADC PGA R        ★ 右 PGA 增益"
read_reg 0x1B "ADC ALC Control 1"
read_reg 0x1C "ADC ALC Control 2"
read_reg 0x1D "DAC Ctrl 8"
read_reg 0x26 "DAC Control 15"
read_reg 0x27 "DAC Control 16"
read_reg 0x2E "Output 1 L"
read_reg 0x30 "Output 2 L"

echo
echo "======================================================"
echo " 判读提示"
echo "======================================================"
echo "  · 0x0A  低 2 位选输入："
echo "      00 = LIN1/RIN1（麦克风）  01 = LIN2/RIN2（LINE）"
echo "      10/11 = 差分"
echo "  · 0x03  bit3 = PdnMICB（1=偏置关），bit2 = PdnADCB"
echo "  · 0x17  bit7 = ADC 数据长度/格式"
echo "  · 0x19/0x1A  PGA 增益（0x00=0dB, 0x08=+24dB ...）"
