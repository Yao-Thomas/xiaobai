#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""show_app.py —— 把板载 App 直接画到真实屏幕并停住（给人看）

════════════════════════════════════════════════════════════════════
为什么需要
════════════════════════════════════════════════════════════════════
板子没有 uinput（/dev/uinput 不存在），我注入不了触摸，
没法自己点开「系统管家小白」看实际效果。

所以这个脚本走另一条路：
    停掉桌面 -> 用【真实的 fbui + apps_agent】把界面画到 /dev/fb0
    -> 停住 N 秒让人看 -> 恢复桌面

★ 这和真实运行几乎一样（同一套 fbui、同一套 apps_agent），
  区别只是没有触摸事件循环 —— 用来"看颜色对不对"足够了。

用法（板子，root）:
    sudo python3 show_app.py --page main  --stay 120
    sudo python3 show_app.py --page set0  --stay 120
    sudo python3 show_app.py --page kb    --stay 120
"""
import argparse
import os
import subprocess
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, "/home/zynq/ui")


def build(page):
    import fbui
    import apps_agent as AA

    scr = fbui.Screen()
    app = AA.AgentApp.__new__(AA.AgentApp)      # 不跑 __init__（会连网络）
    app.msgs = [
        ("bot", "我是系统管家小白 —— 这块板子的系统管家。"),
        ("sys", "打字后按回车问我；也可以点「按住说话」用说的。"),
        ("user", "现在多少度"),
        ("bot", "现在 65.7 度，正常。守护会在超过 85 度时开始降载。"),
        ("user", "板载示波器的采样率是多少"),
        ("bot", "scope_cap_axi 在 0x43CC0000：4096 点 × 8 bit 双 bank，"
                "采样率 = 100 MHz / DIV，DIV=5 时 20 MSPS。"),
    ]
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
    app.kb = fbui.MiniKeyboard(y0=AA.KB_TOP, key_w=76, key_h=AA.KB_KH,
                               gap=AA.KB_GAP)
    app.muted = False
    app.settings_open = False
    app.settings_page = 0
    app.settings_hit = {}
    app.models = ["deepseek-flash", "deepseek-v4-pro", "本地（离线 RAG）"]
    app.cur_model = "deepseek-v4-pro"
    app.has_key = True
    app.api_base = "https://api.deepseek.com"
    app._settings_dirty = False
    app._rec_until = 0.0
    app.await_key = False
    app._pend_t = 0.0
    app.mode = "auto"
    app.kb_open = False
    app.sessions = [("现在多少度", ""), ("波形识别", ""),
                    ("温度多少", ""), ("改个FPGA", "")]
    app.cur_session = 3

    if page == "set0":
        app.settings_open = True
        app.settings_page = 0
    elif page == "set1":
        app.settings_open = True
        app.settings_page = 1
    elif page == "set2":
        app.settings_open = True
        app.settings_page = 2
    elif page == "kb":
        app.kb_open = True
        app.cur = "现在多少"
    elif page == "muted":
        app.muted = True

    return scr, app


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--page", default="main",
                    choices=["main", "set0", "set1", "set2", "kb", "muted"])
    ap.add_argument("--stay", type=int, default=120)
    a = ap.parse_args()

    print("  停桌面 ...")
    subprocess.call(["systemctl", "stop", "zynq-desktop"])
    time.sleep(2)

    print("  用真实 fbui 渲染 page=%s ..." % a.page)
    scr, app = build(a.page)
    btns = app.buttons(scr)
    app.draw(scr, btns)
    scr.flush()
    print("  ✓ 已上屏，停 %d 秒（请看屏幕）" % a.stay)

    try:
        time.sleep(a.stay)
    except KeyboardInterrupt:
        pass

    print("  恢复桌面 ...")
    subprocess.call(["systemctl", "start", "zynq-desktop"])
    time.sleep(3)
    print("  zynq-desktop: %s"
          % subprocess.check_output(["systemctl", "is-active",
                                     "zynq-desktop"]).decode().strip())
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
