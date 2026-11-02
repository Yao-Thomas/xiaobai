#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""patch_asr_baidu.py —— 给 agent/asr.py 加百度语音识别，作为**首选**引擎

背景（2026-09-28 实测）：
  * 板载麦克风录的音，百度一次就认出了完整句子：
        "我在吃饭，你怎么说出来了？你这个5000。"   err_no=0
  * 而离线 vosk 把"现在几点"认成"法" —— **瓶颈在识别引擎，不在麦克风**
  * 所以把百度设为首选，vosk 退为**离线兜底**（断网时还能用）

两个必须注意的坑：
  1) 板子的 SSL 证书链不全 -> urllib 会 CERTIFICATE_VERIFY_FAILED。
     复用 tts.py 里那套 _urlopen（CA 级联 -> 最后降级不校验）。
  2) 百度要求 16kHz / 单声道 / 16bit PCM。
"""
import io
import sys

P = "agent/asr.py"
src = io.open(P, encoding="utf-8").read()

if "recognize_baidu" in src:
    print("已经打过补丁，跳过")
    sys.exit(0)

ADD = '''

# ══════════════════════════════════════════════════════════════════
#  百度短语音识别（首选引擎）
#  实测：板载麦克风录的音，百度一次认出完整句子；离线 vosk 则差很多。
# ══════════════════════════════════════════════════════════════════

BAIDU_ENV = "/etc/zynq-baidu.env"
BAIDU_TOKEN_URL = "https://aip.baidubce.com/oauth/2.0/token"
BAIDU_ASR_URL = "https://vop.baidu.com/server_api"
_baidu_tok = {"v": None, "exp": 0.0}


def _baidu_creds():
    """密钥来源：环境变量 -> /etc/zynq-baidu.env -> agent/config.py"""
    ak = os.environ.get("BAIDU_API_KEY", "")
    sk = os.environ.get("BAIDU_SECRET_KEY", "")
    if ak and sk:
        return ak, sk
    try:
        for line in open(BAIDU_ENV, encoding="utf-8"):
            line = line.strip()
            if line.startswith("BAIDU_API_KEY="):
                ak = line.split("=", 1)[1].strip()
            elif line.startswith("BAIDU_SECRET_KEY="):
                sk = line.split("=", 1)[1].strip()
    except OSError:
        pass
    return ak, sk


def _open(req_or_url, timeout=25):
    """★ 复用 tts.py 的 SSL 策略：CA 级联失败就降级不校验。

    板子的证书链不全，urllib 默认会 CERTIFICATE_VERIFY_FAILED；
    而系统 curl 能通是因为它自带 CA 包。
    """
    try:
        from agent.tts import _urlopen as _tts_open
        return _tts_open(req_or_url, timeout)
    except Exception:
        pass
    import ssl
    import urllib.request
    cafiles = ["/etc/ssl/certs/ca-certificates.crt",
               "/etc/pki/tls/certs/ca-bundle.crt",
               "/usr/share/ca-certificates/mozilla/certifi.crt"]
    for c in cafiles:
        if os.path.exists(c):
            try:
                return urllib.request.urlopen(
                    req_or_url, timeout=timeout,
                    context=ssl.create_default_context(cafile=c))
            except Exception:
                continue
    return urllib.request.urlopen(
        req_or_url, timeout=timeout,
        context=ssl._create_unverified_context())


def baidu_available():
    ak, sk = _baidu_creds()
    return bool(ak and sk)


def _baidu_token(force=False):
    """取 access_token，内存缓存（有效期 30 天）"""
    import json
    import time
    import urllib.parse
    if (not force and _baidu_tok["v"]
            and time.time() < _baidu_tok["exp"] - 60):
        return _baidu_tok["v"]
    ak, sk = _baidu_creds()
    if not (ak and sk):
        raise RuntimeError("没有百度密钥（BAIDU_API_KEY / BAIDU_SECRET_KEY）")
    q = urllib.parse.urlencode({"grant_type": "client_credentials",
                                "client_id": ak, "client_secret": sk})
    with _open(BAIDU_TOKEN_URL + "?" + q, 25) as r:
        j = json.loads(r.read().decode("utf-8", "replace"))
    if "access_token" not in j:
        raise RuntimeError("百度换 token 失败: %s"
                           % json.dumps(j, ensure_ascii=False)[:200])
    _baidu_tok["v"] = j["access_token"]
    _baidu_tok["exp"] = time.time() + float(j.get("expires_in", 2592000))
    return _baidu_tok["v"]


def recognize_baidu(wav_path, normalize=True, rate=16000):
    """用百度识别一个 WAV。返回识别文本（失败抛异常）

    要求：16kHz / 单声道 / 16bit PCM。
    normalize=True 时先做自动增益（和 vosk 那条路一样的预处理，
    对电平偏低的板载录音有帮助）。
    """
    import base64
    import json
    import urllib.request
    import wave

    src = wav_path
    if normalize:
        try:
            src, _ = normalize_wav(wav_path)
        except Exception:
            src = wav_path

    w = wave.open(src, "rb")
    ch, sw, fr = w.getnchannels(), w.getsampwidth(), w.getframerate()
    data = w.readframes(w.getnframes())
    w.close()
    if sw != 2:
        raise RuntimeError("百度要求 16bit PCM，当前 %d bit" % (sw * 8))

    body = {"format": "pcm", "rate": fr, "channel": ch, "cuid": "zynq-board",
            "token": _baidu_token(),
            "speech": base64.b64encode(data).decode(), "len": len(data)}
    req = urllib.request.Request(
        BAIDU_ASR_URL, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    with _open(req, 40) as r:
        res = json.loads(r.read().decode("utf-8", "replace"))
    if res.get("err_no") != 0:
        raise RuntimeError("百度识别失败 err_no=%s %s"
                           % (res.get("err_no"), res.get("err_msg")))
    out = res.get("result") or []
    return "".join(out).strip()
'''

src = src.rstrip() + "\n" + ADD

# 把 recognize() 改成 Baidu 优先
if "def recognize(" in src:
    import re
    m = re.search(r"def recognize\((.*?)\):(.*?)(?=\ndef |\Z)", src, re.S)
    if m:
        old = m.group(0)
        new = ('def recognize(%s):\n'
               '    """识别一个 WAV。**百度优先**，失败再退回离线 vosk。\n\n'
               '    （实测：板载录音百度一次认出完整句子，vosk 差很多；\n'
               '      但断网时 vosk 还能兜底。）\n'
               '    """\n'
               '    if baidu_available():\n'
               '        try:\n'
               '            t = recognize_baidu(wav_path)\n'
               '            if t:\n'
               '                return t\n'
               '        except Exception as e:\n'
               '            print("[asr] 百度失败，退回 vosk: %%s" %% e, flush=True)\n'
               '    try:\n'
               '        return recognize_vosk(wav_path%%s)\n'
               '    except Exception as e:\n'
               '        raise RuntimeError("识别失败（百度和 vosk 都不行）: %%s" %% e)\n'
               % (m.group(1),
                  ', rate=rate' if 'rate' in m.group(1) else ''))
        src = src.replace(old, new, 1)
        print("  recognize() 已改为百度优先")
    else:
        print("  [!] 没匹配到 recognize() 函数体，需要手工改")

io.open(P, "w", encoding="utf-8").write(src)

import ast
ast.parse(io.open(P, encoding="utf-8").read())
print("补丁完成, syntax OK")
