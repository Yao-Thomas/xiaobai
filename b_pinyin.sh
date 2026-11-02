# 键盘坐标（从截图量）
# q行 y=420: q150 w232 e314 r396 t478 y560 u642 i724 o806 p888
# a行 y=465: a150 s232 d314 f396 g478 h560 j642 k724 l806
# z行 y=510: z150 x232 c314 v396 b478 n560 m642
TAP() { printf "$1" | sudo tee /tmp/ui_tap >/dev/null; sync; sleep 0.5; }

echo "=== 输入拼音 xianzai ==="
TAP "232,510"   # x
TAP "724,420"   # i
TAP "150,465"   # a
TAP "560,510"   # n
TAP "150,510"   # z
TAP "150,465"   # a
TAP "724,420"   # i
sleep 1.5
sudo python3 /home/zynq/ui/shot_fb.py /tmp/shot_py1.raw 2>&1 | tail -1