#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""patch_addmodel.py —— 给板载 App 的设置页加「＋ 添加模型」按钮

════════════════════════════════════════════════════════════════════
用户："你这个提交了 API Key 会有什么变化？又没写模型名，而且能添加模型吗？"

回答 / 做法：
  · 提交 API Key = 只是"钥匙"，解锁云端模型；模型名是另一个配置项
  · 模型列表原来完全来自 DeepSeek 的 /models（只有官方那两三个）
  · ⇒ 现在支持自己添：写进覆盖文件的 extra_models，
       /llm/models 会把它合并进返回结果，客户端下拉就能选到

这个脚本负责 App 这侧的 UI：
  1. 模型列表从 4 个放宽到 6 个
  2. 每个自定义模型后面标「（自定义）」，跟官方模型区分开
  3. 列表下面加一个绿色「＋ 添加模型」按钮
  4. 点它进入文本输入模式（复用 API Key 那套 UI，敲完回车就写进去）

用法:
    python patch_addmodel.py --check
    python patch_addmodel.py
"""
import argparse
import io
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

P = os.path.join(os.path.dirname(os.path.abspath(__file__)), "apps_agent.py")

OLD = '''            for m in self.models[:4]:
                onm = (m == self.cur_model)
                r = [cx, y, cx + cw - 20, y + 40]
                h["model:%s" % m] = r
                scr.rrect(r, 9, fill=(40, 78, 132) if onm else (38, 38, 38),
                          outline=(110, 165, 230) if onm else (61, 61, 61))
                # 选中圈
                cc = cx + 22
                ccy = (r[1] + r[3]) // 2
                scr.d.ellipse([cc - 8, ccy - 8, cc + 8, ccy + 8],
                              outline=(180, 210, 245), width=2)
                if onm:
                    scr.d.ellipse([cc - 4, ccy - 4, cc + 4, ccy + 4],
                                  fill=(150, 200, 250))
                scr.text((cc + 20, ccy), m, 17,
                         (245, 245, 245) if onm else (206, 206, 206),
                         anchor="lm", cn=True)
                y += 46
            y += 8
            sep(y - 10)
'''

NEW = '''            # ★ 显示 6 个（面板够高）；自定义模型标个记号好区分
            for m in self.models[:6]:
                onm = (m == self.cur_model)
                r = [cx, y, cx + cw - 20, y + 36]
                h["model:%s" % m] = r
                scr.rrect(r, 9, fill=(40, 78, 132) if onm else (38, 38, 38),
                          outline=(110, 165, 230) if onm else (61, 61, 61))
                # 选中圈
                cc = cx + 22
                ccy = (r[1] + r[3]) // 2
                scr.d.ellipse([cc - 7, ccy - 7, cc + 7, ccy + 7],
                              outline=(180, 210, 245), width=2)
                if onm:
                    scr.d.ellipse([cc - 3, ccy - 3, cc + 3, ccy + 3],
                                  fill=(150, 200, 250))
                # ★ 不在官方列表里、也不是本地的 -> 标「（自定义）」
                nm = m
                if m not in ("deepseek-flash", "deepseek-v4-pro") \\
                        and "本地" not in m:
                    nm = m + "  （自定义）"
                scr.text((cc + 18, ccy), nm, 16,
                         (245, 245, 245) if onm else (206, 206, 206),
                         anchor="lm", cn=True)
                y += 40
            # ★★★ 「＋ 添加模型」（用户："能添加模型吗"）
            #   点它进入文本输入模式（复用 API Key 那套 UI），
            #   打完回车写进 extra_models，列表立刻多一项。
            h["addmodel"] = [cx, y, cx + 190, y + 34]
            btn(scr, h["addmodel"], "＋ 添加模型", fill=(40, 96, 70),
                size=16, cn=True, radius=9)
            scr.text((cx + 202, y + 17), "输入模型名，如 deepseek-chat",
                     13, (140, 152, 176), anchor="lm", cn=True)
            y += 44
            sep(y - 8)
'''

# 点「添加模型」的处理（挂在 key 按钮那块后面）
ANCHOR = '''                if hit(H.get("key", [0, 0, 0, 0]), x, y):'''
ADD = '''                # ★ 添加模型：进入文本输入模式，回车写进 extra_models
                if hit(H.get("addmodel", [0, 0, 0, 0]), x, y):
                    app.start_text_input("model")
                    app.out("★ 请输入要添加的模型名，按【回车】提交"
                            "（如 deepseek-chat / 你自己的模型名）")
                    continue
                if hit(H.get("key", [0, 0, 0, 0]), x, y):'''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()

    src = io.open(P, encoding="utf-8").read()
    orig = src
    print("=" * 68)
    print(" 给设置页加「＋ 添加模型」")
    print("=" * 68)

    if OLD in src:
        src = src.replace(OLD, NEW, 1)
        print("   ✓ 模型列表：4 个 -> 6 个，自定义的标「（自定义）」")
        print("   ✓ 加了「＋ 添加模型」绿色按钮")
    else:
        print("   ✗ 模型列表那段没匹配到（可能已经改过了）")

    if ANCHOR in src and 'H.get("addmodel"' not in src:
        src = src.replace(ANCHOR, ADD, 1)
        print("   ✓ 接了点击处理（start_text_input(\"model\")）")
    elif 'H.get("addmodel"' in src:
        print("   （点击处理已存在，跳过）")
    else:
        print("   ✗ key 按钮那段没匹配到")

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
