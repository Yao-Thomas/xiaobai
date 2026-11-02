#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""系统管家小白 —— 板载音频服务 (独占)

音频硬件是全局独占资源，所以只在**这一个进程**里碰 PL 寄存器和 ES8388，
外面（Agent / GUI / 命令行）一律通过 HTTP 访问，避免互相抢寄存器。

监听 127.0.0.1:8767（默认）

接口
    GET  /health                 -> {"ok":true,...}
    GET  /state                  -> 音量/忙闲/放音录音状态
    POST /volume   {"v":30}      -> 设置输出音量 0..33
    POST /play     {"file":"/x.wav"}  或  {"tone":1000,"secs":1,"amp":0.4}
    POST /say      {"file":"/x.wav"}  语义同 play（TTS 用）
    POST /record   {"secs":3,"rate":16000,"mono":true}
                                 -> 返回 WAV 字节 (audio/wav)
    POST /stop

★ 录音用的是"大环形 + 停 DMA 后线性读"，绝不按写指针旋转 ——
  之前按 XFER%ring 旋转读出来的全是垃圾数据，这一点踩过大坑。
"""
import sys
import io
import os
import json
import time
import math
import wave
import struct
import threading
import traceback

sys.path.insert(0, "/home/zynq/ui")
import audio_pl as A                                          # noqa: E402
from audio_pl import AudioOut, make_sine, es8388_set_vol      # noqa: E402
from rec_big import RawCap                                    # noqa: E402

try:
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
except ImportError:                                           # pragma: no cover
    from http.server import BaseHTTPRequestHandler, HTTPServer as ThreadingHTTPServer

PORT = int(os.environ.get("AUDIO_SVC_PORT", "8767"))
FS = A.FS
BYTES_PER_FRAME = A.BYTES_PER_FRAME
MAX_TONE_SECS = 60.0
MAX_REC_SECS = 30.0
# 录音取哪一路：L / R / sum / diff —— 实测 L 最稳（见 pcm_to_int16_mono 注释）
CAP_MODE = os.environ.get("AUDIO_CAP_MODE", "L")
# 麦克风寄存器组合（实测可用值，见 见 14_音频勘验/实测报告）
ADC_03 = int(os.environ.get("AUDIO_ADC_03", "0x51"), 0)
ADC_09 = int(os.environ.get("AUDIO_ADC_09", "0x66"), 0)
ADC_0A = int(os.environ.get("AUDIO_ADC_0A", "0x00"), 0)


# ---------------------------------------------------------------- 小工具

def s24(w):
    w &= 0xFFFFFF
    return w - 0x1000000 if w & 0x800000 else w


def pcm_to_int16_mono(data, src_rate=FS, dst_rate=16000, mode=None):
    """8字节一帧(2ch x 32bit) -> 单声道 16bit，线性插值重采样。

    ★ 通道取法很关键：实测只有**单端 0x0A=0x00 + 取 L 通道**能复现出
      放音/静音 +28.8dB 的稳定结果；把 L/R 相加会互相抵消（曾因此自检失败）。
    """
    mode = mode or CAP_MODE
    n = len(data) // BYTES_PER_FRAME
    if n == 0:
        return []
    mono = []
    for i in range(n):
        l = s24(int.from_bytes(data[8 * i:8 * i + 4], "little"))
        r = s24(int.from_bytes(data[8 * i + 4:8 * i + 8], "little"))
        if mode == "L":
            mono.append(l)
        elif mode == "R":
            mono.append(r)
        elif mode == "diff":
            mono.append((l - r) // 2)
        else:
            mono.append((l + r) // 2)
    if dst_rate == src_rate:
        return [max(-32768, min(32767, v >> 8)) for v in mono]
    out_n = int(n * dst_rate / float(src_rate))
    step = src_rate / float(dst_rate)
    out = []
    for k in range(out_n):
        p = k * step
        i0 = int(p)
        frac = p - i0
        i1 = min(i0 + 1, n - 1)
        v = int(mono[i0] * (1.0 - frac) + mono[i1] * frac)
        out.append(max(-32768, min(32767, v >> 8)))
    return out


def wav_bytes(samples, rate, channels=1):
    buf = io.BytesIO()
    w = wave.open(buf, "wb")
    w.setnchannels(channels)
    w.setsampwidth(2)
    w.setframerate(rate)
    w.writeframes(struct.pack("<%dh" % len(samples), *samples))
    w.close()
    return buf.getvalue()


def read_wav(path):
    """读 WAV -> (int16 样本列表, 采样率, 声道数)。只支持 8/16/24/32bit PCM。"""
    with wave.open(path, "rb") as w:
        ch = w.getnchannels()
        sw = w.getsampwidth()
        rate = w.getframerate()
        raw = w.readframes(w.getnframes())
    out = []
    if sw == 1:
        out = [(b - 128) << 8 for b in raw]
    elif sw == 2:
        out = list(struct.unpack("<%dh" % (len(raw) // 2), raw))
    elif sw == 3:
        for i in range(len(raw) // 3):
            v = int.from_bytes(raw[3 * i:3 * i + 3], "little")
            if v & 0x800000:
                v -= 0x1000000
            out.append(v >> 8)
    elif sw == 4:
        for i in range(len(raw) // 4):
            out.append(struct.unpack("<i", raw[4 * i:4 * i + 4])[0] >> 16)
    else:
        raise ValueError("不支持的位宽 %d" % sw)
    return out, rate, ch


def goe(v, f, rate=FS):
    """加窗 Goertzel：单频能量（除以 N/4 归一化）"""
    n = len(v)
    if n < 64:
        return 0.0
    w = 2.0 * math.pi * f / rate
    c = 2.0 * math.cos(w)
    s1 = s2 = 0.0
    for i, x in enumerate(v):
        x = x * (0.5 - 0.5 * math.cos(2.0 * math.pi * i / (n - 1)))
        s0 = x + c * s1 - s2
        s2, s1 = s1, s0
    return math.sqrt(max(0.0, s1 * s1 + s2 * s2 - c * s1 * s2)) / (n / 4.0)


def mono_of(raw):
    """formatter 原始字节流 -> 单声道 24bit 列表（取 L 通道）"""
    return [s24(int.from_bytes(raw[8 * i:8 * i + 4], "little"))
            for i in range(len(raw) // 8)]


# ---------------------------------------------------------------- 引擎

class Engine(object):
    """独占音频硬件。所有公开方法都在锁里跑。"""

    def __init__(self, verbose=True):
        self.lock = threading.RLock()
        self.verbose = verbose
        # ★ 2026-09-28: 30 -> 33。验收脚本查到输出音量寄存器只有 0x1E(=30, +0.0dB)，
        #   而最大是 33 = +4.5dB —— 白白少了 4.5dB。
        #   es8388_set_vol 的映射: 0..33, 33=+4.5dB(最大), 0=-45dB。
        #   这是"声音小"里唯一还没用上的软件余量。
        self.volume = 33
        self.busy = ""
        self.last_error = ""
        self.rec_count = 0
        self.play_count = 0

        # ★ 先要大块连续内存给录音，再建播放侧（顺序反了容易碎片化失败）
        self.cap = RawCap(verbose=verbose)
        self.out = AudioOut(verbose=verbose)
        self.out.codec_up()
        self.out.i2s_config()
        self.out.fmt_config()
        self.cap.cfg()
        self._codec_adc()
        es8388_set_vol(self.out.i2c, self.volume, 0)
        self._silence = b"\x00" * self.out.ring
        self.out.buf.write(0, self._silence)
        self.out.start()                 # 收发 I2S 都使能，DAC 时钟常活
        self.cap.mem.wr(A.I2S_RX_BASE, A.I2S_CORE_CTRL, 1)
        self.cap.mem.wr(A.I2S_BASE, A.I2S_CORE_CTRL, 1)
        self._ensure_alive()             # ★ 启动时确认 ADC 真的在出数据
        if verbose:
            print("[svc] 就绪: 放音 ring=%d 录音 ring=%d 音量=%d"
                  % (self.out.ring, self.cap.ring, self.volume))

    def _codec_adc(self):
        """麦克风 = 板载麦克风，接 LIN1/RIN1（原理图 MIC_P->pin24, MIC_N->pin23）。

        ★ 具体取值是实测出来的（见 14_音频勘验/实测报告_音频链路打通.md）：
          0x03=0x59 是厂家值；0x0A=0x00 选 LIN1/RIN1；取 L 通道做单声道。
          之前用 0x0A=0xF0(差分) + L/R 平均，结果自检失败（L/R 反相抵消）。
        """
        i = self.cap.i2c
        for r, v in ((0x08, 0x00), (0x00, 0x06), (0x01, 0x50), (0x02, 0x00),
                     (0x03, ADC_03), (0x09, ADC_09), (0x0A, ADC_0A),
                     (0x0B, 0x02), (0x0C, 0x00), (0x0D, 0x0C),
                     (0x10, 0x00), (0x11, 0x00)):
            i.wr(r, v)
        if self.verbose:
            print("[svc] ADC: 0x03=0x%02X 0x09=0x%02X 0x0A=0x%02X "
                  "0x0D=0x%02X 0x2B=0x%02X 取声道=%s"
                  % (i.rd(0x03), i.rd(0x09), i.rd(0x0A), i.rd(0x0D),
                     i.rd(0x2B), CAP_MODE))

    # ---- ADC 存活守卫 ----
    def _adc_rms(self, secs=0.25):
        self.cap.cfg()
        self.cap.grab(0.08)
        self.cap.cfg()
        d, _ = self.cap.grab(secs)
        v = mono_of(d)
        if not v:
            return 0.0
        return math.sqrt(sum(float(x) * x for x in v) / len(v))

    def _ensure_alive(self, tries=6):
        """★★ 这一步不能省！实测 codec 有时上电就是"死"的（ADC 采不到东西），
        表现为"频谱矩阵对角线不占优、回录能量只有正常值的 1/1000"。
        启动时确认一次，不活就**完整重初始化**（只写回 0x03 是救不回来的）。
        """
        r = 0.0
        for k in range(tries):
            r = self._adc_rms()
            if r > 1000:
                if self.verbose:
                    print("[svc] ADC 存活检查通过 RMS=%.1f（第 %d 次）" % (r, k + 1))
                return r, k
            if self.verbose:
                print("[svc] ADC 第 %d 次检查 RMS=%.1f 太死，重初始化 codec ..."
                      % (k + 1, r))
            self.out.codec_up()
            es8388_set_vol(self.out.i2c, self.volume, 0)
            self._codec_adc()
            time.sleep(0.45)
        if self.verbose:
            print("[svc] ⚠ ADC 仍然很死 RMS=%.1f，先继续（录音可能不可用）" % r)
        return r, tries

    # ---- 音量 ----
    def set_volume(self, v):
        with self.lock:
            self.volume = max(0, min(33, int(v)))
            es8388_set_vol(self.out.i2c, self.volume, 0)
            return self.volume

    # ---- 播放 ----
    def _fill_ring(self, samples, channels=1, rate=FS):
        """int16 样本 -> formatter 要的 32bit 左对齐/右对齐格式，填满播放环形。"""
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
        n = len(samples)
        if n == 0:
            return
        # ★ 一定要铺满**整个**播放环形，否则剩下的是上次的残留内容
        want = self.out.ring
        buf = bytearray()
        i = 0
        while len(buf) < want:
            v = samples[i % n]
            if self.out.pack == "lj":
                v = (v * 256) & 0xFFFFFFFF
            else:
                v = (v * 256) & 0xFFFFFF
            buf += struct.pack("<I", v)
            i += 1
        self.out.buf.write(0, bytes(buf[:want]))
        return want

    # ★ 归一化目标：峰值提到 int16 满量程的 90%（≈ -1 dBFS，和 amp=0.9 的纯音相当）
    TARGET_PEAK = int(0.90 * 32767)
    # 最大放大倍数（避免把一段极安静的录音抬成噪声墙）
    GAIN_MAX = 12.0

    def _pack_stream(self, samples, channels=1, rate=FS):
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

        # ★★ 自动归一化（2026-09-28 加）
        #   实测：纯音 amp=0.9 的峰值 7549746 用户听着"超级大"，
        #   而 03_小星星.wav 峰值只有 2987264（-9dBFS）-> 听不到。
        #   再叠加音量档位（33 vs 20）差 27.5 dB。
        #   所以这里把峰值提到目标档位，让文件播放和纯音一样饱满。
        #   GAIN_MAX 限幅：本来就很响的文件不会被放大到削波。
        pk = 0
        for x in samples:
            ax = x if x >= 0 else -x
            if ax > pk:
                pk = ax
        if pk > 0:
            g = self.TARGET_PEAK / float(pk)
            if g > self.GAIN_MAX:
                g = GAIN_MAX
            if abs(g - 1.0) > 0.01:
                samples = [int(x * g) for x in samples]

        buf = bytearray()
        if self.out.pack == "lj":
            for v in samples:
                buf += struct.pack("<I", (v * 256) & 0xFFFFFFFF)
        else:
            for v in samples:
                buf += struct.pack("<I", (v * 256) & 0xFFFFFF)
        return bytes(buf)

    def play_samples(self, samples, channels=1, rate=FS, secs=None):
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
                        blk = blk + b"\x00" * (blk_bytes - len(blk))
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

    def play_tone(self, freq=1000.0, secs=1.0, amp=0.4):
        frames = max(64, self.out.period_bytes // BYTES_PER_FRAME)
        tone = make_sine(freq, frames=frames, amp=amp, pack=self.out.pack)
        # make_sine 已经是 2ch 32bit
        with self.lock:
            self.busy = "play"
            try:
                es8388_set_vol(self.out.i2c, self.volume, 0)
                self.out.buf.write(0, (tone * 8)[:self.out.ring])
                secs = max(0.05, min(MAX_TONE_SECS, float(secs)))
                t = time.time() + secs
                while time.time() < t:
                    time.sleep(0.05)
                self.out.buf.write(0, self._silence)
                self.play_count += 1
                return secs
            finally:
                self.busy = ""

    def play_wav(self, path):
        samples, rate, ch = read_wav(path)
        return self.play_samples(samples, channels=ch, rate=rate)

    # ---- 录音 ----
    def record_raw(self, secs):
        """分块连续录 -> 原始 formatter 字节流（32bit x 2ch）。

        ★★ 必须丢掉第一次采集 ★★
          实测（rec_mic.py）：0x03=0xFD(ADC全断电) 时
              第1次 grab = 3140226→3139458→3138690…（每次递减 768 的斜坡，暂态）
              第2~5次 grab = 17（稳定，这才是"无数据"的基准）
          ADC 打开时麦克风稳定给 20000~47000（峰 164386）。不丢第一次就会
          把暂态当成信号，这是之前反复误判的直接原因。
        """
        secs = max(0.1, min(MAX_REC_SECS, float(secs)))
        self.cap.cfg()
        self.cap.grab(0.08)                   # ★ 丢弃的暂态
        chunk = 0.80 * self.cap.ring / 352800.0
        out = bytearray()
        left = secs
        while left > 0.01:
            take = min(chunk, left)
            self.cap.cfg()                     # 复位 S2MM，写指针回到缓冲起点
            d, rate = self.cap.grab(take)
            if rate < 1000:
                raise RuntimeError("录音速率异常 %.0f B/s（PL 时钟没起来？）" % rate)
            out += d
            left -= take
        return bytes(out), rate

    def record_wav(self, secs=3.0, rate=16000, mono=True):
        with self.lock:
            self.busy = "record"
            try:
                raw, r = self.record_raw(secs)
                samples = pcm_to_int16_mono(raw, FS, rate if mono else FS)
                self.rec_count += 1
                if mono:
                    return wav_bytes(samples, rate, 1), r
                return wav_bytes(samples, FS, 2), r
            finally:
                self.busy = ""

    def stop(self):
        with self.lock:
            self.out.buf.write(0, self._silence)

    # ---- 免耳朵自检：放一个单音，同时用麦克风录，看 1kHz 分量有没有抬起来 ----
    def loopback_selftest(self, freq=990.53, secs=1.2, amp=0.9):
        with self.lock:
            self.busy = "selftest"
            try:
                frames = max(64, self.out.period_bytes // BYTES_PER_FRAME)
                tone = make_sine(freq, frames=frames, amp=amp,
                                 pack=self.out.pack)
                ring_tone = (tone * 8)[:self.out.ring]

                def _ch(raw, mode):
                    n = len(raw) // 8
                    out = []
                    for i in range(n):
                        l = s24(int.from_bytes(raw[8 * i:8 * i + 4], "little"))
                        r = s24(int.from_bytes(raw[8 * i + 4:8 * i + 8], "little"))
                        if mode == "L":
                            out.append(l)
                        elif mode == "R":
                            out.append(r)
                        elif mode == "diff":
                            out.append((l - r) // 2)
                        else:
                            out.append((l + r) // 2)
                    return out

                # 基线：播静音
                self.out.buf.write(0, self._silence)
                time.sleep(self.out.ring / 352800.0 + 0.10)
                q_raw, q_rate = self.record_raw(secs)
                q_all = {m: _ch(q_raw, m) for m in ("L", "R", "sum", "diff")}

                # 放音（另开线程），同时录
                self.out.buf.write(0, ring_tone)
                th = threading.Thread(target=self._wait_then_silence,
                                      args=(secs + 0.8,))
                th.start()
                time.sleep(self.out.ring / 352800.0 + 0.10)
                t_raw, t_rate = self.record_raw(secs)
                th.join()
                t_all = {m: _ch(t_raw, m) for m in ("L", "R", "sum", "diff")}

                def goe(v, f):
                    if len(v) < 64:
                        return 0.0
                    w = 2.0 * math.pi * f / A.FS
                    c = 2.0 * math.cos(w)
                    s1 = s2 = 0.0
                    for x in v:
                        s0 = x + c * s1 - s2
                        s2, s1 = s1, s0
                    return math.sqrt(max(0.0, s1 * s1 + s2 * s2 - c * s1 * s2)) / (len(v) / 2.0)

                def rms(v):
                    return 0.0 if not v else math.sqrt(sum(float(x) * x for x in v) / len(v))

                per = {}
                for m in ("L", "R", "sum", "diff"):
                    gq, gt = goe(q_all[m], freq), goe(t_all[m], freq)
                    per[m] = {"rms_quiet": round(rms(q_all[m]), 1),
                              "rms_tone": round(rms(t_all[m]), 1),
                              "goe_quiet": round(gq, 1), "goe_tone": round(gt, 1),
                              "ratio_db": round(20 * math.log10(max(1e-9, gt) /
                                                                max(1e-9, gq)), 1)}
                use = per.get(CAP_MODE, per["L"])
                db = use["ratio_db"]
                return {"ok": True, "freq": freq, "secs": secs, "cap_mode": CAP_MODE,
                        "rate_quiet": round(q_rate), "rate_tone": round(t_rate),
                        "rms_quiet": use["rms_quiet"], "rms_tone": use["rms_tone"],
                        "goe_quiet": use["goe_quiet"], "goe_tone": use["goe_tone"],
                        "ratio_db": db, "per_channel": per,
                        "pass": bool(db > 6.0 and use["goe_tone"] > 50.0),
                        "verdict": ("麦克风听到放音了 ✔" if (db > 6.0 and
                                                           use["goe_tone"] > 50.0)
                                    else "没听到 —— 看 per_channel 里哪一路有反应")}
            finally:
                self.out.buf.write(0, self._silence)
                self.busy = ""

    def _wait_then_silence(self, secs):
        time.sleep(secs)
        try:
            self.out.buf.write(0, self._silence)
        except Exception:
            pass

    # ---- 频谱矩阵自证：放音 -> 喇叭 -> 麦克风 -> 频谱，看对角线是否占优 ----
    def spectral_matrix(self, secs=0.5, amp=0.9):
        """★ 在这里做而不是在探针脚本里做，是为了**避开内存碎片化**：
        脚本每次都要新分配 8MB 池去找物理连续内存，跑两轮就失败了；
        服务常驻、缓冲只分配一次，所以由它做才能'随时可复现'。
        返回矩阵，对角线命中即证明 放音链路被麦克风回录证实。
        """
        with self.lock:
            self.busy = "matrix"
            try:
                frames = max(64, self.out.period_bytes // BYTES_PER_FRAME)
                ks = [23, 30, 46, 60, 70, 93]
                freqs = [round(k * float(FS) / frames, 2) for k in ks]
                secs = max(0.25, min(secs, 0.9 * self.cap.ring / 352800.0))

                self.out.buf.write(0, self._silence)
                time.sleep(self.out.ring / 352800.0 + 0.15)
                q_raw, _ = self.record_raw(secs)
                base = [goe(mono_of(q_raw), f) for f in freqs]

                rows = []
                for f0 in freqs:
                    tone = make_sine(f0, frames=frames, amp=amp,
                                     pack=self.out.pack)
                    self.out.buf.write(0, (tone * 8)[:self.out.ring])
                    time.sleep(self.out.ring / 352800.0 + 0.12)
                    t_raw, _ = self.record_raw(secs)
                    v = mono_of(t_raw)
                    e = [goe(v, f) for f in freqs]
                    # ★ 有效性（故障 B）：全零 = 这一次没采到数据。
                    #   必须**先判 valid**：e 全零时 max(e)=0，e.index(0)=0，
                    #   top 会恒等于 freqs[0]，从而把"没采到"错判成"命中"。
                    valid = max(e) > 0
                    top = e.index(max(e)) if valid else -1
                    med = sorted(e)[len(e) // 2] or 1e-9
                    rows.append({
                        "play": f0,
                        "energy": [round(x, 1) for x in e],
                        "top": freqs[top] if valid else None,
                        "valid": valid,
                        "hit": bool(valid and top == freqs.index(f0)),
                        "peak": round(e[top], 1),
                        "base": round(base[top], 1),
                        # ★ 平坦度才是决定性判据。离线实测(test_audio_math.py)：
                        #   纯音 990.5Hz ~7.6e5，白噪声只有 1.70，斜坡图案 2.01。
                        #   只看"对角线命中"或"峰/基线"会被噪声骗过去
                        #   （噪声的峰/基线也能很大，因为静音基线很小）。
                        "flatness": round(max(e) / med, 1),
                        "gain_db": round(20 * math.log10(
                            max(1e-9, e[top]) / max(1e-9, base[top])), 1),
                    })
                self.out.buf.write(0, self._silence)
                hit = sum(1 for r in rows if r["hit"])
                vrows = [r for r in rows if r.get("valid")]
                # ★ min_flatness 只在**有效**行上取。全零行的 flatness 是 0.0，
                #   混进来会把结果拉到 0，看起来像"过载"，其实没采到数据。
                minflat = min((r["flatness"] for r in vrows), default=0.0)
                zero_captures = len(rows) - len(vrows)
                # ★ good 要求六行全部有效
                good = bool(len(vrows) == len(freqs)
                            and hit >= len(freqs) - 1 and minflat > 100)
                return {
                    "ok": True, "freqs": freqs, "rows": rows,
                    "baseline": [round(x, 1) for x in base],
                    "secs": round(secs, 3),
                    "hit": hit, "total": len(freqs),
                    "min_flatness": minflat,
                    "valid_rows": len(vrows),
                    "zero_captures": zero_captures,
                    "pass": good,
                    "verdict": ("放音链路被麦克风回录证实（对角线占优且有尖峰）"
                                if good else
                                "不合格: 命中%d/%d 最小平坦度%.1f "
                                "（>100 才算真有尖峰，白噪声约 1.7）"
                                % (hit, len(freqs), minflat)),
                }
            finally:
                self.out.buf.write(0, self._silence)
                self.busy = ""

    def state(self):
        with self.lock:
            return {"ok": True, "busy": self.busy, "volume": self.volume,
                    "play_count": self.play_count, "rec_count": self.rec_count,
                    "play_ring": self.out.ring, "rec_ring": self.cap.ring,
                    "fs": FS, "last_error": self.last_error}

    def close(self):
        try:
            self.out.close()
        finally:
            self.cap.close()


ENGINE = None


# ---------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "XiaoBaiAudio/0.1"

    def log_message(self, fmt, *a):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:
            pass

    def _json(self, code, obj):
        self._send(code, json.dumps(obj, ensure_ascii=False))

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        raw = self.rfile.read(n)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {"_raw": raw}

    def do_GET(self):
        p = self.path.split("?")[0]
        try:
            if p in ("/health", "/"):
                return self._json(200, {"ok": True, "name": "系统管家小白-音频服务",
                                        "port": PORT})
            if p == "/state":
                return self._json(200, ENGINE.state())
            return self._json(404, {"ok": False, "error": "no such path"})
        except Exception as e:
            traceback.print_exc()
            return self._json(500, {"ok": False, "error": str(e)})

    def do_POST(self):
        p = self.path.split("?")[0]
        try:
            b = self._body()
            if p == "/volume":
                return self._json(200, {"ok": True,
                                        "volume": ENGINE.set_volume(b.get("v", 30))})
            if p == "/stop":
                ENGINE.stop()
                return self._json(200, {"ok": True})
            if p in ("/play", "/say"):
                if b.get("file"):
                    if not os.path.isfile(b["file"]):
                        return self._json(400, {"ok": False,
                                                "error": "no file " + str(b["file"])})
                    d = ENGINE.play_wav(b["file"])
                else:
                    d = ENGINE.play_tone(float(b.get("tone", 1000)),
                                         float(b.get("secs", 1.0)),
                                         float(b.get("amp", 0.4)))
                return self._json(200, {"ok": True, "secs": round(d, 3)})
            if p == "/matrix":
                return self._json(200, ENGINE.spectral_matrix(
                    float(b.get("secs", 0.5)), float(b.get("amp", 0.9))))
            if p == "/selftest":
                return self._json(200, ENGINE.loopback_selftest(
                    float(b.get("freq", 1000.0)), float(b.get("secs", 1.2))))
            if p == "/record":
                wav, rate = ENGINE.record_wav(float(b.get("secs", 3.0)),
                                              int(b.get("rate", 16000)),
                                              bool(b.get("mono", True)))
                return self._send(200, wav, "audio/wav")
            if p == "/record_raw":
                raw, rate = ENGINE.record_raw(float(b.get("secs", 3.0)))
                return self._send(200, raw, "application/octet-stream")
            return self._json(404, {"ok": False, "error": "no such path"})
        except Exception as e:
            traceback.print_exc()
            try:
                ENGINE.last_error = "%s: %s" % (type(e).__name__, e)
            except Exception:
                pass
            return self._json(500, {"ok": False,
                                    "error": "%s: %s" % (type(e).__name__, e)})


def main():
    global ENGINE
    quiet = "--quiet" in sys.argv
    ENGINE = Engine(verbose=not quiet)
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    srv.daemon_threads = True
    print("[svc] 监听 http://127.0.0.1:%d  (Ctrl-C 退出)" % PORT)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
        ENGINE.close()


if __name__ == "__main__":
    main()
