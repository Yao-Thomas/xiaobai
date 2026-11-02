echo "=== 1) amixer 简易控件全表 ==="
sudo amixer -c 0 scontrols 2>&1
echo
echo "=== 2) 关键控件的值 ==="
sudo amixer -c 0 2>&1 | head -40
echo
echo "=== 3) 逐个 content（找和 ADC 输入相关的）==="
sudo amixer -c 0 contents 2>/dev/null | grep -A3 -iE "name='(Capture|ADC|Input|PGA|Mic|Line|Left Channel|Right Channel)" | head -60