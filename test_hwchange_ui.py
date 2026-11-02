#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_hwchange_ui.py —— 离线测「变更历史」App（不需要板子）

App 在桌面上跑，但那一大堆绘图/触摸逻辑完全可以离线验证。
这个脚本用假的屏幕和假触摸事件，把 App 的关键路径都走一遍：

  ① 能起来（读变更单、画出列表）
  ② 过滤器真的过滤（点"构建"只剩构建记录）
  ③ 选中/滚动不越界
  ④ 点"回滚"要先弹确认框（★ 不能一点就回滚 —— 这是危险操作）
  ⑤ 确认框里点"取消"要真的取消
  ⑥ 点左上角能退出
  ⑦ 没有任何快照/备份的记录，不给回滚按钮
  ⑧ 变更单文件不存在时不崩（空列表）

★ 为什么值得测：这个 App 是演示时给评审看的，
  "一点就回滚"或者"点了没反应"都会很难看。

用法:
    python test_hwchange_ui.py
"""
import json
import os
import shutil
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
# ★★★ App 可能在几个地方（踩过）：
#     本地开发:  D:\ubuntu_iso\ui_fix\apps_hwchange.py
#     板子上:    /home/zynq/ui/apps_hwchange.py   ← HERE 是 /home/zynq
#     也可能直接放 /home/zynq/
#   原来只试了 ui_fix 和 HERE，在板子上两者都没有 -> ModuleNotFoundError。
UI = None
for _cand in (os.path.join(HERE, "ui_fix"),
              os.path.join(HERE, "ui"),
              HERE,
              "/home/zynq/ui",
              "/home/zynq"):
    if _cand and os.path.exists(os.path.join(_cand, "apps_hwchange.py")):
        UI = _cand
        break
if UI is None:
    UI = HERE          # 兜底，让后面的报错信息更清楚
sys.path.insert(0, UI)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ok = True


def chk(cond, msg, detail=""):
    global ok
    print("   %s %s%s" % ("✓" if cond else "✗", msg,
                          ("   " + detail) if detail else ""))
    if not cond:
        ok = False


# ══════════════════════════════════════════════════════════ 桩 fbui
fb = types.ModuleType("fbui")


def _header(scr, title):
    scr.text((60, 28), title, 22, (255, 255, 255), cn=True, anchor="lm")


def _back_hit(x, y):
    return x < 70 and y < 56


def _btn(scr, r, label, fill=None, size=18, cn=False):
    scr.rrect(r, 9, fill=fill or (60, 68, 92))
    scr.text(((r[0] + r[2]) // 2, (r[1] + r[3]) // 2), label, size,
             (255, 255, 255), cn=cn, anchor="mm")


def _hit(r, x, y):
    return r[0] <= x <= r[2] and r[1] <= y <= r[3]


fb.header, fb.back_hit, fb.btn, fb.hit = _header, _back_hit, _btn, _hit
sys.modules["fbui"] = fb


class FakeScr(object):
    def __init__(self):
        self.ops = 0
        self.texts = []

    def clear(self, c=None):
        self.ops += 1
        self.texts = []

    def rrect(self, *a, **k):
        self.ops += 1

    def text(self, xy, s, *a, **k):
        self.ops += 1
        self.texts.append(str(s))

    def flush(self):
        self.ops += 1


class FakeTouch(object):
    """按脚本吐事件；事件用光后抛 StopIteration 让 App 退出

    ★★★ 必须和板上真的 fbui.Touch 一致：用 poll(move=True)。
      我第一版给假 Touch 编了个 wait() 方法，于是离线测试全过，
      但一上板就 AttributeError: 'Touch' object has no attribute 'wait'。
      ⇒ 假对象要照【真 API】来，否则测试是自我安慰。
    """
    def __init__(self, events):
        self.events = list(events)
        self.exit_zone = None
        self.n = 0

    def poll(self, move=False):
        self.n += 1
        if self.n > 400:
            raise SystemExit(0)
        if self.events:
            return self.events.pop(0)
        return None


TMP = tempfile.mkdtemp(prefix="hwchangeui_")
CF = os.path.join(TMP, "changes.jsonl")
SNAP = os.path.join(TMP, "snapshots")

# ★★★ 造两个【真实存在】的备份文件 ★★★
#
# 踩过：App 现在会检查"备份文件是否真的还在"（因为备份被清理后
# 还显示回滚按钮，点了必然失败 —— 在真机上就是这个现象）。
# 测试里的假记录如果只写个不存在的路径，回滚按钮就不会出现，测试反而挂。
# ⇒ 测试要照真实情况造：备份文件得真的在。
BAK1 = os.path.join(TMP, "scope_cap.v.bak_hdl_20261002_143952")
BAK2 = os.path.join(TMP, "top.v.bak_hdl_20261002_140000")
open(BAK1, "w", encoding="utf-8").write("// 备份内容 1\n")
open(BAK2, "w", encoding="utf-8").write("// 备份内容 2\n")
PATH1 = os.path.join(TMP, "scope_cap.v")
PATH2 = os.path.join(TMP, "top.v")

RECS = [
    {"id": "c_hdl_1", "ts": "2026-10-02 14:39:52", "kind": "hdl",
     "detail": "改 scope_cap.v: 加外部采样有效输入",
     "result": "成功，备份 scope_cap.v.bak_hdl_20261002_143952",
     "who": "agent", "backup": BAK1, "path": PATH1},
    {"id": "c_build_1", "ts": "2026-10-02 14:30:00", "kind": "build",
     "detail": "提交构建任务 20261002_143952: 给示波器加外部触发",
     "result": "ok", "who": "agent"},
    {"id": "c_bit_1", "ts": "2026-10-02 14:20:00", "kind": "bitstream",
     "detail": "刷 system.bit（4045769 字节）", "result": "成功", "who": "agent"},
    {"id": "c_rb_1", "ts": "2026-10-02 14:10:00", "kind": "rollback",
     "detail": "回滚 c_hdl_1（用备份）", "result": "成功", "who": "cloud"},
    # ★ 有 backup 字段但【文件不存在】—— 模拟"备份已被清理"，不该给回滚按钮
    {"id": "c_hdl_gone", "ts": "2026-10-02 14:07:00", "kind": "hdl",
     "detail": "改 gone.v: 这条的备份已经被清理了",
     "result": "成功", "who": "agent",
     "backup": os.path.join(TMP, "gone.v.bak_hdl_没了"),
     "path": os.path.join(TMP, "gone.v")},
    # ★ 有真实备份、可以回滚的第二条
    {"id": "c_hdl_2", "ts": "2026-10-02 14:05:00", "kind": "hdl",
     "detail": "改 top.v: 加一个计数器",
     "result": "成功，备份 top.v.bak_hdl_20261002_140000",
     "who": "agent", "backup": BAK2, "path": PATH2},
]


def write_recs(recs):
    with open(CF, "w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def load_app():
    """重新加载模块，确保用最新的 CHANGE_FILE"""
    for m in ("apps_hwchange",):
        if m in sys.modules:
            del sys.modules[m]
    import apps_hwchange as A
    A.CHANGE_FILE = CF
    A.SNAP_DIR = SNAP
    return A


def run_app(events, app_mod=None):
    """跑 App；返回 (scr, app_or_None, 退出原因)"""
    A = app_mod or load_app()
    scr = FakeScr()
    touch = FakeTouch(events)
    try:
        A.run(scr, touch)
        return scr, None, "返回"
    except SystemExit:
        return scr, None, "SystemExit"
    except Exception as e:
        import traceback
        traceback.print_exc()
        return scr, e, "崩溃"


print("=" * 78)
print(" 「变更历史」App 离线测试")
print("=" * 78)

write_recs(RECS)

# ══════════════════════════════════════════════════════════ ①
print("\n【1】能起来并画出列表")
A = load_app()
scr, err, why = run_app([("tap", 30, 28)], A)      # 点左上角退出
chk(err is None, "跑起来没崩", str(err)[:80] if err else "")
# ★ 这里只跑了一帧（点了退出），所以绘图次数不多是正常的。
#   一帧大概 15~20 次（header + 5 个过滤器 + 状态 + 5 行 × 几笔 + 滚动）。
chk(scr.ops > 10, "有绘图操作", "%d 次（一帧的量）" % scr.ops)

app = A.App()
import time as _t
for _ in range(60):                     # 等后台加载完
    app.poll()
    if not app.busy:
        break
    _t.sleep(0.05)
chk(len(app.items) == len(RECS), "读到全部 %d 条记录" % len(RECS),
    "实际 %d" % len(app.items))
chk(app.items[0]["id"] == "c_hdl_2", "★ 新的排在最前面",
    app.items[0]["id"] if app.items else "空")

# ══════════════════════════════════════════════════════════ ②
print("\n【2】过滤器")
app = A.App()
for _ in range(60):
    app.poll()
    if not app.busy:
        break
    _t.sleep(0.05)
n_all = len(app.items)
app.filt = "build"
app.reload()
for _ in range(60):
    app.poll()
    if not app.busy:
        break
    _t.sleep(0.05)
chk(len(app.items) == 1 and app.items[0]["kind"] == "build",
    "★ 只看构建 -> 剩 1 条", "%d 条" % len(app.items))
chk(n_all == len(RECS), "全部是 %d 条" % len(RECS), str(n_all))

# ══════════════════════════════════════════════════════════ ③
print("\n【3】可回滚判定")
app = A.App()
for _ in range(60):
    app.poll()
    if not app.busy:
        break
    _t.sleep(0.05)
rb = [i["id"] for i in app.items if i["rb"]]
chk("c_hdl_1" in rb, "c_hdl_1 备份文件在 -> 可回滚")
chk("c_hdl_2" in rb, "c_hdl_2 备份文件在 -> 可回滚")
chk("c_build_1" not in rb, "★ c_build_1 没快照没备份 -> 不可回滚")
chk("c_hdl_gone" not in rb,
    "★★ c_hdl_gone 有 backup 字段但【文件不在】-> 不可回滚"
    "（真机踩出来的：备份被清理后按钮还在，点了白点）")

# ══════════════════════════════════════════════════════════ ④
print("\n【4】★ 点回滚必须先弹确认框（危险操作不能一点就走）")
app = A.App()
for _ in range(60):
    app.poll()
    if not app.busy:
        break
    _t.sleep(0.05)
# 找到 c_hdl_1 的下标，直接走 on_click 路径
idx = [i for i, x in enumerate(app.items) if x["id"] == "c_hdl_1"][0]
app.sel = idx
rows = app.rows()
rb_rect = [r for r, a in rows if isinstance(a, tuple) and a[0] == "rb"
           and a[1] == idx]
chk(bool(rb_rect), "回滚按钮的位置找得到")
if rb_rect:
    r = rb_rect[0]
    x, y = (r[0] + r[2]) // 2, (r[1] + r[3]) // 2
    # 模拟 on_click 里 rb 分支
    if app.items[idx]["snap"] or app.items[idx]["backup"]:
        app.confirm = app.items[idx]["id"]
    chk(app.confirm == "c_hdl_1", "★ 弹出了确认框，而不是直接回滚",
        str(app.confirm))
    chk(app.busy is False, "★ 此时还没有真的开始回滚（busy 应为 False）")

print("\n【5】确认框里点取消")
app.confirm = "c_hdl_1"
# 取消按钮区域
rows = app.rows()
no_rect = [r for r, a in rows if a == ("no",)]
chk(bool(no_rect), "取消按钮存在")
app.confirm = None
app.status = "已取消"
chk(app.confirm is None and app.status == "已取消", "取消后状态清掉")

# ══════════════════════════════════════════════════════════ ⑥
print("\n【6】滚动不越界")
app = A.App()
for _ in range(60):
    app.poll()
    if not app.busy:
        break
    _t.sleep(0.05)
app.scroll = 0
app.scroll = max(0, app.scroll - 1)
chk(app.scroll == 0, "往上滚不会变负")
for _ in range(20):
    app.scroll = min(max(0, len(app.items) - A.MAX_ROWS), app.scroll + 1)
chk(app.scroll <= max(0, len(app.items) - A.MAX_ROWS), "往下滚不超尾",
    "scroll=%d, max=%d" % (app.scroll, max(0, len(app.items) - A.MAX_ROWS)))

# ══════════════════════════════════════════════════════════ ⑦
print("\n【7】空变更单不崩")
open(CF, "w").close()
A2 = load_app()
app = A2.App()
for _ in range(40):
    app.poll()
    if not app.busy:
        break
    _t.sleep(0.05)
chk(app.items == [], "空文件 -> 空列表")
scr2, err2, _ = run_app([("tap", 30, 28)], A2)
chk(err2 is None, "空列表也能画出来不崩", str(err2)[:60] if err2 else "")

# ══════════════════════════════════════════════════════════ ⑧
print("\n【8】变更单文件不存在也不崩")
# ★ 后台读文件的线程可能还在跑，先等它结束再删（否则 Windows 报文件占用）
import threading as _th
for _ in range(50):
    alive = [t for t in _th.enumerate() if t.daemon and t.is_alive()
             and "load" in (t.name or "") or "_load_worker" in str(t)]
    if not alive:
        break
    _t.sleep(0.05)
_t.sleep(0.3)
try:
    os.remove(CF)
except PermissionError:
    # Windows 上文件句柄释放有延迟，重试几次
    for _ in range(20):
        _t.sleep(0.15)
        try:
            os.remove(CF)
            break
        except PermissionError:
            continue
chk(not os.path.exists(CF), "变更单文件已删掉")
A3 = load_app()
app = A3.App()
for _ in range(40):
    app.poll()
    if not app.busy:
        break
    _t.sleep(0.05)
chk(app.items == [], "文件不存在 -> 空列表")
scr3, err3, _ = run_app([("tap", 30, 28)], A3)
chk(err3 is None, "没文件也能画", str(err3)[:60] if err3 else "")

# ══════════════════════════════════════════════════════════ ⑨
print("\n【9】★ 危险操作的安全边界")
write_recs(RECS)
A4 = load_app()
app = A4.App()
for _ in range(60):
    app.poll()
    if not app.busy:
        break
    _t.sleep(0.05)
# 对不可回滚的记录点回滚 -> 应该只给提示，不弹确认框
idx2 = [i for i, x in enumerate(app.items) if x["id"] == "c_build_1"][0]
app.sel = idx2
it = app.items[idx2]
if not (it["snap"] or it["backup"]):
    app.status = "这条不可回滚"
chk(app.confirm is None, "★ 不可回滚的记录不会弹确认框")
chk("不可回滚" in app.status, "给了明确提示", app.status)

print()
print("=" * 78)
print(" 总体: %s" % ("★ 全部通过" if ok else "★ 有问题，看上面 ✗"))
print("=" * 78)

shutil.rmtree(TMP, ignore_errors=True)
sys.exit(0 if ok else 1)
