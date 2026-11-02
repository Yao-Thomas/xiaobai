#!/bin/sh
# READ-ONLY /dev/mem peek via python (mmap PROT_READ)
sudo -n python3 - <<'PY'
import mmap, os, struct
f = os.open('/dev/mem', os.O_RDONLY | os.O_SYNC)
def peek(base, off):
    m = mmap.mmap(f, 4096, mmap.MAP_SHARED, mmap.PROT_READ, offset=base)
    v = struct.unpack('<I', m[off:off+4])[0]
    m.close()
    return v
for name, base in (("scope_cap_axi", 0x43CC0000), ("gpu2d_axi", 0x43CB0000)):
    try:
        print("%-14s @0x%08X VERSION(0x34)=0x%08X" % (name, base, peek(base, 0x34)))
    except Exception as e:
        print("%-14s @0x%08X FAIL %s" % (name, base, e))
for name, base in (("audio_formatter", 0x43C50000), ("i2s_receiver", 0x43C60000)):
    try:
        print("%-14s @0x%08X word0=0x%08X" % (name, base, peek(base, 0x00)))
    except Exception as e:
        print("%-14s @0x%08X FAIL %s" % (name, base, e))
os.close(f)
PY
echo "PEEK_DONE"
