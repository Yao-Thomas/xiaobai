#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""patch_stream_play.py —— 修「播文件只放前 0.186 秒」的 bug

═══ Bug ═══
`_fill_ring()` 只把样本灌满**一个**播放环就返回：

    want = self.out.ring        # 65536 字节
    while len(buf) < want:
        v = samples[i % n]
        buf += struct.pack("<I", v)
    self.out.buf.write(0, bytes(buf[:want]))

65536 字节 = 8192 帧 = **0.186 秒**。
环是 DMA 循环读的，所以结果就是：**只播文件的前 0.186 秒，反复循环。**

如果那 0.186 秒是静音（前奏、淡入），听起来就完全没声音 ——
这正是 `03_小星星.wav`（RMS 3462、有内容）播出来没声的原因。

而 `play_tone` 是现场按 amp 合成整环，所以不受影响、响得吓人。

═══ 修法 ═══
新增 `_pack_stream()`：把整个文件打包成 8 字节/帧的**完整字节流**。
改写 `play_samples()`：把字节流按环大小**分块流式**写入，
每块等它该播的时长再写下块 —— 这样是连续播放整首曲子。

保留原来的 `_fill_ring()`（别的地方还在用），不动它。
"""
import io
import sys

P = "ui/audio_svc.py"
src = io.open(P, encoding="utf-8").read()

if "_pack_stream" in src:
    print("已经打过补丁，跳过")
    sys.exit(0)

# ─────────────────────── 1) 新增 _pack_stream（放在 _fill_ring 之后）
anchor = '''    def play_samples(self, samples, channels=1, rate=FS, secs=None):'''
NEWFN = '''    def _pack_stream(self, samples, channels=1, rate=FS):
        """把 int16 样本列表打包成**完整**的 8 字节/帧字节流（不截断）。

        与 _fill_ring 的区别：这个返回整个文件的字节流，供流式播放用；
        _fill_ring 只返回一个环的量（会截断，是"播 0.186 秒"bug 的根源）。
        """
        if channels == 1:
            samples = [x for x in samples for _ in (0, 1)]
        if rate != FS:
            n = len(samples)
            out_n = int(n * FS / float(rate))
            step = rate / float(FS)
            out = []
            for k in range(out_n):
                p = k * step
                i0 = int(p)
                i1 = min(i0 + 1, n - 1)
                f = p - i0
                out.append(int(samples[i0] * (1 - f) + samples[i1] * f))
            samples = out
        buf = bytearray()
        if self.out.pack == "lj":
            for v in samples:
                buf += struct.pack("<I", (v * 256) & 0xFFFFFFFF)
        else:
            for v in samples:
                buf += struct.pack("<I", (v * 256) & 0xFFFFFF)
        return bytes(buf)

'''
assert anchor in src, "play_samples 锚点没找到"
src = src.replace(anchor, NEWFN + anchor, 1)
print("  OK: 新增 _pack_stream()（整文件字节流）")

# ─────────────────────── 2) 改写 play_samples 为流式
OLD = '''    def play_samples(self, samples, channels=1, rate=FS, secs=None):
        with self.lock:
            self.busy = "play"
            try:
                es8388_set_vol(self.out.i2c, self.volume, 0)
                self._fill_ring(samples, channels, rate)
                n = len(samples) / float(rate or FS)
                dur = secs if secs else max(0.15, n)
                dur = min(dur, MAX_TONE_SECS)
                t = time.time() + dur
                while time.time() < t:
                    time.sleep(0.05)
                self.out.buf.write(0, self._silence)
                self.play_count += 1
                return dur
            finally:
                self.busy = ""
'''
NEW = '''    def play_samples(self, samples, channels=1, rate=FS, secs=None):
        """★ 流式播放整段音频（修掉了"只播前 0.186 秒"的 bug）。

        做法：把样本打包成完整的 8 字节/帧字节流，然后按播放环大小
        **分块写入**，每块等它该播的时长 —— 环是 DMA 循环读的，
        所以只要按时换块，听感就是连续的。
        """
        with self.lock:
            self.busy = "play"
            try:
                es8388_set_vol(self.out.i2c, self.volume, 0)
                pcm = self._pack_stream(samples, channels, rate)
                ring = self.out.ring
                # 每块都是整数帧，避免撕裂
                ring_frames = max(1, ring // BYTES_PER_FRAME)
                blk_bytes = ring_frames * BYTES_PER_FRAME
                total = len(pcm)
                chunk_secs = ring_frames / float(FS)

                pos = 0
                while pos < total:
                    blk = pcm[pos:pos + blk_bytes]
                    nf = len(blk) // BYTES_PER_FRAME
                    if len(blk) < blk_bytes:
                        blk = blk + b"\\x00" * (blk_bytes - len(blk))
                    self.out.buf.write(0, blk)
                    # 等这一块播完（留一点点余量，别追得太紧）
                    time.sleep(max(0.005, nf / float(FS) * 0.92))
                    pos += blk_bytes

                self.out.buf.write(0, self._silence)
                dur = total / float(BYTES_PER_FRAME * FS)
                self.play_count += 1
                return dur
            finally:
                self.busy = ""
'''
assert OLD in src, "play_samples 函数体锚点没找到"
src = src.replace(OLD, NEW, 1)
print("  OK: play_samples 改成流式分块播放")

io.open(P, "w", encoding="utf-8").write(src)
import ast
ast.parse(io.open(P, encoding="utf-8").read())
print("audio_svc.py syntax OK")
