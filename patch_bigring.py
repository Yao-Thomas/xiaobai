#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""patch_bigring.py —— 把播放环从 0.186 秒放大到能装下整首歌

═══ 问题 ═══
audio_pl.AudioOut.__init__：

    self.buf = DmaBuffer(64 << 10)        # 缓冲只有 64 KB
    pb = max(PAGE, min(pb, 16384))        # 周期上限写死 16384
    self.ring = period_bytes * periods    # = 16384*4 = 65536 字节

65536 字节 = 8192 帧 = **0.186 秒**（@44100Hz, 8字节/帧）。

整首歌 7.42 秒 → 要流式换 40 次块。写块和 DMA 消费一旦错位就重复/撕裂，
表现就是"一堆的 do"（《小星星》开头正好是 do do）。

═══ 实测依据（本轮） ═══
DMA 消费速率实测 **44056 帧/秒**（期望 44100，比值 0.9990）——
速率是**正确**的，所以不是速率问题，是**缓冲太小**。

═══ 修法 ═══
1. DmaBuffer 从 64 KB 提到 2 MB（可配环境变量 AUDIO_PLAY_BUF）
2. period_bytes 上限从 16384 放到 buf.avail/periods
3. ring = period_bytes * periods  -> 最大约 2 MB = 5.9 秒
4. reserve_contig 失败时自动回退到小尺寸（不能因为拿不到大块连续内存就崩）

★ 只改 AudioOut（放音侧）。录音侧的 RawCap 不动 —— 录音现在是好的。
"""
import io
import sys

P = "ui/audio_pl.py"
src = io.open(P, encoding="utf-8").read()

if "AUDIO_PLAY_BUF" in src:
    print("已经打过补丁，跳过")
    sys.exit(0)

OLD = '''        self.buf = DmaBuffer(64 << 10, verbose=verbose)

        if period_bytes is None:
            pb = (self.buf.avail // periods) & ~(PAGE - 1)
            pb = max(PAGE, min(pb, 16384))
            period_bytes = pb
        self.periods = periods
        self.period_bytes = period_bytes
        self.ring = period_bytes * periods
        assert self.ring <= self.buf.avail
'''

NEW = '''        # ★ 播放缓冲大小（2026-09-28 改）
        #   原来写死 64 KB -> ring 只有 65536 字节 = 0.186 秒，
        #   整首歌要流式换 40 次块，容易重复/撕裂（"一堆的 do"）。
        #   实测 DMA 速率是正确的 44056 帧/秒，所以问题在缓冲大小。
        #   默认 2 MB（约 5.9 秒），可用 AUDIO_PLAY_BUF 覆盖。
        want_buf = int(os.environ.get("AUDIO_PLAY_BUF", str(2 << 20)))
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

if OLD not in src:
    print("  [!] __init__ 锚点没找到")
    sys.exit(1)
src = src.replace(OLD, NEW, 1)
print("  OK: 播放缓冲 64KB -> 2MB（带回退）")

# 确认 os 已 import
if "\nimport os" not in src:
    src = src.replace("import math", "import math\nimport os", 1)
    print("  OK: 补 import os")

io.open(P, "w", encoding="utf-8").write(src)
import ast
ast.parse(io.open(P, encoding="utf-8").read())
print("audio_pl.py syntax OK")
