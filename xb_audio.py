#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""xb_audio.py —— ★ PC 侧录音/放音（零第三方依赖）

════════════════════════════════════════════════════════════════════
为什么不用 sounddevice / pyaudio
════════════════════════════════════════════════════════════════════
实测这台机器上：
    sounddevice   ✗ 没装
    pyaudio       ✗ 没装
    soundfile     ✗ 没装
    ffmpeg        ✗ 没有

但 Windows【自带 MCI】（Media Control Interface，winmm.dll），
用 ctypes 就能录音 + 放音，不装任何东西：
    ✓ PyInstaller 打包干净（不用带 portaudio 的 DLL）
    ✓ 不用 pip install
    ✓ 能指定 16kHz / 单声道 / 16bit —— 正好是 vosk 要的格式

★ 板子侧 asr.py 用 vosk，要求 16kHz 单声道 16bit PCM wav
  ⇒ 录音参数就按这个设，不用转码。

用法:
    python xb_audio.py --test          # 录 3 秒并检查
    python xb_audio.py --play x.wav
    python xb_audio.py --info x.wav
"""
import ctypes
import ctypes.util
import os
import sys
import tempfile
import time
import wave

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

IS_WIN = (os.name == "nt")

# ★ vosk 要的格式
TARGET_RATE = 16000
TARGET_CH = 1
TARGET_BITS = 16

# ══════════════════════════════════════════════════════════════════
#  ★ 录音后端：优先 sounddevice，退 MCI
# ══════════════════════════════════════════════════════════════════
# 实测（2026-10-02，这台机器）：
#
#   MCI（winmm 自带）：
#       16kHz/mono/16bit   → ✗ "未安装可按当前格式记录文件的波形设备"
#       44.1kHz/mono/16bit → ✗ 同上
#       【系统默认格式】     → ✓ 但只能录到 11025 Hz / 单声道 / 【8 bit】
#   ⇒ 8bit 只有 256 个量化级，喂给 vosk 识别率会明显下降。
#
#   sounddevice（走 MME/WASAPI，需要 portaudio）：
#       ★ 16000 Hz / mono / int16 直接录成功，峰值 3912（真录到声音了）
#   ⇒ 所以默认用 sounddevice；它不在就退 MCI（能跑但音质差，会提示）。
try:
    import sounddevice as _sd
    HAS_SD = True
    SD_WHY = ""
except Exception as _e:                       # noqa: BLE001
    _sd = None
    HAS_SD = False
    SD_WHY = "%s: %s" % (type(_e).__name__, _e)

try:
    import numpy as _np
    HAS_NP = True
except Exception:                             # noqa: BLE001
    _np = None
    HAS_NP = False


# ══════════════════════════════════════════════════════════════════
#  MCI 封装
# ══════════════════════════════════════════════════════════════════
class MciError(Exception):
    pass


class MCI(object):
    """Windows MCI 的薄封装（ctypes 调 winmm.dll）

    ★ 为什么要包一层：mciSendStringW 的错误信息要用 mciGetErrorStringW 取，
      直接看返回值只是一串数字。
    """

    def __init__(self):
        self.ok = False
        self.why = ""
        if not IS_WIN:
            self.why = "不是 Windows（MCI 是 Windows 专有）"
            return
        try:
            self.winmm = ctypes.WinDLL("winmm.dll")
        except Exception as e:
            self.why = "加载 winmm.dll 失败: %s" % e
            return
        self.winmm.mciSendStringW.argtypes = [
            ctypes.c_wchar_p, ctypes.c_wchar_p,
            ctypes.c_uint, ctypes.c_void_p]
        self.winmm.mciSendStringW.restype = ctypes.c_uint
        self.winmm.mciGetErrorStringW.argtypes = [
            ctypes.c_uint, ctypes.c_wchar_p, ctypes.c_uint]
        self.winmm.mciGetErrorStringW.restype = ctypes.c_bool
        self.ok = True

    def send(self, cmd, want_ret=False):
        """发一条 MCI 命令；want_ret=True 时返回返回字符串"""
        if not self.ok:
            raise MciError(self.why)
        buf = ctypes.create_unicode_buffer(512) if want_ret else None
        rc = self.winmm.mciSendStringW(cmd, buf, 512 if buf else 0, None)
        if rc != 0:
            err = ctypes.create_unicode_buffer(512)
            self.winmm.mciGetErrorStringW(rc, err, 512)
            raise MciError("MCI '%s' 失败: %s (rc=%d)"
                           % (cmd.split()[0], err.value or "?", rc))
        return buf.value if buf else ""


_MCI = None


def mci():
    global _MCI
    if _MCI is None:
        _MCI = MCI()
    return _MCI


# ══════════════════════════════════════════════════════════════════
#  wav 工具（标准库 wave，跨平台）
# ══════════════════════════════════════════════════════════════════
def info(path):
    """读 wav 头，返回 dict"""
    try:
        with wave.open(path, "rb") as w:
            n = w.getnframes()
            rate = w.getframerate()
            return {"ok": True, "path": path,
                    "channels": w.getnchannels(),
                    "rate": rate,
                    "bits": w.getsampwidth() * 8,
                    "frames": n,
                    "seconds": round(n / float(rate), 2) if rate else 0,
                    "bytes": os.path.getsize(path)}
    except Exception as e:
        return {"ok": False, "error": "%s: %s" % (type(e).__name__, e)}


def resample_to_target(src, dst=None, rate=TARGET_RATE):
    """把任意 wav 转成 16kHz 单声道 16bit

    ★ 用最朴素的方法：线性插值重采样 + 多声道平均。
      这里【不引入 numpy 以外的东西】，而且 numpy 也可能没打进包里，
      所以纯标准库实现。
      （音质不追求 HiFi —— 只要能喂给 vosk 就够了。）
    """
    return _resample_pure(src, dst, rate)


def _resample_pure(src, dst=None, rate=TARGET_RATE):
    """纯标准库重采样"""
    with wave.open(src, "rb") as w:
        ch = w.getnchannels()
        sw = w.getsampwidth()
        sr = w.getframerate()
        raw = w.readframes(w.getnframes())
    if sw != 2:
        # 只支持 16bit（MCI 录出来就是 16bit）
        raise ValueError("只支持 16bit wav（这个文件是 %d bit）" % (sw * 8))
    # 多声道 -> 单声道
    if ch == 2:
        import array
        a = array.array("h")
        a.frombytes(raw)
        mono = array.array("h", [(a[i] + a[i + 1]) // 2
                                 for i in range(0, len(a) - 1, 2)])
        samples = mono
    else:
        import array
        samples = array.array("h")
        samples.frombytes(raw)
    # 重采样（线性插值）
    if sr != rate and len(samples) > 1:
        import array
        n_out = int(len(samples) * float(rate) / sr)
        out = array.array("h", [0]) * n_out
        ratio = float(sr) / rate
        for i in range(n_out):
            x = i * ratio
            i0 = int(x)
            i1 = min(i0 + 1, len(samples) - 1)
            frac = x - i0
            out[i] = int(samples[i0] * (1 - frac) + samples[i1] * frac)
        samples = out
    if dst is None:
        dst = os.path.join(tempfile.gettempdir(), "xb_16k.wav")
    with wave.open(dst, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(samples.tobytes())
    return dst


def peak(path):
    """返回峰值（0~32767）—— 用来判断"是不是录到了静音" """
    try:
        with wave.open(path, "rb") as w:
            if w.getsampwidth() != 2:
                return None
            import array
            a = array.array("h")
            a.frombytes(w.readframes(w.getnframes()))
            return max(abs(v) for v in a) if a else 0
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════════
#  录音 —— ★ 优先 sounddevice，退 MCI
# ══════════════════════════════════════════════════════════════════
class Recorder(object):
    """录音（后台进行，stop() 时落盘）

    ★ 两个后端，自动选：
      ① sounddevice —— 直接录 16kHz/mono/int16（vosk 要的格式），音质好
      ② MCI        —— 系统自带，但实测只能录 11025Hz/mono/【8bit】，
                      音质差，喂 vosk 识别率会掉。作为兜底。

    ★ 为什么要"后台录音 + stop 时落盘"而不是阻塞录 N 秒：
      界面上是「按住说话 / 点一下开始、再点一下结束」，
      录音期间 UI 还要响应（不然会卡住），所以必须后台跑。
    """

    ALIAS = "xbrec"

    def __init__(self, prefer=None):
        # prefer: None 自动 / "sd" / "mci"
        self.prefer = prefer
        self.active = False
        self.path = None
        self.t0 = 0.0
        self.backend = None
        self.why = ""
        self._stream = None
        self._chunks = []

    # ---------- 后端选择 ----------
    def _pick(self):
        if self.prefer == "sd":
            return "sd" if HAS_SD else None
        if self.prefer == "mci":
            return "mci" if mci().ok else None
        if HAS_SD:
            return "sd"
        if mci().ok:
            return "mci"
        return None

    # ---------- 开始 ----------
    def start(self, path=None):
        if self.active:
            self.stop()
        if path is None:
            path = os.path.join(tempfile.gettempdir(), "xb_rec.wav")
        path = os.path.abspath(path)
        d = os.path.dirname(path)
        if d and not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)
        if os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass
        self.path = path
        self._chunks = []
        self.backend = self._pick()
        self.why = ""
        if self.backend is None:
            self.why = ("没有可用录音后端（sounddevice: %s；MCI: %s）"
                        % (SD_WHY or "无", mci().why or "不可用"))
            raise MciError(self.why)

        if self.backend == "sd":
            self._start_sd()
        else:
            self._start_mci()
        self.active = True
        self.t0 = time.time()
        return path

    def _start_sd(self):
        """sounddevice：开一个输入流，回调里收数据"""
        def cb(indata, frames, t, status):
            # indata 是 numpy int16 (frames, 1)
            self._chunks.append(indata.copy())

        self._stream = _sd.InputStream(
            samplerate=TARGET_RATE, channels=TARGET_CH,
            dtype="int16", callback=cb, blocksize=0)
        self._stream.start()

    def _start_mci(self):
        m = mci()
        try:
            m.send("close %s" % self.ALIAS)
        except Exception:
            pass
        m.send("open new type waveaudio alias %s" % self.ALIAS)
        # ★ 实测：指定 16k/16bit 会报
        #   "未安装可按当前格式记录文件的波形设备"，
        #   所以【不设格式】，用系统默认（这台机器是 11025/8bit），
        #   录完再 resample 到 16k/16bit。
        self.why = ("MCI 只能录 11025Hz/8bit（音质差）—— "
                    "装 sounddevice 可以得到 16kHz/16bit")
        m.send("record %s" % self.ALIAS)

    # ---------- 状态 ----------
    def elapsed(self):
        return time.time() - self.t0 if self.active else 0.0

    def level(self):
        """当前录音的峰值（0~1），用于界面上画音量条"""
        if not self.active or not self._chunks:
            return 0.0
        try:
            last = self._chunks[-1]
            if HAS_NP:
                import numpy as _n
                return min(1.0, float(_n.abs(last).max()) / 32768.0)
        except Exception:
            pass
        return 0.0

    # ---------- 停止 ----------
    def stop(self):
        """停止并保存，返回 (path, 秒数)"""
        if not self.active:
            return None, 0.0
        secs = time.time() - self.t0
        self.active = False
        if self.backend == "sd":
            self._stop_sd()
        else:
            self._stop_mci()
        return self.path, secs

    def _stop_sd(self):
        try:
            if self._stream is not None:
                self._stream.stop()
                self._stream.close()
        except Exception:
            pass
        self._stream = None
        # 拼起来写 wav
        if not self._chunks:
            raise MciError("没录到任何数据（麦克风被占用？）")
        import numpy as _n
        data = _n.concatenate(self._chunks, axis=0)
        with wave.open(self.path, "wb") as w:
            w.setnchannels(TARGET_CH)
            w.setsampwidth(2)
            w.setframerate(TARGET_RATE)
            w.writeframes(data.astype("<i2").tobytes())

    def _stop_mci(self):
        m = mci()
        try:
            m.send("stop %s" % self.ALIAS)
        except Exception:
            pass
        raw = self.path + ".mci.wav"
        m.send('save %s "%s"' % (self.ALIAS, raw))
        try:
            m.send("close %s" % self.ALIAS)
        except Exception:
            pass
        # ★ MCI 录出来是 11025/8bit，转成 16k/16bit 再交给上面
        try:
            _resample_pure(raw, self.path, TARGET_RATE)
        except Exception:
            # 转不了就直接用原文件（至少还能放）
            try:
                os.replace(raw, self.path)
            except Exception:
                pass
            raise
        try:
            os.remove(raw)
        except Exception:
            pass

    def cancel(self):
        """丢弃这次录音"""
        if not self.active:
            return
        self.active = False
        if self.backend == "sd":
            try:
                if self._stream is not None:
                    self._stream.abort()
                    self._stream.close()
            except Exception:
                pass
            self._stream = None
        else:
            m = mci()
            try:
                m.send("stop %s" % self.ALIAS)
            except Exception:
                pass
            try:
                m.send("close %s" % self.ALIAS)
            except Exception:
                pass
        self._chunks = []


def record(seconds, path=None):
    """录固定秒数（阻塞）"""
    r = Recorder()
    r.start(path)
    time.sleep(seconds)
    return r.stop()


# ══════════════════════════════════════════════════════════════════
#  放音
# ══════════════════════════════════════════════════════════════════
def play(path, block=False):
    """播放 wav

    ★ 用 winsound.PlaySound —— 标准库，支持异步。
      它只认 wav（这也正好是我们的格式）。
      非 Windows 上退回 MCI。
    """
    if not os.path.exists(path):
        raise IOError("找不到 %s" % path)
    if IS_WIN:
        import winsound
        flags = winsound.SND_FILENAME
        if not block:
            flags |= winsound.SND_ASYNC
        winsound.PlaySound(path, flags)
        return True
    # 非 Windows：MCI
    m = mci()
    m.send('open "%s" alias xbplay' % path)
    m.send("play xbplay")
    if block:
        m.send("close xbplay")
    return True


def stop_play():
    if IS_WIN:
        import winsound
        winsound.PlaySound(None, winsound.SND_PURGE)
        return
    try:
        mci().send("close xbplay")
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════
#  给板子用的打包（base64）
# ══════════════════════════════════════════════════════════════════
def wav_to_b64(path):
    import base64
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


def b64_to_wav(b64, path):
    import base64
    raw = base64.b64decode(b64)
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)
    with open(path, "wb") as f:
        f.write(raw)
    return path


# ══════════════════════════════════════════════════════════════════
#  自测
# ══════════════════════════════════════════════════════════════════
def selftest(do_record=True):
    print("=" * 70)
    print(" PC 侧录音/放音自测")
    print("=" * 70)
    ok = True

    def chk(c, m, d=""):
        nonlocal ok
        print("   %s %s%s" % ("✓" if c else "✗", m, ("   " + d) if d else ""))
        ok = ok and c

    print()
    print("【1】环境")
    chk(IS_WIN, "Windows 平台")
    m = mci()
    chk(m.ok, "MCI 可用", m.why or "winmm.dll 加载成功")
    try:
        import winsound  # noqa: F401
        chk(True, "winsound 可用")
    except Exception as e:
        chk(False, "winsound", str(e))

    if not do_record or not m.ok:
        print()
        print(" 总体: %s" % ("★ 通过" if ok else "★ 有问题"))
        return ok

    print()
    print("【2】录音 3 秒（★ 请对着麦克风说点话）")
    path = os.path.join(tempfile.gettempdir(), "xb_audio_test.wav")
    try:
        p, secs = record(3.0, path)
        chk(os.path.exists(p), "录到文件", p)
        i = info(p)
        print("     格式: %d Hz / %d 声道 / %d bit / %.2f 秒"
              % (i.get("rate"), i.get("channels"), i.get("bits"),
                 i.get("seconds")))
        chk(i.get("ok"), "wav 头合法")
        pk = peak(p)
        chk(pk is not None and pk > 100, "录到了声音（不是静音）",
            "峰值 %s / 32767" % pk)
    except Exception as e:
        chk(False, "录音", "%s: %s" % (type(e).__name__, e))

    print()
    print("【3】重采样到 16k 单声道（vosk 要的格式）")
    try:
        p2 = _resample_pure(path)
        i2 = info(p2)
        print("     %s" % p2)
        print("     %d Hz / %d 声道 / %d bit / %.2f 秒"
              % (i2["rate"], i2["channels"], i2["bits"], i2["seconds"]))
        chk(i2["rate"] == TARGET_RATE and i2["channels"] == 1,
            "格式正确（16kHz 单声道）")
    except Exception as e:
        chk(False, "重采样", "%s: %s" % (type(e).__name__, e))

    print()
    print("【4】base64 往返")
    try:
        b = wav_to_b64(path)
        p3 = b64_to_wav(b, os.path.join(tempfile.gettempdir(), "xb_rt.wav"))
        chk(os.path.getsize(p3) == os.path.getsize(path),
            "解码后大小一致", "%d 字节" % len(b))
    except Exception as e:
        chk(False, "base64", str(e))

    print()
    print("【5】放音（应该能听到刚才录的）")
    try:
        play(path)
        time.sleep(3.5)
        chk(True, "播放没报错")
    except Exception as e:
        chk(False, "放音", "%s: %s" % (type(e).__name__, e))

    print()
    print("=" * 70)
    print(" 总体: %s" % ("★ 全部通过" if ok else "★ 有问题"))
    print("=" * 70)
    return ok


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--no-record", action="store_true")
    ap.add_argument("--play", metavar="WAV")
    ap.add_argument("--info", metavar="WAV")
    ap.add_argument("--record", type=float, metavar="SECS")
    a = ap.parse_args()
    if a.play:
        play(a.play, block=True)
        return 0
    if a.info:
        print(info(a.info))
        return 0
    if a.record:
        p, s = record(a.record)
        print("%s  (%.1fs)" % (p, s))
        print(info(p))
        return 0
    return 0 if selftest(do_record=not a.no_record) else 1


if __name__ == "__main__":
    sys.exit(main() or 0)
