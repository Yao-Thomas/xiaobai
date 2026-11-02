#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""analyze_wav.py —— 波形分析（流式，内存安全）

★★★ 2026-10-01 重写 ★★★
  上一版把整个 WAV 读成 Python list。分析 55 MB 的《半岛铁盒》时，
  Python 的 int 每个占 28 字节，直接吃掉 653 MB —— 板子只有 1 GB，
  立刻开始颠簸，CPU 98.7% 卡死十几分钟，SSH 都连不上。
  （用串口才看到是 python3 analyze_wav.py 在吃内存）

  现在改成：
    · 分块读（默认 64K 帧一块），永不整文件驻留
    · 用 array('i') 而不是 list，4 字节/样本
    · 大文件默认只分析前 N 秒 + 均匀抽样几段（--max-seconds 调）
    · 先检查文件大小，超阈值自动降级成抽样

本板采集的坑（踩了三次才搞对，记在这里）：
  · 采集只支持 S24_LE，而且**只有 44100 Hz** 能装上参数（48000 报
    set_params: Unable to install hw params）
  · 24 位数据**没有符号扩展**：字节 FE FF FF 00 实际是 -2，
    直接按 int32 读会得到 16777214，右移 8 位会得到 65535 —— 都是假象。

用法:
    sudo python3 analyze_wav.py 文件.wav [--max-seconds 10] [--head 32]
    sudo python3 analyze_wav.py 文件.wav --full        # 强制全量（小文件才用）
"""
import array
import math
import os
import struct
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

CHUNK_FRAMES = 65536          # 每块 64K 帧
BIG_FILE_MB = 8               # 超过这个大小就默认抽样
SAMPLE_SECONDS = 6            # 抽样时看多少秒


def read_header(f):
    """读 WAV 头，返回 (nch, bits, rate, blockalign, data_off, data_len)"""
    hdr = f.read(12)
    if hdr[:4] != b"RIFF" or hdr[8:12] != b"WAVE":
        raise SystemExit("不是 WAV 文件")
    while True:
        cid = f.read(4)
        if len(cid) < 4:
            raise SystemExit("找不到 fmt/data 块")
        csz = struct.unpack("<I", f.read(4))[0]
        if cid == b"fmt ":
            body = f.read(csz)
            afmt, nch, rate, brate, balign, bits = struct.unpack_from(
                "<HHIIHH", body, 0)
        elif cid == b"data":
            data_off = f.tell()
            data_len = csz
            break
        else:
            f.seek(csz + (csz & 1), 1)
    return nch, bits, rate, balign, data_off, data_len


def decode(raw, bits):
    """把一块原始字节解成有符号整数数组（内存友好）"""
    if bits == 8:
        a = array.array("i", raw)
        for i in range(len(a)):
            a[i] -= 128
        return a
    if bits == 16:
        a = array.array("h")
        a.frombytes(raw[:len(raw) // 2 * 2])
        return array.array("i", a)
    if bits == 24:
        # ★ 本板 24 位没有符号扩展：低 3 字节 + 从 bit23 手动扩展
        a = array.array("i")
        a.frombytes(raw[:len(raw) // 4 * 4])
        for i in range(len(a)):
            if a[i] >= 0x800000:
                a[i] -= 0x1000000
        return a
    if bits == 32:
        a = array.array("i")
        a.frombytes(raw[:len(raw) // 4 * 4])
        return a
    raise SystemExit("不支持的位深: %d" % bits)


class Acc(object):
    """逐声道增量统计（不存全部样本）"""

    def __init__(self, nch, full):
        self.nch = nch
        self.full = full
        self.mn = [1 << 62] * nch
        self.mx = [-(1 << 62)] * nch
        self.sumsq = [0.0] * nch
        self.n = [0] * nch
        self.nz = [0] * nch
        self.pk = [0] * nch
        self.first = [None] * nch

    def feed(self, vals, keep_first=20):
        nch = self.nch
        for c in range(nch):
            xs = vals[c::nch]
            if not xs:
                continue
            mn = min(xs)
            mx = max(xs)
            if mn < self.mn[c]:
                self.mn[c] = mn
            if mx > self.mx[c]:
                self.mx[c] = mx
            s = 0.0
            nz = 0
            pk = 0
            for x in xs:
                s += float(x) * x
                if x:
                    nz += 1
                ax = x if x >= 0 else -x
                if ax > pk:
                    pk = ax
            self.sumsq[c] += s
            self.n[c] += len(xs)
            self.nz[c] += nz
            if pk > self.pk[c]:
                self.pk[c] = pk
            if self.first[c] is None and len(xs) >= keep_first:
                self.first[c] = list(xs[:keep_first])

    def report(self):
        full = self.full
        for c in range(self.nch):
            if self.n[c] == 0:
                print("\n 声道 %d: 无样本" % c)
                continue
            rms = math.sqrt(self.sumsq[c] / self.n[c])
            dbfs = 20 * math.log10(rms / full) if rms > 0 else -999.0
            pkdb = 20 * math.log10(self.pk[c] / full) if self.pk[c] > 0 else -999.0
            print("\n 声道 %d:" % c)
            print("   min=%-12d max=%-12d 峰峰=%-12d"
                  % (self.mn[c], self.mx[c], self.mx[c] - self.mn[c]))
            print("   RMS=%.1f (%.1f dBFS)   峰值=%.1f dBFS"
                  % (rms, dbfs, pkdb))
            print("   非零=%d/%d (%.1f%%)"
                  % (self.nz[c], self.n[c], 100.0 * self.nz[c] / self.n[c]))
            print("   满量程参考=±%d" % full)
            if self.first[c]:
                print("   前%d样本: %s" % (len(self.first[c]), self.first[c]))
            if self.mx[c] == self.mn[c]:
                print("   ★★★ 恒定值 %d —— 这一路完全没信号" % self.mx[c])
            elif self.pk[c] >= full:
                print("   ★★★ 触到满量程")
            elif dbfs < -60:
                print("   ★ 电平极低（%.1f dBFS）" % dbfs)
            else:
                print("   ✓ 正常信号")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    path = args[0] if args else "/tmp/cap.wav"
    if not os.path.exists(path):
        raise SystemExit("文件不存在: %s" % path)

    head = 20
    if "--head" in sys.argv:
        head = int(sys.argv[sys.argv.index("--head") + 1])
    maxsec = None
    if "--max-seconds" in sys.argv:
        maxsec = float(sys.argv[sys.argv.index("--max-seconds") + 1])

    size_mb = os.path.getsize(path) / 1048576.0

    with open(path, "rb") as f:
        nch, bits, rate, balign, data_off, data_len = read_header(f)
        nframes = data_len // balign

        print("=" * 66)
        print(" 文件: %s  (%.1f MB)" % (path, size_mb))
        print(" 声道=%d  位深=%d  采样率=%d  帧数=%d (%.2f 秒)"
              % (nch, bits, rate, nframes, nframes / float(rate)))
        print("=" * 66)

        full = float(2 ** (bits - 1))
        acc = Acc(nch, full)

        # ---- 决定怎么读 ----
        if maxsec is not None:
            plan = [("前 %.1f 秒" % maxsec, data_off, int(maxsec * rate))]
        elif size_mb > BIG_FILE_MB:
            sec = min(SAMPLE_SECONDS, nframes / float(rate))
            nf = int(sec * rate)
            # 头 / 中 / 尾 三段
            plan = [("开头 %.1f 秒" % sec, data_off, nf),
                    ("中间 %.1f 秒" % sec,
                     data_off + max(0, (nframes // 2) * balign), nf),
                    ("结尾 %.1f 秒" % sec,
                     data_off + max(0, (nframes - nf) * balign), nf)]
            print("\n ★ 文件较大（%.1f MB > %d MB），自动抽样三段，避免吃爆内存"
                  % (size_mb, BIG_FILE_MB))
        else:
            plan = [("全部", data_off, nframes)]

        for label, off, nf in plan:
            f.seek(off)
            left = nf
            while left > 0:
                take = min(CHUNK_FRAMES, left)
                raw = f.read(take * balign)
                if not raw:
                    break
                vals = decode(raw, bits)
                acc.feed(vals, keep_first=head)
                left -= take
            print("\n [已读: %s]" % label)

        acc.report()

        # 声道相关性（只对抽样部分算，用累计量近似不了，这里单独读一小段）
        if nch >= 2:
            f.seek(data_off)
            raw = f.read(min(nframes, int(2 * rate)) * balign)
            vals = decode(raw, bits)
            a = vals[0::nch]
            b = vals[1::nch]
            m = min(len(a), len(b))
            if m > 100:
                sa = sum(a[:m]) / float(m)
                sb = sum(b[:m]) / float(m)
                da = math.sqrt(sum((a[i] - sa) ** 2 for i in range(m)))
                db = math.sqrt(sum((b[i] - sb) ** 2 for i in range(m)))
                if da > 0 and db > 0:
                    num = sum((a[i] - sa) * (b[i] - sb) for i in range(m))
                    r = num / (da * db)
                    print("\n 声道相关系数(前2秒): %.4f" % r)
                    if r > 0.999:
                        print("   ★ 两声道几乎完全相同 —— 可能是单声道复制")


if __name__ == "__main__":
    main()
