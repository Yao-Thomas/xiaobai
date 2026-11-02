md5sum /mnt/boot/system.bit
ls -la /mnt/boot/system.bit
echo
echo "=== 3) CNN 地址现在能不能读 ==="
sudo python3 - <<'PYEOF'
import mmap, os, struct
for name, base in [("scope", 0x43CC0000), ("cnn_conv", 0x43CD0000), ("cnn_fc", 0x43CE0000)]:
    pid = os.fork()
    if pid == 0:
        try:
            fd = os.open("/dev/mem", os.O_RDONLY | os.O_SYNC)
            m = mmap.mmap(fd, 4096, mmap.MAP_SHARED, mmap.PROT_READ, offset=base)
            v = struct.unpack("<I", m[0:4])[0]
            print("  %-9s @0x%08X = 0x%08X" % (name, base, v)); os._exit(0)
        except Exception as e:
            print("  %-9s @0x%08X  BUS ERROR" % (name, base)); os._exit(1)
    os.waitpid(pid, 0)
PYEOF