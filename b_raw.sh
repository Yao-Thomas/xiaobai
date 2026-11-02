cd /home/zynq
sudo python3 - <<'PYEOF'
import struct
data = open("/tmp/cap44.wav","rb").read()
# 找 data 块
i = data.find(b"data")
hdr = i + 8
print("=== WAV 头信息 ===")
print("  fmt 块:", data[12:36].hex())
afmt, nch, rate, brate, balign, bits = struct.unpack_from("<HHIIHH", data, 20)
print("  afmt=%d nch=%d rate=%d byterate=%d blockalign=%d bits=%d" %
      (afmt, nch, rate, brate, balign, bits))
print("  data 块从偏移 %d 开始" % hdr)

print()
print("=== 原始字节（前 48 字节）===")
raw = data[hdr:hdr+48]
for k in range(0, 48, 16):
    chunk = raw[k:k+16]
    print("  %3d: %s" % (k, " ".join("%02X" % b for b in chunk)))

print()
print("=== 按 4 字节一组看（S24_LE 小端，看高 3 字节）===")
for k in range(0, 32, 4):
    b0,b1,b2,b3 = raw[k], raw[k+1], raw[k+2], raw[k+3]
    v32 = b0 | (b1<<8) | (b2<<16) | (b3<<24)
    if v32 >= 2**31: v32 -= 2**32
    print("  [%2d] %02X %02X %02X %02X  -> i32=%-12d  >>8 = %-10d  高3字节=%02X%02X%02X" %
          (k//4, b0,b1,b2,b3, v32, v32>>8, b2,b1,b0))

print()
print("=== 按 2 字节一组看（如果是 16 位）===")
for k in range(0, 32, 2):
    v = struct.unpack_from("<h", raw, k)[0]
    print("  [%2d] %02X %02X -> i16=%d" % (k//2, raw[k], raw[k+1], v))
PYEOF