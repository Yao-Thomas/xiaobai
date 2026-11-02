#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""patch_hold_talk.py —— 给音频服务加「流式录音」（按住说话用）

════════════════════════════════════════════════════════════════════
用户："这个语音……他并不是按住说话，而是点击，然后我说完了也不能取消，
      而且还识别不到"

查下来的问题：
  ① apps_agent.py 的 run() 调的是 touch.poll() —— 没传 move=True，
     所以永远只拿到 ('tap',x,y)，拿不到 ('down',...) / ('up',...)。
     ⇒ 想做"按住"都没有事件可用，只能做成一按就跑的固定 4 秒。
  ② voice() 里写死 VoiceLoop.once(secs=4.0) —— 点一下录 4 秒，
     跟用户按住多久毫无关系。
  ③ audio_alsa_svc.py 的 capture() 是 arecord -d <时长> 的【阻塞式】录音，
     没法"按下的那一刻就开始录、松开就停"。

这个脚本解决 ③：把阻塞录音拆成 start / stop 两半。
   /record/start  -> 后台起一个 arecord，立刻开始采集
   /record/stop   -> 停掉它，把已经采到的 raw 转成 wav 返回

★ 为什么必须"按下就开始录"：
  如果等松开再录，用户说的那句话根本没被采到。
  只有按下就起录音进程，松开时才有"刚才那段"。

用法:
    python patch_hold_talk.py --check
    python patch_hold_talk.py
"""
import argparse
import io
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
P = os.path.join(HERE, "audio_alsa_svc.py")

# ── ① 把 capture() 里"raw -> wav"那段抽成独立方法，start/stop 共用 ──
OLD_CAP = '''    def capture(self, seconds, rate, mono):
        seconds = max(0.1, min(60.0, float(seconds)))
        rate = max(8000, min(48000, int(rate)))
        duration = int(math.ceil(seconds))
        raw = subprocess.run(
            ["arecord", "-q", "-D", "hw:0,1", "-f", "S24_LE", "-c", "2",
             "-r", "44100", "-d", str(duration), "-t", "raw"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            check=False, timeout=duration + 10)
        if raw.returncode:
            raise RuntimeError(raw.stderr.decode(errors="replace").strip())
        source = raw.stdout[:int(seconds * 44100) * 8]
'''

NEW_CAP = '''    def capture(self, seconds, rate, mono):
        """阻塞式录固定时长（老接口，保留兼容）"""
        seconds = max(0.1, min(60.0, float(seconds)))
        rate = max(8000, min(48000, int(rate)))
        duration = int(math.ceil(seconds))
        raw = subprocess.run(
            ["arecord", "-q", "-D", "hw:0,1", "-f", "S24_LE", "-c", "2",
             "-r", "44100", "-d", str(duration), "-t", "raw"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            check=False, timeout=duration + 10)
        if raw.returncode:
            raise RuntimeError(raw.stderr.decode(errors="replace").strip())
        return self._raw_to_wav(raw.stdout, seconds, rate, mono)

    # ══════════════════════════════════════════════════════════════
    #  ★★★ 流式录音（2026-10-03 加，给"按住说话"用）
    # ══════════════════════════════════════════════════════════════
    #   /record/start -> 后台起 arecord，【按下那一刻就开始采】
    #   /record/stop  -> 停掉，把已采到的转成 wav 返回
    #
    # ★ 为什么不能等松开再录：那样用户说的那句话根本没被采到。
    # ★ arecord 不带 -d 就是"一直录到被杀死"，正好符合需要。
    # ══════════════════════════════════════════════════════════════
    def capture_start(self, rate=44100):
        """开始后台录音（已有在录的先停掉）"""
        try:
            self.capture_stop(rate, True, cancel=True)   # 清掉上一次残留
        except Exception:
            pass
        self.stop()                       # 半双工：先停喇叭，免得录到自己的声音
        cmd = ["arecord", "-q", "-D", "hw:0,1", "-f", "S24_LE", "-c", "2",
               "-r", str(int(rate)), "-t", "raw"]
        self._rec = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL)
        self._rec_rate = int(rate)
        self._rec_t0 = time.time()
        return {"ok": True, "rate": self._rec_rate,
                "cmd": " ".join(cmd)}

    def capture_stop(self, rate=None, mono=True, cancel=False):
        """停止后台录音；cancel=True 就丢弃（用于"上滑取消"）"""
        p = getattr(self, "_rec", None)
        if p is None:
            return None
        self._rec = None
        rate = int(rate or getattr(self, "_rec_rate", 44100))
        t0 = getattr(self, "_rec_t0", time.time())
        try:
            p.terminate()
        except Exception:
            pass
        try:
            out, _ = p.communicate(timeout=5)
        except Exception:
            try:
                p.kill()
                out, _ = p.communicate(timeout=3)
            except Exception:
                out = b""
        if cancel:
            return None
        seconds = max(0.1, min(60.0, time.time() - t0))
        return self._raw_to_wav(out or b"", seconds, rate, mono)

    def _raw_to_wav(self, raw_stdout, seconds, rate, mono):
        """把 arecord 的 S24_LE 立体声 raw 转成 16bit wav（原来在 capture 里）"""
        seconds = max(0.1, min(60.0, float(seconds)))
        rate = max(8000, min(48000, int(rate)))
        source = raw_stdout[:int(seconds * 44100) * 8]
'''

# 把原来 capture 里剩下的部分（samples/pcm 那段）接到 _raw_to_wav 上
OLD_TAIL = '''    def s24_to_s16(v):'''
NEW_TAIL = '''        def s24_to_s16(v):'''

# 结尾 return 之后的缩进要对齐 _raw_to_wav（4 空格方法体，内部原样）
ANCHOR_POST = '''    def send_data(self, status, payload, content_type):'''
ADD_ROUTES = '''    # （流式录音的 HTTP 入口在 do_POST 里，见 /record/start 和 /record/stop）

    def send_data(self, status, payload, content_type):'''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()

    src = io.open(P, encoding="utf-8").read()
    orig = src
    print("=" * 68)
    print(" 给音频服务加「流式录音」（按住说话）")
    print("=" * 68)

    if OLD_CAP in src:
        src = src.replace(OLD_CAP, NEW_CAP, 1)
        print("   ✓ capture() 拆出 _raw_to_wav，加了 capture_start / capture_stop")
    else:
        print("   ✗ capture() 没匹配到")

    # s24_to_s16 从闭包函数变成 _raw_to_wav 的内部函数：缩进深一层
    if OLD_TAIL in src and "def _raw_to_wav" in src:
        # 只改 _raw_to_wav 里那一个（它是文件里第一个 "    def s24_to_s16"）
        idx = src.find("def _raw_to_wav")
        head, tail = src[:idx], src[idx:]
        if OLD_TAIL in tail:
            tail = tail.replace(OLD_TAIL, NEW_TAIL, 1)
            # 该块剩下的行也要整体多缩进 4 格，直到 "return out.getvalue()"
            lines = tail.split("\n")
            out, inside, done = [], False, False
            for ln in lines:
                if ln.startswith("        def s24_to_s16(v):"):
                    inside = True
                if inside and not done:
                    if ln.strip() == "return out.getvalue()":
                        out.append("    " + ln)
                        done = True
                        inside = False
                        continue
                    out.append(("    " + ln) if ln.strip() else ln)
                else:
                    out.append(ln)
            tail = "\n".join(out)
            src = head + tail
            print("   ✓ _raw_to_wav 内部缩进已对齐")
    else:
        print("   ! s24_to_s16 那段没处理（检查一下）")

    io.open(P, "w", encoding="utf-8").write(src)
    print("\n 已写回 audio_alsa_svc.py")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
