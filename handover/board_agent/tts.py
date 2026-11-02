#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tts.py —— 系统管家小白的"嘴"和"耳朵"（百度语音）

* `speak(text)`  : 文字 -> 百度 TTS -> WAV -> 交给板载音频服务播出来
* `listen(secs)` : 板载麦克风录一段 -> 百度 ASR -> 文字

密钥从环境变量取（优先）或从 ESP 那份源码里读，避免把 key 写进仓库：
    BAIDU_API_KEY / BAIDU_SECRET_KEY
"""
import base64
import io
import json
import os
import re
import ssl
import time
import wave
import urllib.parse
import urllib.request

from . import audio_client as ac

TOKEN_URL = "https://aip.baidubce.com/oauth/2.0/token"
TTS_URL = "https://tsn.baidu.com/text2audio"
ASR_URL = "https://vop.baidu.com/server_api"

ESP_SRC = os.environ.get(
    "ESP_SRC", "/home/zynq/esp32_ref/main.cpp")

_token = {"v": None, "t": 0.0}

# ★ 板子的系统 CA 用不了（实测 CERTIFICATE_VERIFY_FAILED，老 armhf 镜像常见）。
#   先试正常校验，失败再退回不校验 —— 和 agent/llm.py 里的做法一致。
_CAFILES = ["/etc/ssl/certs/ca-certificates.crt",
            "/etc/pki/tls/certs/ca-bundle.crt",
            "/etc/ssl/cert.pem"]


def _urlopen(req, timeout):
    ctxs = []
    for c in _CAFILES:
        if os.path.exists(c):
            try:
                ctxs.append(ssl.create_default_context(cafile=c))
            except Exception:
                pass
    try:
        ctxs.append(ssl.create_default_context())
    except Exception:
        pass
    err = None
    for ctx in ctxs:
        try:
            return urllib.request.urlopen(req, timeout=timeout, context=ctx)
        except Exception as e:
            err = e
    try:
        return urllib.request.urlopen(req, timeout=timeout,
                                      context=ssl._create_unverified_context())
    except Exception:
        raise err if err else RuntimeError("urlopen 失败")


# ---------------------------------------------------------------- 密钥

def _grep_key(text, name):
    m = re.search(r'#define\s+%s\s+"([^"]+)"' % name, text)
    return m.group(1) if m else ""


# ★★★ 密钥文件的候选位置（2026-10-03 加）
# ────────────────────────────────────────────────────────────────
# 为什么加这个 —— 这是"语音识别不准"的根因：
#
#   密钥本来只靠【环境变量】传，而环境变量是 systemd 注入的：
#       zynq-agent.service:  EnvironmentFile=-/etc/zynq-baidu.env   ✓ 有
#       zynq-desktop.service: （没有这一行）                        ✗ 没有
#
#   桌面 App（apps_agent.py）是跑在 zynq-desktop 里的 ⇒ 它的环境里
#   没有 BAIDU_API_KEY ⇒ tts._keys() 抛异常 ⇒ asr.recognize() 退回
#   vosk（离线）⇒ 识别率一塌糊涂（实测把"现在几点"认成"法"）。
#
#   ⇒ 不能指望"谁启动我就给我配好环境变量"。直接自己读文件，
#     谁调用都能拿到密钥。这样改代码比改部署更可靠 ——
#     以后再有新服务跑语音，也不用记得配 EnvironmentFile。
_ENV_FILES = (
    "/etc/zynq-baidu.env",              # 板子上放密钥的地方
    "/etc/zynq-agent.env",
)


def _load_env_files():
    """从密钥文件里补环境变量（找不到就算了，不报错）

    ★ 格式就是 KEY=VALUE 一行一条，允许 # 注释和引号。
    ★ 只在环境变量【还没有】该键时才填 —— 不覆盖调用方显式设的值。
    """
    for p in _ENV_FILES:
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, _, v = line.partition("=")
                    k = k.strip()
                    v = v.strip().strip('"').strip("'")
                    if k and v and not os.environ.get(k):
                        os.environ[k] = v
        except Exception:
            continue


def _keys():
    k = os.environ.get("BAIDU_API_KEY", "")
    s = os.environ.get("BAIDU_SECRET_KEY", "")
    if k and s:
        return k, s
    # ★ 环境变量没有 -> 自己从文件里读（桌面 App 走的就是这条路）
    _load_env_files()
    k = os.environ.get("BAIDU_API_KEY", "")
    s = os.environ.get("BAIDU_SECRET_KEY", "")
    if k and s:
        return k, s
    for p in (ESP_SRC, os.path.join(os.path.dirname(__file__), "esp32", "src", "main.cpp")):
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                t = f.read()
            k = k or _grep_key(t, "BAIDU_API_KEY")
            s = s or _grep_key(t, "BAIDU_SECRET_KEY")
            if k and s:
                break
        except Exception:
            continue
    if not k or not s:
        raise RuntimeError("没有百度密钥：请设置 BAIDU_API_KEY / BAIDU_SECRET_KEY "
                           "环境变量，或放一份到 %s，"
                           "或把 ESP 源码放到 %s"
                           % (_ENV_FILES[0], ESP_SRC))
    return k, s


def token(force=False):
    """拿 access_token（缓存 25 天）"""
    if not force and _token["v"] and time.time() - _token["t"] < 25 * 86400:
        return _token["v"]
    k, s = _keys()
    q = urllib.parse.urlencode({"grant_type": "client_credentials",
                                "client_id": k, "client_secret": s})
    with _urlopen(TOKEN_URL + "?" + q, 20) as r:
        d = json.loads(r.read().decode("utf-8"))
    if "access_token" not in d:
        raise RuntimeError("拿 access_token 失败: %s" % d)
    _token["v"] = d["access_token"]
    _token["t"] = time.time()
    return _token["v"]


# ---------------------------------------------------------------- TTS

# ★ 优先用**离线** espeak-ng。
#   原因：ESP 那套百度密钥已经失效（实测 oauth 返回 401 invalid_client:
#   "unknown client id"），而且答辩/演示现场不一定有网。espeak-ng 装了就有，
#   一条命令：sudo apt-get install -y espeak-ng
ESPEAK = "/usr/bin/espeak-ng"
ESPEAK_VOICE = os.environ.get("ESPEAK_VOICE", "cmn")     # 普通话
ESPEAK_SPEED = os.environ.get("ESPEAK_SPEED", "160")


def _espeak(text, out_path, voice=None, speed=None):
    import subprocess
    if not os.path.exists(ESPEAK):
        raise RuntimeError("没装 espeak-ng（sudo apt-get install -y espeak-ng）")
    cmd = [ESPEAK, "-v", voice or ESPEAK_VOICE,
           "-s", str(speed or ESPEAK_SPEED), "-w", out_path, text]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       timeout=60)
    if p.returncode != 0:
        raise RuntimeError("espeak-ng 失败(%d): %s"
                           % (p.returncode,
                              p.stdout.decode("utf-8", "replace")[:200]))
    if not os.path.exists(out_path) or os.path.getsize(out_path) < 100:
        raise RuntimeError("espeak-ng 没产出有效 WAV")
    return out_path


def synth(text, out_path="/tmp/xiaobai_say.wav", per=0, spd=5, pit=5, vol=15,
          aue=6, timeout=40, engine=None):
    """文字 -> WAV 文件，返回路径。

    ★ 顺序（2026-09-28 实测后调整）：**百度优先，espeak 兜底**
      百度是自然语音，espeak 是机器音（之前 ASR 识别不准的帮凶之一）。
      实测百度 vol 参数（板上升级过）：
          vol=5  RMS 2429  峰值 12831
          vol=15 RMS 4858  峰值 25662   = +6 dB  ← 现在默认这个
      断网时自动退回 espeak-ng（离线，装了就有）。

    engine: None/"auto" 自动（先百度，失败再试离线 espeak-ng）
            "espeak" 只用离线；"baidu" 只用百度（需要有效密钥）
    per: 0=度小满女声 1=度小满男声 3=度逍遥 4=度丫丫  （仅百度引擎）
    aue: 6=wav 3=mp3 4=pcm16k                        （仅百度引擎）
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("要合成的文字是空的")
    eng = (engine or os.environ.get("TTS_ENGINE") or "auto").lower()

    last = None
    if eng in ("auto", "baidu"):
        try:
            return _baidu_synth(text, out_path, per, spd, pit, vol, aue,
                                timeout)
        except Exception as e:
            if eng == "baidu":
                raise
            last = e

    try:
        return _espeak(text[:1200], out_path)
    except Exception as e:
        raise RuntimeError("TTS 全部失败。百度: %s；离线 espeak-ng: %s"
                           % (last, e))


def _baidu_synth(text, out_path, per, spd, pit, vol, aue, timeout):
    text = text[:900]                       # 百度单次上限约 1024 字节
    tok = token()
    data = urllib.parse.urlencode({
        "tex": text,
        "tok": tok,
        "cuid": "zynq7020-xiaobai",
        "ctp": 1,
        "lan": "zh",
        "spd": spd, "pit": pit, "vol": vol,
        "per": per,
        "aue": aue,
    }).encode("utf-8")
    req = urllib.request.Request(TTS_URL, data=data, headers={
        "Content-Type": "application/x-www-form-urlencoded"})
    with _urlopen(req, timeout) as r:
        ctype = r.headers.get("Content-Type", "")
        body = r.read()
    if "json" in ctype or body[:1] in (b"{", b"["):
        raise RuntimeError("百度 TTS 返回错误: %s"
                           % body.decode("utf-8", "replace")[:300])
    if not body.startswith(b"RIFF"):
        raise RuntimeError("百度 TTS 没给 WAV（Content-Type=%s, 头=%r）"
                           % (ctype, body[:8]))
    with open(out_path, "wb") as f:
        f.write(body)
    return out_path


def speak(text, per=0, block=True, out_path="/tmp/xiaobai_say.wav"):
    """合成并**从板载喇叭说出来**。返回 (wav 路径, 秒数)。"""
    p = synth(text, out_path=out_path, per=per)
    try:
        with wave.open(p, "rb") as w:
            secs = w.getnframes() / float(w.getframerate() or 16000)
    except Exception:
        secs = 2.0
    r = ac.play_file(p)
    return p, r.get("secs", secs)


# ---------------------------------------------------------------- ASR

def recognize(wav_path, rate=16000, timeout=40):
    """一段 16k 单声道 WAV -> 文字。

    ★ 目前只能走百度，而**ESP 那套密钥已失效**（oauth 401 invalid_client）。
      所以听写暂时不可用；录音本身是好的（见 14_音频勘验/实测报告_录音通路打通.md），
      缺的只是识别引擎。离线方案：装 vosk + 中文小模型（约 40MB）。
    """
    with open(wav_path, "rb") as f:
        speech = f.read()
    try:
        tok = token()
    except Exception as e:
        raise RuntimeError(
            "语音识别不可用：拿不到百度 token（%s）。"
            "录音文件在 %s，可以用别的方式识别；"
            "要离线识别请装 vosk + 中文小模型。" % (e, wav_path))
    body = json.dumps({
        "format": "wav",
        "rate": int(rate),
        "channel": 1,
        "cuid": "zynq7020-xiaobai",
        "token": tok,
        "speech": base64.b64encode(speech).decode("ascii"),
        "len": len(speech),
    }).encode("utf-8")
    req = urllib.request.Request(ASR_URL, data=body, headers={
        "Content-Type": "application/json"})
    with _urlopen(req, timeout) as r:
        d = json.loads(r.read().decode("utf-8"))
    if d.get("err_no") not in (0, None):
        raise RuntimeError("百度 ASR 失败 err_no=%s err_msg=%s"
                           % (d.get("err_no"), d.get("err_msg")))
    return "".join(d.get("result") or []).strip()


def listen(secs=4.0, rate=16000, wav_path="/tmp/xiaobai_heard.wav"):
    """录一段并识别。返回 (文字, wav 路径)。"""
    ac.record_to(wav_path, secs=secs, rate=rate, mono=True)
    return recognize(wav_path, rate=rate), wav_path


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "listen":
        t, p = listen(float(sys.argv[2]) if len(sys.argv) > 2 else 4.0)
        print("听到:", t, "  (", p, ")")
    else:
        txt = " ".join(sys.argv[1:]) or "我是系统管家小白，这块板子的系统管家。"
        p, s = speak(txt)
        print("已播放 %.2fs  %s" % (s, p))
