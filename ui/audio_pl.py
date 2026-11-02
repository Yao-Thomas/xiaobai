#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audio_pl.py —— Zynq PL 音频链路「全用户态驱动」

    DDR 缓冲
      │  audio formatter MM2S (AXI master, S_AXI_HP3)
      ▼
    0x43C50000  audio_formatter        (+0x100 = MM2S 寄存器组)
      │  AXI-Stream
      ▼
    0x43C70000  AXI I2S 发送器
      │  BCLK / LRC / DACDAT
      ▼
    ES8388  I2C0 (PS) 地址 0x10  →  耳机 / 喇叭

── 为什么要全用户态 ────────────────────────────────────────────────
内核 `xlnx_snd_card` 注册失败（ASoC -517，定位到 soc-core.c 的
`soc_init_dai_link` → `soc_find_component`，见 14_音频勘验\\根因勘验报告.md）。
但 `xlnx_i2s` / `xlnx_formatter_pcm` 两个驱动 probe 成功、时钟已使能，而且
**空闲时根本不碰寄存器**（没有声卡就永远不会有 PCM 流）。所以不解绑它们，
直接从用户态操作这套寄存器 —— 解绑反而会把 aud_mclk / FCLK 的引用计数放掉。

── ★ 最关键的一个发现：把 AUD_CTRL 的位宽设成 32 位，可以绕开 AES 编码 ──
厂家的 BD 里 formatter 是 `C_MM2S_DATAFORMAT = 3`（PCM → AES）。
这在 Xilinx IP 的 HDL 里是**综合期常量**，看起来没法改……但是：

    audio_formatter_v1_0_rfs.v:5252-5255   （generate if C_MM2S_DATAFORMAT == 3）
        assign pcm_data = ... : {m_axis_tdata_mem[23:0]};
        assign m_axis_tdata = (pcm_data_width == 'd4) ? m_axis_tdata_mem
                                                      : aes_enc_data;

而 `pcm_data_width` 是**运行时寄存器字段**：

    audio_formatter_v1_0_rfs.v:2093
        pcm_data_width <= iAxi_WData[18:16];

正是 AUD_CTRL 的 [18:16]（`xlnx_formatter_pcm.c` 里写的就是这个字段）。
**所以只要把数据位宽写成 4（32 位），`m_axis_tdata` 就直接等于 DDR 里的原始
32bit 字，AES 编码器被旁路掉。** 这是纯软件就能解的，不用重新综合。

（AES 模式下 `aes_enc` 把样本塞进 tdata[27:4]：
  `out_data = {parity, cs, user, valid, in_data[23:0], preamble[3:0]}`
 —— 送到 I2S 发送器必然错位，所以必须绕开。）

── 样本在 32bit 字里怎么摆 ──────────────────────────────────────
formatter 自己的 PCM_TO_PCM 分支（HDL:5296-5299）是：
        (24bit) ? {8'd0, m_axis_tdata_mem[23:0]}
即**样本右对齐在低 24 位**，高位补 0（也就是 ALSA 的 S24_LE 语义）。
所以在 32 位位宽下我们也**右对齐**：`word = sample24 & 0xFFFFFF`。
如果 I2S 发送器其实是取 tdata[31:8]，就用 `--pack lj`（左对齐）再试一次。

── 其它踩过的坑 ────────────────────────────────────────────────
1. 读**未定义**的 PL 寄存器偏移 → AXI DECERR → ARM 报 **SIGBUS**。
   （formatter 的 0x104、i2s 的 0x18 都是坑）
2. PL 的 HP 口和 CPU cache **不相干**，喂 DMA 必须走 /dev/mem 的 noncached 别名。
3. 物理连续内存：root 读 `/proc/self/pagemap` 能拿到真实 PFN。
   （非 root 会返回 present=1 但 PFN=0；不要用"扫 1GB /dev/mem"那种办法）
4. 停 DMA 会把 `XFER_COUNT` 清零 —— 测速率必须在 stop() **之前**取。
5. ES8388 的采样率设置**不用改**：厂家 `coeff_div` 表里
   `{16934400, 44100, 384, 0x3}` 和初始化表的 `0x18=0x03` 本来就对上。
"""

from __future__ import annotations

import array
import ctypes
import math
import mmap
import os
import struct
import sys
import time

try:
    import fcntl          # 只在板子 (Linux) 上有
except ImportError:       # pragma: no cover
    fcntl = None

# ---------------------------------------------------------------- 常量

FMT_BASE = 0x43C50000          # audio formatter
I2S_BASE = 0x43C70000          # AXI I2S 发送器
I2S_RX_BASE = 0x43C60000       # AXI I2S 接收器  ★ 也必须开，见 i2s_config 说明
MM2S = 0x100                   # MM2S 寄存器组相对 formatter 基址

# formatter 寄存器（相对 FMT_BASE 的绝对偏移）
R_CORE_CFG = 0x004             # AUD_CORE_CONFIG (只读, 两路共用)
R_CTRL = MM2S + 0x10           # 0x110 AUD_CTRL
R_STS = MM2S + 0x14            # 0x114 AUD_STS
R_FS_MULT = MM2S + 0x18        # 0x118 AUD_FS_MULTIPLIER
R_PERIOD = MM2S + 0x1C         # 0x11C AUD_PERIOD_CONFIG
R_BUF_LSB = MM2S + 0x20        # 0x120 AUD_BUFF_ADDR_LSB
R_BUF_MSB = MM2S + 0x24        # 0x124 AUD_BUFF_ADDR_MSB
R_XFER = MM2S + 0x28           # 0x128 AUD_XFER_COUNT (只读, 已传字节)
R_CH_STS = MM2S + 0x2C         # 0x12C AUD_CH_STS_START
R_BYTES_PER_CH = MM2S + 0x44   # 0x144

CTRL_RESET = 1 << 1
CTRL_DMA_EN = 1 << 0
CTRL_IOC_IRQ = 1 << 13
CTRL_TOUT_IRQ = 1 << 14
CTRL_DW_SHIFT = 16             # [18:16] 数据位宽  ← 关键字段
CTRL_CH_SHIFT = 19             # [22:19] 活动声道数
STS_IOC = 1 << 31
STS_CH_STS = 1 << 29

# 位宽字段的取值（= xlnx_formatter_pcm.c 的 enum bit_depth）
BIT_DEPTH = {8: 0, 16: 1, 20: 2, 24: 3, 32: 4}

# I2S 发送器寄存器
I2S_CORE_CTRL = 0x08           # bit0 = 启动
I2S_I2STIM = 0x20              # SCLKOUT 分频 (低 8 位)
I2S_CH0 = 0x30                 # 0x30 + (n-1)*4 = 声道号

# 音频参数（由 MCLK = 16.9344 MHz 反推）
FS = 44100
MCLK = 16934400
MCLK_RATIO = 384               # MCLK / fs
SAMPLE_BITS = 24               # I2S IP 的 xlnx,dwidth=24
CHANNELS = 2
I2S_DIV = (MCLK_RATIO + 2 * CHANNELS * SAMPLE_BITS - 1) // (
    2 * CHANNELS * SAMPLE_BITS)          # ceil(384/96) = 4
BYTES_PER_FRAME = 8            # 2ch × 32bit 容器

# 默认：位宽字段写 32 位（旁路 AES 编码器），样本右对齐
DEFAULT_DW = 32
DEFAULT_PACK = "rj"

# ES8388
I2C_BUS = 1
I2C_ADDR = 0x10
I2C_SLAVE = 0x0703
PAGE = 4096


# ---------------------------------------------------------------- /dev/mem

class Mem:
    """进程内共享的 /dev/mem 映射（只碰白名单偏移）"""

    def __init__(self):
        self.fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
        self._maps = {}

    def _win(self, base):
        m = self._maps.get(base)
        if m is None:
            m = mmap.mmap(self.fd, PAGE, mmap.MAP_SHARED,
                          mmap.PROT_READ | mmap.PROT_WRITE, offset=base)
            self._maps[base] = m
        return m

    def rd(self, base, off):
        return struct.unpack("<I", self._win(base)[off:off + 4])[0]

    def wr(self, base, off, val):
        self._win(base)[off:off + 4] = struct.pack("<I", val & 0xFFFFFFFF)

    def close(self):
        for m in self._maps.values():
            m.close()
        self._maps.clear()
        os.close(self.fd)


# ---------------------------------------------------------------- I2C

class I2C:
    def __init__(self, bus=I2C_BUS, addr=I2C_ADDR):
        self.fd = os.open("/dev/i2c-%d" % bus, os.O_RDWR)
        fcntl.ioctl(self.fd, I2C_SLAVE, addr)
        self.addr = addr

    def wr(self, reg, val):
        os.write(self.fd, bytes([reg & 0xFF, val & 0xFF]))

    def rd(self, reg):
        os.write(self.fd, bytes([reg & 0xFF]))
        return os.read(self.fd, 1)[0]

    def close(self):
        os.close(self.fd)


# 厂家《Linux驱动例程/28_codec/es8388.c》的初始化表, 顺序不能改。
# ★ 采样率那两位**本来就是给 16.9344MHz 用的**:
#   同一份代码的 coeff_div 表有 {16934400, 44100, 384, 0x3, 0x0},
#   而 0x18 写的正好是 0x03（384FS 的码值）。
ES8388_INIT = [
    (0x00, 0x80),   # 复位
    (0x00, 0x00),
    (0x01, 0x58),   # 模拟电源关
    (0x01, 0x50),
    (0x02, 0xF3),   # 电源管理
    (0x02, 0x00),
    (0x03, 0x09),   # ADC 电源
    (0x00, 0x06),   # 参考电压 500K
    (0x04, 0x3C),   # DAC 电源开
    (0x08, 0x00),   # ★ 从机模式, MCLK 不分频
    (0x09, 0x66),   # ADC PGA
    (0x0A, 0x50),
    (0x0C, 0x00),
    (0x0D, 0x0C),   # ADC MCLK/fs
    (0x10, 0x00),
    (0x11, 0x00),
    (0x12, 0xC0),
    (0x17, 0x00),
    (0x18, 0x03),   # ★ DAC MCLK/fs = 384
    (0x1A, 0x48),
    (0x1B, 0x48),
    (0x1D, 0x1C),
    (0x27, 0xF8),
    (0x2A, 0xF8),
    (0x2B, 0x80),   # DACLRC/ADCLRC 共用
    (0x2E, 0x20),
    (0x2F, 0x20),
    (0x30, 0x20),
    (0x31, 0x20),
    (0x19, 0x02),
    (0x30, 0x1B),   # LOUT2 音量
    (0x31, 0x1B),   # ROUT2 音量
    (0x07, 0x7C),
    (0x05, 0x00),
    (0x06, 0x00),
    (0x02, 0x00),   # 上电
    (0x03, 0x59),
    # ★★ 这两行是厂家表里**没有**的，但必须补上 —— 见 es8388_set_vol 的说明：
    #   DAC 数字音量 (R26/R27) 是反的（0x00=0dB最大, 0xC0=-96dB静音），
    #   厂家表写的 0x48 只有 -36dB，他们手册里跑测试前会
    #   `amixer sset Playback 192,192` 把它覆盖成 0x00。不补就是"什么都没声音"。
    (0x1A, 0x00),   # DAC 数字音量 L = 0 dB
    (0x1B, 0x00),   # DAC 数字音量 R = 0 dB
]


def es8388_init(i2c):
    # ★ 最后两行 (0x1A/0x1B = 0x00) 是关键：
    #   厂家表里写的是 0x48(=-36dB)，他们手册里跑测试前会补一条
    #   `amixer sset Playback 192,192` 覆盖成 0x00(0dB)。我们直接写进表里。
    for reg, val in ES8388_INIT:
        i2c.wr(reg, val)


def es8388_set_vol(i2c, v=27, dac_digital=0):
    """输出音量。

    v             : 0..33, 33 = 最大(+4.5dB), 0 = 最小(-45dB)
                    厂家 `out_tlv = DECLARE_TLV_DB_SCALE(-4500, 150, 0)` —— 是「0 最小」,
                    跟一般 codec 反着来, 别搞错。
                    0x2E/0x2F = Output1(L/R, 走耳机), 0x30/0x31 = Output2(L/R, 走喇叭功放)
    dac_digital   : DAC 数字音量寄存器值, 0..0xC0。

    ★★ 这是之前"什么都没声音"的根因 ★★
        ES8388 的 DAC 数字音量 (0x1A/0x1B) **是反的**:
            0x00 = 0 dB(最大)   0xC0 = -96 dB(最小/静音)
        依据是厂家驱动里:
            SOC_DOUBLE_R_TLV("Playback Volume", ES8388_DACCONTROL4,
                             ES8388_DACCONTROL5, 0, 192, 1/*xinvert*/, dac_tlv)
        xinvert=1 -> 寄存器值 = 192 - ALSA值, ALSA 192(最大) 对应寄存器 0。
        而 ES8388 复位默认就是 0xC0(静音)。

        厂家初始化表把 0x1A/0x1B 写成 0x48 (= ALSA 120 = -36dB), 然后
        **在他们手册的喇叭/耳机测试步骤里补了一条**:
            amixer sset Playback 192,192        # R26/R27 写 0x00
        我们照抄了初始化表却漏了这个覆盖 -> 一直在 -36dB 上跑, 基本听不见。
    """
    v = max(0, min(33, int(v)))
    for r in (0x2E, 0x2F, 0x30, 0x31):
        i2c.wr(r, v)
    # DAC 数字音量顶满（0 = 最大）
    dac_digital = max(0, min(0xC0, int(dac_digital)))
    i2c.wr(0x1A, dac_digital)
    i2c.wr(0x1B, dac_digital)
    return v


def es8388_dump(i2c):
    return {r: i2c.rd(r) for r in sorted({r for r, _ in ES8388_INIT})}


def es8388_verify(i2c, verbose=True):
    """回读初始化表, 返回不一致的寄存器列表"""
    bad = []
    for reg in sorted({r for r, _ in ES8388_INIT}):
        last = [v for r, v in ES8388_INIT if r == reg][-1]
        got = i2c.rd(reg)
        if got != last:
            bad.append((reg, last, got))
    if verbose:
        if bad:
            print("[codec] !! 回读不一致: %s"
                  % ", ".join("0x%02X 期望 0x%02X 实际 0x%02X" % b for b in bad))
        else:
            print("[codec] 回读校验通过: %d 个寄存器全部与初始化表一致"
                  % len({r for r, _ in ES8388_INIT}))
    return bad


# ------------------------------------------------- 物理连续的 DMA 缓冲

def _pfns_of(va, npages, pagemap="/proc/self/pagemap"):
    """一次 pread 读完整段 pagemap, 返回 PFN 列表（无效页为 0）"""
    base = (va // PAGE) * 8
    fd = os.open(pagemap, os.O_RDONLY)
    try:
        raw = os.pread(fd, npages * 8, base)
    finally:
        os.close(fd)
    out = []
    for i in range(min(npages, len(raw) // 8)):
        e = struct.unpack_from("<Q", raw, i * 8)[0]
        out.append((e & ((1 << 55) - 1)) if (e >> 63) & 1 else 0)
    out += [0] * (npages - len(out))
    return out


def _longest_run(pfns):
    best = (0, 0, 0)
    i, n = 0, len(pfns)
    while i < n:
        if not pfns[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and pfns[j + 1] == pfns[j] + 1:
            j += 1
        if j - i + 1 > best[0]:
            best = (j - i + 1, i, j)
        i = j + 1
    return best


def reserve_contig(need_bytes, pool_bytes=None, verbose=True, tries=8):
    """预留一块**物理连续**的 DDR, 返回 (phys, avail, anon_mmap, 起始页号)。

    ★ 实测踩过的坑：DDR 会越来越碎片化，一次分配失败就抛异常的话，
      常驻服务会陷入 systemd 重启循环（见过 restart counter = 14）。
      所以这里**失败就加大池子重试** —— 池子越大，里面出现一条长连续段的概率越高。
    """
    need_pages = max(2, (need_bytes + PAGE - 1) // PAGE)
    base = pool_bytes if pool_bytes else (8 << 20)
    base = max(base, need_pages * PAGE * 2)

    last = (0, 0)
    for attempt in range(tries):
        pb = base * (2 ** attempt)
        pb = min(pb, 512 << 20)                  # 最多 512MB
        pb = ((pb + PAGE - 1) // PAGE) * PAGE
        npages = pb // PAGE
        try:
            buf = mmap.mmap(-1, pb, mmap.MAP_PRIVATE | mmap.MAP_ANONYMOUS)
        except Exception as e:
            if verbose:
                print("[dma] 池 %dMB 映射失败: %s" % (pb >> 20, e))
            continue
        for i in range(npages):                  # 一页一页触碰, 把物理页要下来
            buf[i * PAGE] = i & 0xFF
        pfns = _pfns_of(ctypes.addressof(ctypes.c_char.from_buffer(buf)), npages)
        run, i, j = _longest_run(pfns)
        if verbose:
            print("[dma] 第%d次 池 %d 页(%dMB), 最长连续 = %d 页 (%.1f KB) @ 0x%08X"
                  % (attempt + 1, npages, pb >> 20, run, run * PAGE / 1024.0,
                     (pfns[i] * PAGE) if run else 0))
        if run >= need_pages:
            return pfns[i] * PAGE, run * PAGE, buf, i
        last = (run, npages)
        buf.close()                              # 放掉，下次用更大的池子再来
    raise RuntimeError("试了 %d 次都拿不到 %d 页连续内存（最好一次 %d/%d 页）。"
                       "重启板子即可，或减少请求量" % (tries, need_pages, last[0], last[1]))


class DmaBuffer:
    """物理连续缓冲: 匿名映射留位 + /dev/mem noncached 别名读写"""

    def __init__(self, want_bytes, verbose=True):
        self.phys, self.avail, self._anon, _ = reserve_contig(
            want_bytes, verbose=verbose)
        fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
        try:
            self.mem = mmap.mmap(fd, self.avail, mmap.MAP_SHARED,
                                 mmap.PROT_READ | mmap.PROT_WRITE,
                                 offset=self.phys)
        finally:
            os.close(fd)

    def write(self, off, data):
        assert off + len(data) <= self.avail, "音频缓冲越界"
        self.mem[off:off + len(data)] = data

    def read(self, off, n):
        return self.mem[off:off + n]

    def close(self):
        self.mem.close()
        self._anon.close()


# ---------------------------------------------------------------- AudioOut

# ★ R_PERIOD 的字段上限（低16位=period_bytes，高16位=periods）
PERIOD_MAX_BYTES = 16384          # period_bytes 必须 <= 65535，这里保守取 16384
PERIODS_MAX = 4096                # periods 上限（高16位字段够放，但别太夸张）


class AudioOut:
    """把 PCM 字节流喂给 audio formatter -> I2S -> ES8388"""

    def __init__(self, period_bytes=None, periods=4, dw=DEFAULT_DW,
                 pack=DEFAULT_PACK, verbose=True):
        self.verbose = verbose
        self.dw = int(dw)
        self.pack = pack
        self.mem = Mem()
        self.i2c = I2C()
        # ★ 播放缓冲大小（2026-09-28 改）
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
        self.periods = max(1, min(want_periods, PERIODS_MAX))
        self.ring = period_bytes * self.periods
        assert self.ring <= self.buf.avail
        assert self.periods <= PERIODS_MAX and period_bytes <= PERIOD_MAX_BYTES

        self.playing = False
        self._prev = None
        self._total = 0
        self.t0 = time.time()

        cfg = self._r(R_CORE_CFG)
        self.core_cfg = cfg
        self.mode = (cfg & (3 << 13)) >> 13
        self.interleaved = not (cfg & (1 << 12))
        self.ch_limit = (cfg >> 8) & 0xF
        if verbose:
            print("[fmt] CORE_CONFIG=0x%08X MM2S=%s S2MM=%s mode=%d(%s) "
                  "interleaved=%s ch_limit=%d"
                  % (cfg, bool(cfg & (1 << 15)), bool(cfg & (1 << 31)),
                     self.mode,
                     {0: "AES->AES", 1: "AES->PCM", 2: "PCM->PCM",
                      3: "PCM->AES"}.get(self.mode, "?"),
                     self.interleaved, self.ch_limit))
            print("[cfg] 位宽字段=%d(%dbit)  样本摆放=%s  "
                  "(位宽写 32 可以旁路 AES 编码器)"
                  % (BIT_DEPTH[self.dw], self.dw, self.pack))
            print("[dma] ring=%d B (%d 周期 x %d B) @ 物理 0x%08X (可用 %d B)"
                  % (self.ring, periods, period_bytes, self.buf.phys,
                     self.buf.avail))

    # --- 寄存器 ---
    def _r(self, off):
        return self.mem.rd(FMT_BASE, off)

    def _w(self, off, val):
        self.mem.wr(FMT_BASE, off, val)

    def _i2s_r(self, off):
        return self.mem.rd(I2S_BASE, off)

    def _i2s_w(self, off, val):
        self.mem.wr(I2S_BASE, off, val)

    def _rx_r(self, off):
        return self.mem.rd(I2S_RX_BASE, off)

    def _rx_w(self, off, val):
        self.mem.wr(I2S_RX_BASE, off, val)

    # --- 初始化 ---
    def codec_up(self):
        es8388_init(self.i2c)
        if self.verbose:
            print("[codec] ES8388 初始化完成")

    def codec_vol(self, v=27):
        return es8388_set_vol(self.i2c, v)

    def i2s_config(self):
        """配置两个 I2S IP。

        ★★★ 为什么**接收器也必须开** —— 这是"速率完全正确却一点声音都没有"的根因 ★★★

        厂家 BD 里的连线（`Navigator_7020.gen/sources_1/bd/system/synth/system.v`
        第 504-576 行）：

            system_i2s_receiver_0    .lrclk_out(aud_adclrc)      // → 板子 AUD_ADCLRC = L20
            system_i2s_transmitter_0 .lrclk_out(aud_daclrc)      // → 板子 AUD_DACLRC = G18
            system_util_vector_logic_0 .Op1(i2s_transmitter_sclk_out)
                                       .Op2(i2s_receiver_sclk_out)
                                       .Res(aud_bclk)            // = 两个 sclk 相与

        而底板原理图上，**ES8388 的 LRCK(pin 7) 接的是 AUD_ADCLRC**，也就是
        **接收器**的 lrclk_out（V3.8 换 ES8388 时改了线，AUD_DACLRC 空着）。

        所以：
          * BCLK  = AND(发送器 sclk, 接收器 sclk)  —— 接收器不开，BCLK 恒为 0
          * LRCK  = 接收器的 lrclk_out           —— 接收器不开，LRCK 恒为 0
          * 发送器**内部**的 sclk 是活的，所以 AXI-Stream 照样按 44100 帧/s 消费数据
            → 表现出来就是"DMA 速率 1.0000 完美，但耳机/喇叭一点声音没有"

        结论：两个 IP 都要写 CORE_CTRL=1，而且分频要一致（同一个 MCLK、同一个值）。
        """
        # ---- 发送器 ----
        self._i2s_w(I2S_CORE_CTRL, 0)
        self._i2s_w(I2S_I2STIM, I2S_DIV)
        self._i2s_w(I2S_CH0, 1)
        # ---- 接收器（BCLK 与 codec 的 LRCK 都由它提供）----
        self._rx_w(I2S_CORE_CTRL, 0)
        self._rx_w(I2S_I2STIM, I2S_DIV)
        self._rx_w(I2S_CH0, 1)
        if self.verbose:
            print("[i2s] 发送器+接收器都配上: div=%d core_ctrl=0 ch0=1 两路" % I2S_DIV)

    def fmt_config(self):
        self._w(R_CTRL, self._r(R_CTRL) | CTRL_RESET)
        ok = False
        for _ in range(200):
            if not (self._r(R_CTRL) & CTRL_RESET):
                ok = True
                break
            time.sleep(0.001)
        if not ok:
            raise RuntimeError("audio formatter 复位超时")

        ctrl = self._r(R_CTRL)
        ctrl &= ~(0x7 << CTRL_DW_SHIFT)
        ctrl |= BIT_DEPTH[self.dw] << CTRL_DW_SHIFT
        ctrl &= ~(0xF << CTRL_CH_SHIFT)
        ctrl |= CHANNELS << CTRL_CH_SHIFT
        ctrl &= ~(CTRL_DMA_EN | CTRL_IOC_IRQ | CTRL_TOUT_IRQ)
        self._w(R_CTRL, ctrl)

        self._w(R_FS_MULT, MCLK_RATIO)
        self._w(R_PERIOD, (self.periods << 16) | self.period_bytes)
        self._w(R_BYTES_PER_CH, self.period_bytes // CHANNELS)
        self._w(R_BUF_LSB, self.buf.phys & 0xFFFFFFFF)
        self._w(R_BUF_MSB, (self.buf.phys >> 32) & 0xFFFFFFFF)
        self._w(R_STS, STS_IOC | STS_CH_STS)
        if self.verbose:
            print("[fmt] CTRL=0x%08X (位宽字段=%d) FS_MULT=%d PERIOD=0x%08X "
                  "BYTES_PER_CH=%d"
                  % (ctrl, (ctrl >> CTRL_DW_SHIFT) & 0x7, MCLK_RATIO,
                     (self.periods << 16) | self.period_bytes,
                     self.period_bytes // CHANNELS))

    def start(self):
        # ★ 接收器必须先起：BCLK = AND(两个 sclk)，codec 的 LRCK 也来自接收器
        self._rx_w(I2S_CORE_CTRL, 1)
        self._i2s_w(I2S_CORE_CTRL, 1)
        self._w(R_CTRL, self._r(R_CTRL) | CTRL_DMA_EN)
        self.playing = True
        self._prev = self._r(R_XFER)
        self._total = 0
        self.t0 = time.time()

    def stop(self):
        self._w(R_CTRL, self._r(R_CTRL) & ~CTRL_DMA_EN)
        self._i2s_w(I2S_CORE_CTRL, 0)
        self._rx_w(I2S_CORE_CTRL, 0)
        self.playing = False

    # --- 进度 ---
    def raw_xfer(self):
        return self._r(R_XFER)

    def poll_pos(self):
        """返回 (环形位置, 累计字节)。XFER_COUNT 到 ring 大小回绕。"""
        x = self._r(R_XFER)
        if self._prev is None:
            self._prev = x
            return x % self.ring, self._total
        d = x - self._prev
        if d < 0:
            d += self.ring
        if d > self.ring:
            d = 0
        self._total += d
        self._prev = x
        return x % self.ring, self._total

    def close(self):
        for fn in (self.stop, self.i2c.close, self.buf.close, self.mem.close):
            try:
                fn()
            except Exception:
                pass


# ---------------------------------------------------------------- AudioIn

# S2MM（录音）寄存器都在 formatter 基址的**偏移 0**（MM2S 是 +0x100）
R2_CTRL = 0x10
R2_STS = 0x14
R2_FS_MULT = 0x18
R2_PERIOD = 0x1C
R2_BUF_LSB = 0x20
R2_BUF_MSB = 0x24
R2_XFER = 0x28
R2_BYTES_PER_CH = 0x44

# ES8388 的 ADC 输入选择（寄存器 0x0A）
ADC_IN = {
    "lin1": 0x00,     # LIN1/RIN1 —— 板子上的**麦克风**接在这里
    "mic1": 0x05,     # MIC1（带内部偏置）
    "mic2": 0x06,
    "line": 0x50,     # LIN2/RIN2 —— 板子上的 LINE_IN 插孔（厂家默认值）
    "diff": 0xF0,
}


class AudioIn:
    """录音：ES8388 ADC → AXI I2S 接收器 → audio formatter S2MM → DDR

    ★ 和放音一样，S2MM 的 `C_S2MM_DATAFORMAT = 1`（AES→PCM），会在写内存前
      跑一个 `aes_dec`。同一个套路把它旁路掉：**位宽字段写 32**，
      HDL 里（rfs.v:2577-2580）

          assign m_axis_tdata_dm = ... (pcm_data_width == 'd4) ? m_axis_tdata : ...

      写 32 时内存里拿到的就是 I2S 接收器送来的原始 32bit 字。

    ★ 另一个关键：**I2S 接收器既是录音的数据源，又是 BCLK 和 codec LRCK 的来源**
      （见 AudioOut.i2s_config 的说明），所以录音本来就得开它。
    """

    def __init__(self, period_bytes=8192, periods=4, dw=32, verbose=True):
        self.verbose = verbose
        self.dw = int(dw)
        self.mem = Mem()
        self.i2c = I2C()
        self.buf = DmaBuffer(64 << 10, verbose=verbose)
        if period_bytes is None:
            period_bytes = 8192
        self.periods = periods
        self.period_bytes = period_bytes
        self.ring = period_bytes * periods
        assert self.ring <= self.buf.avail
        self.playing = False
        self._prev = None
        self._total = 0
        cfg = self.mem.rd(FMT_BASE, R_CORE_CFG)
        self.core_cfg = cfg
        self.mode = (cfg & (3 << 29)) >> 29          # S2MM 传输模式 bits[30:29]
        self.ch_limit = (cfg >> 24) & 0xF
        if verbose:
            print("[rec] CORE_CONFIG=0x%08X S2MM=%s mode=%d(%s) ch_limit=%d"
                  % (cfg, bool(cfg & (1 << 31)), self.mode,
                     {0: "AES->AES", 1: "AES->PCM", 2: "PCM->PCM"}.get(
                         self.mode, "?"), self.ch_limit))
            print("[rec] ring=%d B @ 物理 0x%08X (可用 %d B)"
                  % (self.ring, self.buf.phys, self.buf.avail))

    # ---- 寄存器 ----
    def _r(self, off):
        return self.mem.rd(FMT_BASE, off)

    def _w(self, off, val):
        self.mem.wr(FMT_BASE, off, val)

    # ---- codec 的 ADC 那一半 ----
    def codec_adc_up(self, adc_in="lin1", pga=0x66):
        """给 ES8388 的 ADC 上电并选输入。

        adc_in : ADC_IN 里的键（默认 lin1 = 板载麦克风）
        pga    : 0x09，bit[6:4]=左 PGA，bit[2:0]=右 PGA，单位 3dB（0x66 = +18dB）
        """
        sel = ADC_IN.get(adc_in, 0x00)
        i2c = self.i2c
        i2c.wr(0x08, 0x00)      # 从机模式
        i2c.wr(0x00, 0x06)      # 参考 500K
        i2c.wr(0x01, 0x50)      # 模拟电源开
        i2c.wr(0x02, 0x00)      # 全部上电
        i2c.wr(0x03, 0x59)      # ★ ADC 上电（含 mic bias）
        i2c.wr(0x09, pga)       # ADC PGA
        i2c.wr(0x0A, sel)       # ★ ADC 输入选择
        i2c.wr(0x0B, 0x02)      # ADC 高通/去直流
        i2c.wr(0x0C, 0x00)      # ADC 数据格式 = I2S, 24bit
        i2c.wr(0x0D, 0x0C)      # ADC MCLK/fs
        i2c.wr(0x10, 0x00)      # ★ ADC 数字音量 L（同样是反的：0 = 0dB 最大）
        i2c.wr(0x11, 0x00)      # ★ ADC 数字音量 R
        if self.verbose:
            print("[rec] ADC 输入=%s(0x%02X) PGA=0x%02X  "
                  "0x03=0x%02X 0x0A=0x%02X 0x10/0x11=%02X/%02X"
                  % (adc_in, sel, pga, i2c.rd(0x03), i2c.rd(0x0A),
                     i2c.rd(0x10), i2c.rd(0x11)))

    # ---- I2S 接收器 ----
    def i2s_config(self):
        # 接收器：既是数据源，又提供 BCLK 和 codec 的 LRCK
        self.mem.wr(I2S_RX_BASE, I2S_CORE_CTRL, 0)
        self.mem.wr(I2S_RX_BASE, I2S_I2STIM, I2S_DIV)
        self.mem.wr(I2S_RX_BASE, I2S_CH0, 1)
        # 发送器也要配上：BCLK = AND(两个 sclk)，它不动 BCLK 就是死的
        self.mem.wr(I2S_BASE, I2S_CORE_CTRL, 0)
        self.mem.wr(I2S_BASE, I2S_I2STIM, I2S_DIV)
        self.mem.wr(I2S_BASE, I2S_CH0, 1)
        if self.verbose:
            print("[rec] I2S 收发都配上 (div=%d)，BCLK 才是活的" % I2S_DIV)

    def fmt_config(self):
        # 复位 S2MM
        self._w(R2_CTRL, self._r(R2_CTRL) | CTRL_RESET)
        ok = False
        for _ in range(200):
            if not (self._r(R2_CTRL) & CTRL_RESET):
                ok = True
                break
            time.sleep(0.001)
        if not ok:
            raise RuntimeError("S2MM 复位超时")
        ctrl = self._r(R2_CTRL)
        ctrl &= ~(0x7 << CTRL_DW_SHIFT)
        ctrl |= BIT_DEPTH[self.dw] << CTRL_DW_SHIFT      # ★ 32 位 = 旁路 aes_dec
        ctrl &= ~(0xF << CTRL_CH_SHIFT)
        ctrl |= CHANNELS << CTRL_CH_SHIFT
        ctrl &= ~(CTRL_DMA_EN | CTRL_IOC_IRQ | CTRL_TOUT_IRQ)
        self._w(R2_CTRL, ctrl)
        self._w(R2_FS_MULT, MCLK_RATIO)
        self._w(R2_PERIOD, (self.periods << 16) | self.period_bytes)
        self._w(R2_BYTES_PER_CH, self.period_bytes // CHANNELS)
        self._w(R2_BUF_LSB, self.buf.phys & 0xFFFFFFFF)
        self._w(R2_BUF_MSB, (self.buf.phys >> 32) & 0xFFFFFFFF)
        self._w(R2_STS, STS_IOC | STS_CH_STS)
        if self.verbose:
            print("[rec] S2MM CTRL=0x%08X (位宽=%d) PERIOD=0x%08X BUF=0x%08X"
                  % (ctrl, (ctrl >> CTRL_DW_SHIFT) & 0x7,
                     (self.periods << 16) | self.period_bytes, self.buf.phys))

    def start(self):
        self.mem.wr(I2S_RX_BASE, I2S_CORE_CTRL, 1)       # 接收器先起
        self.mem.wr(I2S_BASE, I2S_CORE_CTRL, 1)
        self._w(R2_CTRL, self._r(R2_CTRL) | CTRL_DMA_EN)
        self.playing = True
        self._prev = self._r(R2_XFER)
        self._total = 0
        self.t0 = time.time()

    def stop(self):
        self._w(R2_CTRL, self._r(R2_CTRL) & ~CTRL_DMA_EN)
        self.mem.wr(I2S_RX_BASE, I2S_CORE_CTRL, 0)
        self.mem.wr(I2S_BASE, I2S_CORE_CTRL, 0)
        self.playing = False

    def raw_xfer(self):
        return self._r(R2_XFER)

    def poll_pos(self):
        x = self._r(R2_XFER)
        if self._prev is None:
            self._prev = x
            return x % self.ring, self._total
        d = x - self._prev
        if d < 0:
            d += self.ring
        if d > self.ring:
            d = 0
        self._total += d
        self._prev = x
        return x % self.ring, self._total

    def read_ring(self):
        """把整个环形缓冲读出来（按 DMA 写指针切成正确的顺序）"""
        pos, _ = self.poll_pos()
        return self.buf.read(pos, self.ring - pos) + self.buf.read(0, pos)

    def close(self):
        for fn in (self.stop, self.i2c.close, self.buf.close, self.mem.close):
            try:
                fn()
            except Exception:
                pass


# ---------------------------------------------------------------- 音频数据


def pack_sample(s, pack=DEFAULT_PACK):
    """把 -8388608..8388607 的 24bit 样本摆进 32bit 字。

    rj = 右对齐在低 24 位（formatter 自己 PCM_TO_PCM 分支的约定 / ALSA S24_LE）
    lj = 左对齐在高 24 位（I2S 发送器若取 tdata[31:8] 时用）
    """
    s &= 0xFFFFFF
    if pack == "lj":
        return (s << 8) & 0xFFFFFFFF
    return s


def make_sine(freq=1000.0, frames=1024, fs=FS, amp=0.35, pack=DEFAULT_PACK):
    """生成 24bit 立体声 PCM（32bit 容器，按 pack 摆放）"""
    peak = int(amp * 8388607)
    out = array.array("I")
    assert out.itemsize == 4
    for i in range(frames):
        v = int(peak * math.sin(2 * math.pi * freq * i / fs))
        s = pack_sample(v, pack)
        out.append(s)
        out.append(s)
    return out.tobytes()


def make_silence(frames=1024):
    return b"\x00" * (frames * BYTES_PER_FRAME)


# ---------------------------------------------------------------- 播放

def play_tone(a, freq, seconds, vol=None, amp=0.35):
    """在已配置好的 AudioOut 上播一个单音，返回实测帧率"""
    if vol is not None:
        a.codec_vol(vol)
    pb = a.period_bytes
    tone = make_sine(freq, frames=pb // BYTES_PER_FRAME, pack=a.pack, amp=amp)
    assert len(tone) == pb
    a.buf.write(0, (tone * (a.periods + 1))[:a.ring])
    a.start()
    t_end = time.time() + seconds
    while time.time() < t_end:
        a.poll_pos()
        time.sleep(0.002)
    _, tot = a.poll_pos()          # ★ 必须在 stop() 之前取
    dt = time.time() - a.t0
    a.stop()
    time.sleep(0.02)
    return tot / dt / BYTES_PER_FRAME if dt else 0.0


def selftest(seconds=3.0, freq=1000.0, vol=27, dw=DEFAULT_DW,
             pack=DEFAULT_PACK):
    a = AudioOut(dw=dw, pack=pack)
    try:
        a.codec_up()
        es8388_verify(a.i2c)
        print("[codec] 输出音量 = %d/33" % a.codec_vol(vol))
        a.i2s_config()
        a.fmt_config()
        print("[test] 播放 %.1f kHz 正弦 %.1f 秒 ..." % (freq / 1000.0, seconds))
        fps = play_tone(a, freq, seconds)
        print("[test] 实测 %.1f 帧/s，期望 %d 帧/s，比值 %.4f"
              % (fps, FS, fps / FS))
        return fps
    finally:
        a.close()


def play_motif(vol=27, dw=DEFAULT_DW, pack=DEFAULT_PACK):
    """播 C-E-G-C 四个音（听得出来就说明数据是对的）"""
    a = AudioOut(dw=dw, pack=pack)
    try:
        a.codec_up()
        a.codec_vol(vol)
        a.i2s_config()
        a.fmt_config()
        for f, d in ((523, 0.55), (659, 0.55), (784, 0.55), (1047, 1.2)):
            fps = play_tone(a, float(f), d)
            print("   %5.0f Hz  %.2fs  实测 %.1f 帧/s (%.4f x fs)"
                  % (f, d, fps, fps / FS))
        return True
    finally:
        a.close()


def wav_open(path):
    """打开一个 WAV，返回 (info, fetch)。

    info = dict(nch, sw, sr, nfr)
    fetch(i) -> (l, r)，24bit 有符号（-8388608..8388607），单声道会自动复制
    支持 8/16/24/32bit、1/2 声道。只用标准库，板子上不用装东西。
    """
    import wave
    with wave.open(path, "rb") as w:
        nch, sw, sr, nfr = (w.getnchannels(), w.getsampwidth(),
                            w.getframerate(), w.getnframes())
    if nch not in (1, 2):
        raise ValueError("只支持 1 或 2 声道，这个文件是 %d 声道" % nch)
    if sw not in (1, 2, 3, 4):
        raise ValueError("不支持 %d 字节采样（8/16/24/32bit 才行）" % sw)

    raw = open(path, "rb").read()
    # 正经找 data chunk（不要盲信 44 字节偏移）
    p = 12
    data = b""
    while p + 8 <= len(raw):
        cid = raw[p:p + 4]
        sz = struct.unpack_from("<I", raw, p + 4)[0]
        if cid == b"data":
            data = raw[p + 8:p + 8 + sz]
            break
        p += 8 + sz + (sz & 1)
    if not data:
        data = raw[44:]

    frame_bytes = sw * nch
    n = min(nfr or (len(data) // frame_bytes), len(data) // frame_bytes)

    def fetch(i):
        if i < 0 or i >= n:
            return 0, 0
        o = i * frame_bytes
        if sw == 1:                       # 8bit 无符号
            l = (data[o] - 128) << 16
            r = l if nch == 1 else (data[o + 1] - 128) << 16
        elif sw == 2:                     # 16bit
            l = struct.unpack_from("<h", data, o)[0] << 8
            r = l if nch == 1 else struct.unpack_from("<h", data, o + 2)[0] << 8
        elif sw == 3:                     # 24bit
            v = data[o] | (data[o + 1] << 8) | (data[o + 2] << 16)
            l = v - (1 << 24) if v & 0x800000 else v
            if nch == 1:
                r = l
            else:
                v = (data[o + 3] | (data[o + 4] << 8) | (data[o + 5] << 16))
                r = v - (1 << 24) if v & 0x800000 else v
        else:                             # 32bit
            l = struct.unpack_from("<i", data, o)[0] >> 8
            r = l if nch == 1 else struct.unpack_from("<i", data, o + 4)[0] >> 8
        return l, r

    return dict(nch=nch, sw=sw, sr=sr, nfr=n, bytes=len(data)), fetch


def play_file(path, vol=27, dw=DEFAULT_DW, pack=DEFAULT_PACK, max_sec=0):
    """播一个音频文件。WAV 直接播；其它格式（mp3 等）有 ffmpeg 就转一下。"""
    head = b""
    try:
        with open(path, "rb") as f:
            head = f.read(12)
    except Exception as e:
        print("[play] 打不开 %s: %s" % (path, e))
        return False

    tmp = None
    if head[:4] != b"RIFF":
        import shutil
        import subprocess
        import tempfile
        ff = shutil.which("ffmpeg")
        if not ff:
            print("[play] %s 不是 WAV，而且板子上没有 ffmpeg。" % path)
            print("       先转一下：ffmpeg -i in.mp3 -ac 2 -ar 44100 out.wav")
            return False
        tmp = os.path.join(tempfile.gettempdir(), "_play_tmp.wav")
        print("[play] 用 ffmpeg 转成 WAV ...")
        r = subprocess.run([ff, "-y", "-loglevel", "error", "-i", path,
                            "-ac", "2", "-ar", str(FS), "-acodec", "pcm_s16le",
                            tmp], stdout=subprocess.DEVNULL,
                           stderr=subprocess.PIPE)
        if r.returncode != 0:
            print("[play] ffmpeg 失败: %s"
                  % (r.stderr or b"").decode("utf-8", "replace")[:300])
            return False
        path = tmp
    try:
        return _play_wav(path, vol, dw, pack, max_sec)
    finally:
        if tmp and os.path.exists(tmp):
            try:
                os.remove(tmp)
            except Exception:
                pass


def _play_wav(path, vol=27, dw=DEFAULT_DW, pack=DEFAULT_PACK, max_sec=0):
    info, fetch = wav_open(path)
    nch, sw, sr, nfr = info["nch"], info["sw"], info["sr"], info["nfr"]
    print("[wav] %s  %dch %dbit %dHz %d 帧 (%.1fs)"
          % (os.path.basename(path), nch, sw * 8, sr, nfr,
             nfr / float(sr or 1)))
    if sr != FS:
        print("[wav] 采样率 %d != %d，做线性插值重采样" % (sr, FS))

    a = AudioOut(dw=dw, pack=pack)
    try:
        a.codec_up()
        a.codec_vol(vol)
        a.i2s_config()
        a.fmt_config()
        pb = a.period_bytes
        fpp = pb // BYTES_PER_FRAME                 # 每个周期几帧
        step = sr / float(FS)
        total = int(nfr * FS / float(sr))
        if max_sec:
            total = min(total, int(max_sec * FS))

        # 先灌满一个环，避免一上来就 underrun
        def gen(start_frame, count):
            out = array.array("I")
            for k in range(count):
                i = start_frame + k
                if i >= total:
                    out.append(0); out.append(0)
                    continue
                l, r = fetch(int(i * step))
                out.append(pack_sample(l, pack))
                out.append(pack_sample(r, pack))
            return out.tobytes()

        blob = gen(0, fpp * a.periods)
        a.buf.write(0, blob[:a.ring])
        print("[wav] 开始播放 ...")
        a.start()
        w_abs = a.ring
        total_bytes = total * BYTES_PER_FRAME
        t0 = time.time()
        last = t0
        while True:
            _, read_abs = a.poll_pos()
            if read_abs >= total_bytes:
                break
            while w_abs < total_bytes and w_abs <= read_abs + a.ring - pb:
                a.buf.write(w_abs % a.ring, gen(w_abs // BYTES_PER_FRAME, fpp))
                w_abs += pb
            now = time.time()
            if now - last >= 2.0:
                last = now
                print("   %5.1fs / %.1fs" % (now - t0, total / float(FS)))
            if now - t0 > total / float(FS) + 8:
                raise RuntimeError("播放 DMA 未按预期推进")
            time.sleep(0.002)
        _, tot = a.poll_pos()          # ★ 在 stop() 之前取
        print("[wav] 放完，DMA 共 %d 字节 (%.1fs)" % (tot, tot / 352800.0))
        return True
    finally:
        a.close()


def wavinfo(path):
    info, fetch = wav_open(path)
    print("%s" % path)
    print("   声道 %d   位宽 %dbit   采样率 %d Hz   帧数 %d   时长 %.2fs"
          % (info["nch"], info["sw"] * 8, info["sr"], info["nfr"],
             info["nfr"] / float(info["sr"] or 1)))
    print("   data 字节 %d" % info["bytes"])
    print("   前 5 帧 (24bit):", [fetch(i) for i in range(min(5, info["nfr"]))])
    mid = info["nfr"] // 2
    print("   中间 3 帧     :", [fetch(i) for i in range(mid, min(mid + 3,
                                                                info["nfr"]))])
    print("   最后 3 帧     :", [fetch(i) for i in
                                 range(max(0, info["nfr"] - 3), info["nfr"])])
    return info


# ---------------------------------------------------------------- 引导式听音

TRIALS = [
    # (位宽字段, 样本摆放, 音高Hz, 说明)
    (32, "rj", 500,  "32位位宽 + 右对齐（默认，最可能对）"),
    (32, "lj", 1000, "32位位宽 + 左对齐"),
    (24, "rj", 2000, "24位位宽 + 右对齐（会走 AES 编码器）"),
    (24, "lj", 4000, "24位位宽 + 左对齐（会走 AES 编码器）"),
]


def guided(vol=27):
    """依次用四种配置各播一个**不同音高**的正弦，让你听哪个是干净的。

    音高当编号：500 / 1000 / 2000 / 4000 Hz。
    ★ 另外还会**用蜂鸣器嘀 N 声**报"这是第 N 组"，每组装两遍 ——
      靠数嘀声比靠分辨音高可靠得多（蜂鸣器和音频链路是两回事，
      所以"嘀"是记号，后面带音高的才是音频）。
    """
    try:
        import beep as _beep
    except Exception:
        _beep = None
    has_beeper = bool(_beep and _beep.open_beeper() is not None)

    print("=" * 68)
    print(" 引导式听音：4 种配置各播一个正弦音，每组**连播两遍**")
    print(" ★ 每组开始前，蜂鸣器会「嘀」N 声报组号：")
    print("     嘀            = 第 1 组  500 Hz  (位宽32 右对齐)")
    print("     嘀嘀          = 第 2 组 1000 Hz  (位宽32 左对齐)")
    print("     嘀嘀嘀        = 第 3 组 2000 Hz  (位宽24 右对齐)")
    print("     嘀嘀嘀嘀      = 第 4 组 4000 Hz  (位宽24 左对齐)")
    print(" 注意：嘀声是【蜂鸣器】；嘀完之后那个**有音高的**声音才是音频链路。")
    print(" 听完告诉我：第几组能听出干净的音调。")
    print("=" * 68)
    for i, (dw, pack, freq, desc) in enumerate(TRIALS):
        print("\n--- 第 %d 组：%s" % (i + 1, desc))
        if has_beeper:
            print("    >>> 蜂鸣器嘀 %d 声 ..." % (i + 1))
            _beep.beep(i + 1, 160)
        time.sleep(0.8)
        a = AudioOut(dw=dw, pack=pack)
        try:
            a.codec_up()
            a.codec_vol(vol)
            a.i2s_config()
            a.fmt_config()
            for rep in (1, 2):
                fps = play_tone(a, float(freq), 2.2)
                print("    >> 第 %d 遍 %.0f Hz 播完，DMA 实测 %.1f 帧/s（%.4f x fs）"
                      % (rep, freq, fps, fps / FS))
                time.sleep(0.5)
        except Exception as e:
            print("    >> 失败: %s: %s" % (type(e).__name__, e))
        finally:
            a.close()
        time.sleep(0.6)
    print("\n听完之后：记住是【第几组】（数嘀声），或者告诉我音高也行。")
    print("第 1 组最好 -> 直接 python3 audio_pl.py --motif")
    print("第 2 组最好 -> 用 --pack lj")
    print("第 3/4 组最好，或者只有沙沙声 -> 说明是 AES 那条路，我再改。")


# ---------------------------------------------------------------- 诊断

def diag():
    print("=== formatter 寄存器快照（只读，只碰白名单偏移）")
    m = Mem()
    try:
        for name, base, offs in (
                ("S2MM", FMT_BASE,
                 [0x04, 0x10, 0x14, 0x18, 0x1C, 0x20, 0x24, 0x28, 0x2C, 0x44]),
                ("MM2S", FMT_BASE,
                 [0x110, 0x114, 0x118, 0x11C, 0x120, 0x124, 0x128, 0x12C,
                  0x144]),
                ("i2s_tx", I2S_BASE,
                 [0x00, 0x04, 0x08, 0x0C, 0x10, 0x14, 0x20, 0x30, 0x34])):
            print("-- %s" % name)
            for off in offs:
                try:
                    print("   0x%03X = 0x%08X" % (off, m.rd(base, off)))
                except Exception as e:
                    print("   0x%03X !! %s" % (off, e))
        cfg = m.rd(FMT_BASE, R_CORE_CFG)
        print("\n-- 解码")
        print("   MM2S 使能        = %s" % bool(cfg & (1 << 15)))
        print("   MM2S 传输模式    = %d (%s)"
              % ((cfg >> 13) & 3,
                 {0: "AES->AES", 1: "AES->PCM", 2: "PCM->PCM",
                  3: "PCM->AES"}.get((cfg >> 13) & 3, "?")))
        print("   打包模式         = %s"
              % ("非交织" if cfg & (1 << 12) else "交织(interleaved)"))
        print("   最大声道数       = %d" % ((cfg >> 8) & 0xF))
        ctrl = m.rd(FMT_BASE, R_CTRL)
        print("   AUD_CTRL         = 0x%08X" % ctrl)
        print("   位宽字段[18:16]  = %d  (%s)"
              % ((ctrl >> 16) & 7,
                 {0: "8bit", 1: "16bit", 2: "20bit", 3: "24bit(AES 生效)",
                  4: "32bit(AES 旁路)"}.get((ctrl >> 16) & 7, "?")))
        print("   DMA 使能         = %s" % bool(ctrl & 1))
    finally:
        m.close()
    print("\n=== ES8388")
    i2c = I2C()
    try:
        for r in sorted({r for r, _ in ES8388_INIT}):
            print("   0x%02X = 0x%02X" % (r, i2c.rd(r)))
        es8388_verify(i2c)
    finally:
        i2c.close()


# ---------------------------------------------------------------- CLI

USAGE = """用法:
  python3 audio_pl.py                 打印寄存器快照 + 解码（只读）
  python3 audio_pl.py --diag          同上，再加 ES8388 全寄存器
  python3 audio_pl.py --codec         初始化 ES8388 并回读校验
  python3 audio_pl.py --vol N         输出音量 0..33（33 最大）
  python3 audio_pl.py --guided         ★ 引导式听音：4 种配置各播一个不同音高
  python3 audio_pl.py --selftest [秒]  播 1kHz 正弦并测 DMA 速率
  python3 audio_pl.py --motif         播 C-E-G-C 四个音
  python3 audio_pl.py --tone 频率 秒   播指定单音
  python3 audio_pl.py --play 文件.wav  播 WAV

可选参数:
  --pack rj|lj    样本在 32bit 字里右对齐/左对齐（默认 rj）
  --dw 24|32      formatter 位宽字段（默认 32 = 旁路 AES 编码器）
  --vol N         输出音量
"""


def main(argv):
    if not argv:
        diag()
        return
    opt = {"dw": DEFAULT_DW, "pack": DEFAULT_PACK, "vol": 27, "amp": 0.35}
    rest = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--dw":
            opt["dw"] = int(argv[i + 1]); i += 2
        elif a == "--pack":
            opt["pack"] = argv[i + 1]; i += 2
        elif a == "--vol":
            opt["vol"] = int(argv[i + 1]); i += 2
        elif a == "--amp":
            opt["amp"] = float(argv[i + 1]); i += 2
        else:
            rest.append(a); i += 1
    if not rest:
        diag()
        return

    cmd = rest[0]
    if cmd == "--diag":
        diag()
    elif cmd == "--codec":
        i2c = I2C()
        try:
            es8388_init(i2c)
            es8388_verify(i2c)
        finally:
            i2c.close()
    elif cmd == "--vol":
        i2c = I2C()
        try:
            print("音量 ->", es8388_set_vol(i2c, opt["vol"]))
        finally:
            i2c.close()
    elif cmd == "--guided":
        guided(opt["vol"])
    elif cmd == "--selftest":
        selftest(float(rest[1]) if len(rest) > 1 else 3.0,
                 vol=opt["vol"], dw=opt["dw"], pack=opt["pack"])
    elif cmd == "--motif":
        play_motif(opt["vol"], dw=opt["dw"], pack=opt["pack"])
    elif cmd == "--tone":
        a = AudioOut(dw=opt["dw"], pack=opt["pack"])
        try:
            a.codec_up(); a.codec_vol(opt["vol"])
            a.i2s_config(); a.fmt_config()
            fps = play_tone(a, float(rest[1]) if len(rest) > 1 else 1000.0,
                            float(rest[2]) if len(rest) > 2 else 3.0,
                            amp=opt["amp"])
            print("[tone] 实测 %.1f 帧/s (%.4f x fs)" % (fps, fps / FS))
        finally:
            a.close()
    elif cmd == "--ab":
        # A/B 对比：奇数段 = A，偶数段 = B，同音高，只听响度差
        f = float(rest[1]) if len(rest) > 1 else 700.0
        secs = float(rest[2]) if len(rest) > 2 else 3.5
        n = int(rest[3]) if len(rest) > 3 else 3
        variants = [("A", opt["dw"], "rj"), ("B", 32, "lj"),
                    ("C", 24, "rj"), ("D", 24, "lj")]
        use = [(t, dw, pk) for (t, dw, pk) in variants
               if t in ("A", "B")]        # 默认只比 A/B
        print("=" * 62)
        print(" A/B 对比：同一音高 %.0fHz，奇数段=A(位宽32右对齐) 偶数段=B(位宽32左对齐)" % f)
        print(" 每段 %.1f 秒，中间停 1.5 秒，一共 %d 对。听**哪一段明显更响**。" % (secs, n))
        print("=" * 62)
        for k in range(n):
            for tag, dw, pk in use:
                print("\n--- 第 %d 对 段%s：位宽=%d 摆放=%s ---" % (k + 1, tag, dw, pk))
                a = AudioOut(dw=dw, pack=pk)
                try:
                    a.codec_up(); a.codec_vol(opt["vol"])
                    a.i2s_config(); a.fmt_config()
                    fps = play_tone(a, f, secs, amp=opt["amp"])
                    print("    >> %.0fHz 段%s 播完 %.1f帧/s" % (f, tag, fps))
                except Exception as e:
                    print("    >> 段%s 失败 %s" % (tag, e))
                finally:
                    a.close()
                time.sleep(1.5)
        print("\n结论看：奇数段(A)响 还是 偶数段(B)响。")
        print("B 明显更响 -> 数据摆放改成 --pack lj")
        print("A 更响或者一样 -> 摆放没错，是别的环节（我再查）")
    elif cmd == "--play":
        if len(rest) < 2:
            print("要指定 wav 文件")
            return
        play_file(rest[1], vol=opt["vol"], dw=opt["dw"], pack=opt["pack"])
    elif cmd == "--wavinfo":
        if len(rest) < 2:
            print("要指定 wav 文件")
            return
        wavinfo(rest[1])
    else:
        print(USAGE)


if __name__ == "__main__":
    main(sys.argv[1:])
