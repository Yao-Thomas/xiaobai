cd /home/zynq/ui
echo "=== 1) 看 I2C 相关代码 ==="
grep -nE "I2C_SLAVE|I2C_BUS|I2C_ADDR|ioctl" audio_pl.py | head -12
echo
echo "=== 2) 备份 + 改成 FORCE ==="
TS=$(date +%Y%m%d_%H%M%S)
cp audio_pl.py audio_pl.py.bak_i2cforce_$TS
echo "  备份: audio_pl.py.bak_i2cforce_$TS"
sudo python3 - <<'PYEOF'
p = "/home/zynq/ui/audio_pl.py"
s = open(p, encoding="utf-8").read()
orig = s
# 加一个 FORCE 常量
if "I2C_SLAVE_FORCE" not in s:
    # 在 I2C_SLAVE 定义后面加
    import re
    m = re.search(r"^(I2C_SLAVE\s*=\s*0x0703.*)$", s, re.M)
    if m:
        s = s.replace(m.group(1),
                      m.group(1) + "\n\n# ★ 2026-10-01 加：内核 es8388 驱动会占着 0x10 这个地址，\n"
                      "#   普通 I2C_SLAVE 会报 EBUSY。FORCE 版本跳过占用检查，\n"
                      "#   不需要卸载驱动（卸载反而会把 aud_mclk 的引用计数放掉）。\n"
                      "I2C_SLAVE_FORCE = 0x0706", 1)
    else:
        print("  !! 找不到 I2C_SLAVE 定义")
    # 把 ioctl 换成 FORCE
    if "ioctl(self.fd, I2C_SLAVE," in s:
        s = s.replace("ioctl(self.fd, I2C_SLAVE,",
                      "ioctl(self.fd, I2C_SLAVE_FORCE,", 1)
        print("  ioctl 已改为 I2C_SLAVE_FORCE")
    else:
        print("  !! 找不到 ioctl 调用")
if s != orig:
    open(p, "w", encoding="utf-8").write(s)
    print("  已写入")
else:
    print("  没变化")
PYEOF
echo
echo "=== 3) 确认改动 ==="
grep -nE "I2C_SLAVE" audio_pl.py | head -8
python3 -c "import ast,io; ast.parse(io.open('audio_pl.py',encoding='utf-8').read()); print('syntax OK')"