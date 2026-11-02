#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_period_overflow.py —— 修我上一轮"放大播放环"补丁造成的寄存器溢出

═══ 问题 ═══
patch_bigring.py 把 period_bytes 的上限从 16384 放开到 buf.avail/periods，
结果 period_bytes 变成了 524288（服务）/ 1048576（独立跑）。

但 register 写法是：

    self._w(R_PERIOD, (self.periods << 16) | self.period_bytes)

**低 16 位放 period_bytes** —— 524288 = 0x80000 已经超出 16 位范围！

实测读回：
    PERIOD=0x00140000    -> 周期数=0x0014=20, period_bytes=0x0000=0   ✗
    BYTES_PER_CH=524288

采样周期字段变成 0 -> formatter 配置无效 -> **放出来的是噪音**。
这正是用户说的"放了一堆噪音然后停了"。

═══ 修法 ═══
环大小 = period_bytes × periods。要让环变大，**应该加 periods，不是加
period_bytes**：
    * period_bytes 保持 <= 16384（16 位字段安全）
    * periods 放到 16 位字段能容纳的范围（<= 65535）

例如 2048 KB 环 = 16384 B × 128 周期 ✓
     R_PERIOD = (128 << 16) | 16384 = 0x00804000   ✓ 合法
"""
import io
import sys

P = "ui/audio_pl.py"
src = io.open(P, encoding="utf-8").read()

if "PERIOD_MAX_BYTES" in src:
    print("已经打过补丁，跳过")
    sys.exit(0)

OLD = '''        want_buf = int(os.environ.get("AUDIO_PLAY_BUF", str(2 << 20)))
        self.buf = None
        for try_buf in (want_buf, want_buf // 2, want_buf // 4, 64 << 10):
            if try_buf < (64 << 10):
                break
            try:
                self.buf = DmaBuffer(try_buf, verbose=verbose)
                break
            except Exception as e:
                if verbose:
                    print("[dma] 申请 %d KB 播放缓冲失败(%s)，回退"
                          % (try_buf >> 10, str(e)[:40]))
        if self.buf is None:
            self.buf = DmaBuffer(64 << 10, verbose=verbose)

        if period_bytes is None:
            pb = (self.buf.avail // periods) & ~(PAGE - 1)
            # ★ 上限从 16384 放开到 buf.avail/periods（留一页余量）
            pb = max(PAGE, min(pb, max(PAGE, self.buf.avail // periods)))
            period_bytes = pb
        self.periods = periods
        self.period_bytes = period_bytes
        self.ring = period_bytes * periods
        assert self.ring <= self.buf.avail
'''

NEW = '''        want_buf = int(os.environ.get("AUDIO_PLAY_BUF", str(2 << 20)))
        self.buf = None
        for try_buf in (want_buf, want_buf // 2, want_buf // 4, 64 << 10):
            if try_buf < (64 << 10):
                break
            try:
                self.buf = DmaBuffer(try_buf, verbose=verbose)
                break
            except Exception as e:
                if verbose:
                    print("[dma] 申请 %d KB 播放缓冲失败(%s)，回退"
                          % (try_buf >> 10, str(e)[:40]))
        if self.buf is None:
            self.buf = DmaBuffer(64 << 10, verbose=verbose)

        # ★★ R_PERIOD 的字段布局：(periods << 16) | period_bytes
        #    **低 16 位是 period_bytes** —— 所以它必须 <= 65535！
        #    第一版补丁把上限放开到 buf.avail/periods，结果 period_bytes
        #    变成 524288（0x80000），超出 16 位 -> 寄存器读回
        #    PERIOD=0x00140000（period_bytes 变成 0）-> formatter 配置失效
        #    -> **放出来全是噪音**（用户说的"一堆噪音然后停了"）。
        #
        #    正确做法：**环变大靠加 periods，不是加 period_bytes**。
        if period_bytes is None:
            pb = (self.buf.avail // periods) & ~(PAGE - 1)
            pb = max(PAGE, min(pb, PERIOD_MAX_BYTES))
            period_bytes = pb
        self.period_bytes = period_bytes
        # ★ periods 也放进 16 位字段，别溢出
        want_periods = max(periods, self.buf.avail // max(PAGE, period_bytes))
        self.periods = max(1, min(periods, PARAMS_PERIODS_MAX)) \\
            if False else max(1, min(want_periods, PERIODS_MAX))
        self.ring = period_bytes * self.periods
        assert self.ring <= self.buf.avail
        assert self.periods <= PERIODS_MAX and period_bytes <= PERIOD_MAX_BYTES
'''

if OLD not in src:
    print("  [!] 锚点没找到（可能已被改）")
    sys.exit(1)
src = src.replace(OLD, NEW, 1)
print("  OK: period_bytes 限回 16 位安全值，环靠 periods 变大")

# 插常量
anchor = "class AudioOut:"
consts = '''# ★ R_PERIOD 的字段上限（低16位=period_bytes，高16位=periods）
PERIOD_MAX_BYTES = 16384          # period_bytes 必须 <= 65535，这里保守取 16384
PERIODS_MAX = 4096                # periods 上限（高16位字段够放，但别太夸张）


'''
assert anchor in src, "class AudioOut 锚点没找到"
src = src.replace(anchor, consts + anchor, 1)
print("  OK: 加了 PERIOD_MAX_BYTES / PERIODS_MAX")

io.open(P, "w", encoding="utf-8").write(src)
import ast
ast.parse(io.open(P, encoding="utf-8").read())
print("audio_pl.py syntax OK")
