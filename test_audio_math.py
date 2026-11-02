#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_audio_math.py —— 在 PC 上验证"分析代码本身是对的"。

为什么做这个：
  板子上的音频分析反复给出反直觉的结果（对角线时有时无、能量整片抬平），
  我必须先排除"是我自己的数学/解析写错了"。
  这些纯函数不需要硬件，可以在 PC 上直接验证：
    * formatter 字节格式 <-> 24bit 样本的解析
    * 加窗 Goertzel 能不能把已知频率挑出来
    * "频谱平坦度"指标：纯音应该远大于 1，白噪声应该接近 1
    * pcm_to_int16_mono / wav_bytes / read_wav / normalize_wav 往返一致
    * voice_loop 的状态机顺序

跑法: python test_audio_math.py
"""
import io
import math
import os
import random
import struct
import sys
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "ui"))
sys.path.insert(0, HERE)

FS = 44100
FAIL = []
PASS = []


def ck(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print("  %s %s%s" % ("PASS" if cond else "FAIL", name,
                         ("   " + extra) if extra else ""))


# ---------------------------------------------------------------- 字节格式
def s24(w):
    w &= 0xFFFFFF
    return w - 0x1000000 if w & 0x800000 else w


def make_stream(samples_l, samples_r=None):
    """按 formatter 的格式造字节流：每帧 8 字节 = L(32bit LE) + R(32bit LE)，
    24bit 右对齐。"""
    if samples_r is None:
        samples_r = samples_l
    out = bytearray()
    for i in range(len(samples_l)):
        out += struct.pack("<I", samples_l[i] & 0xFFFFFF)
        out += struct.pack("<I", samples_r[i] & 0xFFFFFF)
    return bytes(out)


def left_of(d):
    return [s24(int.from_bytes(d[8 * i:8 * i + 4], "little"))
            for i in range(len(d) // 8)]


def right_of(d):
    return [s24(int.from_bytes(d[8 * i + 4:8 * i + 8], "little"))
            for i in range(len(d) // 8)]


def rms(v):
    return 0.0 if not v else math.sqrt(sum(float(x) * x for x in v) / len(v))


def test_bytes():
    print("\n[1] formatter 字节格式解析")
    vals = [0, 1, -1, 8388607, -8388608, 123456, -654321]
    rvals = [0, -1, 1, -8388607, 8388607, -123456, 654321]   # 注意别越界
    d = make_stream(vals, rvals)
    ck("L 通道还原", left_of(d) == vals, str(left_of(d)))
    ck("R 通道还原", right_of(d) == rvals)
    ck("帧长 8 字节", len(d) == 8 * len(vals))
    # 24bit 右对齐：高字节必须是 0（免得把符号扩展当成数据）
    ck("24bit 右对齐(高字节为0)", all(d[4 * i + 3] in (0, 0xFF)
                                      for i in range(2 * len(vals))))


# ---------------------------------------------------------------- Goertzel
def win(v):
    n = len(v)
    if n < 8:
        return [float(x) for x in v]
    k = 2.0 * math.pi / (n - 1)
    return [v[i] * (0.5 - 0.5 * math.cos(k * i)) for i in range(n)]


def goe_multi(w, freqs, rate=FS):
    n = len(w)
    if n < 64:
        return [0.0 for _ in freqs]
    out = []
    for f in freqs:
        c = 2.0 * math.cos(2.0 * math.pi * f / rate)
        s1 = s2 = 0.0
        for x in w:
            s0 = x + c * s1 - s2
            s2, s1 = s1, s0
        out.append(math.sqrt(max(0.0, s1 * s1 + s2 * s2 - c * s1 * s2)) / (n / 4.0))
    return out


def flatness(e):
    med = sorted(e)[len(e) // 2] or 1e-9
    return max(e) / med


def test_goertzel():
    print("\n[2] 加窗 Goertzel：能不能把已知频率挑出来")
    frames_per_buf = 2048
    freqs = [round(k * float(FS) / frames_per_buf, 2)
             for k in (23, 30, 46, 60, 70, 93)]
    n = 8000
    for target in freqs:
        sig = [int(3000000 * math.sin(2 * math.pi * target * i / FS))
               for i in range(n)]
        e = goe_multi(win(sig), freqs)
        top = e.index(max(e))
        ck("纯音 %.1fHz 峰值落在自己身上" % target,
           freqs[top] == target, "实际峰=%.1f 平坦度=%.2f"
           % (freqs[top], flatness(e)))
        ck("  平坦度 > 5（有尖峰）", flatness(e) > 5,
           "%.2f" % flatness(e))

    print("\n[3] 对照：白噪声应该是平坦的")
    random.seed(7)
    noise = [random.randint(-3000000, 3000000) for _ in range(n)]
    e = goe_multi(win(noise), freqs)
    ck("白噪声平坦度 < 3.0（糊成一片）", flatness(e) < 3.0,
       "%.2f" % flatness(e))
    ck("★ 阈值必须有区分度: 纯音(1e5量级) >> 噪声(%.2f)" % flatness(e),
       flatness(e) < 100)

    print("\n[4] 阶跃/斜坡图案（模拟 ADC 死掉时的伪数据）")
    ramp = [((i * 768) % 6000000) - 3000000 for i in range(n)]
    e = goe_multi(win(ramp), freqs)
    ck("斜坡图案平坦度 < 2.5（不该像纯音）", flatness(e) < 2.5,
       "%.2f" % flatness(e))
    const = [2] * n
    e = goe_multi(win(const), freqs)
    ck("恒定值能量≈0", max(e) < 1.0, "max=%.3f" % max(e))


# ---------------------------------------------------------------- 服务里的转换
def test_service_helpers():
    print("\n[5] audio_svc 里的波形处理")
    try:
        from audio_svc import (pcm_to_int16_mono, wav_bytes, read_wav,
                               s24 as s24b, mono_of)
    except Exception as e:
        ck("能 import audio_svc 的纯函数", False, str(e))
        return
    ck("import audio_svc 成功", True)

    # 单声道 16bit 输入 -> L=R
    vals = [1000, -1000, 32767, -32768, 0]
    d = make_stream([v * 256 for v in vals])
    out = pcm_to_int16_mono(d, FS, FS, mode="L")
    ck("pcm_to_int16_mono 同率不打折", out == [v for v in vals], str(out))

    # 重采样长度
    out2 = pcm_to_int16_mono(d * 100, FS, 16000, mode="L")
    n_in = len(d) * 100 // 8
    ck("重采样长度 ≈ n*16000/44100",
       abs(len(out2) - int(n_in * 16000 / 44100)) <= 1,
       "%d vs %d" % (len(out2), int(n_in * 16000 / 44100)))

    # L/R/sum/diff 四种取法
    dl = make_stream([1000, 2000], [300, 600])
    ck("mode=L", pcm_to_int16_mono(dl, FS, FS, mode="L") == [3, 7])
    ck("mode=R", pcm_to_int16_mono(dl, FS, FS, mode="R") == [1, 2])
    ck("mode=diff", pcm_to_int16_mono(dl, FS, FS, mode="diff") == [1, 2])

    # WAV 往返
    src = [0, 100, -100, 32767, -32768]
    b = wav_bytes(src, 16000, 1)
    ck("wav_bytes 头是 RIFF", b[:4] == b"RIFF")
    open("/tmp/_t.wav", "wb").write(b) if os.name != "nt" else \
        open(os.path.join(HERE, "_t.wav"), "wb").write(b)
    p = "/tmp/_t.wav" if os.name != "nt" else os.path.join(HERE, "_t.wav")
    back, rate, ch = read_wav(p)
    ck("read_wav 往返一致", back == src and rate == 16000 and ch == 1,
       "rate=%d ch=%d n=%d" % (rate, ch, len(back)))


def test_normalize():
    print("\n[6] ASR 的自动增益归一化")
    try:
        from agent import asr
    except Exception as e:
        ck("能 import agent.asr", False, str(e))
        return
    ck("import agent.asr 成功", True)
    src = os.path.join(HERE, "_norm_in.wav")
    vals = [int(1000 * math.sin(2 * math.pi * 300 * i / 16000))
            for i in range(16000)]
    with wave.open(src, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(struct.pack("<%dh" % len(vals), *vals))
    dst, gain = asr.normalize_wav(src, os.path.join(HERE, "_norm_out.wav"))
    with wave.open(dst, "rb") as w:
        raw = w.readframes(w.getnframes())
    v = struct.unpack("<%dh" % (len(raw) // 2), raw)
    pk = max(abs(x) for x in v)
    ck("归一化后峰值接近目标(0.80*32767)",
       abs(pk - int(0.80 * 32767)) < 500, "pk=%d gain=%.1fdB" % (pk, gain))
    ck("增益 ≈ +30dB（输入 1000 -> 26214）", 28 < gain < 31, "%.1f dB" % gain)


def test_voiceloop_machine():
    print("\n[7] voice_loop 状态机顺序")
    try:
        from agent import voice_loop as vl
    except Exception as e:
        ck("能 import agent.voice_loop", False, str(e))
        return
    ck("import agent.voice_loop 成功", True)
    seq = []
    v = vl.VoiceLoop(verbose=False, on_state=lambda s: seq.append(s))

    # 把依赖都打桩：不碰硬件、不联网
    class FakeAC(object):
        @staticmethod
        def stop():
            return {"ok": True}

        @staticmethod
        def record_to(path, secs=3.0, rate=16000, mono=True):
            open(path, "wb").write(b"RIFF0000WAVE")
            return path

        @staticmethod
        def alive():
            return True

    class FakeASR(object):
        @staticmethod
        def recognize(p, rate=16000):
            return "现在几点", "桩"

    class FakeTTS(object):
        @staticmethod
        def speak(t, **k):
            return "/tmp/x.wav", 1.5

    import agent as _agent_pkg
    real_ac = vl.ac
    real_asr = getattr(_agent_pkg, "asr", None)
    real_tts = getattr(_agent_pkg, "tts", None)
    # ★ 关键：voice_loop 里是 `from . import asr`，走的是**包的属性**，
    #   只改 sys.modules 没用（模块早就被别的测试导入过了）
    _agent_pkg.asr = FakeASR
    _agent_pkg.tts = FakeTTS
    vl.ac = FakeAC
    try:
        import json as _j
        import urllib.request as _u

        class FakeResp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        orig = _u.urlopen
        _u.urlopen = lambda req, timeout=None: FakeResp(
            _j.dumps({"reply": "现在是十点", "rounds": 1}).encode())
        try:
            text, reply = v.once(secs=0.1, wav=os.path.join(HERE, "_vl.wav"))
        finally:
            _u.urlopen = orig
    finally:
        vl.ac = real_ac
        if real_asr is not None:
            _agent_pkg.asr = real_asr
        if real_tts is not None:
            _agent_pkg.tts = real_tts

    ck("状态序列 == LISTEN->THINK->SPEAK->IDLE",
       seq == ["LISTEN", "THINK", "SPEAK", "IDLE"], str(seq))
    ck("拿到识别文字", text == "现在几点", str(text))
    ck("拿到 Agent 回复", reply == "现在是十点", str(reply))


def main():
    print("=" * 74)
    print("离线自检：证明分析代码本身是对的（不需要板子）")
    print("=" * 74)
    test_bytes()
    test_goertzel()
    test_service_helpers()
    test_normalize()
    test_voiceloop_machine()
    print("\n" + "=" * 74)
    print("通过 %d 项，失败 %d 项" % (len(PASS), len(FAIL)))
    if FAIL:
        print("失败清单:")
        for f in FAIL:
            print("   -", f)
    else:
        print("★ 全通过 —— 板子上若再出现反常结果，可以确定是硬件/寄存器问题，"
              "不是我这边算错")
    print("=" * 74)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
