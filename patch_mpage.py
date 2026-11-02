#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""patch_mpage.py —— 模型列表改成分页（每页 4 个）

════════════════════════════════════════════════════════════════════
用户："好像只能显示四个？你要不加个翻页？"

原因：设置面板 P = [72, 72, 952, 560]，可用高度只有 488px。
      内容从 y=160 开始：
        标题 40 + 模型行 40×N + 添加按钮 44 + API Key 50 + 云端地址
      4 个模型时刚好塞满；我改成 6 个之后，第 5、6 行画到面板外面去了
      —— 所以用户看到"好像只能显示四个"。

修法：模型列表分页，每页 4 个，下面一行翻页控件：
        [◀ 上一页]   1 / 2   [下一页 ▶]
      最后一页末尾放「＋ 添加模型」。
      模型少于等于 4 个时不画翻页条（省得界面啰嗦）。

用法:
    python patch_mpage.py --check
    python patch_mpage.py
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

OLD = '''            # ★ 显示 6 个（面板够高）；自定义模型标个记号好区分
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

NEW = '''            # ★★★ 模型列表【分页】显示（用户："好像只能显示四个？加个翻页？"）
            #   面板可用高度只有 488px，4 行模型 + 添加按钮 + API Key +
            #   云端地址刚好塞满。多了就必须分页，不能硬画到面板外面。
            MPP = 4                      # 每页几个
            _n = max(1, len(self.models))
            _pages = (len(self.models) + MPP - 1) // MPP if self.models else 1
            _pg = min(max(0, getattr(self, "model_page", 0)), _pages - 1)
            self.model_page = _pg
            _lst = self.models[_pg * MPP:(_pg + 1) * MPP]
            for m in _lst:
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
            # ★ 翻页条（只有多于 1 页时才画）
            if _pages > 1:
                h["mpage:prev"] = [cx, y, cx + 96, y + 32]
                h["mpage:next"] = [cx + 210, y, cx + 306, y + 32]
                btn(scr, h["mpage:prev"], "◀ 上一页",
                    fill=(52, 62, 88) if _pg > 0 else (38, 38, 38),
                    size=15, cn=True, radius=8)
                btn(scr, h["mpage:next"], "下一页 ▶",
                    fill=(52, 62, 88) if _pg < _pages - 1 else (38, 38, 38),
                    size=15, cn=True, radius=8)
                scr.text((cx + 153, y + 16), "%d / %d" % (_pg + 1, _pages),
                         16, (200, 210, 230), anchor="mm", cn=True)
                y += 38
            # ★★★ 「＋ 添加模型」（用户："能添加模型吗"）
            #   点它进入文本输入模式（复用 API Key 那套 UI），
            #   打完回车写进 extra_models，列表立刻多一项。
            h["addmodel"] = [cx, y, cx + 190, y + 34]
            btn(scr, h["addmodel"], "＋ 添加模型", fill=(40, 96, 70),
                size=16, cn=True, radius=9)
            scr.text((cx + 202, y + 17), "输入模型名，如 deepseek-chat",
                     13, (140, 152, 176), anchor="lm", cn=True)
            y += 42
            sep(y - 6)
'''

# 点击处理：翻页
ANCHOR = '''                # ★ 添加模型：进入文本输入模式，回车写进 extra_models'''
ADD = '''                # ★ 模型列表翻页
                if hit(H.get("mpage:prev", [0, 0, 0, 0]), x, y):
                    app.model_page = max(0, getattr(app, "model_page", 0) - 1)
                    app.settings_open = True
                    continue
                if hit(H.get("mpage:next", [0, 0, 0, 0]), x, y):
                    app.model_page = getattr(app, "model_page", 0) + 1
                    app.settings_open = True
                    continue
                # ★ 添加模型：进入文本输入模式，回车写进 extra_models'''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()

    src = io.open(P, encoding="utf-8").read()
    orig = src
    print("=" * 68)
    print(" 模型列表改分页（每页 4 个）")
    print("=" * 68)

    if OLD in src:
        src = src.replace(OLD, NEW, 1)
        print("   ✓ 列表 -> 分页（每页 4），加了翻页条和页码")
    else:
        print("   ✗ 列表那段没匹配到")

    if ANCHOR in src and 'H.get("mpage:prev"' not in src:
        src = src.replace(ANCHOR, ADD, 1)
        print("   ✓ 接了翻页点击处理")
    elif 'H.get("mpage:prev"' in src:
        print("   （翻页处理已存在）")
    else:
        print("   ✗ 添加模型那段没匹配到")

    # 初始化 model_page
    if "self.model_page = 0" not in src:
        tgt = "        self.await_text = None          # ★ 等什么"
        if tgt in src:
            src = src.replace(tgt,
                              "        self.model_page = 0            # ★ 模型列表翻到第几页\n" + tgt, 1)
            print("   ✓ __init__ 里加了 model_page")

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
