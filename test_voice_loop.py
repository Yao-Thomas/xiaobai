#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_voice_loop.py —— ★ 语音链路闭环测试（不需要人对着话筒说话）

════════════════════════════════════════════════════════════════════
为什么这么测
════════════════════════════════════════════════════════════════════
链路是：
    PC 录音 ──/asr──▶ 板子 vosk ──▶ 文字 ──/voice──▶ agent ──▶ 回复
                                                            │
    PC 播放 ◀── wav ◀──/tts─────────────────────────────────┘

要测它，最直接的是"人对着话筒说一句"。但那样：
    · 每次都要人配合
    · 识别对不对还要人判断
    · 自动化不了

★ 所以这里用【板子自己的 TTS 合成一句话，再喂回板子的 ASR】：
    /tts("现在多少度") → wav → /asr(wav) → 看是不是识别回"现在多少度"
  这样整条音频链（合成→编码→base64→解码→重采样→vosk）全程都被测到，
  而且不需要人说话。

★ 如果这一步过不了，说明音频格式/编码有问题，
  那"人说话识别不了"就不是话筒的问题，是我们的链路有问题。

用法:
    python test_voice_loop.py --ip 192.168.110.144 --token u6kCWANi
"""
import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import xb_audio as A                     # noqa: E402

TMP = os.environ.get("TEMP", "/tmp")


def http(url, body=None, timeout=60, method=None):
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method=method or ("POST" if data else "GET"))
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return {"code": r.status,
                    "body": json.loads(r.read().decode("utf-8", "replace")),
                    "ms": int((time.time() - t0) * 1000)}
    except urllib.error.HTTPError as e:
        return {"code": e.code,
                "body": r_decode(e), "ms": int((time.time() - t0) * 1000)}
    except Exception as e:
        return {"code": 0, "body": {"error": "%s: %s" % (type(e).__name__, e)},
                "ms": int((time.time() - t0) * 1000)}


def r_decode(e):
    try:
        return json.loads(e.read().decode("utf-8", "replace"))
    except Exception:
        return {"error": "HTTP %s" % e.code}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default="192.168.110.144")
    ap.add_argument("--token", default="u6kCWANi")
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args()
    base = "http://%s:%d" % (a.ip, a.port)

    print("=" * 74)
    print(" 语音链路闭环测试（TTS → ASR，不需要话筒）")
    print("=" * 74)
    ok = True

    def chk(c, m, d=""):
        nonlocal ok
        print("   %s %s%s" % ("✓" if c else "✗", m, ("   " + d) if d else ""))
        ok = ok and c

    # ── ① 语音依赖 ──
    print()
    print("【1】板子上的语音依赖")
    r = http(base + "/status", timeout=15)
    st = r["body"] if isinstance(r["body"], dict) else {}
    print("   asr : %s" % st.get("asr"))
    print("   tts : %s" % st.get("tts"))
    chk(bool(st.get("asr", {}).get("vosk")), "vosk 可用（语音识别）")
    tts_ok = bool(st.get("tts", {}).get("baidu_keys")) or \
        bool(st.get("tts", {}).get("espeak"))
    chk(tts_ok, "TTS 可用（百度 or espeak）")

    # ── ② TTS 合成 ──
    print()
    print("【2】板子 TTS 合成（『现在多少度』）")
    r = http(base + "/tts", {"text": "现在多少度"}, timeout=90)
    d = r["body"] if isinstance(r["body"], dict) else {}
    chk(d.get("ok"), "合成成功", "HTTP %s  %d ms  %s 字节"
        % (r["code"], r["ms"], d.get("bytes")))
    if not d.get("ok"):
        print("     错误: %s" % d.get("error"))
        print()
        print(" 总体: ★ TTS 这一步就不通，后面的没法测")
        return 1
    wav = os.path.join(TMP, "xb_tts_test.wav")
    A.b64_to_wav(d["audio"], wav)
    info = A.info(wav)
    print("     落到 PC: %s" % wav)
    print("     格式: %d Hz / %d 声道 / %d bit / %.2f 秒"
          % (info.get("rate"), info.get("channels"), info.get("bits"),
             info.get("seconds")))
    chk(info.get("ok"), "是合法 wav")

    # ── ③ PC 能播 ──
    print()
    print("【3】PC 播放这段合成音频")
    try:
        A.play(wav, block=True)
        chk(True, "播放没报错")
    except Exception as e:
        chk(False, "播放", "%s: %s" % (type(e).__name__, e))

    # ── ④ ★ 喂回去让 ASR 认 ──
    print()
    print("【4】★ 把这段音频喂回板子 ASR（闭环关键）")
    b64 = A.wav_to_b64(wav)
    r = http(base + "/asr", {"audio": b64, "rate": info.get("rate") or 16000},
             timeout=120)
    d2 = r["body"] if isinstance(r["body"], dict) else {}
    print("     HTTP %s  %d ms" % (r["code"], r["ms"]))
    print("     识别结果: %r" % d2.get("text"))
    print("     引擎: %s" % d2.get("engine"))
    chk(d2.get("ok"), "ASR 没报错")
    txt = (d2.get("text") or "").strip()
    # ★ 不要求字字对上（百度合成的声音 vosk 不一定认得准），
    #   但至少要认出【一点东西】，不能是空的
    chk(len(txt) > 0, "识别出了内容（不空）",
        "" if txt else "★ 空结果 —— 说明音频格式或编码有问题")

    # ── ⑤ 全链路：识别 → agent → 回复 ──
    print()
    print("【5】全链路：识别出的文字 → agent → 回复")
    q = txt or "现在多少度"
    r = http(base + "/voice", {"text": q}, timeout=180)
    d3 = r["body"] if isinstance(r["body"], dict) else {}
    print("     问: %s" % q)
    print("     答: %s" % str(d3.get("reply", ""))[:120].replace("\n", " "))
    chk(bool(d3.get("reply")), "agent 有回复")

    # ── ⑥ PC 录音（可选，需要话筒）──
    print()
    print("【6】PC 录音（★ 这一段需要你对着话筒说话）")
    if not A.HAS_SD:
        print("     （没有 sounddevice，跳过）")
    else:
        print("     录 4 秒…")
        try:
            p, secs = A.record(4.0, os.path.join(TMP, "xb_mic_test.wav"))
            ii = A.info(p)
            pk = A.peak(p)
            print("     录到 %.1fs，%d Hz / %d 声道，峰值 %s"
                  % (secs, ii.get("rate"), ii.get("channels"), pk))
            if pk and pk > 200:
                r = http(base + "/asr", {"audio": A.wav_to_b64(p),
                                         "rate": ii.get("rate") or 16000},
                         timeout=120)
                dd = r["body"] if isinstance(r["body"], dict) else {}
                print("     板子听到: %r" % dd.get("text"))
                chk(bool(dd.get("text")), "话筒录的内容能识别",
                    "" if dd.get("text") else "★ 空 —— 可能没说话或麦克风静音")
            else:
                print("     ⚠ 峰值太低（%s），像是没说话/麦克风被静音" % pk)
                chk(True, "录音链路本身通了（只是没声音）")
        except Exception as e:
            chk(False, "PC 录音", "%s: %s" % (type(e).__name__, e))

    print()
    print("=" * 74)
    print(" 总体: %s" % ("★ 语音链路通了" if ok else "★ 有问题，看上面 ✗"))
    print("=" * 74)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main() or 0)
