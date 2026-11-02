#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""patch_holdtalk_app.py —— 板载 App 接上「真按住说话」

════════════════════════════════════════════════════════════════════
用户："他并不是按住说话，而是点击，然后我说完了也不能取消，
      而且还识别不到"

服务端（audio_alsa_svc.py）已经做好了流式录音：
    POST /record/start  -> 按下那一刻就开始采
    POST /record/stop   -> 松开就停；{"cancel":true} 是上滑取消

这个脚本改 App 端两件事：
  ① run() 里 touch.poll() -> touch.poll(move=True)，并且【保留 kind】
     （原来写的是 `_, x, y = ev`，把事件类型丢了，
       所以永远只拿到 tap，想做"按住"都没有事件可用）
  ② 「按住说话」按钮改成真正的按下/松开：
        down 在按钮上        -> voice_begin()  开始录音
        move 移出按钮        -> 标记为"将取消"（松手就丢）
        up 还在按钮上        -> voice_end()    停止 + 识别 + 问 agent
        up 已在按钮外        -> voice_end(cancel=True)  丢弃
     录音期间按钮变红 + 显示"正在聆听…"

★ 其它按钮保持"点一下"的行为不变：只在 up/tap 时触发，
  down/move 直接跳过（原来是 tap，等价）。
════════════════════════════════════════════════════════════════════
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
P = os.path.join(HERE, "apps_agent.py")

# ── ① run() 里打开 move 事件并保留 kind ──
OLD_EV = '''          ev = touch.poll()
          if ev:
              _, x, y = ev
              if back_hit(x, y):
                  return
'''
NEW_EV = '''          # ★★★ 打开 move 事件并【保留事件类型】（2026-10-03）
          #   原来写的是 `_, x, y = ev` + touch.poll()（默认 move=False），
          #   永远只拿得到 ('tap',x,y) —— 想做"按住说话"根本没有事件可用。
          #   现在拿 down/move/up/tap 四类，按住说话才有得处理。
          ev = touch.poll(move=True)
          if ev:
              kind, x, y = ev

              # ---- ★ 按住说话：单独处理 down / move / up ----
              vr = app.voice_rect(scr)
              if kind == "down":
                  if vr and hit(vr, x, y) and not app.busy:
                      app.voice_begin()
                      continue
              elif kind == "move":
                  if app.recording:
                      app.voice_move(hit(vr, x, y) if vr else False)
                      continue
              elif kind == "up":
                  if app.recording:
                      app.voice_end(cancel=(not vr) or (not hit(vr, x, y)))
                      continue

              # ---- 其它按钮：只在"松开/点击"时触发（按下和移动跳过）----
              if kind in ("down", "move"):
                  continue

              if back_hit(x, y):
                  return
'''

# ── ② 加 voice_begin / voice_move / voice_end / voice_rect ──
ANCHOR = '''    def voice(self, secs=4.0):'''
NEW_METHODS = '''    # ══════════════════════════════════════════════════════════════
    #  ★★★ 真正的「按住说话」（2026-10-03）
    # ══════════════════════════════════════════════════════════════
    # 用户："他并不是按住说话，而是点击，然后我说完了也不能取消"
    #
    # 原来 voice() 是点一下 -> 固定录 4 秒，跟按住多久无关。
    # 现在：
    #   down 在按钮上 -> voice_begin()  让音频服务【立刻开始采集】
    #   move 移出按钮 -> 标记"松手就取消"（按钮变灰提示）
    #   up  还在按钮 -> voice_end()     停 + 识别 + 问 agent
    #   up  已在按钮外 -> voice_end(cancel=True) 丢弃这段
    #
    # ★ 为什么必须"按下就开始录"：等松开再录的话，
    #   用户说的那句话根本没被采到。
    # ══════════════════════════════════════════════════════════════
    def voice_rect(self, scr):
        """「按住说话」按钮的矩形（没找到返回 None）"""
        try:
            for name, act, r in self.buttons(scr):
                if act == "voice":
                    return r
        except Exception:
            pass
        return None

    def voice_begin(self):
        """按下：让音频服务开始后台录音"""
        self.recording = True
        self.rec_cancel = False
        self.rec_t0 = time.time()

        def fn():
            try:
                _post(AUDIO_URL + "/record/start", {}, timeout=15)
                return None            # 开始成功，不写日志
            except Exception as e:
                return "录音启动失败: %s" % e
        self._bg("rec_start", fn)
        self.out("● 正在聆听…（松开发送，上滑到按钮外取消）")

    def voice_move(self, inside):
        """手指移动：移出按钮就标记为"松手取消\""""
        self.rec_cancel = (not inside)

    def voice_end(self, cancel=False):
        """松开：停止录音；不取消的话走 识别 -> agent"""
        if not self.recording:
            return
        self.recording = False
        cancel = bool(cancel or self.rec_cancel)
        self.rec_cancel = False
        held = time.time() - getattr(self, "rec_t0", time.time())

        # ★ 太短（<0.4s）当误触，直接丢
        if held < 0.4 and not cancel:
            cancel = True

        def fn():
            import sys as _s
            try:
                # ① 停录音，拿 wav
                req = urllib.request.Request(
                    AUDIO_URL + "/record/stop",
                    data=json.dumps({"cancel": cancel,
                                     "rate": 16000}).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST")
                with urllib.request.urlopen(req, timeout=30) as r:
                    raw = r.read()
                    ctype = r.headers.get("Content-Type", "")
                if cancel:
                    return "已取消（按住 %.1fs）" % held
                if "audio" not in (ctype or ""):
                    return "录音没拿到音频: %s" % raw[:120]

                # ② 存盘
                wav = "/tmp/xiaobai_hold.wav"
                with open(wav, "wb") as f:
                    f.write(raw)

                # ③ 识别
                if "/home/zynq" not in _s.path:
                    _s.path.insert(0, "/home/zynq")
                from agent import asr
                text, eng = asr.recognize(wav, rate=16000)
                if not text:
                    return ("没听清（引擎 %s，按住 %.1fs）—— "
                            "靠近麦克风、说清楚一点再试" % (eng, held))

                # ④ 交给板载 agent
                d = _post(AGENT_URL + "/voice", {"text": text}, timeout=300)
                self.last_reply = d.get("reply") or ""
                return ("我> %s\\n小白> %s\\n      (%s · 按住 %.1fs · %s 轮)"
                        % (text, self.last_reply, eng, held,
                           d.get("rounds")))
            except Exception as e:
                return "语音失败: %s: %s" % (type(e).__name__, e)
        self._bg("voice", fn)

    def voice(self, secs=4.0):'''

# ── ③ __init__ 加录音状态 ──
INIT_ANCHOR = "        self.model_page = 0            # ★ 模型列表翻到第几页"
INIT_ADD = '''        self.model_page = 0            # ★ 模型列表翻到第几页
        # ★ 按住说话的状态
        self.recording = False         # 正在录音
        self.rec_cancel = False        # 手指移出按钮 -> 松手取消
        self.rec_t0 = 0.0'''

# ── ④ 画按钮时，录音中显示红色 ──
DRAW_ANCHOR = '''            if act == "ask":
                fill = (40, 110, 70) if not on else (150, 90, 40)'''
DRAW_ADD = '''            if act == "ask":
                fill = (40, 110, 70) if not on else (150, 90, 40)
            elif act == "voice" and getattr(self, "recording", False):
                # ★ 录音中：按钮变红/灰，一眼看出在录 / 已标记取消
                fill = (170, 60, 60) if not getattr(self, "rec_cancel",
                                                    False) else (90, 90, 90)
                name = ("● 聆听中…" if not getattr(self, "rec_cancel", False)
                        else "松开取消")'''

# ── ⑤ 提示条显示录音状态 ──
HINT_ANCHOR = '''        if self.busy:
            scr.text((BAR_RECT[0] + 4, HINT_Y), "工作中:" + self.busy,'''
HINT_ADD = '''        if getattr(self, "recording", False):
            _held = time.time() - getattr(self, "rec_t0", time.time())
            scr.text((BAR_RECT[0] + 4, HINT_Y),
                     "● 正在聆听 %.1fs（松开发送 · 移出按钮取消）" % _held,
                     15, (255, 120, 120), anchor="lm", cn=True)
        elif self.busy:
            scr.text((BAR_RECT[0] + 4, HINT_Y), "工作中:" + self.busy,'''


def patch_one(src, old, new, label):
    if old in src:
        return src.replace(old, new, 1), True
    print("   ✗ %s 没匹配到" % label)
    return src, False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()

    src = io.open(P, encoding="utf-8").read()
    orig = src
    print("=" * 68)
    print(" 板载 App 接上「真按住说话」")
    print("=" * 68)

    src, ok1 = patch_one(src, OLD_EV, NEW_EV, "run() 的触摸事件")
    if ok1:
        print("   ✓ run() 打开 move 事件、保留 kind、接管 down/move/up")

    src, ok2 = patch_one(src, ANCHOR, NEW_METHODS, "voice 方法")
    if ok2:
        print("   ✓ 加了 voice_rect / voice_begin / voice_move / voice_end")

    src, ok3 = patch_one(src, INIT_ANCHOR, INIT_ADD, "__init__ 状态")
    if ok3:
        print("   ✓ __init__ 加了 recording / rec_cancel / rec_t0")

    src, ok4 = patch_one(src, DRAW_ANCHOR, DRAW_ADD, "按钮绘制")
    if ok4:
        print("   ✓ 录音时按钮变红并改文字")

    src, ok5 = patch_one(src, HINT_ANCHOR, HINT_ADD, "提示条")
    if ok5:
        print("   ✓ 提示条显示录音秒数")

    if a.check:
        print("\n （--check 模式，未写文件）")
        return 0
    if src == orig:
        print("\n ★ 一个字都没改")
        return 1
    io.open(P, "w", encoding="utf-8").write(src)
    print("\n 已写回 apps_agent.py")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
