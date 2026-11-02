#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""apps_notes.py —— 笔记（Markdown 存储）

功能：
    · 笔记列表（左栏）→ 点开查看/编辑
    · 新建 / 编辑 / 删除 / 保存
    · 存储为 Markdown 文件：/home/zynq/notes/*.md
    · 复用 fbui.MiniKeyboard 做文字输入（点输入框弹出）

布局（1024×600）：
    ┌──────────────────────────────────────────────┐
    │ 笔记                    [+ 新建]  [×] 关闭     │
    ├──────────┬───────────────────────────────────┤
    │ 列表     │ 标题：____________________         │
    │ · 笔记1  │ ┌───────────────────────────────┐  │
    │ · 笔记2  │ │ 内容（多行，自动折行）          │  │
    │ · 笔记3  │ │                               │  │
    │          │ └───────────────────────────────┘  │
    │          │ [保存] [删除]                      │
    ├──────────┴───────────────────────────────────┤
    │ 虚拟键盘（点标题/内容时弹出）                   │
    └──────────────────────────────────────────────┘
"""
import os
import time

import fbui
from fbui import hit, back_hit, btn, MiniKeyboard

W, H = 1024, 600
TOP_H = 40

# 配色
C_BG = (14, 18, 30)
C_PANEL = (22, 28, 44)
C_LIST = (18, 24, 38)
C_LIST_SEL = (40, 58, 92)
C_TEXT = (220, 230, 248)
C_DIM = (130, 145, 172)
C_ACCENT = (74, 158, 255)
C_OK = (92, 224, 138)
C_WARN = (255, 122, 92)
C_FIELD = (16, 22, 36)

NOTES_DIR = "/home/zynq/notes"
KB_Y = 348      # 键盘起始 y（弹出时覆盖下半屏）


# ---------------- 存储 ----------------
def _ensure_dir():
    os.makedirs(NOTES_DIR, exist_ok=True)


def list_notes():
    """返回 [(文件名, 标题, mtime)]，按修改时间倒序"""
    _ensure_dir()
    out = []
    for fn in os.listdir(NOTES_DIR):
        if not fn.endswith(".md"):
            continue
        p = os.path.join(NOTES_DIR, fn)
        try:
            with open(p, encoding="utf-8") as f:
                first = f.readline().strip()
            title = first[2:].strip() if first.startswith("# ") else (first or fn[:-3])
            out.append((fn, title[:24], os.path.getmtime(p)))
        except Exception:
            continue
    out.sort(key=lambda t: -t[2])
    return out


def load_note(fn):
    p = os.path.join(NOTES_DIR, fn)
    try:
        with open(p, encoding="utf-8") as f:
            txt = f.read()
    except Exception:
        return "", ""
    if txt.startswith("# "):
        i = txt.find("\n")
        title = txt[2:i].strip() if i > 0 else txt[2:].strip()
        body = txt[i + 1:].lstrip("\n") if i > 0 else ""
        return title, body
    return fn[:-3], txt


def save_note(fn, title, body):
    _ensure_dir()
    p = os.path.join(NOTES_DIR, fn)
    with open(p, "w", encoding="utf-8") as f:
        f.write("# %s\n\n%s" % (title, body))


def new_name():
    return "note_%s.md" % time.strftime("%Y%m%d_%H%M%S")


def delete_note(fn):
    try:
        os.remove(os.path.join(NOTES_DIR, fn))
        return True
    except Exception:
        return False


# ---------------- App ----------------
class NotesApp(object):
    def __init__(self, scr):
        self.scr = scr
        self.notes = list_notes()
        self.sel = 0                # 列表选中项
        self.fn = None              # 当前编辑的文件名
        self.title = ""
        self.body = ""
        self.field = None           # None / "title" / "body"
        self.kb = MiniKeyboard(y0=KB_Y, key_w=40, key_h=30, gap=4, arrows=True)
        self.dirty = False
        self.status = ""
        self.status_t = 0.0
        self.popup = False      # POPUP_MENU

    # ---------- 布局 ----------
    def _list_rect(self):
        return [10, TOP_H + 8, 250, H - 10]

    def _list_item_rect(self, i):
        y = TOP_H + 16 + i * 42
        return [14, y, 246, y + 38]

    def _title_rect(self):
        return [262, TOP_H + 12, W - 70, TOP_H + 48]

    def _body_rect(self):
        return [262, TOP_H + 56, W - 14, (KB_Y - 46) if self.field else (H - 52)]

    def _btn_new(self):
        return [W - 220, 4, W - 120, TOP_H - 4]

    def _btn_more(self):
        return [W - 110, 4, W - 10, TOP_H - 4]

    def _popup_rect(self):
        return [W - 250, TOP_H + 4, W - 10, TOP_H + 4 + 5 * 46 + 10]

    def _popup_items(self):
        return [("保存", "save"), ("新建", "new"),
                ("重命名", "rename"), ("导出 md", "export"),
                ("删除", "delete")]

    def _btn_save(self):
        return [262, H - 46 if not self.field else KB_Y - 42, 350, H - 8 if not self.field else KB_Y - 6]

    def _btn_del(self):
        return [360, self._btn_save()[1], 448, self._btn_save()[3]]

    # ---------- 绘制 ----------
    def draw(self):
        scr = self.scr
        scr.clear(C_BG)
        # 顶栏
        scr.rect([0, 0, W, TOP_H], fill=C_PANEL)
        scr.text((16, TOP_H // 2), "📝 笔记", 19, C_TEXT, anchor="lm", cn=True)
        if self.status and time.time() - self.status_t < 3:
            scr.text((W // 2, TOP_H // 2), self.status, 14, C_OK, anchor="mm", cn=True)
        btn(scr, self._btn_new(), "＋ 新建", fill=(40, 90, 150), size=15, cn=True)
        btn(scr, self._btn_more(), "⋮ 更多", fill=(60, 70, 100), size=15, cn=True)

        # 左：列表
        r = self._list_rect()
        scr.rect(r, fill=C_LIST)
        for i, (fn, title, _mt) in enumerate(self.notes[:12]):
            rr = self._list_item_rect(i)
            on = (i == self.sel)
            scr.rect(rr, fill=C_LIST_SEL if on else C_LIST)
            scr.text((rr[0] + 8, rr[1] + rr[3] // 2), title, 14,
                     C_TEXT if on else C_DIM, anchor="lm", cn=True)
        if not self.notes:
            scr.text((r[0] + 8, r[1] + 20), "（还没有笔记）", 13, C_DIM,
                     anchor="lm", cn=True)

        # 右：标题 + 内容
        if self.fn is not None:
            tr = self._title_rect()
            scr.rect(tr, fill=C_FIELD, outline=C_ACCENT if self.field == "title" else C_DIM, width=2)
            scr.text((tr[0] + 8, (tr[1] + tr[3]) // 2), self.title or "（点击输入标题）",
                     17, C_TEXT if self.title else C_DIM, anchor="lm", cn=True)
            if self.field == "title" and int(time.time() * 2) % 2 == 0:
                tw = scr.tw(self.title, 17, cn=True) if hasattr(scr, "tw") else 0
                cx = tr[0] + 10 + tw + 2
                scr.rect([cx, tr[1] + 8, cx + 2, tr[3] - 8], fill=C_ACCENT)

            br = self._body_rect()
            scr.rect(br, fill=C_FIELD, outline=C_ACCENT if self.field == "body" else C_DIM, width=2)
            lines = self._wrap(self.body, 30)
            maxl = max(1, (br[3] - br[1] - 12) // 22)
            for k, ln in enumerate(lines[:maxl]):
                scr.text((br[0] + 8, br[1] + 8 + k * 22), ln, 15, C_TEXT,
                         anchor="lm", cn=True)
            if self.field == "body" and int(time.time() * 2) % 2 == 0:
                k = min(len(lines) - 1, maxl - 1) if lines else 0
                last = lines[k] if lines else ""
                tw = scr.tw(last, 15, cn=True) if hasattr(scr, "tw") else 0
                cy = br[1] + 8 + k * 22
                scr.rect([br[0] + 10 + tw + 2, cy - 10, br[0] + 12 + tw + 2, cy + 10],
                         fill=C_ACCENT)

            btn(scr, self._btn_save(), "💾 保存", fill=(40, 110, 80), size=15, cn=True)
            btn(scr, self._btn_del(), "🗑 删除", fill=(140, 50, 50), size=15, cn=True)

        # 键盘
        if self.field is not None:
            self._draw_kb()
        if self.popup:
            self._draw_popup()

        scr.flush()

    def _wrap(self, s, n):
        out, cur = [], ""
        for ch in s:
            if ch == "\n":
                out.append(cur); cur = ""
                continue
            cur += ch
            if len(cur) >= n:
                out.append(cur); cur = ""
        out.append(cur)
        return out

    def _draw_popup(self):
        """POPUP_MENU: 操作弹窗（右上角）"""
        scr = self.scr
        r = self._popup_rect()
        scr.rect([0, TOP_H, W, H], fill=(6, 8, 14))
        scr.rrect(r, 10, fill=C_PANEL, outline=C_ACCENT, width=2)
        for i, (txt, key) in enumerate(self._popup_items()):
            ir = [r[0] + 8, r[1] + 8 + i * 46, r[2] - 8, r[1] + 8 + i * 46 + 40]
            scr.rrect(ir, 6, fill=(34, 44, 66))
            scr.text((ir[0] + 12, ir[1] + 20), txt, 15, C_TEXT, anchor="lm", cn=True)

    def _hit_popup(self, x, y):
        r = self._popup_rect()
        if not hit(r, x, y):
            self.popup = False; self.draw(); return True
        for i, (txt, key) in enumerate(self._popup_items()):
            ir = [r[0] + 8, r[1] + 8 + i * 46, r[2] - 8, r[1] + 8 + i * 46 + 40]
            if hit(ir, x, y):
                self.popup = False
                self._popup_action(key)
                return True
        return True

    def _popup_action(self, key):
        if key == "save":
            self.do_save()
        elif key == "new":
            self.do_new()
        elif key == "delete":
            self.do_delete()
        elif key == "rename":
            if self.fn is not None:
                self.field = "title"
                self._set_status("改标题后保存即可")
                self.draw()
        elif key == "export":
            if self.fn is not None:
                dst = "/home/zynq/received/" + self.fn
                try:
                    os.makedirs("/home/zynq/received", exist_ok=True)
                    with open(os.path.join(NOTES_DIR, self.fn), "rb") as f1,                          open(dst, "wb") as f2:
                        f2.write(f1.read())
                    self._set_status("已导出到 received/")
                except Exception as e:
                    self._set_status("导出失败: %s" % str(e)[:30])
                self.draw()

    def _draw_kb(self):
        scr = self.scr
        kb = self.kb
        scr.rect([0, KB_Y - 6, W, H], fill=(10, 14, 24))
        for k, r in kb.keys:
            btn(scr, r, k, fill=(38, 48, 70), size=15)
        btn(scr, kb.sp, "空格", fill=(38, 48, 70), size=14, cn=True)
        if kb.left:
            btn(scr, kb.left, "◀", fill=(38, 48, 70), size=14)
            btn(scr, kb.right, "▶", fill=(38, 48, 70), size=14)
        btn(scr, kb.bs, "⌫ 退格", fill=(90, 60, 50), size=14, cn=True)
        btn(scr, kb.ent, "✓ 完成", fill=(40, 110, 80), size=14, cn=True)

    # ---------- 动作 ----------
    def _set_status(self, msg):
        self.status = msg
        self.status_t = time.time()

    def open_note(self, i):
        if i < 0 or i >= len(self.notes):
            return
        self.sel = i
        fn = self.notes[i][0]
        self.fn = fn
        self.title, self.body = load_note(fn)
        self.field = None
        self.dirty = False
        self.draw()

    def do_new(self):
        self.fn = new_name()
        self.title = ""
        self.body = ""
        self.field = "title"
        save_note(self.fn, "", "")
        self.notes = list_notes()
        self.sel = 0
        self.draw()

    def do_save(self):
        if self.fn is None:
            return
        save_note(self.fn, self.title or "无标题", self.body)
        self.notes = list_notes()
        self.dirty = False
        self._set_status("已保存")
        self.draw()

    def do_delete(self):
        if self.fn is None:
            return
        if delete_note(self.fn):
            self.notes = list_notes()
            self.fn = None
            self.sel = 0
            self._set_status("已删除")
        self.draw()

    def _kb_tap(self, x, y):
        kb = self.kb
        target = self.title if self.field == "title" else self.body
        changed = False
        for k, r in kb.keys:
            if hit(r, x, y):
                target += k; changed = True
                break
        if not changed:
            if hit(kb.sp, x, y):
                target += " "; changed = True
            elif hit(kb.bs, x, y):
                target = target[:-1]; changed = True
            elif kb.left and hit(kb.left, x, y):
                pass        # 简化：不支持光标移动
            elif hit(kb.ent, x, y):
                self.field = None
                self.draw()
                return
        if changed:
            if self.field == "title":
                self.title = target
            else:
                self.body = target
            self.dirty = True
            self.draw()

    def handle(self, x, y, kind="down"):
        if kind == "move":
            return True
        if kind == "up":
            return True
        if back_hit(x, y):
            return False
        if self.popup:
            return self._hit_popup(x, y)
        if hit(self._btn_more(), x, y):
            self.popup = True
            self.draw()
            return True
        # 键盘优先
        if self.field is not None:
            # 点标题/内容区可切换焦点
            if hit(self._title_rect(), x, y):
                self.field = "title"; self.draw(); return True
            if hit(self._body_rect(), x, y):
                self.field = "body"; self.draw(); return True
            self._kb_tap(x, y)
            return True
        # 新建
        if hit(self._btn_new(), x, y):
            self.do_new(); return True
        # 列表
        for i in range(len(self.notes[:12])):
            if hit(self._list_item_rect(i), x, y):
                self.open_note(i); return True
        # 编辑区 → 弹键盘
        if self.fn is not None:
            if hit(self._title_rect(), x, y):
                self.field = "title"; self.draw(); return True
            if hit(self._body_rect(), x, y):
                self.field = "body"; self.draw(); return True
            if hit(self._btn_save(), x, y):
                self.do_save(); return True
            if hit(self._btn_del(), x, y):
                self.do_delete(); return True
        return True


def run(scr, touch):
    app = NotesApp(scr)
    # 打开第一张笔记
    if app.notes:
        app.open_note(0)
    else:
        app.draw()
    while True:
        ev = touch.poll(move=True)
        if ev:
            x = y = 0
            kind = "down"
            if isinstance(ev, (list, tuple)):
                if len(ev) >= 3:
                    x, y = ev[1], ev[2]
                    kind = ev[3] if len(ev) > 3 else "down"
                elif len(ev) == 2:
                    x, y = ev
            if not app.handle(x, y, kind):
                return
        else:
            # 光标闪烁靠重绘
            if app.field is not None:
                app.draw()
        time.sleep(0.05)
