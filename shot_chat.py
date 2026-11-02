#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""shot_chat.py —— 给聊天界面截图（方便用户看效果）

★ 为什么要截图：
  界面类的东西光说没用，得让用户看到。
  这个脚本起界面 → 填演示数据 → 截屏 → 存 PNG → 关掉。

用法:
    python shot_chat.py
    python shot_chat.py --out ui.png --secs 3
"""
import argparse
import os
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import tkinter as tk                     # noqa: E402
from PIL import ImageGrab                # noqa: E402
import xb_chat as XC                     # noqa: E402


DEMO = [
    ("user", "现在多少度"),
    ("ai", "现在 76.2 度，偏高但还能用。\n守护会在超过 85 度时开始降载。"),
    ("user", "板载示波器的采样率是多少"),
    ("ai", "板载示波器 scope_cap_axi 在 0x43CC0000：\n"
           "· 4096 点 × 8 bit 双 bank BRAM\n"
           "· 采样率 = 100 MHz / DIV，DIV=5 时 20 MSPS\n"
           "· 支持触发 / 预触发\n"
           "★ 当前信号源是板子内部 DDS，外部 XADC 还没接。"),
    ("user", "帮我识别一下这段波形"),
    ("ai", "识别结果：sine（正弦波），置信度 1.00\n"
           "用时 11.5 ms，走的是 PL 加速器（conv1→conv2→fc）。"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(HERE, "ui_chat.png"))
    ap.add_argument("--secs", type=float, default=2.5)
    a = ap.parse_args()

    root = tk.Tk()
    app = XC.ChatApp(root, "", "")
    app._sync_spk()
    # ★ 置顶 —— 不然会被别的窗口（比如终端）挡在截图里
    try:
        root.attributes("-topmost", True)
        root.lift()
    except Exception:
        pass
    # 填演示数据（不要真的去连板子）
    for who, text in DEMO:
        app.store.cur.msgs.append({"who": who, "text": text,
                                   "ts": time.time()})
    app.store.cur.title = "现在多少度"
    app.render_session()
    app.lbl_conn.configure(text="● 192.168.110.144", fg=XC.C["ok"])
    app.lbl_temp.configure(text="76.2°C")
    app.v_model.set("deepseek-v4-pro")
    app.cb_model["values"] = ["deepseek-flash", "deepseek-v4-pro"]
    app.v_mode.set("自动")
    app.set_status("就绪     模型 deepseek-v4-pro · 模式 自动")

    def shot():
        try:
            root.update_idletasks()
            root.update()
            root.geometry("+40+40")
            root.update_idletasks()
            root.update()
            time.sleep(0.4)

            # ★★ 坐标的坑（踩了两次）
            #   第一次：用 winfo_rooty()+height 当 bbox → 底部超出屏幕，输入栏没截到
            #   第二次：先移到 (40,40) 再算 → 还是偏，左边有黑边
            #   ⇒ 原因：tkinter 的 winfo_root* 给的是【客户区】坐标，
            #     而窗口有标题栏和边框，ImageGrab 要的是【屏幕绝对像素】。
            #   ⇒ 改用 Win32 的 GetWindowRect 拿窗口（含边框）的真实矩形。
            x = y = 0
            w = h = 0
            try:
                import ctypes
                u = ctypes.windll.user32
                try:
                    ctypes.windll.shcore.SetProcessDpiAwareness(2)
                except Exception:
                    pass
                hwnd = u.GetParent(root.winfo_id()) or root.winfo_id()
                r = ctypes.wintypes.RECT() if hasattr(ctypes, "wintypes") else None
                import ctypes.wintypes as wt
                r = wt.RECT()
                u.GetWindowRect(hwnd, ctypes.byref(r))
                x, y = r.left, r.top
                w, h = r.right - r.left, r.bottom - r.top
            except Exception:
                x, y = root.winfo_rootx(), root.winfo_rooty()
                w, h = root.winfo_width(), root.winfo_height()

            full = ImageGrab.grab()
            sw, sh = full.size
            x2 = min(sw, x + w)
            y2 = min(sh, y + h)
            if x2 - x < 100 or y2 - y < 100:
                raise RuntimeError("窗口坐标异常 x=%d y=%d w=%d h=%d 屏幕=%dx%d"
                                   % (x, y, w, h, sw, sh))
            img = full.crop((x, y, x2, y2))
            img.save(a.out)
            print("  ✓ 截图已保存: %s  (%dx%d，屏幕 %dx%d)"
                  % (a.out, img.size[0], img.size[1], sw, sh))
            if y2 < y + h:
                print("  ⚠ 窗口底部超出屏幕，裁了 %d px" % (y + h - y2))
        except Exception as e:
            import traceback
            print("  ✗ 截图失败: %s: %s" % (type(e).__name__, e))
            traceback.print_exc()
        finally:
            root.destroy()

    root.after(int(a.secs * 1000), shot)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
