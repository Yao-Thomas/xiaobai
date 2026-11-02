import sys

p = r"E:\boot.scr"
d = open(p, "rb").read()
print("文件大小: %d 字节" % len(d))
magic = d[:4].hex()
print("魔数: 0x%s %s" % (magic, "(uImage 格式 OK)" if magic == "27051956" else "(不是标准 uImage)"))
if magic == "27051956":
    import struct
    ih_name = d[32:64]
    print("  名称: %s" % ih_name.rstrip(b"\x00").decode("ascii", "replace"))
body = d[64:]
txt = body.decode("ascii", "replace")
print("--- 脚本内容 ---")
for line in txt.splitlines():
    s = line.strip()
    if s:
        print("  " + s[:170])
