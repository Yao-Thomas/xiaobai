#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""smoke_app.py —— ★ 板载 App 的冒烟测试（打开就崩这类问题）

════════════════════════════════════════════════════════════════════
为什么要有这个
════════════════════════════════════════════════════════════════════
2026-10-03 我把板载 App 的布局重做了，但用 PowerShell 的字符串替换
去加 `self.sessions` 等初始化 —— **替换静默失败了**（没匹配到），
于是 `draw_sidebar()` 里访问 `self.sessions` 抛 AttributeError，
用户一点图标就"应用出错打不开"。

★ 这种错跑一次 draw() 就能抓到，但之前没有任何测试覆盖"界面能不能画出来"。

这个脚本就干一件事：
    真构造 App（跳过网络）→ 调 buttons() → 调 draw() → 报错就抛出来
再顺手把几个状态（主界面/静音/设置/键盘弹出）都画一遍。

用法（板子上）:
    sudo python3 /home/zynq/smoke_app.py
    sudo python3 /home/zynq/smoke_app.py --no-screen   # 不发到 framebuffer
"""
import argparse
import os
import sys
import traceback

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, "/home/zynq/ui")


# ★★★ 属性检查：找出「方法里读了自己没在 __init__ 里赋值的属性」
def check_attrs(path):
    """静态找 'self.X 被读但从未被赋值' —— 就是这次的崩因"""
    import ast
    src = open(path, encoding="utf-8").read()
    tree = ast.parse(src)
    cls = None
    for n in tree.body:
        if isinstance(n, ast.ClassDef) and n.name == "AgentApp":
            cls = n
            break
    if cls is None:
        return []

    # 收集【所有】方法里的属性赋值（不只 __init__ —— 方法里赋值也算定义）
    assigned = set()
    methods = set()
    for n in cls.body:
        if isinstance(n, ast.FunctionDef):
            methods.add(n.name)
            for x in ast.walk(n):
                if (isinstance(x, ast.Attribute)
                        and isinstance(x.value, ast.Name)
                        and x.value.id == "self"
                        and isinstance(x.ctx, ast.Store)):
                    assigned.add(x.attr)

    # 收集读取
    used = {}
    for n in cls.body:
        if not isinstance(n, ast.FunctionDef):
            continue
        for x in ast.walk(n):
            if (isinstance(x, ast.Attribute)
                    and isinstance(x.value, ast.Name)
                    and x.value.id == "self"
                    and isinstance(x.ctx, ast.Load)):
                used.setdefault(x.attr, set()).add(n.name)

    # ★ 排除方法名（self.foo() 是调用不是读属性）
    missing = {}
    for k, v in used.items():
        if k in assigned or k in methods:
            continue
        missing[k] = v
    return missing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-screen", action="store_true")
    a = ap.parse_args()

    print("=" * 72)
    print(" 板载 App 冒烟测试")
    print("=" * 72)
    ok = True

    def chk(c, m, d=""):
        nonlocal ok
        print("   %s %s%s" % ("✓" if c else "✗", m, ("   " + d) if d else ""))
        ok = ok and c

    PATH = "/home/zynq/ui/apps_agent.py"

    # ── ① 静态：属性有没有漏初始化 ──
    print()
    print("【1】静态检查：self.X 被读但没赋值")
    try:
        missing = check_attrs(PATH)
        if missing:
            for k, v in missing.items():
                print("     ★ self.%-18s 被 %s 读，但从来没有赋值过"
                      % (k, ", ".join(sorted(v))))
            chk(False, "没有漏初始化的属性")
        else:
            chk(True, "没有漏初始化的属性")
    except Exception as e:
        chk(False, "静态检查本身出错", str(e))

    # ── ② 语法 ──
    print()
    print("【2】语法")
    try:
        import ast as _a
        _a.parse(open(PATH, encoding="utf-8").read())
        chk(True, "ast.parse 通过")
    except SyntaxError as e:
        chk(False, "语法错误", "第 %s 行: %s" % (e.lineno, e.msg))

    # ── ③ 导入 ──
    print()
    print("【3】导入")
    try:
        import fbui
        chk(True, "fbui 可导入")
    except Exception as e:
        chk(False, "fbui", str(e))
        print()
        print(" 总体: ★ 连 fbui 都进不来，后面没法测")
        return 1
    try:
        import apps_agent as AA
        chk(True, "apps_agent 可导入")
    except Exception as e:
        chk(False, "apps_agent", "%s: %s" % (type(e).__name__, e))
        traceback.print_exc()
        return 1

    # ── ④ 构造（跳过真网络）──
    print()
    print("【4】构造 App")
    app = None
    try:
        import queue as _q
        app = AA.AgentApp.__new__(AA.AgentApp)      # ★ 不跑 __init__（会连网络）
        # 手动补齐 __init__ 该给的东西 —— ★ 这里也必须和真的 __init__ 一致
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
        app.mode = "auto"
        app.kb_open = False
        app.sessions = []
        app.cur_session = -1
        app.q = _q.Queue()
        chk(True, "补齐属性后构造成功")
    except Exception as e:
        chk(False, "构造", "%s: %s" % (type(e).__name__, e))
        traceback.print_exc()
        return 1

    # ★★★ 真构造一次（重点是跑真的 __init__ 看会不会崩）
    print()
    print("【5】★ 真构造 __init__（会去连 agent/音频服务，10 秒超时）")
    try:
        real = AA.AgentApp()
        chk(True, "真 __init__ 没抛异常")
        # ★ 关键：检查 __init__ 之后，所有 draw 会用到的属性都在
        # ────────────────────────────────────────────────────────────
        # ★★★ 2026-10-03 补 voice_* —— 这个列表当时漏了它，直接导致：
        #   加了「重说」按钮（读 self.voice_text）之后，
        #   __init__ 里却没有 voice_text（只在 voice_begin() 里创建）
        #   ⇒ 切到语音模式立刻崩：
        #        AttributeError: 'AgentApp' object has no attribute 'voice_text'
        #   而【这个检查没报】，因为它压根没查 voice_text。
        #   教训：加了"绘制时要读"的新属性，必须同步加进这个列表。
        # ────────────────────────────────────────────────────────────
        need = ("msgs", "cur", "py", "kb", "muted", "settings_open",
                "models", "cur_model", "has_key", "mode", "kb_open",
                "sessions", "cur_session", "busy", "pending",
                "bar_rendered",
                # ★ 流式语音（绘制语音面板时会读）
                "voice_text", "voice_seq", "recording", "rec_cancel",
                "rec_t0", "_voice_prefix", "_voice_stop")
        miss = [n for n in need if not hasattr(real, n)]
        chk(not miss, "draw 需要的属性都在",
            ("★ 缺: %s" % miss) if miss else "共查 %d 个" % len(need))
    except Exception as e:
        chk(False, "真 __init__", "%s: %s" % (type(e).__name__, e))
        traceback.print_exc()

    # ── ⑥ 画四个状态 ──
    print()
    print("【6】画各个状态（这是最容易崩的地方）")
    scr = None
    if not a.no_screen:
        try:
            scr = fbui.Screen()
        except Exception as e:
            print("     （拿不到屏幕，用假的：%s）" % e)
    if scr is None:
        class _S(object):
            """--no-screen 时的假屏幕

            ★ 必须实现 App 真的会用到的所有方法（clear/text/rrect/rect/
              line/tw/flush + .d），不然会报 '_S' object has no attribute 'tw'。
              我第一次就是漏了 tw。
            """
            w, h = 1024, 600

            class _D(object):
                def line(self, *a, **k):
                    pass

                def rectangle(self, *a, **k):
                    pass

                def polygon(self, *a, **k):
                    pass

                def ellipse(self, *a, **k):
                    pass

                def arc(self, *a, **k):
                    pass

            def __init__(self):
                self.d = _S._D()

            def clear(self, *a, **k):
                pass

            def rect(self, *a, **k):
                pass

            def rrect(self, *a, **k):
                pass

            def text(self, *a, **k):
                pass

            def line(self, *a, **k):
                pass

            def fill(self, *a, **k):
                pass

            def tw(self, s, size=20, **k):
                # 粗略估宽：中文按 1.0*size，ASCII 按 0.55*size
                n = 0
                for ch in str(s):
                    n += size if ord(ch) > 127 else size * 0.55
                return int(n)

            def flush(self, *a, **k):
                pass
        scr = _S()

    app.msgs = [("bot", "我是系统管家小白。"), ("user", "现在多少度"),
                ("bot", "现在 67 度。")]
    app.sessions = [("现在多少度", ""), ("温度", "")]
    app.cur_session = 1
    app.models = ["deepseek-flash", "deepseek-v4-pro"]
    app.cur_model = "deepseek-v4-pro"

    for name, setup in (
            ("主界面", lambda: None),
            ("静音", lambda: setattr(app, "muted", True)),
            ("键盘弹出", lambda: (setattr(app, "muted", False),
                                  setattr(app, "kb_open", True))),
            ("设置页", lambda: (setattr(app, "kb_open", False),
                                setattr(app, "settings_open", True))),
            # ★★★ 2026-10-03 补：三套输入面板（原来一个都没画）
            # ────────────────────────────────────────────────────────
            # 踩过的坑：加了「重说」按钮读 self.voice_text，
            # 而 voice_text 只在 voice_begin() 里创建 ——
            # 切到语音模式直接 AttributeError，App 打不开。
            # 但当时这里【只测主界面/静音/键盘/设置页】，
            # 语音面板压根没画过 ⇒ 测试全绿，用户一用就崩。
            # ⇒ 凡是"能切过去"的面板，都得进这个循环。
            # ────────────────────────────────────────────────────────
            ("语音面板", lambda: (setattr(app, "kb_open", False),
                                  setattr(app, "in_mode", AA.IN_VOICE))),
            ("语音面板-录音中", lambda: (setattr(app, "in_mode",
                                                 AA.IN_VOICE),
                                         setattr(app, "recording", True),
                                         setattr(app, "voice_text",
                                                 "现在几点了"))),
            ("手写面板", lambda: (setattr(app, "recording", False),
                                  setattr(app, "in_mode", AA.IN_HAND))),
            ("键盘面板", lambda: (setattr(app, "in_mode", AA.IN_KB),
                                  setattr(app, "kb_open", True))),
    ):
        try:
            setup()
            btns = app.buttons(scr)
            app.draw(scr, btns)
            chk(True, "画 %s 没崩" % name,
                "buttons=%d 个" % len(btns))
        except Exception as e:
            chk(False, "画 %s" % name, "%s: %s" % (type(e).__name__, e))
            traceback.print_exc()
        finally:
            app.settings_open = False
            app.kb_open = False
            app.recording = False
            app.in_mode = AA.IN_KB

    print()
    print("=" * 72)
    print(" 总体: %s" % ("★ 全部通过" if ok else "★ 有 ✗，见上"))
    print("=" * 72)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main() or 0)
