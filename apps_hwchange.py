#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""apps_hwchange.py —— 硬件变更历史（「agent 改 FPGA」的可视化证据）

════════════════════════════════════════════════════════════════════
为什么要有这个 App
════════════════════════════════════════════════════════════════════
这个项目最核心的主张是「**agent 能改自己的硬件**」。
但改硬件这件事本身是看不见的 —— 改了 RTL、重新综合、刷了流，
屏幕上什么都没发生。评审/观众凭什么信？

这个 App 就是那个"看得见"的部分：
    · 每一次改动都有记录（什么时间、改了哪个文件、改成什么、谁改的）
    · 每条记录能不能回滚一目了然
    · 点一下就能回滚，而且回滚本身也进历史

演示的时候：让 agent 改个东西 → 打开这个 App → 记录就在那儿 →
点回滚 → 又回到原样。整条链路肉眼可见。

════════════════════════════════════════════════════════════════════
数据从哪来
════════════════════════════════════════════════════════════════════
    /var/lib/hwchange/changes.jsonl     变更单（JSONL，一行一条）
    /var/lib/hwchange/snapshots/<id>/   快照（能恢复多个文件）
    <file>.bak_hdl_<ts>_<rand>          单文件备份（hw_hdl_edit 留的）

★ 兼容两条回滚路径：
    有快照 -> 用快照（能恢复多个文件）
    没快照 -> 用变更单里记的 backup 路径
  这是 hw_change.rollback() 已经实现的，这里直接调它。

════════════════════════════════════════════════════════════════════
界面
════════════════════════════════════════════════════════════════════
    ┌──────────────────────────────────────────────────────┐
    │ ←  硬件变更历史                          刷新        │
    ├──────────────────────────────────────────────────────┤
    │ [全部] [HDL] [构建] [刷流] [回滚]   共 42 条          │
    ├──────────────────────────────────────────────────────┤
    │ 14:39  HDL    改 scope_cap.v                          │
    │        加外部采样有效输入                              │
    │        ✓ 可回滚                            [回滚]     │
    ├──────────────────────────────────────────────────────┤
    │ 14:30  构建   提交构建任务 ...                        │
    │        给示波器加外部触发                              │
    │        结果 ok                                        │
    └──────────────────────────────────────────────────────┘

★ 所有读文件/跑命令都在后台线程（有看门狗，主循环不能阻塞）。
"""
import json
import os
import queue
import subprocess
import sys
import threading
import time

from fbui import header, back_hit, btn, hit

W, H = 1024, 600
HDR = 56
PAD = 26
CHANGE_FILE = "/var/lib/hwchange/changes.jsonl"
SNAP_DIR = "/var/lib/hwchange/snapshots"

# 类型 -> (显示名, 颜色)
KINDS = {
    "hdl":       ("HDL",   (86, 140, 246)),
    "bd":        ("BD",    (150, 110, 235)),
    "bitstream": ("刷流",  (235, 150, 60)),
    "build":     ("构建",  (60, 180, 150)),
    "driver":    ("驱动",  (200, 120, 180)),
    "dataset":   ("数据集", (120, 180, 90)),
    "rollback":  ("回滚",  (200, 90, 90)),
}
FILTERS = [("全部", None), ("HDL", "hdl"), ("构建", "build"),
           ("刷流", "bitstream"), ("回滚", "rollback")]

ROW_H = 66
LIST_TOP = 150      # ★ 给状态行让位（原来 132 会和过滤器叠在一起）
MAX_ROWS = 6


def _read_changes(limit=400):
    """读变更单（新→旧）"""
    out = []
    try:
        with open(CHANGE_FILE, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except Exception:
        return out
    for ln in lines[-limit:]:
        ln = ln.strip()
        if not ln:
            continue
        try:
            out.append(json.loads(ln))
        except Exception:
            pass
    out.reverse()
    return out


def _has_snapshot(cid):
    try:
        return os.path.exists(os.path.join(SNAP_DIR, cid, "manifest.json"))
    except Exception:
        return False


def _rollback_worker(cid, q):
    """★ 后台线程里回滚 —— 别阻塞主循环（看门狗 25 秒）"""
    try:
        sys.path.insert(0, "/home/zynq")
        from agent import hw_change as HC
        ok, why = HC.rollback(cid, verbose=False)
        q.put(("rollback", ok, str(why)))
    except Exception as e:
        q.put(("rollback", False, "%s: %s" % (type(e).__name__, e)))


def _load_worker(filt, q):
    """后台线程里读变更单"""
    try:
        recs = _read_changes()
        items = []
        for r in recs:
            if filt and r.get("kind") != filt:
                continue
            # ★★★ 必须检查备份文件【是否真的还在】★★★
            #
            # 踩过：原来只判断 backup 字段非空就给"回滚"按钮，
            # 但备份文件可能早被清理了（比如演示脚本 /tmp 收尾时删掉了），
            # 于是那个按钮点了必然失败 —— 用户看到的就是"点了没反应"。
            # cloud_api 的 /hw/changes 有 backup_exists 字段就是这个意思；
            # 这个 App 直接读文件系统，自己判一下。
            bak = r.get("backup") or ""
            bak_alive = bool(bak and os.path.exists(bak))
            snap = _has_snapshot(r.get("id", ""))
            items.append({
                "id": r.get("id", "?"),
                "ts": (r.get("ts") or "")[11:16],       # 只取 HH:MM
                "date": (r.get("ts") or "")[:10],
                "kind": r.get("kind", "?"),
                "detail": r.get("detail", ""),
                "result": r.get("result", ""),
                "who": r.get("who", ""),
                "path": r.get("path", ""),
                "backup": bak,
                "snap": snap,
                "backup_alive": bak_alive,
                # ★ rb 才是"真的能回滚"：有快照，或者备份文件还在
                "rb": bool(snap or (bak_alive and r.get("path"))),
            })
        q.put(("list", True, items))
    except Exception as e:
        q.put(("list", False, "%s: %s" % (type(e).__name__, e)))


class App(object):
    def __init__(self):
        self.items = []
        self.filt = None
        self.filt_name = "全部"
        self.sel = 0
        self.scroll = 0
        self.status = "正在读变更单…"
        self.busy = False
        self.q = queue.Queue()
        self.confirm = None          # 待确认的回滚 id
        self._down = None            # ★ 按下时的坐标（down..up 当成点击用）
        self.t0 = time.time()
        self.reload()

    # ---- 数据 ----
    def reload(self):
        if self.busy:
            return
        self.busy = True
        self.status = "正在读变更单…"
        threading.Thread(target=_load_worker, args=(self.filt, self.q),
                         daemon=True).start()

    def poll(self):
        """★ 主循环每帧调一次 —— 只做非阻塞的队列检查"""
        try:
            while True:
                kind, ok, payload = self.q.get_nowait()
                if kind == "list":
                    self.busy = False
                    if ok:
                        self.items = payload
                        self.sel = 0
                        self.scroll = 0
                        n_rb = len([i for i in self.items
                                    if i["rb"]])
                        self.status = "共 %d 条，其中 %d 条可回滚" % (
                            len(self.items), n_rb)
                    else:
                        self.status = "读失败：" + str(payload)[:60]
                elif kind == "rollback":
                    self.busy = False
                    if ok:
                        self.status = "✓ 回滚成功：" + str(payload)[:60]
                    else:
                        self.status = "✗ 回滚失败：" + str(payload)[:60]
                    self.confirm = None
                    time.sleep(0.4)
                    self.reload()
        except queue.Empty:
            pass

    def do_rollback(self):
        it = self.items[self.sel] if 0 <= self.sel < len(self.items) else None
        if not it:
            return
        if not it["rb"]:
            self.status = "这条没有快照也没有备份，回滚不了"
            return
        self.busy = True
        self.status = "正在回滚 %s …" % it["id"]
        threading.Thread(target=_rollback_worker, args=(it["id"], self.q),
                         daemon=True).start()

    # ---- 布局 ----
    def rows(self):
        """返回 [(rect, action), ...] 给主循环做命中测试"""
        out = []
        # 过滤器
        x = PAD
        for name, k in FILTERS:
            w = 34 + len(name) * 15
            out.append(([x, 92, x + w, 124], ("filt", k, name)))
            x += w + 8
        # 刷新
        out.append(([W - PAD - 88, 92, W - PAD, 124], ("reload",)))
        # 列表
        y = LIST_TOP
        shown = self.items[self.scroll:self.scroll + MAX_ROWS]
        for i, it in enumerate(shown):
            idx = self.scroll + i
            r = [PAD, y, W - PAD, y + ROW_H - 6]
            out.append((r, ("row", idx)))
            # 回滚按钮
            if it["rb"]:
                out.append(([W - PAD - 96, y + 30, W - PAD - 12, y + 60],
                            ("rb", idx)))
            y += ROW_H
        # 滚动
        if len(self.items) > MAX_ROWS:
            out.append(([W - PAD + 6, 158, W - 8, 238], ("up",)))
            out.append(([W - PAD + 6, 258, W - 8, 338], ("down",)))
        # 确认框
        if self.confirm:
            out.append(([W // 2 - 190, H // 2 + 46, W // 2 - 12, H // 2 + 94],
                        ("yes",)))
            out.append(([W // 2 + 12, H // 2 + 46, W // 2 + 190, H // 2 + 94],
                        ("no",)))
        return out

    # ---- 画 ----
    def draw(self, scr):
        scr.clear((20, 20, 20))
        header(scr, "硬件变更历史")

        # ---- 过滤器 ----
        for name, k in FILTERS:
            w = 34 + len(name) * 15
            x = PAD
            # 找这个过滤器的 x（和 rows() 一致）
            for n2, k2 in FILTERS:
                if n2 == name:
                    break
                x += 34 + len(n2) * 15 + 8
            cur = (k == self.filt)
            scr.rrect([x, 92, x + w, 124], 10,
                      fill=(46, 78, 140) if cur else (34, 34, 34),
                      outline=(70, 110, 190) if cur else (60, 60, 60))
            scr.text((x + w // 2, 108), name, 17,
                     (255, 255, 255) if cur else (170, 185, 215),
                     cn=True, anchor="mm")

        btn(scr, [W - PAD - 88, 92, W - PAD, 124], "刷新",
            fill=(52, 92, 150), size=17, cn=True)

        # ---- 状态行 ----
        # ★ 位置要让开过滤器（它们在 92~124），所以放在 132 上方一点点，
        #   而列表从 LIST_TOP=146 开始（原来 132 会和过滤器叠在一起 —— 截图里看到了）
        scr.text((PAD, 136), self.status, 15, (150, 200, 150) if
                 self.status.startswith("✓") else
                 ((230, 140, 140) if self.status.startswith("✗")
                  else (140, 155, 185)), cn=True, anchor="lm")

        # ---- 列表 ----
        y = LIST_TOP
        shown = self.items[self.scroll:self.scroll + MAX_ROWS]
        if not shown:
            scr.text((W // 2, H // 2), "没有变更记录" if not self.busy
                     else "正在读…", 22, (130, 145, 180), cn=True,
                     anchor="mm")
        for i, it in enumerate(shown):
            idx = self.scroll + i
            cur = (idx == self.sel)
            r = [PAD, y, W - PAD, y + ROW_H - 6]
            scr.rrect(r, 10,
                      fill=(45, 45, 45) if cur else (32, 32, 32),
                      outline=(70, 100, 160) if cur else (50, 50, 50))

            kname, kcol = KINDS.get(it["kind"], (it["kind"][:4], (139, 139, 139)))
            # 类型徽标
            scr.rrect([r[0] + 10, y + 8, r[0] + 10 + 54, y + 30], 6, fill=kcol)
            scr.text((r[0] + 37, y + 19), kname, 15, (255, 255, 255),
                     cn=True, anchor="mm")
            # 时间
            scr.text((r[0] + 74, y + 19), it["ts"], 15, (160, 175, 205),
                     anchor="lm")
            # 详情（截断）
            d = it["detail"]
            if len(d) > 44:
                d = d[:43] + "…"
            scr.text((r[0] + 130, y + 19), d, 16, (231, 231, 231),
                     cn=True, anchor="lm")
            # 结果
            res = it["result"]
            if len(res) > 52:
                res = res[:51] + "…"
            okc = (120, 200, 140) if ("成功" in res or res == "ok" or
                                      "ok" in res) else (184, 184, 184)
            scr.text((r[0] + 130, y + 42), res or "—", 14, okc,
                     cn=True, anchor="lm")

            # 回滚按钮
            if it["rb"]:
                meth = "快照" if it["snap"] else ("备份" if it["backup_alive"] else "备份已丢")
                scr.text((W - PAD - 150, y + 44), meth, 13, (140, 160, 195),
                         cn=True, anchor="lm")
                btn(scr, [W - PAD - 96, y + 30, W - PAD - 12, y + 60],
                    "回滚", fill=(150, 70, 60), size=15, cn=True)
            else:
                scr.text((W - PAD - 150, y + 44), "不可回滚", 13,
                         (117, 117, 117), cn=True, anchor="lm")
            y += ROW_H

        # ---- 滚动提示 ----
        if len(self.items) > MAX_ROWS:
            scr.text((W - PAD + 2, 154), "▲", 16, (110, 130, 170), anchor="mm")
            scr.text((W - PAD + 2, 242), "▼", 16, (110, 130, 170), anchor="mm")
            scr.text((W - PAD + 2, 198), "%d/%d" % (self.scroll + 1,
                     len(self.items)), 12, (120, 135, 165), anchor="mm")

        # ---- 确认框 ----
        if self.confirm:
            cid = self.confirm
            scr.rrect([W // 2 - 330, H // 2 - 40, W // 2 + 330, H // 2 + 110],
                      16, fill=(38, 38, 38), outline=(90, 120, 180))
            scr.text((W // 2, H // 2), "确定要回滚这条变更？", 26,
                     (244, 244, 244), cn=True, anchor="mm")
            scr.text((W // 2, H // 2 + 26), cid, 15, (165, 180, 210),
                     anchor="mm")
            btn(scr, [W // 2 - 190, H // 2 + 46, W // 2 - 12, H // 2 + 94],
                "确定回滚", fill=(160, 70, 60), size=19, cn=True)
            btn(scr, [W // 2 + 12, H // 2 + 46, W // 2 + 190, H // 2 + 94],
                "取消", fill=(68, 68, 68), size=19, cn=True)


def run(scr, touch):
    app = App()
    last_beat = 0.0

    def on_click(x, y, rows):
        """返回 True 表示退出 App"""
        if back_hit(x, y):
            if app.confirm:
                app.confirm = None
                return False
            return True

        # ★ 确认框在最上层，先处理它
        if app.confirm:
            for r, act in rows:
                if not hit(r, x, y):
                    continue
                if act == ("yes",):
                    app.do_rollback()
                    return False
                if act == ("no",):
                    app.confirm = None
                    app.status = "已取消"
                    return False
            return False      # 确认框开着时点别处不生效

        # ★★★ 按钮要【优先】于行 ★★★
        #
        # 踩过：rows() 里"行"排在"按钮"前面，而这个循环命中第一个就 return，
        # 于是行矩形把回滚按钮盖住了 —— 点按钮只会把那一行选中（高亮），
        # 永远弹不出确认框。
        # 修法：遇到行先记着，等所有非行元素都检查完、确实没命中别的，
        #       才把它当"选中行"处理。
        row_hit = None
        for r, act in rows:
            if not hit(r, x, y):
                continue
            if not isinstance(act, tuple):
                continue
            k = act[0]
            if k == "row":
                row_hit = act[1]        # 先记下，不立刻处理
                continue
            if k == "filt":
                app.filt = act[1]
                app.filt_name = act[2]
                app.sel = 0
                app.scroll = 0
                app.reload()
            elif k == "reload":
                app.reload()
            elif k == "rb":
                app.sel = act[1]
                it = app.items[act[1]]
                if it["rb"]:
                    app.confirm = it["id"]
                else:
                    app.status = "这条不可回滚"
            elif k == "up":
                app.scroll = max(0, app.scroll - 1)
            elif k == "down":
                app.scroll = min(max(0, len(app.items) - MAX_ROWS),
                                 app.scroll + 1)
            return False

        if row_hit is not None:
            app.sel = row_hit
        return False
        return False

    while True:
        app.poll()
        rows = app.rows()
        app.draw(scr)
        scr.flush()

        # ★ 心跳：这个 App 可能开着很久，得让看门狗知道桌面还活着
        now = time.time()
        if now - last_beat > 5:
            last_beat = now
            try:
                with open("/run/desktop_beat", "w") as f:
                    f.write(str(int(now)))
            except Exception:
                pass

        # ★★★ 触摸事件：必须用 touch.poll(move=True) ★★★
        #
        # 踩过：我第一版写了 `touch.wait(200)` —— 那是我在离线测试里
        # 给假 Touch 编的方法，板上真的 fbui.Touch 根本没有 wait()。
        # 结果一打开这个 App 就报：
        #     AttributeError: 'Touch' object has no attribute 'wait'
        # 真实 API（见 ui/fbui.py 的 Touch 类和 apps_settings.py 的用法）：
        #     ev = touch.poll(move=True)  ->  None 或 ("tap",x,y) / ("down",x,y) ...
        ev = touch.poll(move=True)
        if not ev:
            time.sleep(0.02)      # ★ 没事件也要小睡一下，否则空转烧 CPU
            continue
        kind = ev[0] if isinstance(ev, (tuple, list)) else ev
        if kind == "tap":
            x, y = ev[1], ev[2]
            if on_click(x, y, rows):
                return
        elif kind == "down":
            # 有些触摸屏点按是 down..up 两个事件，up 才是"点击"。
            # 这里记下位置，等 up 再当点击处理。
            app._down = (ev[1], ev[2])
        elif kind == "up":
            x, y = ev[1], ev[2]
            dx = abs(x - (app._down or (x, y))[0])
            dy = abs(y - (app._down or (x, y))[1])
            app._down = None
            if dx < 20 and dy < 20:        # 没怎么动 -> 当成点击
                if on_click(x, y, rows):
                    return
        elif kind == "key":
            k = ev[1] if len(ev) > 1 else ""
            if k in ("esc", "back"):
                if app.confirm:
                    app.confirm = None
                else:
                    return
            elif k in ("down", "j"):
                app.sel = min(len(app.items) - 1, app.sel + 1)
                if app.sel >= app.scroll + MAX_ROWS:
                    app.scroll = app.sel - MAX_ROWS + 1
            elif k in ("up", "k"):
                app.sel = max(0, app.sel - 1)
                if app.sel < app.scroll:
                    app.scroll = app.sel
            elif k in ("enter", "return"):
                it = app.items[app.sel] if app.items else None
                if it and it["rb"]:
                    app.confirm = it["id"]
            elif k == "r":
                app.reload()


if __name__ == "__main__":
    print("这个模块是给桌面调用的：模块里要有 def run(scr, touch)")
    print("单独运行请用：python3 -c \"import apps_hwchange\"")
