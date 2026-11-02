#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""asr.py —— 语音识别（把录到的 WAV 变成文字）

★ 优先**离线 vosk**（板子上装一次就能用，不依赖网络/密钥）：
      sudo pip3 install vosk
      # 中文小模型 ~42MB，解压到 /home/zynq/vosk-model-small-cn-0.22
      https://alphacephei.com/vosk/models/vosk-model-small-cn-0.22.zip
  退路是百度 ASR（需要有效密钥，目前 ESP 那套已失效 401）。

用法:
    python3 -m agent.asr /tmp/x.wav
"""
import json
import math
import os
import wave

MODEL_DIR = os.environ.get("VOSK_MODEL",
                           "/home/zynq/vosk-model-small-cn-0.22")
_model = None


def vosk_available():
    if not os.path.isdir(MODEL_DIR):
        return False
    try:
        import vosk                                            # noqa: F401
        return True
    except Exception:
        return False


def _get_model():
    global _model
    if _model is None:
        import vosk
        vosk.SetLogLevel(-1)
        _model = vosk.Model(MODEL_DIR)
    return _model


def normalize_wav(src, dst=None, target=0.80):
    """自动增益归一化 —— 送识别前**必须**做。

    实测：板载喇叭放出来的语音，麦克风回录的峰值只有满量程的 4~5%
    （小喇叭低频弱 + 麦克风灵敏度低）。不归一化的话 vosk 几乎认不出。
    这里把峰值拉到 target 满量程，噪声底也跟着放大，但语音/噪声比不变，
    而识别引擎对绝对电平是敏感的。
    """
    import struct
    dst = dst or (src + ".norm.wav")
    with wave.open(src, "rb") as w:
        ch, sw, fr, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    if sw != 2 or ch != 1:
        raise RuntimeError("normalize 只支持单声道16bit")
    v = list(struct.unpack("<%dh" % (len(raw) // 2), raw))
    pk = max((abs(x) for x in v), default=0)
    if pk < 1:
        return src, 0.0
    gain = (target * 32767.0) / pk
    gain = min(gain, 64.0)                  # 最多 36dB，别把纯噪声也拉爆
    out = [max(-32768, min(32767, int(x * gain))) for x in v]
    with wave.open(dst, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(fr)
        w.writeframes(struct.pack("<%dh" % len(out), *out))
    return dst, 20 * math.log10(gain)


def recognize_vosk(wav_path, rate=16000, normalize=True):
    """离线识别。返回文字（可能为空串）。"""
    import vosk
    if normalize:
        try:
            wav_path, _ = normalize_wav(wav_path)
        except Exception:
            pass
    m = _get_model()
    with wave.open(wav_path, "rb") as w:
        ch = w.getnchannels()
        sw = w.getsampwidth()
        fr = w.getframerate()
    if ch != 1 or sw != 2:
        raise RuntimeError("vosk 需要单声道 16bit WAV，收到 ch=%d width=%d"
                           % (ch, sw))
    rec = vosk.KaldiRecognizer(m, fr)
    with wave.open(wav_path, "rb") as w:
        while True:
            data = w.readframes(4000)
            if not data:
                break
            rec.AcceptWaveform(data)
    return (json.loads(rec.FinalResult()).get("text") or "").strip()


def recognize(wav_path, rate=16000, engine=None):
    """统一入口。返回 (文字, 用的引擎)。

    ★ 顺序（2026-09-28 实测后调整）：**百度优先，vosk 兜底**
      同一段板载录音：
          百度 -> "我在吃饭，你怎么说出来了？你这个5000。"   err_no=0
          vosk -> "法"（把"现在几点"认成这样）
      所以瓶颈是离线引擎，不是麦克风。百度只在联网时可用，
      断网时自动退回 vosk，保证还能用。

    engine 参数：auto(默认) / baidu / vosk
    """
    eng = (engine or os.environ.get("ASR_ENGINE") or "auto").lower()

    if eng in ("auto", "baidu"):
        try:
            from . import tts               # 百度那条路在 tts.py 里
            return tts.recognize(wav_path, rate=rate), "百度(在线)"
        except Exception as e:
            if eng == "baidu":
                raise
            last = e
    else:
        last = None

    try:
        return recognize_vosk(wav_path, rate), "vosk(离线兜底)"
    except Exception as e:
        raise RuntimeError("识别全部失败。百度: %s；vosk: %s" % (last, e))


# ══════════════════════════════════════════════════════════════════
#  ★★★ 静音检测 / 句子切分（2026-10-03 加）
# ══════════════════════════════════════════════════════════════════
# 为什么需要它 —— 流式语音的"最后一公里"
# ──────────────────────────────────────────────────────────────────
# 桌面 App 的「按住说话」是这样做的：后台每 1.2 秒向音频服务要一份
# "从头到现在"的录音快照，整段送 ASR，用最新结果覆盖输入框。
#
# 实测（2.89 秒的「现在几点了帮我看看」）：
#     1.2s -> "现在几点了？"            1.1 秒
#     2.4s -> "现在几点了？帮我看看。"   0.6 秒
#     2.9s -> "现在几点了？帮我看看。"   0.5 秒
# 短句完全没问题，而且比音频本身还快（2.2s vs 2.89s）。
#
# ★ 但长句会塌：每次送的都是【从头到现在】的整段 ——
#   说到 20 秒时每次要传 ~640KB，百度要处理 2~3 秒，
#   识别结果开始落后于嘴，越说越滞后（而且百度短语音上限 60 秒）。
#
# ★ 解法就是真流式的做法：**用静音把话切成句**。
#   已说完的句子（后面跟了足够长的静音）【定稿】——只识别一次、缓存住；
#   只有最后那句（还没说完的）需要每次重识别。
#   每句都短 ⇒ 又快又准，而且说多久都不会越拖越慢。
#
# ★ 为什么手写而不用现成库：
#     · 板子上【没有 numpy】（1GB 内存，不想为这个装）
#     · PC 上【没有 audioop】（Python 3.13 已按 PEP 594 移除）
#   ⇒ 用 struct 解 int16 + 自己算 RMS。20ms 一帧，代码不多，够用。
# ══════════════════════════════════════════════════════════════════

FRAME_MS = 20                 # 能量计算帧长
# ★★★ 多长的静音才算"一句说完了"（2026-10-03 从 0.45 调到 0.85）
# ────────────────────────────────────────────────────────────────
# 用户反馈："速度是快了，准确率不太行啊，稍微长一点就不对"
#
# 排查过程：用 TTS 合成的 2s/3.9s/7.9s 三段音频测，
#   整段识别和 VAD 分句识别【结果完全一致且全对】——
#   说明切分逻辑本身没错。
#   但这些合成音频有个共同点：**中间没有停顿**（只有结尾静音），
#   所以 VAD 只切出了一个边界，等于没切。
#
# 而真人说话不一样：长句里全是自然停顿（呼吸、思考、"嗯…"）。
#   0.45 秒的阈值会把"帮我看看 / 今天天气 / 怎么样"切成三段，
#   每段单独送百度 ⇒ **失去上下文** ⇒ 长句开始出错。
#   （短句没这个风险，所以"短的对、稍微长一点就不对"。）
#
# ⇒ 阈值提到 0.85 秒：只在【真的说完了】的地方切。
#   配合下面 last_boundary 的"多带上下文"，切出来的段也带前后文。
# ────────────────────────────────────────────────────────────────
MIN_SIL_SEC = 0.85            # 多长的静音才算"一句说完了"
SIL_RATIO = 0.06              # 静音阈值 = 峰值帧能量 * 这个比例
CTX_SEC = 0.35                # ★ 定稿段前后各多带这么多秒的上下文


def read_wav_mono(path):
    """读 WAV -> (int16 列表, 采样率)。读不了返回 ([], 0)"""
    try:
        with wave.open(path, "rb") as w:
            ch = w.getnchannels()
            sw = w.getsampwidth()
            rate = w.getframerate()
            n = w.getnframes()
            raw = w.readframes(n)
    except Exception:
        return [], 0
    if sw != 2:
        return [], 0
    import struct
    try:
        s = list(struct.unpack("<%dh" % (len(raw) // 2), raw[:len(raw) // 2 * 2]))
    except Exception:
        return [], 0
    if ch == 2:
        s = [(s[i] + s[i + 1]) // 2 for i in range(0, len(s) - 1, 2)]
    return s, rate


def frame_energy(samples, rate, frame_ms=FRAME_MS):
    """逐帧 RMS 能量（返回 [float, ...]，一帧一个值）"""
    step = max(1, int(rate * frame_ms / 1000.0))
    out = []
    for i in range(0, len(samples) - step + 1, step):
        acc = 0
        for v in samples[i:i + step]:
            acc += v * v
        out.append(math.sqrt(acc / step))
    return out


def sentence_boundaries(samples, rate,
                        min_sil=MIN_SIL_SEC, ratio=SIL_RATIO):
    """返回"句边界"的位置（采样点下标列表）

    做法：逐帧算能量 -> 阈值 = 峰值 * ratio -> 找连续 >=min_sil 的
    低能量段 -> 每段的中点就是一个句边界。
    """
    if not samples or rate <= 0:
        return []
    en = frame_energy(samples, rate)
    if not en:
        return []
    peak = max(en)
    if peak <= 0:
        return []
    th = peak * ratio
    step = max(1, int(rate * FRAME_MS / 1000.0))
    need = max(1, int(min_sil * 1000.0 / FRAME_MS))   # 需要连续几帧静音
    bounds = []
    run = 0
    run_start = 0
    for i, e in enumerate(en):
        if e < th:
            if run == 0:
                run_start = i
            run += 1
        else:
            if run >= need:
                mid = run_start + run // 2
                bounds.append(min(len(samples) - 1, mid * step))
            run = 0
    if run >= need:      # 结尾那段静音也算（说明最后一句已经说完）
        mid = run_start + run // 2
        bounds.append(min(len(samples) - 1, mid * step))
    return bounds


def last_boundary(wav_path):
    """★ 流式专用：返回"最后一个句边界"的秒数（没有则 0）

    桌面 App 每轮拿快照后调它：
        b = last_boundary("/tmp/snap.wav")
        if b > 已定稿位置:
            已定稿 += ASR(音频[已定稿位置 : b])     ← 只做一次，缓存
        当前句 = ASR(音频[b : 末尾])                ← 每轮重做
        显示   = 已定稿文字 + 当前句文字
    """
    s, rate = read_wav_mono(wav_path)
    if not s or rate <= 0:
        return 0.0
    b = sentence_boundaries(s, rate)
    return (b[-1] / float(rate)) if b else 0.0


def rms_of(wav_path):
    """这段音频的 RMS 能量（读不了返回 0）

    ★★★ 为什么需要它 —— 踩到的真 bug（2026-10-03）：
    ────────────────────────────────────────────────
    用已知音频「现在几点了帮我看看」跑流式，VAD 把 2.46 秒处切成边界，
    于是：
        定稿段 [0, 2.46)    -> "现在几点了？帮我看看。"   ← 对
        当前段 [2.46, 末尾) -> "我知道。"                ← ★ 凭空多出来的
    尾部那 0.4 秒是【纯静音】，但百度对静音会**幻觉**出文字。
    合成起来输入框里就多了一句不存在的话。

    ⇒ 送 ASR 之前先量一下能量：低于阈值就不送（当它是静音）。
    ★ 阈值取 100：实测真实说话的 16kHz/16bit 音频 RMS 在 800~3000，
      板子自己的底噪在 50 以下，100 这个位置分得很开。
    """
    s, rate = read_wav_mono(wav_path)
    if not s:
        return 0.0
    acc = 0
    for v in s:
        acc += v * v
    return math.sqrt(acc / len(s))


# ★ 低于这个 RMS 的音频不送 ASR（静音幻觉）
SPEECH_RMS = 100.0


def has_speech(wav_path, thresh=SPEECH_RMS):
    """这段音频里有没有"像人说话"的东西（够不够响）"""
    return rms_of(wav_path) >= thresh


def slice_wav(src, dst, start_sec, end_sec=None, ctx=0.0):
    """把 src 的 [start_sec, end_sec) 切出来写成 dst（16bit 单声道）

    流式识别用：已定稿的那段只识别一次，之后只重识别"当前句"。
    ★ 返回是否切成功。切不动（参数不合理/读不了）就返回 False，
      调用方可以退回"整段识别"。

    ctx > 0 时前后各多带 ctx 秒（★ 2026-10-03 加）：
      切在静音中间虽然不会切到词，但把【前后文】一起给百度，
      它给的结果明显更稳（尤其是句尾的语气词、连读）。
      多带的部分不影响结果 —— 静音里没有可识别的字。
    """
    try:
        with wave.open(src, "rb") as w:
            ch, sw, rate, n = (w.getnchannels(), w.getsampwidth(),
                               w.getframerate(), w.getnframes())
            if sw != 2 or rate <= 0:
                return False
            i0 = max(0, int((start_sec - ctx) * rate))
            i1 = n if end_sec is None else min(n, int((end_sec + ctx) * rate))
            if i1 <= i0:
                return False
            w.setpos(i0)
            raw = w.readframes(i1 - i0)
    except Exception:
        return False
    if ch == 2:
        import struct
        s = struct.unpack("<%dh" % (len(raw) // 2), raw[:len(raw) // 2 * 2])
        s = [(s[i] + s[i + 1]) // 2 for i in range(0, len(s) - 1, 2)]
        raw = struct.pack("<%dh" % len(s), *s)
    try:
        with wave.open(dst, "wb") as o:
            o.setnchannels(1)
            o.setsampwidth(2)
            o.setframerate(rate)
            o.writeframes(raw)
        return True
    except Exception:
        return False


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 2 and sys.argv[1] == "--bounds":
        s, rate = read_wav_mono(sys.argv[2])
        b = sentence_boundaries(s, rate)
        print("采样点:", len(s), " 采样率:", rate,
              " 时长: %.2fs" % (len(s) / float(rate or 1)))
        print("句边界(秒):", ["%.2f" % (x / float(rate or 1)) for x in b])
        sys.exit(0)
    p = sys.argv[1] if len(sys.argv) > 1 else "/tmp/xiaobai_heard.wav"
    print("模型目录:", MODEL_DIR, "可用:", vosk_available())
    t, e = recognize(p)
    print("引擎=%s  识别结果: %r" % (e, t))
