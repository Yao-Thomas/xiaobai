cd /home/zynq
sudo python3 - <<'PYEOF'
import mmap, os, struct, time
base = 0x43CD0000
print("=== 1) 打开 /dev/mem ===")
for flags, name in [(os.O_RDWR | os.O_SYNC, "O_SYNC"),
                    (os.O_RDWR, "O_RDWR")]:
    try:
        fd = os.open("/dev/mem", flags)
        mm = mmap.mmap(fd, 4096, mmap.MAP_SHARED,
                       mmap.PROT_READ | mmap.PROT_WRITE, offset=base)
        ap0 = struct.unpack_from("<I", mm, 0)[0]
        print("  %-8s 打开成功, 初始 ap_ctrl = 0x%08X" % (name, ap0))
        # 写 ap_start=1 然后立刻读回
        struct.pack_into("<I", mm, 0, 1)
        time.sleep(0.001)
        ap1 = struct.unpack_from("<I", mm, 0)[0]
        print("           写 1 之后读回 = 0x%08X  (期望 ap_start 或 done 置位)" % ap1)
        # 等一会儿看 done
        for i in range(10):
            time.sleep(0.1)
            ap = struct.unpack_from("<I", mm, 0)[0]
            if ap & 2:
                print("           第 %d 次读到 done=1, ap=0x%08X" % (i, ap))
                break
        else:
            print("           等 1 秒也没等到 done, 最后 ap=0x%08X" % ap)
        mm.close(); os.close(fd)
    except Exception as e:
        print("  %-8s 失败: %s" % (name, e))
PYEOF
echo
echo "=== 2) 用 devmem 工具直接读（交叉验证）==="
which devmem busybox 2>/dev/null
sudo python3 -c "
import mmap, os, struct
fd = os.open('/dev/mem', os.O_RDWR|os.O_SYNC)
mm = mmap.mmap(fd, 64, mmap.MAP_SHARED, mmap.PROT_READ|mmap.PROT_WRITE, offset=0x43CD0000)
print('  43CD0000:')
for off in range(0, 64, 4):
    print('    +0x%02X = 0x%08X' % (off, struct.unpack_from('<I', mm, off)[0]))
mm.close(); os.close(fd)
"