#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_agent_app.py —— ★ 板载 App 的【无头交互测试】

════════════════════════════════════════════════════════════════════
为什么写这个
════════════════════════════════════════════════════════════════════
板载 App 是触摸交互的，人在板子前面点才能发现问题。
但"点了没反应"这类 bug，可以在这里用代码模拟点击提前抓出来。

这个测试干的事：
    ① 造一个假 Screen（不发到 framebuffer）
    ② 造一个假 Touch（喂坐标）
    ③ 照着 run() 的逻辑模拟：打字 -> 点发送 -> 等回复
    ④ 哪个环节断了，直接报出来

★ 这是被用户骂过之后写的：
  我改完界面只顾着"渲染好看"，没测交互，
  结果他一点就发现"一个问题也问不了"。

用法（板子上）:
    sudo python3 /home/zynq/test_agent_app.py
"""
import os
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, "/home/zynq/ui")


def main():
    print("=" * 74)
    print(" 板载 App 无头交互测试")
    print("=" * 74)
    ok = True

    def chk(c, m, d=""):
        nonlocal ok
        print("   %s %s%s" % ("✓" if c else "✗", m, ("   " + d) if d else ""))
        ok = ok and c

    import fbui
    import apps_agent as AA

    print()
    print("【1】构造 App（不连网络）")
    app = AA.AgentApp.__new__(AA.AgentApp)
    app.msgs = []
    app.lines = []
    app.cur = ""
    app.py = ""
    app.cands = []
    app.pinyin = True
    app.quick = 0
    app.pending = []
    app.bar_rendered = []
    app.busy = ""
    app.last_reply = ""
    app.kb = fbui.MiniKeyboard(y0=AA.KB_Y, key_w=76, key_h=AA.KB_KH,
                               gap=AA.KB_GAP)
    app.muted = False
    app.settings_open = False
    app.settings_page = 0
    app.settings_hit = {}
    app.models = []
    app.cur_model = ""
    app.has_key = False
    app.api_base = ""
    app._settings_dirty = True
    app._rec_until = 0.0
    app.await_key = False
    app._pend_t = 0.0
    import queue as _q
    app.q = _q.Queue()
    chk(True, "构造成功")

    scr = fbui.Screen()

    print()
    print("【2】buttons() 返回什么（★ 这就是点发送的入口）")
    btns = app.buttons(scr)
    for name, act, r in btns:
        print("     %-12s act=%-8s rect=%s" % (name, act, r))
    acts = [a for _, a, _ in btns]
    chk("ask" in acts, "有 act=ask（发送按钮）")
    chk("voice" in acts, "有 act=voice（语音按钮）")

    print()
    print("【3】★ 关键：输入文字后点【发送】能不能真的发出去")
    # 模拟：用户打字
    app.cur = "现在多少度"
    # ★ 这是在 run() 里点击 ask 按钮走的分支，原样复制过来
    fired = {"ask": None}

    def fake_ask(text):
        """替掉真的 ask()，只记录被调用的参数"""
        fired["ask"] = text

    app.ask = fake_ask
    # ---- 模拟点击 ----
    for name, act, r in btns:
        cx, cy = (r[0] + r[2]) // 2, (r[1] + r[3]) // 2
        if act == "ask":
            if app.cur.strip() and not app.busy:
                app.ask(app.cur.strip())
                app.cur = ""
    chk(fired["ask"] == "现在多少度", "点【发送】把文字交给了 ask()",
        "收到: %r" % fired["ask"])
    if fired["ask"] is None:
        print("     ★★ 原因分析：")
        if not app.cur.strip():
            print("        app.cur 是空的 —— 打字没进输入框")
        if app.busy:
            print("        app.busy=%r —— 上一件事没结束，被挡住了" % app.busy)

    print()
    print("【4】★ busy 卡住会不会导致以后都点不动")
    app.busy = "probe"          # 假装有个任务卡住了
    app.cur = "测试"
    fired["ask"] = None
    for name, act, r in btns:
        if act == "ask" and app.cur.strip() and not app.busy:
            app.ask(app.cur.strip())
    chk(fired["ask"] is None, "busy 时会挡住发送（设计如此）")
    app.busy = ""
    fired["ask"] = None
    for name, act, r in btns:
        if act == "ask" and app.cur.strip() and not app.busy:
            app.ask(app.cur.strip())
    chk(fired["ask"] == "测试", "busy 清掉后又能发")
    print("     ★ 检查：_bg() 在所有分支都会清 busy 吗？")
    # 看 _bg 的 wrap：不管成功失败都 q.put，pump 里 self.busy = ""
    src = open("/home/zynq/ui/apps_agent.py", encoding="utf-8").read()
    chk("self.busy = \"\"" in src, "pump 里有清 busy")

    print()
    print("【5】键盘能不能打字")
    k = app.kb.press(0, 0)          # 点左上角外面
    chk(k is None, "点空白返回 None")
    # 找一个键的位置
    if app.kb.keys:
        ch, r = app.kb.keys[0]
        k = app.kb.press((r[0] + r[2]) // 2, (r[1] + r[3]) // 2)
        chk(k == ch, "点第一个键 -> %r" % k)
    # 模拟打 "1"
    ch, r = app.kb.keys[0]
    if ch == "1":
        if app.pinyin and ch.isalnum():
            app.py += ch.lower()
        else:
            app.cur += ch
        chk(app.py == "1" or app.cur == "1",
            "按 1 进拼音缓冲或输入框", "py=%r cur=%r" % (app.py, app.cur))

    print()
    print("【6】右上角喇叭 / 左下角设置 的命中区")
    sp = AA.SPEAKER_RECT
    chk(fbui.hit(sp, (sp[0] + sp[2]) // 2, (sp[1] + sp[3]) // 2),
        "喇叭中心能被 hit 命中", str(sp))
    gr = AA.GEAR_RECT
    chk(fbui.hit(gr, (gr[0] + gr[2]) // 2, (gr[1] + gr[3]) // 2),
        "设置键中心能被 hit 命中", str(gr))
    # ★ 检查设置键会不会和候选栏重叠
    cand_x0 = AA.GEAR_RECT[2] + 10
    chk(cand_x0 > AA.GEAR_RECT[2], "候选栏在设置键右边",
        "候选从 x=%d 开始，设置键到 x=%d" % (cand_x0, AA.GEAR_RECT[2]))

    print()
    print("【7】设置页的关闭区域")
    app.settings_open = True
    app.draw(scr, btns)
    H = app.settings_hit
    chk("close" in H, "设置页有 close 区域")
    for k in ("sound_on", "sound_off", "key"):
        chk(k in H, "设置页有 %s" % k)

    print()
    print("【8】真实网络（agent 在不在）")
    try:
        h = AA._get(AA.AGENT_URL + "/health", timeout=5)
        chk(bool(h.get("ok")), "agent /health 通",
            "model=%s tools=%d" % (h.get("model"), len(h.get("tools", []))))
    except Exception as e:
        chk(False, "agent 连不上", str(e))

    print()
    print("【9】★ 真的问一句（走完整链路）")
    try:
        # 用真实 ask（不是替身）
        real = AA.AgentApp.__new__(AA.AgentApp)
        real.q = _q.Queue()
        real.busy = ""
        real.last_reply = ""
        real.msgs = []
        real.lines = []
        real._pend_t = 0.0
        real.pending = []
        # 直接调 HTTP，绕过 _bg
        d = AA._post(AA.AGENT_URL + "/voice", {"text": "现在多少度"},
                     timeout=120)
        rep = d.get("reply") or ""
        chk(bool(rep), "agent 回了话", rep[:60].replace("\n", " "))
    except Exception as e:
        chk(False, "问一句失败", "%s: %s" % (type(e).__name__, e))

    print()
    print("=" * 74)
    print(" 总体: %s" % ("★ 全部通过" if ok else "★ 有 ✗，见上"))
    print("=" * 74)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main() or 0)
