#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_baidu_asr.py —— 验证百度密钥 + 拿真机录音实测识别

流程：
  1) 用 API Key + Secret Key 换 access_token
  2) 把板载麦克风录到的那段人声 WAV 发给百度短语音识别
  3) 打印识别结果

★ 这一步的意义：之前 vosk 离线识别把"现在几点"认成"法"，
   如果百度能认出来，说明**问题在识别引擎，不在麦克风**。
"""
import base64
import json
import os
import sys
import urllib.parse
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

AK = "YOUR_API_KEY_HERE"
SK = "YOUR_API_KEY_HERE"
TOKEN_URL = "https://aip.baidubce.com/oauth/2.0/token"
ASR_URL = "https://vop.baidu.com/server_api"


def get_token(ak, sk):
    url = TOKEN_URL + "?" + urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": ak, "client_secret": sk})
    with urllib.request.urlopen(url, timeout=20) as r:
        return json.loads(r.read().decode())


def asr(pcm, rate=16000, channels=1, fmt="pcm", cuid="zynq-tianji"):
    """把裸 PCM 发给百度短语音识别"""
    tok = get_token(AK, SK)
    if "access_token" not in tok:
        return {"error": "换 token 失败", "raw": tok}
    body = {
        "format": fmt,
        "rate": rate,
        "channel": channels,
        "cuid": cuid,
        "token": tok["access_token"],
        "speech": base64.b64encode(pcm).decode(),
        "len": len(pcm),
    }
    req = urllib.request.Request(
        ASR_URL, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.loads(r.read().decode())


def read_wav_pcm(path):
    import wave
    w = wave.open(path, "rb")
    n, ch, sw, rate = w.getnframes(), w.getnchannels(), w.getsampwidth(), \
        w.getframerate()
    d = w.readframes(n)
    w.close()
    return d, rate, ch, sw


def main():
    print("=" * 74)
    print("1) 换 access_token")
    print("=" * 74)
    tok = get_token(AK, SK)
    if "access_token" in tok:
        print("  ✓ 成功！token 前 24 字符:", tok["access_token"][:24], "...")
        print("     有效期 %s 秒（约 %.1f 天）"
              % (tok.get("expires_in"), tok.get("expires_in", 0) / 86400.0))
        print("     权限范围:", tok.get("scope", "-"))
    else:
        print("  ✗ 失败:", json.dumps(tok, ensure_ascii=False)[:400])
        return 1

    print()
    print("=" * 74)
    print("2) 拿真机录音实测识别")
    print("=" * 74)
    cands = [
        sys.argv[1] if len(sys.argv) > 1 else None,
        r"D:\总文件夹\FPGA2026_项目交接包\14_音频勘验\真机录音_人声证据_20260928.wav",
        r"D:\ubuntu_iso\rec_evidence.wav",
    ]
    path = None
    for c in cands:
        if c and os.path.exists(c):
            path = c
            break
    if not path:
        print("  找不到测试用的 WAV")
        return 1

    pcm, rate, ch, sw = read_wav_pcm(path)
    print("  文件: %s" % os.path.basename(path))
    print("  格式: %d Hz  %d 声道  %d 字节/样本  时长 %.2f 秒"
          % (rate, ch, sw, len(pcm) / float(rate * ch * sw)))
    if sw != 2:
        print("  [!] 百度要求 16bit，当前 %d bit —— 结果可能不准" % (sw * 8))
    if len(pcm) > 60 * rate * ch * sw:
        print("  [!] 超过 60 秒会被拒")

    print()
    print("  正在识别 ...")
    try:
        res = asr(pcm, rate=rate, channels=ch,
                  fmt="pcm" if sw == 2 else "wav")
    except Exception as e:
        print("  ✗ 请求异常:", e)
        return 1

    print()
    print("  百度返回:")
    print("   ", json.dumps(res, ensure_ascii=False)[:500])
    print()
    if res.get("err_no") == 0:
        print("  ★★ 识别成功:", res.get("result"))
    else:
        print("  ✗ 识别失败 err_no=%s  %s" % (res.get("err_no"),
                                              res.get("err_msg")))
        print("     常见原因: 3301 音频质量差 / 3302 鉴权失败 / "
              "3307 服务端问题 / 3308 音频太长")
    return 0


if __name__ == "__main__":
    sys.exit(main())
