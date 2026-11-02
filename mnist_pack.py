#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mnist_pack.py —— 把 mnist_data.h 里的数组打包成二进制，供板子用

输出 mnist_test.bin 的布局（全小端）：
   偏移   大小    内容
   0      784     TEST_IMG   (uint8, 0..255)
   784    72      W1         (int8)
   856    1152    W2         (int8)
   2008   4000    WF         (int8)
   6008   4       label      (uint32, 应为 7)
   总计   6012 字节
"""
import re
import struct
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

SRC = r"D:\ubuntu_iso\_cnn_ref\源码\ps_sw_m4b5\mnist_data.h"
DST = r"D:\ubuntu_iso\mnist_test.bin"


def grab(name, src):
    """从 C 头文件里抠出数组的数值列表"""
    m = re.search(re.escape(name) + r"\s*\[[^\]]*\]\s*=\s*\{(.*?)\};",
                  src, re.S)
    if not m:
        raise SystemExit("找不到数组 %s" % name)
    body = m.group(1)
    body = re.sub(r"//[^\n]*", "", body)          # 去行注释
    nums = []
    for tok in re.findall(r"-?\d+", body):
        nums.append(int(tok))
    return nums


def main():
    src = open(SRC, encoding="utf-8", errors="replace").read()

    img = grab("TEST_IMG", src)
    w1 = grab("W1", src)
    w2 = grab("W2", src)
    wf = grab("WF", src)

    m = re.search(r"TEST_IMG_LABEL\s*=\s*(\d+)", src)
    label = int(m.group(1)) if m else -1

    print("  TEST_IMG : %d 个" % len(img))
    print("  W1       : %d 个" % len(w1))
    print("  W2       : %d 个" % len(w2))
    print("  WF       : %d 个" % len(wf))
    print("  label    : %d" % label)

    assert len(img) == 784, len(img)
    assert len(w1) == 72, len(w1)
    assert len(w2) == 1152, len(w2)
    assert len(wf) == 4000, len(wf)

    blob = bytes(img)                                    # uint8
    blob += struct.pack("<%db" % len(w1), *w1)           # int8
    blob += struct.pack("<%db" % len(w2), *w2)
    blob += struct.pack("<%db" % len(wf), *wf)
    blob += struct.pack("<I", label)

    with open(DST, "wb") as f:
        f.write(blob)
    print("\n  写出 %s（%d 字节）" % (DST, len(blob)))
    print("  校验: img[0..7]=%s  W1[0..7]=%s" % (img[:8], w1[:8]))
    print("  label 应识别为 %d" % label)


if __name__ == "__main__":
    main()
