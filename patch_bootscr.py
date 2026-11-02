import struct, zlib, shutil, os, time

SRC = r"E:\boot.scr"
BAK = r"E:\boot.scr.backup_before_fix"

# ---- 1. 备份 ----
if not os.path.exists(BAK):
    shutil.copy2(SRC, BAK)
    print("已备份原文件 -> %s" % BAK)
else:
    print("备份已存在: %s" % BAK)

d = open(SRC, "rb").read()
assert d[:4] == b"\x27\x05\x19\x56", "不是 uImage 格式"
hdr = bytearray(d[:64])
data = d[64:]
txt = data.decode("ascii", "replace")
print("\n原始脚本 %d 字节" % len(data))

# ---- 2. 在 bootz 之前插入 bootargs ----
NEWARGS = ("console=ttyPS0,115200 root=/dev/mmcblk0p2 rw rootwait earlycon "
           "systemd.mask=zynq-gpu-loader.service")
inject = ('setenv bootargs "%s";\n' % NEWARGS)

if "systemd.mask" in txt:
    print("脚本里已经有 systemd.mask, 不重复插入")
    new_txt = txt
else:
    lines = txt.split("\n")
    out = []
    done = False
    for ln in lines:
        s = ln.strip()
        if (not done) and s.startswith("bootz 0x00200000"):
            out.append(inject)
            done = True
            print("已在 'bootz' 前插入 bootargs ✅")
        out.append(ln)
    new_txt = "\n".join(out)
    if not done:
        print("!! 没找到 bootz 那行, 不改")
        new_txt = txt

if new_txt == txt:
    print("脚本无变化, 不动文件")
    raise SystemExit(0)

new_data = new_txt.encode("ascii", "replace")

# ---- 3. 重建 uImage 头 ----
# 格式: magic hcrc time size load ep dcrc os arch type comp name[32]
dcrc = zlib.crc32(new_data) & 0xFFFFFFFF
newh = bytearray(hdr)
newh[ 8:12] = struct.pack(">I", int(time.time()))     # time
newh[12:16] = struct.pack(">I", len(new_data))        # size
newh[24:28] = struct.pack(">I", dcrc)                 # data crc
newh[ 4: 8] = b"\x00\x00\x00\x00"                     # 计算头 CRC 时先清零
hcrc = zlib.crc32(bytes(newh)) & 0xFFFFFFFF
newh[ 4: 8] = struct.pack(">I", hcrc)                 # header crc

out = bytes(newh) + new_data
open(SRC, "wb").write(out)
print("\n已写入新 boot.scr: %d 字节 (数据段 %d)" % (len(out), len(new_data)))
print("校验: 头部 CRC=0x%08X  数据 CRC=0x%08X" % (hcrc, dcrc))

# ---- 4. 回读校验 ----
chk = open(SRC, "rb").read()
ok_magic = chk[:4] == b"\x27\x05\x19\x56"
ok_size  = struct.unpack(">I", chk[12:16])[0] == len(chk) - 64
ok_dcrc  = (zlib.crc32(chk[64:]) & 0xFFFFFFFF) == struct.unpack(">I", chk[24:28])[0]
h2 = bytearray(chk[:64]); h2[4:8] = b"\x00\x00\x00\x00"
ok_hcrc  = (zlib.crc32(bytes(h2)) & 0xFFFFFFFF) == struct.unpack(">I", chk[4:8])[0]
print("  魔数 %s / 长度 %s / 数据CRC %s / 头CRC %s" %
      ("OK" if ok_magic else "坏", "OK" if ok_size else "坏",
       "OK" if ok_dcrc else "坏", "OK" if ok_hcrc else "坏"))
print("\n--- 新脚本关键部分 ---")
for ln in chk[64:].decode("ascii", "replace").split("\n"):
    s = ln.strip()
    if s.startswith("setenv bootargs") or s.startswith("bootz") or "zynq-gpu" in s:
        print("  " + s[:180])
