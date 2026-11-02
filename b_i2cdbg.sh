echo "=== 1) 直接 sudo i2cget（看报错）==="
sudo /usr/sbin/i2cget -y 1 0x10 0x0A; echo "  退出码=$?"
echo
echo "=== 2) sudo 的环境 ==="
sudo echo "  sudo 可用"
sudo which i2cget || echo "  sudo PATH 里没有 i2cget"
echo "  --- sudo secure_path ---"
sudo -n grep -E "secure_path" /etc/sudoers 2>/dev/null
echo
echo "=== 3) /dev/i2c-1 权限 ==="
ls -la /dev/i2c-1
id
echo
echo "=== 4) 用 python 直接读（绕开 i2cget）==="
sudo python3 - <<'PYEOF'
import fcntl, struct, os
I2C_SLAVE = 0x0703
try:
    fd = os.open("/dev/i2c-1", os.O_RDWR)
    print("  打开 /dev/i2c-1 OK")
    fcntl.ioctl(fd, I2C_SLAVE, 0x10)
    print("  选中 0x10 OK")
    # 先写寄存器地址，再读
    os.write(fd, bytes([0x0A]))
    d = os.read(fd, 1)
    print("  reg 0x0A = 0x%02X" % d[0])
    for r in (0x00, 0x02, 0x03, 0x09, 0x0A, 0x0D, 0x17, 0x19, 0x1A):
        os.write(fd, bytes([r]))
        d = os.read(fd, 1)
        print("  reg 0x%02X = 0x%02X" % (r, d[0]))
    os.close(fd)
except Exception as e:
    print("  失败:", type(e).__name__, e)
PYEOF