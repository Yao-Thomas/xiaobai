echo "=== 1) 能不能读 /proc/self/pagemap ==="
sudo python3 - <<'PYEOF'
import mmap, os, struct, ctypes, ctypes.util
PAGE = 4096
# mlock 一块内存
libc = ctypes.CDLL("libc.so.6", use_errno=True)
buf = mmap.mmap(-1, PAGE*4, prot=mmap.PROT_READ|mmap.PROT_WRITE)
addr = ctypes.addressof(ctypes.c_char.from_buffer(buf))
r = libc.mlock(ctypes.c_void_p(addr), ctypes.c_size_t(PAGE*4))
print("  mlock 返回:", r, "errno:", ctypes.get_errno())

# 读 pagemap 拿物理页号
try:
    with open("/proc/self/pagemap","rb") as f:
        f.seek((addr//PAGE)*8)
        e = struct.unpack("<Q", f.read(8))[0]
    present = (e >> 63) & 1
    pfn = e & ((1<<55)-1)
    print("  pagemap: present=%d pfn=0x%x phys=0x%x" % (present, pfn, pfn*PAGE + addr%PAGE))
except Exception as ex:
    print("  pagemap 读取失败:", ex)
PYEOF
echo
echo "=== 2) cacheflush 系统调用（ARM 专属）==="
sudo python3 - <<'PYEOF'
import ctypes, mmap, os
libc = ctypes.CDLL("libc.so.6", use_errno=True)
buf = mmap.mmap(-1, 4096, prot=mmap.PROT_READ|mmap.PROT_WRITE)
addr = ctypes.addressof(ctypes.c_char.from_buffer(buf))
# ARM cacheflush: syscall 0xf0002
SYS_cacheflush = 0xf0002
# 用 libc.syscall 调
try:
    r = libc.syscall(ctypes.c_long(SYS_cacheflush),
                     ctypes.c_void_p(addr), ctypes.c_void_p(addr+4096), ctypes.c_int(0))
    print("  cacheflush 返回:", r, "errno:", ctypes.get_errno())
except Exception as ex:
    print("  cacheflush 失败:", ex)
PYEOF
echo
echo "=== 3) Arch/CPU 确认 ==="
uname -m
grep -m1 "CPU part" /proc/cpuinfo 2>/dev/null || grep -m1 "model name" /proc/cpuinfo
echo
echo "=== 4) 内核有没有 CONFIG_STRICT_DEVMEM（会限制 /dev/mem）==="
zcat /proc/config.gz 2>/dev/null | grep -E "STRICT_DEVMEM|CONFIG_CMA|CONFIG_DMA" | head -5 || echo "  (没有 /proc/config.gz)"