#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bit2bin.py —— Xilinx .bit 转成 Zynq fpga_manager 要的【字节交换 .bin】

════════════════════════════════════════════════════════════════════
为什么需要（这是踩出来的，记下来）
════════════════════════════════════════════════════════════════════
往 /sys/class/fpga_manager/fpga0/firmware 写文件时，内核报：

    Invalid bitstream, could not find a sync word.
    Bitstream must be a byte swapped .bin file

两个关键词：
  ① **.bin**      —— 不能带 .bit 的文件头
  ② **byte swapped** —— Zynq 的 PCAP 是 32 位接口，而 bitstream 是
                        大端序的，所以要按 32 位字做字节交换

对照实测（cnn_new.bit → 能用的 gpu.bin）：
    .bit  偏移 253 处是 sync word  AA 99 55 66
      往前 16 字节: 00 00 00 bb | 11 22 00 44 | ff ff ff ff | ff ff ff ff
      每 4 字节反转: bb 00 00 00 | 44 00 22 11 | ff ff ff ff | ff ff ff ff
                   ↑ 和已知能用的 gpu.bin 前 16 字节完全一致
    而且 4045769 - 237 = 4045532 = gpu.bin 的大小 ✓

★ 所以规则是：从 sync word 往前 16 字节开始，取到文件尾，按 4 字节反转。

用法:
    python bit2bin.py cnn_new.bit cnn.bin
    python bit2bin.py cnn_new.bit cnn.bin --verify gpu.bin   # 和已知的对一下
"""
import argparse
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

SYNC = bytes.fromhex("aa995566")
SYNC_SWAPPED = bytes.fromhex("665599aa")
BACK = 16          # sync 往前多少字节开始算数据


def bit_to_bin(bit_bytes):
    """真 .bit → 字节交换 .bin

    返回 (bin_bytes, info dict)
    """
    n = bit_bytes.find(SYNC)
    if n < 0:
        # 也许已经是 .bin 了
        m = bit_bytes.find(SYNC_SWAPPED)
        if m >= 0:
            return bit_bytes, {"already_bin": True, "sync_at": m,
                               "offset": 0, "note": "本来就是字节交换 .bin"}
        raise ValueError("找不到 sync word（AA995566 / 665599AA），"
                         "这既不是 .bit 也不是 .bin？")
    off = n - BACK
    if off < 0:
        off = 0
    data = bit_bytes[off:]
    # 补齐到 4 的倍数（多出来的补 0）
    pad = (-len(data)) % 4
    if pad:
        data = data + b"\x00" * pad
    out = bytearray(len(data))
    for i in range(0, len(data), 4):
        out[i:i + 4] = data[i:i + 4][::-1]
    return bytes(out), {"already_bin": False, "sync_at": n, "offset": off,
                        "pad": pad,
                        "size": len(data),
                        "note": "从 sync 前 %d 字节开始，按 4 字节反转" % BACK}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--verify", default="",
                    help="和这个已知能用的 .bin 比对（可选）")
    a = ap.parse_args()

    print("=" * 66)
    print(" .bit → 字节交换 .bin")
    print("=" * 66)
    raw = open(a.src, "rb").read()
    print(" 源: %s  %d 字节" % (a.src, len(raw)))

    out, info = bit_to_bin(raw)
    print("  %s" % info["note"])
    print("  sync 在偏移 %d，数据从 %d 开始" % (info.get("sync_at", -1),
                                              info.get("offset", 0)))
    print(" 产物: %s  %d 字节" % (a.dst, len(out)))
    print(" 前 16 字节: %s" % out[:16].hex(" "))
    print(" 后 16 字节: %s" % out[-16:].hex(" "))

    if out[:4] == SYNC_SWAPPED or out.find(SYNC_SWAPPED) >= 0:
        print(" ✓ 里面有字节交换的 sync word（fpga_manager 要的就是这个）")
    else:
        print(" ★ 没找到字节交换的 sync word —— 格式可能不对")

    if a.verify:
        try:
            ref = open(a.verify, "rb").read()
            print()
            print(" 对照 %s（%d 字节）" % (a.verify, len(ref)))
            if len(ref) == len(out):
                same = sum(1 for i in range(len(ref)) if ref[i] == out[i])
                print("   长度一致 ✓   逐字节相同 %d/%d" % (same, len(ref)))
            else:
                print("   长度不同：%d vs %d" % (len(ref), len(out)))
            print("   参考前 16: %s" % ref[:16].hex(" "))
            print("   我们前 16: %s" % out[:16].hex(" "))
        except Exception as e:
            print("   对照失败: %s" % e)

    with open(a.dst, "wb") as f:
        f.write(out)
    print()
    print(" 已写出 %s" % a.dst)
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
