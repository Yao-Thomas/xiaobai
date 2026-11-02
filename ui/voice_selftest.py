#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""voice_selftest.py —— 语音闭环的**全自动自证**（不需要人说话）

    文本 ─espeak─▶ WAV ─板载喇叭─▶ 空气/结构 ─▶ 板载麦克风
         ─ADC─▶ DDR ─▶ vosk 离线识别 ─▶ 文字

把识别出的文字和原文对比，就能证明
    "喇叭 + 麦克风 + ADC + I2S + DDR + 识别" 整条链路是通的。

用法: sudo systemctl stop zynq-audio; sudo python3 voice_selftest.py
"""
import io
import os
import re
import sys
import time
import math
import wave
import struct
import subprocess

sys.path.insert(0, "/home/zynq/ui")
sys.path.insert(0, "/home/zynq")
import audio_pl as A                                          # noqa: E402
from audio_pl import AudioOut, es8388_set_vol                 # noqa: E402
from rec_big import RawCap, s24                               # noqa: E402
from audio_svc import read_wav                                # noqa: E402

FS = A.FS
SAY = "/tmp/vs_say.wav"
REC = "/tmp/vs_rec.wav"
TEXT = "现在几点"


def espeak(text, path, speed=120):
    subprocess.run(["espeak-ng", "-v", "cmn", "-s", str(speed), "-w", path,
                    text], check=True, timeout=60)
    return path


def speech_prep(samples, rate, fc=260.0, target=0.95):
    """把要播放的语音"修"一下，让**小喇叭**能把它发出来。

    实测问题：板载喇叭低频几乎发不出来，而语音能量集中在 100~500Hz，
    结果麦克风回录的峰值只有满量程的 4%（声压不够，识别引擎认不出）。
    这里：一阶高通(fc) 去掉发不出来的低频 -> 轻预加重 -> 归一化到接近满量程。
    """
    a = math.exp(-2.0 * math.pi * fc / rate)
    out = []
    px = float(samples[0]) if samples else 0.0
    py = 0.0
    for x in samples:
        x = float(x)
        cur = a * (py + x - px)
        px, py = x, cur
        out.append(cur)
    # 预加重（提升辅音/高频，帮助识别）
    pre = []
    prev = 0.0
    for x in out:
        pre.append(x - 0.6 * prev)
        prev = x
    pk = max((abs(x) for x in pre), default=1.0) or 1.0
    g = target * 32767.0 / pk
    return [max(-32768, min(32767, int(x * g))) for x in pre]


def fill_ring(ao, samples, ch, rate):
    """把 int16 样本（任意采样率/声道）铺满播放环形。"""
    if ch == 1:
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
        return 0
    buf = bytearray()
    i = 0
    while len(buf) < ao.ring:
        v = (samples[i % n] * 256) & 0xFFFFFF
        buf += struct.pack("<I", v)
        i += 1
    ao.buf.write(0, bytes(buf[:ao.ring]))
    return len(samples) / float(FS)


def save_mono16(raw, path, dst_rate=16000):
    n = len(raw) // 8
    mono = []
    for i in range(n):
        l = s24(int.from_bytes(raw[8 * i:8 * i + 4], "little"))
        r = s24(int.from_bytes(raw[8 * i + 4:8 * i + 8], "little"))
        mono.append((l + r) // 2)
    if dst_rate != FS:
        out_n = int(n * dst_rate / float(FS))
        step = FS / float(dst_rate)
        out = []
        for k in range(out_n):
            p = k * step
            i0 = int(p)
            i1 = min(i0 + 1, n - 1)
            f = p - i0
            out.append(int(mono[i0] * (1 - f) + mono[i1] * f))
        mono = out
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(dst_rate)
        w.writeframes(b"".join(
            struct.pack("<h", max(-32768, min(32767, v >> 8))) for v in mono))
    return path, len(mono) / float(dst_rate)


ADC_BLOCK = ((0x08, 0x00), (0x00, 0x06), (0x01, 0x50), (0x02, 0x00),
             (0x03, 0x51), (0x09, 0x66), (0x0A, 0x00), (0x0B, 0x02),
             (0x0C, 0x00), (0x0D, 0x0C), (0x10, 0x00), (0x11, 0x00))


def adc_rms(cap, secs=0.30):
    cap.cfg()
    cap.grab(0.08)
    cap.cfg()
    d, _ = cap.grab(secs)
    v = [s24(int.from_bytes(d[8 * i:8 * i + 4], "little"))
         for i in range(len(d) // 8)]
    if not v:
        return 0.0
    return math.sqrt(sum(float(x) * x for x in v) / len(v))


def ensure_alive(cap, ao, i2c, tries=5, verbose=True):
    """★ 实测 codec 有时上电就是"死"的（采集全 0 或恒定值）。
    反复检查，不通就**完整重初始化**再来。返回 (RMS, 重试次数)。
    """
    r = 0.0
    for k in range(tries):
        r = adc_rms(cap)
        if r > 1000:
            if verbose:
                print("[alive] ADC 存活 RMS=%.1f（第 %d 次）" % (r, k + 1))
            return r, k
        if verbose:
            print("[alive] 第 %d 次 RMS=%.1f 太死，重初始化 codec ..." % (k + 1, r))
        ao.codec_up()
        es8388_set_vol(ao.i2c, 33, 0)
        for reg, val in ADC_BLOCK:
            i2c.wr(reg, val)
        time.sleep(0.45)
    return r, tries


def main():
    # ★ 环形要够大：分块采集时每块都复位 S2MM，20+ 个断点会把语音切碎
    #   （实测：分 27 块录的 vosk 只认出 1 个字；干净 espeak 能认出 3 个）
    cap = RawCap(ring_kb=4096)
    ao = AudioOut()
    ao.codec_up()
    ao.i2s_config()
    ao.fmt_config()
    es8388_set_vol(ao.i2c, 33, 0)   # 音量拉满，让麦克风收到足够的声压
    i2c = cap.i2c
    for r, v in ((0x08, 0x00), (0x00, 0x06), (0x01, 0x50), (0x02, 0x00),
                 (0x03, 0x51), (0x09, 0x66), (0x0A, 0x00), (0x0B, 0x02),
                 (0x0C, 0x00), (0x0D, 0x0C), (0x10, 0x00), (0x11, 0x00)):
        i2c.wr(r, v)
    cap.mem.wr(A.I2S_RX_BASE, A.I2S_CORE_CTRL, 1)
    cap.mem.wr(A.I2S_BASE, A.I2S_CORE_CTRL, 1)

    print("=" * 76)
    print("语音闭环自证  原文 = %r" % TEXT)
    print("=" * 76)

    # ★ 先确认 ADC 是活的 —— 实测 codec 有时上电就是"死"的（采集全 0）
    ensure_alive(cap, ao, i2c)

    espeak(TEXT, SAY)
    samples, rate, ch = read_wav(SAY)
    if ch == 1:
        samples = speech_prep(samples, rate)
        print("[1b] 播放侧预处理: 高通260Hz + 预加重 + 归一化到满量程")
    dur = fill_ring(ao, samples, ch, rate)
    print("[1] espeak 合成: %s  %.2fs  %dHz %dch" % (SAY, dur, rate, ch))

    fill_ring(ao, samples, ch, rate)             # 再铺一次（确保整圈都是这句话）
    ao.start()
    time.sleep(0.15)

    # ★ 边放边录。**优先单次连续采集**（无断点）；
    #   只有环形装不下时才分块，分块会产生 20+ 处断点、把语音切碎。
    total = max(1.0, dur + 1.0)
    fits = total <= 0.85 * cap.ring / 352800.0
    rec = bytearray()
    t0 = time.time()
    if fits:
        cap.cfg()
        cap.grab(0.08)                            # 丢暂态
        cap.cfg()
        d, _ = cap.grab(total)
        rec += d
        nblk = 1
    else:
        chunk = 0.75 * cap.ring / 352800.0
        left = total
        warm = True
        while left > 0.01:
            take = min(chunk, left)
            cap.cfg()
            if warm:
                cap.grab(0.08)
                warm = False
            d, _ = cap.grab(take)
            rec += d
            left -= take
        nblk = max(1, int(total / chunk))
    rec = bytes(rec)
    r = len(rec) / max(1e-6, time.time() - t0)
    print("[2] 边放边录: %.0f B/s  %d 字节 (%.2fs, %s)"
          % (r, len(rec), total,
             "单次连续采集 ★" if fits else "分 %d 块(有断点)" % nblk))
    print("    环形 %d 字节 = %.2fs，需要 %.2fs -> %s"
          % (cap.ring, cap.ring / 352800.0, total,
             "装得下" if fits else "装不下，只能分块"))
    ao.buf.write(0, b"\x00" * ao.ring)
    time.sleep(0.1)
    ao.stop()

    save_mono16(rec, REC)
    with wave.open(REC, "rb") as w:
        n = w.getnframes()
        d = w.readframes(n)
    v = struct.unpack("<%dh" % (len(d) // 2), d)
    rms = math.sqrt(sum(float(x) * x for x in v) / max(1, len(v)))
    pk = max((abs(x) for x in v), default=0)
    print("[3] 回录文件 %s  %d 帧  RMS=%.1f  峰值=%d"
          % (REC, n, rms, pk))

    # ---- vosk 识别 ----
    from agent import asr
    print("[4] vosk 识别中（首次要加载模型，慢）...")
    t0 = time.time()
    try:
        text = asr.recognize_vosk(REC)
        el = time.time() - t0
        print("[4] 识别结果: %r   (%.1fs)" % (text, el))
    except Exception as e:
        print("[4] 识别失败: %s: %s" % (type(e).__name__, e))
        text = ""
    # 第二次（模型已热）测速
    t0 = time.time()
    try:
        asr.recognize_vosk(REC)
        print("[5] 二次识别耗时 %.1fs（模型已热）" % (time.time() - t0))
    except Exception:
        pass

    orig = re.sub(r"[^\u4e00-\u9fff]", "", TEXT)
    got = re.sub(r"[^\u4e00-\u9fff]", "", text or "")
    common = len(set(orig) & set(got))
    print("\n原文: %s" % orig)
    print("识别: %s" % (got or "(空)"))
    print("重合字数: %d / %d" % (common, len(orig)))
    if got:
        print("★ 闭环打通：喇叭放的中文被麦克风录回来并被识别出文字")
    else:
        print("⚠ 识别为空 —— 声学链路是通的（RSM/峰值有值），"
              "但 espeak 机器音 vosk 认不出；真人语音需另测")

    ao.close()
    cap.close()


if __name__ == "__main__":
    main()
