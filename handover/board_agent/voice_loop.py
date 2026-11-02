#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""voice_loop.py —— 板载语音闭环（半双工状态机）

    IDLE ──▶ LISTEN ──▶ THINK ──▶ SPEAK ──▶ IDLE
     麦克风录音    ASR        板载Agent    TTS+喇叭

★ 严格半双工：说话时绝不开麦克风，录音时喇叭一定静音 ——
  否则喇叭的声音会被自己录进去（而且满量程放音会把 MIC 输入打到削顶，
  这是实测踩过的坑，见 14_音频勘验/实测报告_录音通路打通.md）。

用法:
    python3 -m agent.voice_loop              # 跑一轮
    python3 -m agent.voice_loop --rounds 3   # 跑三轮
    python3 -m agent.voice_loop --secs 5
"""
import json
import os
import sys
import time
import urllib.request

from . import audio_client as ac

AGENT_URL = os.environ.get("AGENT_SVC", "http://127.0.0.1:8765")

IDLE, LISTEN, THINK, SPEAK = "IDLE", "LISTEN", "THINK", "SPEAK"


def _post(url, obj, timeout=300):
    req = urllib.request.Request(
        url, data=json.dumps(obj).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


class VoiceLoop(object):
    def __init__(self, verbose=True, on_state=None):
        self.state = IDLE
        self.verbose = verbose
        self.on_state = on_state
        self.log = []

    def _say(self, msg):
        self.log.append(msg)
        if self.verbose:
            print(msg, flush=True)

    def _go(self, st):
        self.state = st
        if self.on_state:
            try:
                self.on_state(st)
            except Exception:
                pass

    def once(self, secs=4.0, rate=16000, wav="/tmp/xiaobai_heard.wav"):
        """跑一轮闭环，返回 (听到的文字, 回复)。"""
        # ---- 1) LISTEN：录音（此时喇叭必须是静音的）----
        self._go(LISTEN)
        t0 = time.time()
        try:
            ac.stop()                     # 确保喇叭静音（半双工）
            ac.record_to(wav, secs=secs, rate=rate, mono=True)
        except Exception as e:
            self._go(IDLE)
            self._say("[LISTEN] 录音失败: %s" % e)
            return None, None
        self._say("[LISTEN] 录了 %.1fs -> %s (%.2fs)"
                  % (secs, wav, time.time() - t0))

        # ---- 2) THINK 的准备：识别 ----
        try:
            from . import asr
            text, eng = asr.recognize(wav, rate=rate)
        except Exception as e:
            self._go(IDLE)
            self._say("[ASR] 识别失败: %s" % e)
            self._say("      （录音是好的，只是缺识别引擎；"
                      "装 vosk 即可离线识别）")
            return None, None
        if not text:
            self._go(IDLE)
            self._say("[ASR] (%s) 没听清内容" % eng)
            return None, None
        self._say("[ASR] (%s) 听到: %s" % (eng, text))

        # ---- 3) THINK：交给板载 Agent ----
        self._go(THINK)
        t0 = time.time()
        try:
            d = _post(AGENT_URL + "/voice", {"text": text}, timeout=300)
        except Exception as e:
            self._go(IDLE)
            self._say("[THINK] Agent 调用失败: %s" % e)
            return text, None
        reply = (d.get("reply") or "").strip()
        self._say("[THINK] Agent 回复 (%.1fs, %s 轮): %s"
                  % (time.time() - t0, d.get("rounds"), reply[:160]))

        # ---- 4) SPEAK：TTS + 喇叭 ----
        self._go(SPEAK)
        try:
            from . import tts
            # 口语化：去掉 markdown 记号，太长就截断
            spoken = reply.replace("*", "").replace("#", "").replace("`", "")
            spoken = spoken.replace("|", " ").replace("\n", " ")
            spoken = " ".join(spoken.split())[:180]
            p, s = tts.speak(spoken)
            self._say("[SPEAK] 已从喇叭播出 %.1fs" % s)
        except Exception as e:
            self._say("[SPEAK] 说话失败: %s" % e)

        self._go(IDLE)
        return text, reply


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=1)
    ap.add_argument("--secs", type=float, default=4.0)
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()

    if not ac.alive():
        print("音频服务没在跑。先 sudo systemctl start zynq-audio")
        return 2
    v = VoiceLoop(verbose=not a.quiet)
    for i in range(a.rounds):
        print("\n========== 第 %d 轮 ==========" % (i + 1))
        t, r = v.once(secs=a.secs)
        if t is None:
            print("（这一轮没有有效语音输入）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
