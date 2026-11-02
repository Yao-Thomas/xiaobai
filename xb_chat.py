#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""xb_chat.py —— 系统管家小白 · 桌面客户端（聊天界面）

════════════════════════════════════════════════════════════════════
这一版重做了什么（用户要求）
════════════════════════════════════════════════════════════════════
上一版是个「六个页签的工具箱」（设备信息/文件传输/硬件/变更历史/对话/工具），
用户说不对 —— 要像聊天应用那样：

    ┌──────────────────────────────────────────────────────────┐
    │ 系统管家小白  192.168.110.144 ●   76°C        ⚙ 设置     │
    ├────────────┬─────────────────────────────────────────────┤
    │ 对话记录栏  │  消息区（气泡）                              │
    │            │                                             │
    │ + 新对话    │   ┌──────────────┐                          │
    │            │   │ 现在多少度     │                          │
    │ 今天        │   └──────────────┘                          │
    │  温度怎么样  │        ┌──────────────────┐                 │
    │  改个FPGA   │        │ 现在 76 度，还行。 │                 │
    │            │        └──────────────────┘                 │
    ├────────────┴─────────────────────────────────────────────┤
    │ ┌────────────────────────────────────────┐ ┌───────────┐ │
    │ │ 说点什么…                          🎤  │ │  发送      │ │
    │ └────────────────────────────────────────┘ └───────────┘ │
    │              [deepseek-v4-pro ▾]  [自动 ▾]  🔊 自动朗读   │
    └──────────────────────────────────────────────────────────┘

★ 几个关键点：
  · 对话记录栏在【左边】，从板子的 /chat/sessions 拉，也能本地新建
  · ★ 模型切换在【输入框右下角】—— 用户明确要求的位置
  · ★ 模式切换（云端/本地/自动）也在右下角旁边
  · 语音：🎤 点一下开始录，再点一下停 → 上传 /asr → 自动发送
  · 设置页：板子地址 / token / DeepSeek key / 模型 / 语音开关

★ 上一版还有个问题：语音【根本没做】（只调了 /voice 纯文字）。
  这一版把 /asr 和 /tts 都接上了。

用法:
    python xb_chat.py
    python xb_chat.py --host 192.168.110.144 --token xxxx
    python xb_chat.py --selftest        # 不带界面，跑逻辑自测
"""
import argparse
import base64
import hashlib
import json
import os
import queue
import sys
import threading
import time
import tkinter as tk
import urllib.parse
from tkinter import ttk, messagebox, scrolledtext, filedialog, simpledialog

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# ★ 复用已经测过的 API 层（Board / discover / 配置读写）
import xb_client as X            # noqa: E402
import xb_audio as A             # noqa: E402

# ★★★ PC 端本地语音识别（Windows 自带的中文识别）
#   用户建议："语音输入完全可以接电脑自己的语音输入啊"
#   ⇒ 用 Windows 的 System.Speech（离线、亚秒级），
#     不依赖板子、不依赖百度 key。拿不到就退回原路（录音传板子）。
try:
    import xb_pcsr as PC_SR      # noqa: E402
except Exception:
    PC_SR = None

APP_TITLE = "系统管家小白"
CONF = os.path.join(os.path.expanduser("~"), ".xiaobai_chat.json")

# ══════════════════════════════════════════════════════════════════
#  ★★★ 常见 token（2026-10-03 加）—— 修"连不上板子"
# ══════════════════════════════════════════════════════════════════
# 背景：板子的 /health 不需要认证（所以"扫一扫"能找到它），
#       但 /info、/infer、/voice 都要 token。
#       客户端配置里 token 为空时，一调 /info 就 unauthorized，
#       界面显示"未连接" —— 用户看到的"连不上"其实是没认证。
#
# 做法：连接 / 扫描成功时，依次拿这些 token 试 /info，
#       哪个通就用哪个，并【写回配置】（下次直接命中）。
#
# ★ 把 "u6kCWANi" 放在第一位 —— 这是本项目板子的出厂 token
#   （见板子上的 /etc/xiaobai-cloud.json）。
# ★ 空串放最后：有些板子本来就关了认证。
DEFAULT_TOKENS = ["u6kCWANi", "xiaobai", "123456", "admin", ""]

# ★ 安全开关：设 True 就【不】自动试 token，必须用户手填。
#   演示/自用建议 False；如果这块板子要放到不受控的网络里，改成 True。
REQUIRE_TOKEN = False

# ══════════════════════════════════════════════════════════════════
#  ★★★ 启动日志（2026-10-03 加）
# ══════════════════════════════════════════════════════════════════
# 为什么需要：
#   打包成 --windowed 的 exe 之后【没有控制台】，任何异常都看不见 ——
#   踩过：token 自动配置在源码里跑得好好的，打成 exe 却没生效，
#   而 exe 一点报错都不给，只能瞎猜。
# ⇒ 把关键步骤写进日志文件，出问题让用户把这个文件发过来即可。
#   文件：~/.xiaobai_chat.log（只追加，超过 200KB 自动截断）
LOG = os.path.join(os.path.expanduser("~"), ".xiaobai_chat.log")

# ★★★ busy 看门狗上限（2026-10-03）
#   用户报的"连上了，但是发送不了" —— 查下来发送本身是通的，
#   真凶是 busy 卡住：send() 在 busy 时静默 return、发送按钮变灰，
#   看起来就是"发送不了"。而 busy 可能因为：
#     · 网络请求超时（最长 180 秒）
#     · do_infer 直接赋值 busy，万一回调没跑到就永久卡死
#   ⇒ 超过这个秒数就自动放开，并告诉用户可以再发。
BUSY_MAX = 200.0


def log(msg):
    """写一行启动日志（出错也不抛，日志不能拖垮程序）"""
    try:
        import datetime as _dt
        p = LOG
        if os.path.exists(p) and os.path.getsize(p) > 200 * 1024:
            os.remove(p)                      # 太大就重来，不留一堆历史
        with open(p, "a", encoding="utf-8") as f:
            f.write("%s  %s\n" % (_dt.datetime.now().strftime("%m-%d %H:%M:%S"),
                                  msg))
    except Exception:
        pass


def probe_token(host, want=None, timeout=6):
    """挨个试 DEFAULT_TOKENS，返回第一个能通过 /info 的 token（失败返回 None）

    want: 如果用户已经在设置里填了 token，先试它。
    """
    if not host:
        return None
    from xb_client import Board
    cands = []
    if want:
        cands.append(want)
    if not REQUIRE_TOKEN:
        for t in DEFAULT_TOKENS:
            if t not in cands:
                cands.append(t)
    for t in cands:
        try:
            b = Board(host, t)
            d = b.call("/info", timeout=timeout)
            if d.get("ok"):
                return t
        except Exception:
            continue
    return None
SESS_DIR = os.path.join(os.path.expanduser("~"), ".xiaobai_chat_sessions")

# ★★★ 板子上的"接收区"（2026-10-03）
#   和板端 apps_filehelper.py 的 RECV_DIR 必须一致。
#   PC 端点「📥 传到接收区」就落这里，板子上打开「传输助手」就能看到。
RECV_DIR = "/home/zynq/received"

# 配色（浅色，接近现代聊天应用）
C = {
    "bg":        "#f6f7f9",
    "panel":     "#ffffff",
    "side":      "#f0f1f4",
    "line":      "#e3e5e9",
    "text":      "#1f2329",
    "dim":       "#8a9099",
    "user_bg":   "#d6e8ff",     # 用户气泡
    "user_fg":   "#0b2545",
    "ai_bg":     "#ffffff",     # AI 气泡
    "ai_fg":     "#1f2329",
    "sys_bg":    "#fff7e6",     # 系统提示
    "sys_fg":    "#8a6100",
    "accent":    "#2563eb",
    "rec":       "#dc2626",
    "ok":        "#16a34a",
}


# ══════════════════════════════════════════════════════════════════
#  配置
# ══════════════════════════════════════════════════════════════════
def _fmt_size(n):
    """把字节数变成人看的大小（文件传输页用）"""
    if n is None:
        return "—"
    try:
        n = float(n)
    except Exception:
        return "—"
    for u in ("B", "K", "M", "G"):
        if n < 1024:
            return "%d%s" % (int(n), u) if u == "B" else "%.1f%s" % (n, u)
        n /= 1024.0
    return "%.1fT" % n


def parse_board_settings(s, m, c, local_model=""):
    """★ 把板子三个接口的返回解析成"给人看的一行行文字"

    抽成纯函数是为了能单测（不用起 tkinter）。

    s = GET /llm/settings  的返回
    m = GET /llm/models    的返回
    c = GET /llm/config    的返回
    local_model = PC 本地记的模型（用来对账）

    返回 (行列表, 模型列表, 自定义模型列表)
    """
    lines = []
    if not isinstance(s, dict) or not s.get("ok"):
        err = (s or {}).get("error") if isinstance(s, dict) else "读不到"
        return (["✗ 读不到板子配置：%s" % str(err)[:70]], [], [])
    has = "已配置" if s.get("has_key") else "★ 没配（云端调用会失败）"
    lines.append("板子生效的模型：%s" % (s.get("model") or "?"))
    lines.append("API Key：%s" % has)
    lines.append("api_base：%s" % (s.get("api_base") or "?"))
    lines.append("推理模式：%s" % ((c.get("mode") if isinstance(c, dict)
                                  and c.get("ok") else "?") or "?"))
    lines.append("配置文件：%s" % (s.get("file") or "?"))

    models = []
    extras = []
    if isinstance(m, dict) and m.get("ok"):
        models = list(m.get("models") or [])
        cur = m.get("current") or ""
        # ★ 自定义模型 = 不在官方那几个、也不是"本地"的那些
        builtin = ("deepseek-flash", "deepseek-v4-pro", "deepseek-chat",
                   "本地（离线 RAG）")
        extras = [x for x in models if x not in builtin]
    # ★ 本地记的和板子不一致 -> 明说（以板子为准）
    lm = (local_model or "").strip()
    if lm and s.get("model") and lm != s.get("model"):
        lines.append("★ 本地记的是 %s，和板子不一致（以板子为准）" % lm)
    return lines, models, extras


def fmt_key_state(has_key):
    """key 状态的中文说法（给设置页用）"""
    return "已配置" if has_key else "★ 没配"


def load_conf():
    d = {"host": "", "token": "", "model": "", "mode": "",
         "voice_reply": True, "voice_auto_send": True, "last_ip": ""}
    try:
        # ★★★ 用 utf-8-sig 读（2026-10-03 修）★★★
        #   踩过：配置文件的 JSON 明明是对的，但 host 读出来是空 ——
        #   整个界面显示"未连接"，查了半天网络，其实是文件带 UTF-8 BOM：
        #       json.decoder.JSONDecodeError: Unexpected UTF-8 BOM
        #   而这里 except 一吞，就变成"配置全空"，非常难查。
        #   ★ 用户用记事本"另存为 UTF-8"就会带 BOM（Windows 记事本的老毛病），
        #     所以这个坑不只是我们自己会踩。
        #   utf-8-sig 会【自动吃掉】开头的 BOM，没有 BOM 也照常工作。
        with open(CONF, encoding="utf-8-sig") as f:
            d.update(json.load(f) or {})
    except Exception as e:
        log("load_conf 失败: %s: %s" % (type(e).__name__, e))
    return d


def save_conf(d):
    try:
        with open(CONF, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════
#  本地会话存储（服务端会话 + 本地兜底）
# ══════════════════════════════════════════════════════════════════
class Session(object):
    """一个会话：id / 标题 / 消息列表"""

    def __init__(self, sid="", title=""):
        self.id = sid or time.strftime("local_%Y%m%d_%H%M%S")
        self.title = title or "新对话"
        self.msgs = []          # [{"who": "user"/"ai"/"sys", "text":..., "ts":...}]
        self.touched = time.time()
        # ★ 归档标记（2026-10-03）：归档的会话默认不显示，
        #   但数据还在（archived 字段来自板子，两边同步）
        self.archived = False

    def add(self, who, text):
        m = {"who": who, "text": text, "ts": time.time()}
        self.msgs.append(m)
        # ★ 用第一条用户消息当标题（像聊天应用那样）
        if who == "user" and self.title in ("新对话", ""):
            self.title = text.strip().replace("\n", " ")[:18] or "新对话"
        self.touched = time.time()
        return m

    def to_dict(self):
        return {"id": self.id, "title": self.title,
                "touched": self.touched, "msgs": self.msgs}

    @staticmethod
    def from_dict(d):
        s = Session(d.get("id", ""), d.get("title", ""))
        s.msgs = d.get("msgs", [])
        s.touched = d.get("touched", time.time())
        return s


class SessionStore(object):
    def __init__(self, path=SESS_DIR):
        self.path = path
        self.sessions = []
        self.cur = None
        os.makedirs(path, exist_ok=True)
        self._load()

    def _f(self, sid):
        # SESS_PERSIST_FIX_V1：板子会话来的是 "board:s016_5399"，
        #   Windows 文件名不能有 ':'，原来 open() 直接抛异常而 save()
        #   里是 except: pass => 静默丢数据。这里统一清洗非法字符。
        _safe = str(sid)
        for _ch in (':', '/', '\\', '*', '?', '"', '<', '>', '|'):
            _safe = _safe.replace(_ch, '_')
        return os.path.join(self.path, _safe + ".json")

    def _load(self):
        try:
            for fn in os.listdir(self.path):
                if fn.endswith(".json"):
                    try:
                        with open(os.path.join(self.path, fn),
                                  encoding="utf-8") as f:
                            self.sessions.append(Session.from_dict(json.load(f)))
                    except Exception:
                        pass
        except Exception:
            pass
        self.sessions.sort(key=lambda s: -s.touched)
        if not self.sessions:
            self.sessions = [Session()]
        self.cur = self.sessions[0]

    def save(self, s=None):
        s = s or self.cur
        try:
            with open(self._f(s.id), "w", encoding="utf-8") as f:
                json.dump(s.to_dict(), f, ensure_ascii=False)
        except Exception:
            pass

    def new(self):
        s = Session()
        self.sessions.insert(0, s)
        self.cur = s
        self.save(s)
        return s

    def delete(self, s):
        try:
            os.remove(self._f(s.id))
        except Exception:
            pass
        if s in self.sessions:
            self.sessions.remove(s)
        if not self.sessions:
            self.sessions = [Session()]
        self.cur = self.sessions[0]
        return self.cur

    def group(self):
        """按今天/昨天/更早分组，返回 [(组名, [会话...]), ...]"""
        now = time.time()
        g = [("今天", []), ("昨天", []), ("更早", [])]
        for s in sorted(self.sessions, key=lambda x: -x.touched):
            age = now - s.touched
            if age < 86400:
                g[0][1].append(s)
            elif age < 172800:
                g[1][1].append(s)
            else:
                g[2][1].append(s)
        return [(n, v) for n, v in g if v]


# ══════════════════════════════════════════════════════════════════
#  消息气泡
# ══════════════════════════════════════════════════════════════════
class Bubble(tk.Frame):
    """一条消息气泡

    ★ 为什么用 Frame+Label 而不是 Text+tag：
      Text 的 tag background 是【整行】的，气泡会横贯整屏，
      看起来不像聊天。Frame 包 Label 才能让背景只包住文字。
    """

    def __init__(self, parent, who, text, ts=None, **kw):
        bg = C["bg"]
        super().__init__(parent, bg=bg, **kw)
        self.who = who
        is_user = (who == "user")
        is_sys = (who == "sys")

        bbg = C["user_bg"] if is_user else (C["sys_bg"] if is_sys else C["ai_bg"])
        fg = C["user_fg"] if is_user else (C["sys_fg"] if is_sys else C["ai_fg"])
        # ★ 注意：tkinter 的 anchor 只认 n/ne/e/se/s/sw/w/nw/center，
        #   不认 "left"/"right" —— 传 right 会直接抛 TclError。
        #   （踩过：一开始用 anchor="right"，界面根本起不来。）
        anchor = "e" if is_user else "w"
        padx = (60, 8) if is_user else (8, 60)

        # 头像/名字
        head = tk.Frame(self, bg=bg)
        head.pack(side="top", anchor=anchor, padx=padx)
        name = {"user": "我", "ai": "小白", "sys": "系统"}[who]
        tk.Label(head, text=name, bg=bg,
                 fg=C["accent"] if is_user else C["dim"],
                 font=("Microsoft YaHei", 9, "bold")).pack(side="left")
        tk.Label(head, text=time.strftime("%H:%M", time.localtime(ts or time.time())),
                 bg=bg, fg=C["dim"],
                 font=("Microsoft YaHei", 8)).pack(side="left", padx=(6, 0))

        # 气泡本体 —— ★ 宽度要跟着窗口走，所以用 wraplength 动态设
        self.lbl = tk.Label(self, text=text, bg=bbg, fg=fg,
                            justify="left", anchor="w",
                            font=("Microsoft YaHei", 10),
                            padx=12, pady=9, wraplength=560,
                            bd=0, relief="flat")
        self.lbl.pack(side="top", anchor=anchor, padx=padx, pady=(2, 12))
        self._bind_copy()

    def _bind_copy(self):
        """右键复制（聊天应用该有的）"""
        m = tk.Menu(self, tearoff=0)
        m.add_command(label="复制", command=self._copy)
        m.add_command(label="重新朗读", command=lambda: self._speak())
        lbl = self.lbl

        def popup(e):
            try:
                m.tk_popup(e.x_root, e.y_root)
            finally:
                m.grab_release()
        lbl.bind("<Button-3>", popup)
        self._menu = m

    def set_wrap(self, px):
        self.lbl.configure(wraplength=max(200, px - 140))

    def _copy(self):
        try:
            self.clipboard_clear()
            self.clipboard_append(self.lbl.cget("text"))
        except Exception:
            pass

    def _speak(self):
        cb = getattr(self.master, "on_speak_text", None)
        if cb:
            cb(self.lbl.cget("text"))


# ══════════════════════════════════════════════════════════════════
#  消息区（可滚动）
# ══════════════════════════════════════════════════════════════════
class MessageArea(tk.Frame):
    def __init__(self, parent, **kw):
        super().__init__(parent, bg=C["bg"], **kw)
        self.canvas = tk.Canvas(self, bg=C["bg"], highlightthickness=0, bd=0)
        self.vsb = ttk.Scrollbar(self, orient="vertical",
                                 command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vsb.set)
        self.vsb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.inner = tk.Frame(self.canvas, bg=C["bg"])
        self._win = self.canvas.create_window((0, 0), window=self.inner,
                                              anchor="nw")
        self.inner.bind("<Configure>", self._on_inner)
        self.canvas.bind("<Configure>", self._on_canvas)
        # 滚轮
        self.canvas.bind_all("<MouseWheel>", self._wheel)
        self.bubbles = []

    def _on_inner(self, e):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas(self, e):
        self.canvas.itemconfigure(self._win, width=e.width)
        for b in self.bubbles:
            b.set_wrap(e.width)

    def _wheel(self, e):
        try:
            self.canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        except Exception:
            pass

    def clear(self):
        for b in self.bubbles:
            b.destroy()
        self.bubbles = []

    def add(self, who, text, ts=None):
        b = Bubble(self.inner, who, text, ts)
        b.pack(fill="x", padx=10, pady=1)
        b.set_wrap(self.canvas.winfo_width() or 700)
        self.bubbles.append(b)
        self.after(30, self.scroll_bottom)
        return b

    def scroll_bottom(self):
        try:
            self.canvas.update_idletasks()
            self.canvas.yview_moveto(1.0)
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════
#  对话记录栏（左侧）
# ══════════════════════════════════════════════════════════════════
class Sidebar(tk.Frame):
    def __init__(self, parent, on_pick, on_new, on_del, **kw):
        super().__init__(parent, bg=C["side"], width=230, **kw)
        self.pack_propagate(False)
        self.on_pick = on_pick

        top = tk.Frame(self, bg=C["side"])
        top.pack(fill="x", padx=10, pady=(12, 6))
        tk.Label(top, text="对话记录", bg=C["side"], fg=C["text"],
                 font=("Microsoft YaHei", 11, "bold")).pack(side="left")
        tk.Button(top, text="＋", command=on_new, bd=0, bg=C["side"],
                  fg=C["accent"], activebackground=C["side"],
                  font=("Microsoft YaHei", 13, "bold"),
                  cursor="hand2").pack(side="right")
        # ★ 显示已归档（2026-10-03）：归档只是藏起来，勾上就能看到、能恢复
        self.v_arch = tk.BooleanVar(value=False)
        self.chk_arch = tk.Checkbutton(
            top, text="归档", variable=self.v_arch, command=self._toggle_arch,
            bd=0, bg=C["side"], fg=C["dim"], selectcolor=C["side"],
            activebackground=C["side"], font=("Microsoft YaHei", 9),
            cursor="hand2")
        self.chk_arch.pack(side="right", padx=4)
        self.on_arch_toggle = None

        # 会话列表（用 Canvas 手搓，才能分组 + 高亮）
        self.canvas = tk.Canvas(self, bg=C["side"], highlightthickness=0, bd=0)
        vsb = ttk.Scrollbar(self, orient="vertical",
                            command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.holder = tk.Frame(self.canvas, bg=C["side"])
        self._win = self.canvas.create_window((0, 0), window=self.holder,
                                              anchor="nw")
        self.holder.bind("<Configure>", lambda e: self.canvas.configure(
            scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(
            self._win, width=e.width))
        self.rows = {}
        self.cur_id = None
        self._on_del = on_del

    def render(self, groups, cur_id):
        for w in self.holder.winfo_children():
            w.destroy()
        self.rows = {}
        self.cur_id = cur_id
        for gname, sessions in groups:
            tk.Label(self.holder, text=gname, bg=C["side"], fg=C["dim"],
                     font=("Microsoft YaHei", 8),
                     anchor="w").pack(fill="x", padx=12, pady=(10, 2))
            for s in sessions:
                self._row(s)

    def _row(self, s):
        cur = (s.id == self.cur_id)
        f = tk.Frame(self.holder, bg=C["panel"] if cur else C["side"],
                     cursor="hand2")
        f.pack(fill="x", padx=6, pady=1)
        # ★ 归档的条目加个标记，一眼能看出来（用户要的"归档隐藏"）
        _t = s.title[:16] or "新对话"
        if getattr(s, "archived", False):
            _t = "▣ " + _t
        lbl = tk.Label(f, text=_t,
                       bg=C["panel"] if cur else C["side"],
                       fg=C["accent"] if cur else (
                           C["dim"] if getattr(s, "archived", False)
                           else C["text"]),
                       font=("Microsoft YaHei", 9),
                       anchor="w", justify="left")
        lbl.pack(side="left", fill="x", expand=True, padx=(8, 2), pady=6)

        def pick(e, ss=s):
            self.on_pick(ss)
        for w in (f, lbl):
            w.bind("<Button-1>", pick)
        lbl.bind("<Button-3>", lambda e, ss=s: self._menu(e, ss))
        self.rows[s.id] = f

    def _toggle_arch(self):
        """勾/取消「归档」—— 把已归档的会话放出来看"""
        if self.on_arch_toggle:
            self.on_arch_toggle(self.v_arch.get())

    def _menu(self, e, s):
        """会话条目右键菜单

        ★ 2026-10-03 加「归档」：用户要的"归档隐藏功能，两边同步"。
          归档 = 藏起来但数据还在（点「显示已归档」还能看到、能恢复）；
          删除 = 真没了。两个都给，用户自己选。
        """
        m = tk.Menu(self, tearoff=0)
        if s.id.startswith("board:"):
            m.add_command(
                label=("取消归档" if getattr(s, "archived", False) else "归档（隐藏）"),
                command=lambda: self._on_archive(s,
                                                 not getattr(s, "archived",
                                                             False)))
            m.add_separator()
        m.add_command(label="删除这个对话",
                      command=lambda: self._on_del(s))
        try:
            m.tk_popup(e.x_root, e.y_root)
        finally:
            m.grab_release()


# ══════════════════════════════════════════════════════════════════
#  设置窗口
# ══════════════════════════════════════════════════════════════════
class SettingsDialog(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.title("设置")
        self.configure(bg=C["panel"])
        self.resizable(False, False)
        self.transient(app.root)
        self.grab_set()

        pad = {"padx": 14, "pady": 5}
        row = 0
        tk.Label(self, text="连接", bg=C["panel"], fg=C["text"],
                 font=("Microsoft YaHei", 11, "bold")).grid(
            row=row, column=0, columnspan=2, sticky="w", padx=14, pady=(14, 4))
        row += 1
        self.v_host = tk.StringVar(value=app.conf.get("host", ""))
        self.v_tok = tk.StringVar(value=app.conf.get("token", ""))
        for lab, var, show in (("板子地址", self.v_host, False),
                               ("Token", self.v_tok, True)):
            tk.Label(self, text=lab, bg=C["panel"], fg=C["dim"],
                     font=("Microsoft YaHei", 9)).grid(row=row, column=0,
                                                       sticky="w", **pad)
            e = tk.Entry(self, textvariable=var, width=34, show="*" if show else "",
                         font=("Consolas", 10))
            e.grid(row=row, column=1, sticky="w", **pad)
            if lab == "Token":
                # ★ 2026-10-03：说清楚"留空也能用"——
                #   原来用户看到个 Token 框不知道填什么，留空就 unauthorized，
                #   界面显示"未连接"，看着像连不上。
                tk.Label(self, text="★ 留空会自动试（板子默认 u6kCWANi）",
                         bg=C["panel"], fg=C["dim"],
                         font=("Microsoft YaHei", 8)).grid(
                    row=row, column=1, sticky="w", padx=(250, 0))
            row += 1
        bf = tk.Frame(self, bg=C["panel"])
        bf.grid(row=row, column=1, sticky="w", padx=14)
        tk.Button(bf, text="扫描局域网", command=self.do_scan, bd=0,
                  bg=C["line"], fg=C["text"], padx=10, pady=3,
                  cursor="hand2").pack(side="left")
        tk.Button(bf, text="测试连接", command=self.do_test, bd=0,
                  bg=C["line"], fg=C["text"], padx=10, pady=3,
                  cursor="hand2").pack(side="left", padx=6)
        row += 1

        tk.Label(self, text="模型（DeepSeek）", bg=C["panel"], fg=C["text"],
                 font=("Microsoft YaHei", 11, "bold")).grid(
            row=row, column=0, columnspan=2, sticky="w", padx=14,
            pady=(14, 4))
        row += 1
        self.v_key = tk.StringVar(value="")     # ★ key 不回显，只显示"已配置"
        tk.Label(self, text="API Key", bg=C["panel"], fg=C["dim"],
                 font=("Microsoft YaHei", 9)).grid(row=row, column=0,
                                                   sticky="w", **pad)
        self.e_key = tk.Entry(self, textvariable=self.v_key, width=34,
                              show="*", font=("Consolas", 10))
        self.e_key.grid(row=row, column=1, sticky="w", **pad)
        self.lbl_key = tk.Label(self, text="（留空表示不改）", bg=C["panel"],
                                fg=C["dim"], font=("Microsoft YaHei", 8))
        self.lbl_key.grid(row=row, column=1, sticky="w", padx=14)
        row += 1

        # ★★★ 2026-10-03：这里的措辞很重要
        #   用户问："模型不能用板子的吗？？？为什么要自己配"
        #   —— 他看到"默认模型"以为是 PC 端【自己配】一个模型，
        #      其实这一栏改的就是【板子的】模型（POST /llm/model 打到板子上）。
        #   所以标签和提示都要说清楚"这是板子的"。
        tk.Label(self, text="板子的模型", bg=C["panel"], fg=C["dim"],
                 font=("Microsoft YaHei", 9)).grid(row=row, column=0,
                                                   sticky="w", **pad)
        self.v_model = tk.StringVar(value=app.conf.get("model", ""))
        self.cb_model = ttk.Combobox(self, textvariable=self.v_model, width=32,
                                     font=("Consolas", 10))
        self.cb_model.grid(row=row, column=1, sticky="w", **pad)
        tk.Label(self, text="★ 改这里 = 直接切板子的模型（PC 端不自己配）",
                 bg=C["panel"], fg=C["dim"],
                 font=("Microsoft YaHei", 8)).grid(row=row, column=1,
                                                   sticky="w", padx=(240, 0))
        row += 1
        _bf2 = tk.Frame(self, bg=C["panel"])
        _bf2.grid(row=row, column=1, sticky="w", padx=14)
        tk.Button(_bf2, text="从板子拉模型列表", command=self.do_models,
                  bd=0, bg=C["line"], fg=C["text"], padx=10, pady=3,
                  cursor="hand2").pack(side="left")
        tk.Button(_bf2, text="★ 同步板子配置", command=self.do_sync,
                  bd=0, bg=C["accent"], fg="#ffffff", padx=10, pady=3,
                  cursor="hand2").pack(side="left", padx=6)
        row += 1

        # ── ★★★ 板子上【真正生效】的配置（2026-10-03 加）──
        #   为什么单独一块：
        #     我们踩过"设置里显示 A、板子实际用 B"的坑 ——
        #     因为板子的配置有三个来源，优先级是
        #         覆盖文件(.agent_settings.json) > 环境变量 > .agent.json > 默认
        #     而 cover 文件里可能躺着旧的假 key / 旧的模型名。
        #     ⇒ 这里直接把板子【当前生效】的值显示出来，一眼能对账。
        self.lbl_board = tk.Label(
            self, text="板子上的配置：点「同步板子配置」读取",
            bg=C["panel"], fg=C["dim"], font=("Microsoft YaHei", 8),
            justify="left", anchor="w", wraplength=420)
        self.lbl_board.grid(row=row, column=0, columnspan=2, sticky="w",
                            padx=14, pady=(4, 0))
        row += 1

        # ── ★ 自定义模型（extra_models）──
        #   板子支持往模型列表里加自己的模型名（存在覆盖文件里），
        #   原来只有板载界面能加，PC 端没有入口。
        tk.Label(self, text="自定义模型", bg=C["panel"], fg=C["dim"],
                 font=("Microsoft YaHei", 9)).grid(row=row, column=0,
                                                   sticky="w", **pad)
        _bf3 = tk.Frame(self, bg=C["panel"])
        _bf3.grid(row=row, column=1, sticky="w", padx=14)
        self.v_newmodel = tk.StringVar(value="")
        tk.Entry(_bf3, textvariable=self.v_newmodel, width=22,
                 font=("Consolas", 10)).pack(side="left")
        tk.Button(_bf3, text="添加", command=self.do_add_model, bd=0,
                  bg=C["line"], fg=C["text"], padx=10, pady=3,
                  cursor="hand2").pack(side="left", padx=4)
        tk.Button(_bf3, text="删除选中", command=self.do_del_model, bd=0,
                  bg=C["line"], fg=C["text"], padx=10, pady=3,
                  cursor="hand2").pack(side="left")
        row += 1
        self.lbl_extra = tk.Label(
            self, text="（板子上还没有自定义模型）", bg=C["panel"],
            fg=C["dim"], font=("Microsoft YaHei", 8), justify="left",
            anchor="w", wraplength=440)
        self.lbl_extra.grid(row=row, column=0, columnspan=2, sticky="w",
                            padx=14)
        row += 1

        tk.Label(self, text="语音", bg=C["panel"], fg=C["text"],
                 font=("Microsoft YaHei", 11, "bold")).grid(
            row=row, column=0, columnspan=2, sticky="w", padx=14,
            pady=(14, 4))
        row += 1
        self.v_reply = tk.BooleanVar(value=app.conf.get("voice_reply", True))
        self.v_auto = tk.BooleanVar(value=app.conf.get("voice_auto_send", True))
        tk.Checkbutton(self, text="收到回复后自动朗读", variable=self.v_reply,
                       bg=C["panel"], fg=C["text"], selectcolor=C["panel"],
                       activebackground=C["panel"],
                       font=("Microsoft YaHei", 9)).grid(
            row=row, column=1, sticky="w", padx=14)
        row += 1
        tk.Checkbutton(self, text="语音识别完成后自动发送", variable=self.v_auto,
                       bg=C["panel"], fg=C["text"], selectcolor=C["panel"],
                       activebackground=C["panel"],
                       font=("Microsoft YaHei", 9)).grid(
            row=row, column=1, sticky="w", padx=14)
        row += 1

        # 录音后端提示
        backend = "sounddevice（16kHz/16bit，音质好）" if A.HAS_SD else \
                  "MCI（只有 11025Hz/8bit，音质差 —— 建议 pip install sounddevice）"
        tk.Label(self, text="录音后端：" + backend, bg=C["panel"],
                 fg=C["dim"] if A.HAS_SD else C["rec"],
                 font=("Microsoft YaHei", 8), wraplength=360,
                 justify="left").grid(row=row, column=0, columnspan=2,
                                      sticky="w", padx=14, pady=(6, 0))
        row += 1

        bf2 = tk.Frame(self, bg=C["panel"])
        bf2.grid(row=row, column=0, columnspan=2, pady=14)
        tk.Button(bf2, text="保存", command=self.do_save, bd=0,
                  bg=C["accent"], fg="white", padx=22, pady=5,
                  font=("Microsoft YaHei", 10), cursor="hand2").pack(
            side="left", padx=6)
        tk.Button(bf2, text="取消", command=self.destroy, bd=0,
                  bg=C["line"], fg=C["text"], padx=18, pady=5,
                  font=("Microsoft YaHei", 10), cursor="hand2").pack(
            side="left", padx=6)

        self.m_status = tk.Label(self, text="", bg=C["panel"], fg=C["dim"],
                                 font=("Microsoft YaHei", 9), wraplength=380,
                                 justify="left")
        self.m_status.grid(row=row + 1, column=0, columnspan=2, sticky="w",
                           padx=14, pady=(0, 14))
        self.center()
        # ★★★ 打开设置就自动从板子同步一次（2026-10-03）
        #   用户要的"api 模型同步配置"—— 一打开就看到板子上真正生效的值，
        #   不用手点。★ 只有填了地址才试，免得空地址报错吓人。
        if self.v_host.get().strip():
            self.after(150, self.do_sync)

    def center(self):
        self.update_idletasks()
        w, h = self.winfo_width(), self.winfo_height()
        x = self.app.root.winfo_rootx() + (self.app.root.winfo_width() - w) // 2
        y = self.app.root.winfo_rooty() + 60
        self.geometry("+%d+%d" % (max(0, x), max(0, y)))

    # ---- 动作 ----
    def do_scan(self):
        self.m_status.configure(text="扫描中…", fg=C["dim"])
        self.update_idletasks()
        # ★ 主线程先取值（tk 变量不能跨线程读）
        _hint = self.v_host.get().strip()

        def work():
            hits = X.discover(2.5, extra_ips=[_hint] if _hint else ())
            def done():
                if hits:
                    self.v_host.set(hits[0].get("ip", ""))
                    self.m_status.configure(
                        text="找到：%s（%s，%.1f°C）"
                             % (hits[0].get("ip"), hits[0].get("hostname"),
                                hits[0].get("temperature_c") or 0),
                        fg=C["ok"])
                else:
                    self.m_status.configure(
                        text="没扫到。★ 常见原因：路由器不透传广播。"
                             "可以直接手填板子 IP。", fg=C["rec"])
            self.after(0, done)
        threading.Thread(target=work, daemon=True).start()

    def do_test(self):
        host = self.v_host.get().strip()
        tok = self.v_tok.get().strip()
        self.m_status.configure(text="测试中…", fg=C["dim"])
        self.update_idletasks()

        def work():
            try:
                b = X.Board(host, tok)
                d = b.call("/info", timeout=15)
                def done():
                    if d.get("ok"):
                        self.m_status.configure(
                            text="✓ 连上了：%s / %s / %.1f°C"
                                 % (d.get("hostname"), d.get("model"),
                                    d.get("temperature_c") or 0),
                            fg=C["ok"])
                    else:
                        self.m_status.configure(
                            text="✗ %s" % d.get("error"), fg=C["rec"])
                self.after(0, done)
            except Exception as e:
                self.after(0, lambda: self.m_status.configure(
                    text="✗ %s" % e, fg=C["rec"]))
        threading.Thread(target=work, daemon=True).start()

    def do_models(self):
        self.m_status.configure(text="拉取模型列表…", fg=C["dim"])
        self.update_idletasks()
        # ★ 主线程先取值（tk 变量不能跨线程读）
        _host = self.v_host.get().strip()
        _tok = self.v_tok.get().strip()

        def work():
            try:
                b = self._board(_host, _tok)
                ms = b.call("/tools", timeout=10)      # 保活
                d = b.call("/llm/models", timeout=25)
                def done():
                    if d.get("ok") and d.get("models"):
                        self.cb_model["values"] = d["models"]
                        if not self.v_model.get():
                            self.v_model.set(d.get("current") or d["models"][0])
                        self.m_status.configure(
                            text="✓ 拿到 %d 个模型：%s"
                                 % (len(d["models"]), ", ".join(d["models"])),
                            fg=C["ok"])
                    else:
                        self.m_status.configure(
                            text="✗ %s" % (d.get("error") or "拉不到"),
                            fg=C["rec"])
                self.after(0, done)
            except Exception as e:
                self.after(0, lambda: self.m_status.configure(
                    text="✗ %s" % e, fg=C["rec"]))
        threading.Thread(target=work, daemon=True).start()

    def _board(self, host=None, token=None):
        """造一个 Board

        ★★★ 参数必须由【主线程】先取好再传进来（2026-10-03 踩过）：
            tkinter 的 StringVar.get() 只能在主线程调，
            在后台线程里读会抛
                RuntimeError: main thread is not in main loop
            ⇒ 所以这里 host/token 允许从外面传；
              真正要读 tk 变量的地方，一律在主线程读好再传。
        """
        if host is None:
            host = self.v_host.get().strip()
        if token is None:
            token = self.v_tok.get().strip()
        return X.Board(host, token)

    def do_sync(self):
        """★★★ 从板子读回【真正生效】的配置（2026-10-03 加）

        用户要的"api 模型同步配置"。

        为什么单独做这个动作：
          板子的配置有四个来源，优先级是
              覆盖文件(.agent_settings.json) > 环境变量 > .agent.json > 默认
          而覆盖文件里可能躺着【过期的假 key / 旧模型名】——
          我们踩过：设置页显示 deepseek-chat，板子实际用 deepseek-flash；
          更严重的一次是覆盖文件里有个长度 7 的假 key（"sk-tes…"），
          把 /etc/zynq-agent.env 里的真 key 顶掉了，所有 LLM 请求 401。
          ⇒ 打开设置先"对账"，把这些差异摆出来。
        """
        # ★ 主线程先取好（tk 变量不能跨线程读）
        host = self.v_host.get().strip()
        token = self.v_tok.get().strip()

        def work():
            try:
                b = self._board(host, token)
                # ① 生效的配置
                s = b.call("/llm/settings", timeout=15)
                # ② 可用模型 + 当前项
                m = b.call("/llm/models", timeout=25)
                # ③ 推理模式
                c = b.call("/llm/config", timeout=12)

                def done():
                    if not s.get("ok"):
                        self.lbl_board.configure(
                            text="✗ 读不到板子配置：%s"
                                 % str(s.get("error"))[:70], fg=C["rec"])
                        return
                    # ★ 解析逻辑抽到 parse_board_settings() 里（可单测）
                    lines, models, extras = parse_board_settings(
                        s, m, c, self.app.conf.get("model"))
                    if models:
                        self.cb_model["values"] = models
                        cur = (m or {}).get("current") or ""
                        if cur:
                            self.v_model.set(cur)
                        self._extras = extras
                        self.lbl_extra.configure(
                            text=("板子上的自定义模型：%s" % ", ".join(extras))
                                 if extras else "（板子上还没有自定义模型）")
                    # ★ voice 开关也同步过来
                    if s.get("voice_reply") is not None:
                        self.v_reply.set(bool(s.get("voice_reply")))
                    if s.get("voice_auto_send") is not None:
                        self.v_auto.set(bool(s.get("voice_auto_send")))
                    self.lbl_board.configure(text="\n".join(lines),
                                             fg=C["text"])
                    self.m_status.configure(text="✓ 已从板子同步", fg=C["ok"])
                self.after(0, done)
            except Exception as e:
                self.after(0, lambda: self.lbl_board.configure(
                    text="✗ %s" % e, fg=C["rec"]))
        threading.Thread(target=work, daemon=True).start()

    def do_add_model(self):
        """往板子的 extra_models 里加一个自定义模型名"""
        name = self.v_newmodel.get().strip()
        if not name:
            self.m_status.configure(text="先填模型名", fg=C["rec"])
            return
        # ★ 先在本地列表里加，再整体写回板子（板子那个接口是"整体覆盖"语义）
        cur = list(getattr(self, "_extras", []) or [])
        if name in cur:
            self.m_status.configure(text="已经有了", fg=C["dim"])
            return
        cur.append(name)
        # ★ 主线程先取好连接参数（tk 变量不能跨线程读）
        _host = self.v_host.get().strip()
        _tok = self.v_tok.get().strip()

        def work():
            try:
                r = self._board(_host, _tok).call("/llm/settings", "POST",
                                                  {"extra_models": cur},
                                                  timeout=20)

                def done():
                    if r.get("ok"):
                        self._extras = cur
                        self.v_newmodel.set("")
                        self.lbl_extra.configure(
                            text="板子上的自定义模型：%s" % ", ".join(cur))
                        self.m_status.configure(text="✓ 已添加 %s" % name,
                                                fg=C["ok"])
                        # 顺手刷新下拉框
                        self.do_models()
                    else:
                        self.m_status.configure(
                            text="✗ %s" % (r.get("error") or "失败"), fg=C["rec"])
                self.after(0, done)
            except Exception as e:
                self.after(0, lambda: self.m_status.configure(
                    text="✗ %s" % e, fg=C["rec"]))
        threading.Thread(target=work, daemon=True).start()

    def do_del_model(self):
        """删掉一个自定义模型（把下拉框里当前选中的那个从 extra_models 摘掉）"""
        name = self.v_model.get().strip()
        cur = list(getattr(self, "_extras", []) or [])
        if name not in cur:
            self.m_status.configure(
                text="只能删自定义模型（现在选的是 %s）" % (name or "空"),
                fg=C["dim"])
            return
        cur.remove(name)
        # ★ 主线程先取好连接参数
        _host = self.v_host.get().strip()
        _tok = self.v_tok.get().strip()

        def work():
            try:
                r = self._board(_host, _tok).call("/llm/settings", "POST",
                                                  {"extra_models": cur},
                                                  timeout=20)

                def done():
                    if r.get("ok"):
                        self._extras = cur
                        self.lbl_extra.configure(
                            text=("板子上的自定义模型：%s" % ", ".join(cur))
                                 if cur else "（板子上还没有自定义模型）")
                        self.m_status.configure(text="✓ 已删除 %s" % name,
                                                fg=C["ok"])
                        self.do_models()
                    else:
                        self.m_status.configure(
                            text="✗ %s" % (r.get("error") or "失败"), fg=C["rec"])
                self.after(0, done)
            except Exception as e:
                self.after(0, lambda: self.m_status.configure(
                    text="✗ %s" % e, fg=C["rec"]))
        threading.Thread(target=work, daemon=True).start()

    def do_save(self):
        c = self.app.conf
        c["host"] = self.v_host.get().strip()
        c["token"] = self.v_tok.get().strip()
        c["voice_reply"] = bool(self.v_reply.get())
        c["voice_auto_send"] = bool(self.v_auto.get())
        if self.v_model.get().strip():
            c["model"] = self.v_model.get().strip()
        save_conf(c)
        self.app.reload_conf()
        # ★ key 要送到板子上（写进运行时覆盖文件，立刻生效）
        key = self.v_key.get().strip()
        if key:
            def work():
                try:
                    b = X.Board(c["host"], c["token"])
                    r = b.call("/llm/settings", "POST",
                               {"api_key": key}, timeout=20)
                    self.after(0, lambda: self.m_status.configure(
                        text="✓ key 已写入" if r.get("ok")
                             else "✗ %s" % r.get("error"),
                        fg=C["ok"] if r.get("ok") else C["rec"]))
                except Exception as e:
                    self.after(0, lambda: self.m_status.configure(
                        text="✗ %s" % e, fg=C["rec"]))
            threading.Thread(target=work, daemon=True).start()
        if self.v_model.get().strip():
            self.app.set_model(self.v_model.get().strip(), quiet=True)
        self.app.set_status("设置已保存")
        self.after(400, self.destroy)


# ══════════════════════════════════════════════════════════════════
#  主窗口
# ══════════════════════════════════════════════════════════════════
class ChatApp(object):
    def __init__(self, root, host="", token=""):
        self.root = root
        self.conf = load_conf()
        if host:
            self.conf["host"] = host
        if token:
            self.conf["token"] = token
        self.store = SessionStore()
        self.brd = X.Board(self.conf.get("host", ""), self.conf.get("token", ""))
        self.rec = A.Recorder()
        self.busy = False
        self.recording = False
        self.models = []
        self.modes = ("auto", "cloud", "local")
        self.mode_names = {"auto": "自动", "cloud": "云端", "local": "本地"}
        self.q = queue.Queue()

        root.title(APP_TITLE)
        root.geometry("1000x680")
        root.minsize(780, 520)
        root.configure(bg=C["bg"])
        self._fonts()
        self._build()
        self._pump()
        self.render_session()
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.after(300, self.bootstrap)
        # ★ 定时从板子拉对话（用户建议的"实时刷新"）
        root.after(8000, self._auto_refresh)

    def _fonts(self):
        for n in ("Microsoft YaHei UI", "Microsoft YaHei", "SimHei"):
            try:
                tkfont = __import__("tkinter.font", fromlist=["families"])
                if n in tkfont.families():
                    self.font = n
                    return
            except Exception:
                pass
        self.font = "TkDefaultFont"

    # ---------- ★ 协同示波器 ----------
    def open_scope(self):
        """打开 PC 端示波器窗口（数据从板子的 /scope/* 接口拉）"""
        try:
            from scope_panel import open_scope_panel
            host = (self.conf.get("host") or "").strip()
            token = (self.conf.get("token") or "").strip()
            if not host:
                from tkinter import messagebox
                messagebox.showwarning("提示", "请先在「⚙ 设置」里填板子地址")
                return
            base = host if host.startswith("http") else ("http://" + host)
            after = base.split("//", 1)[-1]
            if ":" not in after:
                base = base + ":8768"
            w = getattr(self, "_scope_win", None)
            if w is not None:
                try:
                    if w.win.winfo_exists():
                        w.win.lift(); w.win.focus_force(); return
                except Exception:
                    pass
            self._scope_win = open_scope_panel(self.root, base, token)
        except Exception as e:
            import traceback
            traceback.print_exc()
            try:
                from tkinter import messagebox
                messagebox.showerror("示波器", "%s: %s" % (type(e).__name__, e))
            except Exception:
                pass

    # ---------- 布局 ----------
    def _build(self):
        # 顶栏
        top = tk.Frame(self.root, bg=C["panel"], height=52)
        top.pack(fill="x", side="top")
        top.pack_propagate(False)
        tk.Label(top, text="系统管家小白", bg=C["panel"], fg=C["text"],
                 font=(self.font, 13, "bold")).pack(side="left", padx=(16, 10))
        self.lbl_conn = tk.Label(top, text="未连接", bg=C["panel"],
                                 fg=C["dim"], font=(self.font, 9))
        self.lbl_conn.pack(side="left")
        # ★ 协同示波器（远程看板子波形）
        tk.Button(top, text="\U0001F4C8 \u793a\u6ce2\u5668", command=self.open_scope, bd=0,
                  bg=C["panel"], fg=C["accent"], font=(self.font, 10),
                  activebackground=C["panel"], cursor="hand2").pack(
            side="right", padx=(0, 6))
        tk.Button(top, text="⚙ 设置", command=self.open_settings, bd=0,
                  bg=C["panel"], fg=C["text"], font=(self.font, 10),
                  activebackground=C["panel"], cursor="hand2").pack(
            side="right", padx=14)
        self.lbl_temp = tk.Label(top, text="", bg=C["panel"], fg=C["dim"],
                                 font=(self.font, 9))
        self.lbl_temp.pack(side="right", padx=10)

        # ★★★ 页签：聊天 / 推理（2026-10-03）
        #   用按钮切换主体内容，不新开窗口 —— 布局改动最小。
        self._tab = "chat"
        self.btn_tab_chat = tk.Button(
            top, text="\U0001f4ac 聊天", command=lambda: self.show_tab("chat"),
            bd=0, bg=C["panel"], fg=C["accent"], font=(self.font, 10, "bold"),
            activebackground=C["panel"], cursor="hand2")
        self.btn_tab_chat.pack(side="left", padx=(18, 4))
        self.btn_tab_infer = tk.Button(
            top, text="\U0001f4ca 推理", command=lambda: self.show_tab("infer"),
            bd=0, bg=C["panel"], fg=C["dim"], font=(self.font, 10),
            activebackground=C["panel"], cursor="hand2")
        self.btn_tab_infer.pack(side="left", padx=4)
        # ★★★ 第三个页签：文件传输（2026-10-03，用户要的"文件同步传输"）
        self.btn_tab_files = tk.Button(
            top, text="\U0001f4c1 文件", command=lambda: self.show_tab("files"),
            bd=0, bg=C["panel"], fg=C["dim"], font=(self.font, 10),
            activebackground=C["panel"], cursor="hand2")
        self.btn_tab_files.pack(side="left", padx=4)

        tk.Frame(self.root, bg=C["line"], height=1).pack(fill="x")

        # 主体
        body = tk.Frame(self.root, bg=C["bg"])
        body.pack(fill="both", expand=True)
        self.side = Sidebar(body, on_pick=self.pick_session,
                            on_new=self.new_session, on_del=self.del_session)
        # ★ 「归档」勾选框 -> 重新拉列表（带/不带已归档）
        self.side.on_arch_toggle = self._set_show_archived
        self.side.pack(side="left", fill="y")
        tk.Frame(body, bg=C["line"], width=1).pack(side="left", fill="y")

        right = tk.Frame(body, bg=C["bg"])
        right.pack(side="left", fill="both", expand=True)
        self.right = right

        # ★★★ 三个页面叠在同一个位置，用 pack/pack_forget 切换
        #   （tk 没有真正的 tab 控件，这是最省事又不破坏布局的做法）
        self.page_chat = tk.Frame(right, bg=C["bg"])
        self.page_infer = tk.Frame(right, bg=C["bg"])
        self.page_files = tk.Frame(right, bg=C["bg"])

        self.msg = MessageArea(self.page_chat)
        self.msg.on_speak_text = self.speak
        self.msg.pack(fill="both", expand=True)

        # ★ 输入区（含右下角的模型/模式切换）
        self._build_input(self.page_chat)

        # ★ 推理页
        self._build_infer(self.page_infer)

        # ★ 文件传输页
        self._build_files(self.page_files)

        self.page_chat.pack(fill="both", expand=True)
        tk.Frame(self.root, bg=C["line"], height=1).pack(fill="x")
        self.status = tk.StringVar(value="就绪")
        # ★ 状态栏：左边文字 + 右边一个应急的「强制解开」
        #   （万一 busy 卡住，用户不用重启程序）
        sbar = tk.Frame(self.root, bg=C["panel"])
        sbar.pack(fill="x", side="bottom")
        tk.Label(sbar, textvariable=self.status, bg=C["panel"],
                 fg=C["dim"], font=(self.font, 8), anchor="w").pack(
            side="left", fill="x", expand=True, padx=10, pady=3)
        tk.Button(sbar, text="强制解开", command=self.force_unbusy, bd=0,
                  bg=C["panel"], fg=C["dim"], font=(self.font, 8),
                  cursor="hand2", activebackground=C["panel"]).pack(
            side="right", padx=8)

    # ══════════════════════════════════════════════════════════════
    #  ★★★ 推理页（2026-10-03 加）
    # ══════════════════════════════════════════════════════════════
    # 板子的 /infer 早就通了（PL 加速器上的 CNN：cnn_conv_pool + cnn_fc），
    # 但 PC 客户端一直没有界面用它。这一页就是给它做的：
    #   选波形 → 生成 4096 点 → 发给板子 → 显示类别/置信度/耗时/引擎。
    # 8 个类别（板子 /infer/health 里报的）：
    #   sine / square / triangle / sawtooth / noise
    #   clipping / signal_loss / duty_abnormal
    # ══════════════════════════════════════════════════════════════
    WAVE_KINDS = [
        ("sine", "正弦"), ("square", "方波"), ("triangle", "三角"),
        ("sawtooth", "锯齿"), ("noise", "噪声"),
        ("clipping", "削顶"), ("signal_loss", "信号丢失"),
        ("duty_abnormal", "占空比异常"),
    ]
    WAVE_CN = dict(WAVE_KINDS)

    def show_tab(self, which):
        """切换 聊天 / 推理 / 文件 页

        ★ 2026-10-03 加了第三页（文件传输）。三个页面共用同一块位置，
          用 pack/pack_forget 切换；每切一次顺便把三个按钮的高亮重置。
        """
        if which == self._tab:
            return
        self._tab = which
        _pages = {"chat": self.page_chat, "infer": self.page_infer,
                  "files": self.page_files}
        _btns = {"chat": self.btn_tab_chat, "infer": self.btn_tab_infer,
                 "files": self.btn_tab_files}
        for k, pg in _pages.items():
            if k == which:
                pg.pack(fill="both", expand=True)
            else:
                pg.pack_forget()
        for k, b in _btns.items():
            b.configure(fg=C["accent"] if k == which else C["dim"],
                        font=(self.font, 10, "bold" if k == which else "normal"))
        if which == "infer":
            self.set_status("推理页：选波形 → 生成并推理")
        elif which == "files":
            self.set_status("文件页：双击进目录；选中文件可上传/下载/删除")
            # ★ 第一次进来自动列一下目录
            if not self.tree_fs.get_children():
                self.fs_list()
        else:
            self.set_status("就绪")

    def _build_infer(self, parent):
        """推理页布局"""
        # ── 参数行 ──
        bar = tk.Frame(parent, bg=C["panel"])
        bar.pack(fill="x", padx=12, pady=(12, 6))

        tk.Label(bar, text="波形", bg=C["panel"], fg=C["text"],
                 font=(self.font, 10)).pack(side="left", padx=(12, 4))
        self.v_wave = tk.StringVar(value="sine")
        cb = ttk.Combobox(bar, textvariable=self.v_wave, width=10,
                          state="readonly",
                          values=[k for k, _ in self.WAVE_KINDS])
        cb.pack(side="left")
        cb.bind("<<ComboboxSelected>>", lambda e: self.infer_preview())

        tk.Label(bar, text="频率", bg=C["panel"], fg=C["text"],
                 font=(self.font, 10)).pack(side="left", padx=(16, 4))
        self.v_freq = tk.IntVar(value=40)
        tk.Spinbox(bar, from_=1, to=400, textvariable=self.v_freq, width=6,
                   command=self.infer_preview).pack(side="left")

        tk.Label(bar, text="幅度", bg=C["panel"], fg=C["text"],
                 font=(self.font, 10)).pack(side="left", padx=(16, 4))
        self.v_amp = tk.IntVar(value=120)
        tk.Spinbox(bar, from_=1, to=127, textvariable=self.v_amp, width=6,
                   command=self.infer_preview).pack(side="left")

        tk.Button(bar, text="★ 生成并推理", command=self.do_infer,
                  bd=0, bg=C["accent"], fg="#ffffff",
                  font=(self.font, 10, "bold"), cursor="hand2",
                  padx=14, pady=4).pack(side="left", padx=(20, 6))
        tk.Button(bar, text="随机换一个", command=self.infer_random,
                  bd=0, bg=C["side"], fg=C["text"],
                  font=(self.font, 10), cursor="hand2",
                  padx=10, pady=4).pack(side="left")

        # ── 波形预览 ──
        pv = tk.Frame(parent, bg=C["panel"],
                      highlightbackground=C["line"], highlightthickness=1)
        pv.pack(fill="x", padx=12, pady=6)
        self.cv_wave = tk.Canvas(pv, height=150, bg="#fbfcfe",
                                 highlightthickness=0)
        self.cv_wave.pack(fill="x", padx=8, pady=8)
        self.cv_wave.bind("<Configure>", lambda e: self.infer_preview())

        # ── 结果 ──
        res = tk.Frame(parent, bg=C["panel"],
                       highlightbackground=C["line"], highlightthickness=1)
        res.pack(fill="x", padx=12, pady=6)
        self.lbl_infer = tk.Label(res, text="还没推理过 —— 点上面「生成并推理」",
                                  bg=C["panel"], fg=C["dim"],
                                  font=(self.font, 12), anchor="w",
                                  justify="left")
        self.lbl_infer.pack(fill="x", padx=14, pady=12)

        # ── 历史 ──
        hp = tk.Frame(parent, bg=C["bg"])
        hp.pack(fill="both", expand=True, padx=12, pady=(0, 10))
        tk.Label(hp, text="历史（最近 10 次）", bg=C["bg"], fg=C["dim"],
                 font=(self.font, 9)).pack(anchor="w")
        self.lst_hist = tk.Listbox(hp, bd=0, bg=C["panel"], fg=C["text"],
                                   font=("Consolas", 10), highlightthickness=1,
                                   highlightbackground=C["line"])
        self.lst_hist.pack(fill="both", expand=True, pady=(4, 0))
        self.infer_hist = []
        self.infer_preview()

    # ---------- 波形生成 ----------
    def gen_wave(self):
        """按当前参数生成 4096 点波形（和板子 /infer 的契约一致）"""
        import math as _m
        import random as _r
        kind = self.v_wave.get()
        f = max(1, int(self.v_freq.get() or 40))
        amp = max(1, min(127, int(self.v_amp.get() or 120)))
        N = 4096
        d = []
        for i in range(N):
            ph = (i * f / float(N)) % 1.0
            if kind == "sine":
                v = _m.sin(2 * _m.pi * ph)
            elif kind == "square":
                v = 1.0 if ph < 0.5 else -1.0
            elif kind == "triangle":
                v = 4 * abs(ph - 0.5) - 1
            elif kind == "sawtooth":
                v = 2 * ph - 1
            elif kind == "noise":
                v = _r.uniform(-1, 1)
            elif kind == "clipping":
                v = _m.sin(2 * _m.pi * ph) * 2.2      # 超幅 -> 削顶
                v = max(-1.0, min(1.0, v))
            elif kind == "signal_loss":
                v = 0.0 if i > N // 4 else _m.sin(2 * _m.pi * ph)
            elif kind == "duty_abnormal":
                v = 1.0 if ph < 0.82 else -1.0        # 占空比 82%
            else:
                v = _m.sin(2 * _m.pi * ph)
            d.append(int(127 + amp * v))
        return kind, [max(0, min(255, x)) for x in d]

    def infer_preview(self):
        """把当前波形画到预览 Canvas（不发网络请求）"""
        try:
            kind, d = self.gen_wave()
        except Exception:
            return
        cv = self.cv_wave
        cv.delete("all")
        w = max(200, cv.winfo_width())
        h = max(60, cv.winfo_height())
        mid = h // 2
        # 中线
        cv.create_line(0, mid, w, mid, fill="#e6e8ec")
        # 波形（4096 点太多，抽稀到宽度）
        step = max(1, len(d) // max(1, w))
        pts = []
        for x in range(0, w):
            i = min(len(d) - 1, x * step)
            y = mid - int((d[i] - 127) / 127.0 * (mid - 8))
            pts += [x, y]
        if len(pts) >= 4:
            cv.create_line(*pts, fill=C["accent"], width=2)
        cv.create_text(8, 12, anchor="w", fill=C["dim"],
                       font=(self.font, 9),
                       text="%s  %d Hz  幅度 %d（4096 点）"
                            % (self.WAVE_CN.get(kind, kind),
                               self.v_freq.get(), self.v_amp.get()))

    def infer_random(self):
        """随机换一个波形类型 + 参数"""
        import random as _r
        k = _r.choice([k for k, _ in self.WAVE_KINDS])
        self.v_wave.set(k)
        self.v_freq.set(_r.choice([10, 25, 40, 60, 100, 180]))
        self.v_amp.set(_r.choice([60, 90, 120, 127]))
        self.infer_preview()

    def do_infer(self):
        """生成波形 -> POST /infer -> 显示结果"""
        if self.busy:
            self.set_status("上一件事还没做完")
            return
        if not self.brd.host:
            self.set_status("还没填板子地址 —— 点右上角「设置」")
            return
        try:
            kind, d = self.gen_wave()
        except Exception as e:
            self.set_status("生成波形失败：%s" % e)
            return
        self._set_busy(True)          # ★ 走 _set_busy，记时间戳给看门狗
        self._pump_busy_ui(True)
        self.set_status("正在发给板子推理…")
        self.lbl_infer.configure(text="推理中…", fg=C["dim"],
                                 font=(self.font, 12))

        def work():
            import time as _t
            t0 = _t.time()
            try:
                r = self.brd.call("/infer", "POST",
                                  {"type": "waveform", "data": d,
                                   "hint": "raw", "api_key": self.brd.token},
                                  timeout=60)
                ms = int((_t.time() - t0) * 1000)
                self.q.put(("infer", {"kind": kind, "res": r, "ms": ms,
                                      "n": len(d)}))
            except Exception as e:
                self.q.put(("infer", {"kind": kind,
                                      "res": {"ok": False, "error": str(e)},
                                      "ms": 0, "n": len(d)}))
        import threading
        threading.Thread(target=work, daemon=True).start()

    def _show_infer(self, p):
        """主线程显示推理结果"""
        self._set_busy(False)         # ★ 走 _set_busy，同步按钮状态
        self._pump_busy_ui(False)
        r = p.get("res") or {}
        if not r.get("ok"):
            self.lbl_infer.configure(
                text="✗ 推理失败：%s" % (r.get("error") or "未知错误"),
                fg=C["rec"], font=(self.font, 11))
            self.set_status("推理失败")
            return
        lab = r.get("label") or "?"
        conf = r.get("confidence")
        el = r.get("elapsed_ms")
        eng = (r.get("detail") or {}).get("engine") or "?"
        txt = ("★ 类别：%s（%s）\n"
               "   置信度：%s\n"
               "   板上耗时：%s ms   （网络往返 %d ms）\n"
               "   引擎：%s\n"
               "   送入点数：%d"
               % (lab, self.WAVE_CN.get(lab, "?"),
                  ("%.1f%%" % (conf * 100)) if isinstance(conf, (int, float))
                  else str(conf),
                  el if el is not None else "?", p.get("ms", 0),
                  eng, p.get("n", 0)))
        # 判对没有？（我们自己知道发的是什么）
        exp = p.get("kind")
        hit = (lab == exp)
        self.lbl_infer.configure(
            text=txt + ("\n\n" + ("✓ 和生成时选的类别一致" if hit
                                  else "⚠ 生成的是 %s，板子判成 %s"
                                       % (self.WAVE_CN.get(exp, exp), lab))),
            fg=C["ok"] if hit else C["sys_fg"],
            font=(self.font, 11))
        import datetime as _dt
        line = ("%s  %-14s %-6s %5sms"
                % (_dt.datetime.now().strftime("%H:%M:%S"),
                   lab, ("%.0f%%" % (conf * 100))
                   if isinstance(conf, (int, float)) else "?",
                   el if el is not None else "?"))
        self.infer_hist.insert(0, line)
        self.lst_hist.insert(0, line)
        while self.lst_hist.size() > 10:
            self.lst_hist.delete("end")
        self.set_status("推理完成：%s" % lab)

    def _build_files(self, parent):
        """★★★ 文件传输页（2026-10-03 加）

        用户要的"文件同步传输"。

        板子侧其实早就有完整接口（cloud_api.py）：
            GET  /fs/list  /fs/stat  /fs/download
            POST /fs/upload/begin → /fs/upload/chunk → /fs/upload/end
            POST /fs/delete  /fs/mkdir
        旧版客户端的「工具箱」界面也用过这些接口，
        但后来界面重做成聊天式之后，文件传输那块【没跟过来】。
        ⇒ 现在补上，做成和「聊天 / 推理」并列的第三个页签。

        ★ 上传是【分块】的（1 MB 一块）+ md5 校验：
          板子只有 1GB 内存，整文件塞进一个请求会把它打爆。
        """
        # ── 路径栏 ──
        bar = tk.Frame(parent, bg=C["panel"])
        bar.pack(fill="x", padx=12, pady=(12, 6))
        tk.Label(bar, text="路径", bg=C["panel"], fg=C["text"],
                 font=(self.font, 10)).pack(side="left", padx=(12, 4))
        self.v_fspath = tk.StringVar(value="/home/zynq")
        e = tk.Entry(bar, textvariable=self.v_fspath, font=("Consolas", 10))
        e.pack(side="left", fill="x", expand=True, padx=(0, 6))
        e.bind("<Return>", lambda ev: self.fs_list())
        for txt, cmd in (("↑ 上级", self.fs_up), ("刷新", self.fs_list),
                         ("新建目录", self.fs_mkdir)):
            tk.Button(bar, text=txt, command=cmd, bd=0, bg=C["line"],
                      fg=C["text"], font=(self.font, 9), cursor="hand2",
                      padx=8, pady=3).pack(side="left", padx=2)

        # ── 快捷目录 ──
        bar2 = tk.Frame(parent, bg=C["bg"])
        bar2.pack(fill="x", padx=12, pady=(0, 4))
        tk.Label(bar2, text="快捷：", bg=C["bg"], fg=C["dim"],
                 font=(self.font, 9)).pack(side="left")
        for p in ("/home/zynq", "/home/zynq/Music", "/home/zynq/Pictures",
                  "/tmp", "/"):
            tk.Button(bar2, text=p, command=lambda pp=p: self.fs_goto(pp),
                      bd=0, bg=C["bg"], fg=C["accent"],
                      font=("Consolas", 8), cursor="hand2").pack(
                side="left", padx=3)

        # ── 文件列表 ──
        wrap = tk.Frame(parent, bg=C["bg"])
        wrap.pack(fill="both", expand=True, padx=12, pady=4)
        cols = ("name", "type", "size", "mtime")
        self.tree_fs = ttk.Treeview(wrap, columns=cols, show="headings")
        for c, t, w in (("name", "名称", 300), ("type", "类型", 70),
                        ("size", "大小", 100), ("mtime", "修改时间", 170)):
            self.tree_fs.heading(c, text=t)
            self.tree_fs.column(c, width=w, anchor="w")
        vsb = ttk.Scrollbar(wrap, orient="vertical",
                            command=self.tree_fs.yview)
        self.tree_fs.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self.tree_fs.pack(side="left", fill="both", expand=True)
        self.tree_fs.bind("<Double-1>", self._fs_dbl)

        # ── 操作按钮 + 进度 ──
        bar3 = tk.Frame(parent, bg=C["panel"])
        bar3.pack(fill="x", padx=12, pady=(4, 10))
        self.btn_up = tk.Button(bar3, text="⬆ 上传到当前目录",
                                command=self.fs_upload, bd=0,
                                bg=C["accent"], fg="#ffffff",
                                font=(self.font, 10, "bold"), cursor="hand2",
                                padx=14, pady=4)
        self.btn_up.pack(side="left", padx=(12, 6))
        # ★★★ 「传到接收区」—— 和板子上的「传输助手」App 配对
        #   板子那个 App 只看 /home/zynq/received，所以这里固定传到那，
        #   免得传到 /lib/firmware 之类的地方让人找不着。
        self.btn_up2 = tk.Button(bar3, text="📥 传到接收区",
                                 command=self.fs_upload_recv, bd=0,
                                 bg="#2f9e78", fg="#ffffff",
                                 font=(self.font, 10, "bold"), cursor="hand2",
                                 activebackground="#27866a",
                                 padx=14, pady=4)
        self.btn_up2.pack(side="left", padx=(0, 6))
        tk.Button(bar3, text="⬇ 下载到电脑", command=self.fs_download, bd=0,
                  bg=C["line"], fg=C["text"], font=(self.font, 10),
                  cursor="hand2", padx=12, pady=4).pack(side="left", padx=4)
        tk.Button(bar3, text="删除", command=self.fs_delete, bd=0,
                  bg=C["line"], fg=C["rec"], font=(self.font, 10),
                  cursor="hand2", padx=12, pady=4).pack(side="left", padx=4)
        self.pb = ttk.Progressbar(bar3, length=180, mode="determinate")
        self.pb.pack(side="right", padx=10)
        self.lbl_fs = tk.Label(parent, text="双击文件夹进入；选中文件可下载/删除",
                               bg=C["bg"], fg=C["dim"],
                               font=(self.font, 8), anchor="w")
        self.lbl_fs.pack(fill="x", padx=14, pady=(0, 6))

    # ---------- 文件传输 ----------
    def _fs_connected(self):
        if not self.brd.host:
            self._fs_status("还没填板子地址 —— 点右上角「设置」")
            return False
        return True

    def _fs_status(self, s):
        try:
            self.lbl_fs.configure(text=s)
        except Exception:
            pass

    def fs_goto(self, p):
        self.v_fspath.set(p)
        self.fs_list()

    def fs_up(self):
        p = self.v_fspath.get().strip().rstrip("/")
        i = p.rfind("/")
        self.v_fspath.set(p[:i] if i > 0 else "/")
        self.fs_list()

    def fs_list(self):
        """列目录（后台拉，回主线程画）"""
        if not self._fs_connected():
            return
        p = self.v_fspath.get().strip() or "/home/zynq"
        self._fs_status("读取 %s …" % p)

        def work():
            try:
                d = self.brd.call("/fs/list?path=" + urllib.parse.quote(p),
                                  timeout=25)
            except Exception as e:
                self.q.put(("fs_list", {"ok": False, "error": str(e)}))
                return
            self.q.put(("fs_list", d))
        threading.Thread(target=work, daemon=True).start()

    def _fs_show_list(self, d):
        """主线程：把目录内容画进表格"""
        if not d.get("ok"):
            self._fs_status("✗ 列目录失败：%s" % str(d.get("error"))[:80])
            return
        p = d.get("path") or self.v_fspath.get()
        self.v_fspath.set(p)
        self.tree_fs.delete(*self.tree_fs.get_children())
        items = d.get("items") or []
        # ★ 目录排前面（板子那边是按名字排的，这里再排一次更好用）
        for it in sorted(items, key=lambda x: (x.get("type") != "dir",
                                               str(x.get("name")))):
            sz = "—" if it.get("type") == "dir" else _fmt_size(it.get("size"))
            self.tree_fs.insert("", "end", values=(
                it.get("name"), "目录" if it.get("type") == "dir" else "文件",
                sz, it.get("mtime", "")))
        free = d.get("free_bytes")
        self._fs_status("%s  共 %d 项%s" % (
            p, len(items),
            ("  剩余 %s" % _fmt_size(free)) if free is not None else ""))

    def _fs_sel(self):
        s = self.tree_fs.selection()
        if not s:
            return None, None
        v = self.tree_fs.item(s[0], "values")
        return v[0], v[1]

    def _fs_dbl(self, ev):
        name, typ = self._fs_sel()
        if not name:
            return
        if typ == "目录":
            base = self.v_fspath.get().strip().rstrip("/")
            self.v_fspath.set(base + "/" + name)
            self.fs_list()
        else:
            self.fs_download()

    def fs_download(self):
        """下载选中的文件到电脑"""
        name, typ = self._fs_sel()
        if not name:
            self._fs_status("先选中一个文件")
            return
        if typ == "目录":
            self._fs_status("目录不能直接下载（先点进去选文件）")
            return
        base = self.v_fspath.get().strip().rstrip("/")
        p = base + "/" + name
        dst = filedialog.asksaveasfilename(initialfile=name)
        if not dst:
            return
        self._fs_status("正在下载 %s …" % name)

        def work():
            try:
                b = self.brd.raw("/fs/download?path="
                                 + urllib.parse.quote(p))
                with open(dst, "wb") as f:
                    f.write(b)
                self.q.put(("fs_msg", "✓ 下载完成：%s（%s）"
                            % (os.path.basename(dst), _fmt_size(len(b)))))
            except Exception as e:
                self.q.put(("fs_msg", "✗ 下载失败：%s" % e))
        threading.Thread(target=work, daemon=True).start()

    def fs_upload(self, recv=False):
        """上传一个文件到板子（分块 + md5 校验）

        recv=True 时固定传到接收区（/home/zynq/received），
        这样板子上的「文件传输助手」App 一眼就能看到。
        """
        if not self._fs_connected():
            return
        fp = filedialog.askopenfilename()
        if not fp:
            return
        name = os.path.basename(fp)
        size = os.path.getsize(fp)
        if recv:
            # ★ 固定接收区（板子那个 App 看的就是这个目录）
            self.v_fspath.set(RECV_DIR)
            target = RECV_DIR.rstrip("/") + "/" + name
        else:
            base = self.v_fspath.get().strip().rstrip("/")
            target = base + "/" + name
        if not messagebox.askyesno(
                "上传", "上传 %s（%s）到\n%s ？" % (name, _fmt_size(size),
                                                  target)):
            return
        self._fs_status("正在上传 %s …" % name)
        self.pb.configure(value=0)
        self.btn_up.configure(state="disabled")
        if hasattr(self, "btn_up2"):
            self.btn_up2.configure(state="disabled")

        def work():
            try:
                h = hashlib.md5()
                with open(fp, "rb") as f:
                    for chunk in iter(lambda: f.read(1 << 20), b""):
                        h.update(chunk)
                md5 = h.hexdigest()
                b = self.brd.call("/fs/upload/begin", "POST",
                                  {"path": target, "size": size,
                                   "md5": md5}, timeout=60)
                if not b.get("ok"):
                    self.q.put(("fs_msg", "✗ 开始上传失败：%s"
                                % str(b.get("error"))[:70]))
                    return
                uid = b["upload_id"]
                CH = 1 << 20
                off = 0
                with open(fp, "rb") as f:
                    while off < size:
                        piece = f.read(CH)
                        r = self.brd.call("/fs/upload/chunk", "POST", {
                            "upload_id": uid, "offset": off,
                            "data": base64.b64encode(piece).decode()},
                            timeout=180)
                        if not r.get("ok"):
                            self.q.put(("fs_msg", "✗ 上传中断（第 %d 块）：%s"
                                        % (off // CH, str(r.get("error"))[:60])))
                            return
                        off += len(piece)
                        self.q.put(("fs_prog", int(off * 100 / max(1, size))))
                e = self.brd.call("/fs/upload/end", "POST",
                                  {"upload_id": uid}, timeout=180)
                if e.get("ok"):
                    self.q.put(("fs_msg", "✓ 上传完成，md5 校验通过：%s"
                                % name))
                else:
                    self.q.put(("fs_msg", "✗ 校验失败：%s"
                                % str(e.get("error"))[:70]))
            except Exception as ex:
                self.q.put(("fs_msg", "✗ 上传出错：%s" % ex))
            finally:
                self.q.put(("fs_refresh", True))
        threading.Thread(target=work, daemon=True).start()

    def fs_upload_recv(self):
        """📥 传到接收区（板子上「文件传输助手」App 看的就是这里）"""
        self.fs_upload(recv=True)

    def fs_delete(self):
        name, typ = self._fs_sel()
        if not name:
            self._fs_status("先选中一项")
            return
        if not messagebox.askyesno("删除", "确定删除？\n%s" % name):
            return
        base = self.v_fspath.get().strip().rstrip("/")
        p = base + "/" + name
        self._fs_status("正在删除 %s …" % name)

        def work():
            try:
                d = self.brd.call("/fs/delete", "POST", {"path": p},
                                  timeout=30)
                self.q.put(("fs_msg", "✓ 已删除" if d.get("ok")
                            else "✗ 删除失败：%s" % str(d.get("error"))[:70]))
            except Exception as e:
                self.q.put(("fs_msg", "✗ 删除出错：%s" % e))
            finally:
                self.q.put(("fs_refresh", True))
        threading.Thread(target=work, daemon=True).start()

    def fs_mkdir(self):
        """在板子上新建目录"""
        if not self._fs_connected():
            return
        name = simpledialog.askstring("新建目录", "目录名：", parent=self.root)
        if not name:
            return
        base = self.v_fspath.get().strip().rstrip("/")
        p = base + "/" + name.strip()

        def work():
            try:
                d = self.brd.call("/fs/mkdir", "POST", {"path": p},
                                  timeout=30)
                self.q.put(("fs_msg", "✓ 已建目录 %s" % name if d.get("ok")
                            else "✗ 失败：%s" % str(d.get("error"))[:70]))
            except Exception as e:
                self.q.put(("fs_msg", "✗ 出错：%s" % e))
            finally:
                self.q.put(("fs_refresh", True))
        threading.Thread(target=work, daemon=True).start()

    def _build_input(self, parent):
        wrap = tk.Frame(parent, bg=C["bg"])
        wrap.pack(fill="x", side="bottom", padx=12, pady=(4, 10))

        box = tk.Frame(wrap, bg=C["panel"],
                       highlightbackground=C["line"], highlightthickness=1)
        box.pack(fill="x")

        # 输入框
        self.txt = tk.Text(box, height=3, wrap="word", bd=0,
                           bg=C["panel"], fg=C["text"],
                           font=(self.font, 10), padx=10, pady=8,
                           insertbackground=C["accent"])
        self.txt.pack(fill="x")
        self.txt.bind("<Return>", self._on_return)
        self.txt.bind("<Shift-Return>", lambda e: None)
        self.txt.bind("<KeyRelease>", self._on_key)

        # 下面一排按钮
        bar = tk.Frame(box, bg=C["panel"])
        bar.pack(fill="x", padx=6, pady=(0, 6))

        # 左：录音 + 提示
        # ★ 图标的问题：emoji（🎤）在不同 Windows 上渲染差异很大，
        #   有些字体会回退成一个奇怪的符号（看起来像支笔）。
        #   所以按钮上用【文字】而不是 emoji，稳妥。
        self.btn_mic = tk.Button(bar, text="🎤 说一句", command=self.toggle_rec,
                                 bd=0, bg=C["panel"], fg=C["text"],
                                 font=(self.font, 10), cursor="hand2",
                                 activebackground=C["panel"],
                                 padx=6, pady=2)
        self.btn_mic.pack(side="left", padx=2)
        self.lbl_rec = tk.Label(bar, text="", bg=C["panel"], fg=C["rec"],
                                font=(self.font, 9))
        self.lbl_rec.pack(side="left", padx=6)
        tk.Label(bar, text="Enter 发送 / Shift+Enter 换行", bg=C["panel"],
                 fg=C["dim"], font=(self.font, 8)).pack(side="left", padx=8)

        # 右：★ 模式 + 模型 + 朗读 + 发送
        self.btn_send = tk.Button(bar, text="发送", command=self.send, bd=0,
                                  bg=C["accent"], fg="white", padx=18, pady=3,
                                  font=(self.font, 10), cursor="hand2",
                                  activebackground="#1d4ed8")
        self.btn_send.pack(side="right", padx=(6, 2))

        self.btn_spk = tk.Button(bar, text="朗读", command=self._toggle_speak,
                                 bd=0, bg=C["panel"], fg=C["text"],
                                 font=(self.font, 9), cursor="hand2", padx=6,
                                 activebackground=C["panel"])
        self.btn_spk.pack(side="right", padx=2)

        # ★ 这个下拉框列的是【板子的】模型（启动时从板子 /llm/models 拉），
        #   选中就是 POST /llm/model 去切板子 —— PC 端不自己配模型。
        self.v_model = tk.StringVar(value=self.conf.get("model", "") or "板子模型")
        self.cb_model = ttk.Combobox(bar, textvariable=self.v_model, width=18,
                                     state="readonly", font=("Consolas", 9))
        self.cb_model.pack(side="right", padx=3)
        self.cb_model.bind("<<ComboboxSelected>>",
                           lambda e: self.set_model(self.v_model.get()))

        self.v_mode = tk.StringVar(value="自动")
        self.cb_mode = ttk.Combobox(bar, textvariable=self.v_mode, width=6,
                                    state="readonly", font=(self.font, 9),
                                    values=("自动", "云端", "本地"))
        self.cb_mode.pack(side="right", padx=3)
        self.cb_mode.bind("<<ComboboxSelected>>", self._on_mode)

        tk.Label(bar, text="模式", bg=C["panel"], fg=C["dim"],
                 font=(self.font, 8)).pack(side="right")
        tk.Label(bar, text="模型", bg=C["panel"], fg=C["dim"],
                 font=(self.font, 8)).pack(side="right", padx=(6, 2))

    # ---------- 事件 ----------
    def _on_return(self, e):
        if e.state & 0x0001:        # Shift
            return None
        self.send()
        return "break"

    def _on_key(self, e):
        pass

    def _on_mode(self, e=None):
        name = self.v_mode.get()
        inv = {v: k for k, v in self.mode_names.items()}
        m = inv.get(name, "auto")
        self.conf["mode"] = m
        save_conf(self.conf)
        self.set_status("切模式 → %s …" % name)

        def work():
            try:
                r = self.brd.call("/llm/config", "POST", {"mode": m}, timeout=15)
                self.q.put(("status", "模式已切到【%s】%s"
                            % (name, "" if r.get("ok") else
                               "  ✗ " + str(r.get("error")))))
            except Exception as ex:
                self.q.put(("status", "切模式失败: %s" % ex))
        threading.Thread(target=work, daemon=True).start()

    def _toggle_speak(self):
        self.conf["voice_reply"] = not self.conf.get("voice_reply", True)
        save_conf(self.conf)
        self._sync_spk()
        self.set_status("自动朗读：" + ("开" if self.conf["voice_reply"] else "关"))

    def _sync_spk(self):
        on = self.conf.get("voice_reply", True)
        self.btn_spk.configure(fg=C["accent"] if on else C["dim"])

    # ---------- 会话 ----------
    def render_session(self):
        self.msg.clear()
        for m in self.store.cur.msgs:
            self.msg.add(m.get("who", "ai"), m.get("text", ""), m.get("ts"))
        self.side.render(self.store.group(), self.store.cur.id)

    # ══════════════════════════════════════════════════════════════
    #  ★★★ 从板子同步会话（2026-10-03）
    # ══════════════════════════════════════════════════════════════
    # 用户报："对话和板子不一致，没同步啊"
    #
    # 根因（板子侧已修）：板子上原本有三套互不相通的会话存储，
    #   而 /chat/sessions 读的那个目录【一直是空的】。
    #   现在板子统一到 /home/zynq/.agent_chats.json，
    #   而 agent 的 /voice 也会往同一个文件追加
    #   ⇒ PC 端发的话板载 UI 能看到，反之亦然。
    #
    # PC 端这边要做的：启动/手动刷新时把板子的会话拉过来显示。
    #   ★ 板子来的会话 id 加 "board:" 前缀，和本地新建的区分开；
    #     拉历史用 /chat/history/<原 id>。
    # ══════════════════════════════════════════════════════════════
    def _set_show_archived(self, on):
        """勾/取消「归档」—— 重新拉一次列表（带或不带已归档的）"""
        self._show_arch = bool(on)
        self.set_status("显示已归档…" if on else "隐藏已归档")

        def work():
            try:
                self.sync_sessions_from_board(quiet=True,
                                              include_archived=self._show_arch)
                self.q.put(("auto_sync", True))
            except Exception as e:
                log("切换归档显示失败: %s" % e)
        threading.Thread(target=work, daemon=True).start()

    def sync_sessions_from_board(self, quiet=True, include_archived=False,
                                 prefer_board_cur=False):
        """从板子拉会话列表 + 各自的历史，合并进本地列表

        ★ include_archived：默认只拉未归档的（用户要的"归档隐藏"）。
          想看归档的点侧栏那个「显示已归档」。
        """
        if not self.brd.host:
            return 0
        # NEWCHAT_KEEP_CUR_V1：记住当前选中的会话，重建后要恢复
        try:
            prev_cur_id = self.store.cur.id if self.store.cur else None
        except Exception:
            prev_cur_id = None
        try:
            path = "/chat/sessions"
            if include_archived:
                path += "?include_archived=1"
            r = self.brd.call(path, timeout=25)
        except Exception as e:
            log("同步会话失败: %s" % e)
            if not quiet:
                self.set_status("同步失败：%s" % e)
            return 0
        if not r.get("ok"):
            if not quiet:
                self.set_status("同步失败：%s" % (r.get("error") or "板子没返回"))
            return 0
        ss = r.get("sessions") or []
        # ★ 本地列表里板子来的先清掉，重建成服务端给的样子
        #   （归档的会被服务端过滤掉；本地重建才能反映"取消归档"）
        keep_local = [s for s in self.store.sessions
                      if not s.id.startswith("board:")]
        # SESS_PERSIST_FIX_V1：先建 id->对象 映射，sync 时复用旧对象
        #   否则每 5 秒整只重建，PC 这边刚加的消息会被冲掉
        _old_map = {}
        for _s in self.store.sessions:
            _old_map[_s.id] = _s
        new_board = []
        n = 0
        for bs in ss:
            sid = "board:" + str(bs.get("id") or "")
            title = str(bs.get("title") or "新对话")
            s = _old_map.get(sid)
            if s is None:
                s = Session(sid, title)
            else:
                if title and title != "新对话":
                    s.title = title
            s.archived = bool(bs.get("archived"))
            # 板子历史
            _hm = []
            try:
                h = self.brd.call("/chat/history/" + str(bs.get("id")),
                                  timeout=25)
                if h.get("ok"):
                    for m in (h.get("messages") or []):
                        who = "user" if m.get("role") == "user" else "ai"
                        _hm.append((who, str(m.get("content") or "")))
            except Exception as e:
                log("拉历史失败 %s: %s" % (sid, e))
            # SESS_PERSIST_FIX_V1：只有板子历史【更多】时才覆盖
            #   （否则会把 PC 刚发、板子还没记上的消息冲掉）
            if len(_hm) > len(s.msgs):
                s.msgs = []
                for _who, _tx in _hm:
                    s.add(_who, _tx)
            new_board.append(s)
            n += 1
        self.store.sessions = new_board + keep_local

        # NEWCHAT_KEEP_CUR_V1：重建列表后【优先恢复原来的选中会话】
        #   ★ 关键：不能无条件把选中切到板子的 cur，
        #     否则用户刚点「新对话」建的本地会话 5 秒内就被抢走
        # SESS_SELECT_FIX_V1：首次同步优先选板子当前会话
        #   （否则启动时 cur 可能是空的本地「新对话」，右边一片空白）
        if prefer_board_cur:
            _bc = None
            for bs2 in ss:
                if bs2.get("cur"):
                    _tgt = "board:" + str(bs2.get("id"))
                    for s2 in new_board:
                        if s2.id == _tgt:
                            _bc = s2
                            break
                    break
            if _bc is not None:
                self.store.cur = _bc
                log("首次同步：选中板子当前会话 %s（%d 条消息）"
                    % (_bc.id, len(_bc.msgs)))
                return n

        _restored = None
        if prev_cur_id:
            for s in self.store.sessions:
                if s.id == prev_cur_id:
                    _restored = s
                    break
        if _restored is not None:
            self.store.cur = _restored
        else:
            # 原会话确实没了 -> 用板子的 cur，再退第一个
            _board_cur = None
            for bs in ss:
                if bs.get("cur"):
                    _target = "board:" + str(bs.get("id"))
                    for s in new_board:
                        if s.id == _target:
                            _board_cur = s
                            break
                    break
            if _board_cur is not None:
                self.store.cur = _board_cur
            elif self.store.sessions:
                self.store.cur = self.store.sessions[0]
        log("从板子同步了 %d 个会话" % n)
        if not quiet:
            self.set_status("已从板子同步 %d 个会话" % n)
        return n

    def _on_archive(self, s, on):
        """归档 / 取消归档（打到板子上，两边同步）"""
        if not s.id.startswith("board:"):
            return
        sid = s.id.split(":", 1)[1]
        self.set_status("正在%s「%s」…" % ("归档" if on else "取消归档",
                                          s.title[:12]))

        def work():
            try:
                r = self.brd.call("/chat/archive", "POST",
                                  {"session_id": sid, "on": bool(on)},
                                  timeout=20)
                if r.get("ok"):
                    self.q.put(("archive_done", (sid, on)))
                else:
                    self.q.put(("status", "归档失败：%s"
                                % (r.get("error") or "板子没返回")))
            except Exception as e:
                self.q.put(("status", "归档失败：%s" % e))
        threading.Thread(target=work, daemon=True).start()

    def pick_session(self, s):
        self.store.cur = s
        self.render_session()

    def new_session(self):
        self.store.new()
        self.render_session()
        self.set_status("新对话")

    def del_session(self, s):
        if not messagebox.askyesno("删除", "删掉「%s」？" % s.title):
            return
        self.store.delete(s)
        self.render_session()

    # ---------- 网络 ----------
    def set_status(self, s):
        self.status.set(s)

    def bootstrap(self):
        """启动时：拉设备信息 + 模型列表 + 模式"""
        def work():
            log("bootstrap 开始  host=%r token=%r" % (self.brd.host,
                                                      self.brd.token))
            # ★ 顺手把 PC 语音识别的可用性记下来 ——
            #   exe 是 --windowed 的没控制台，出问题只能靠这个日志。
            try:
                if PC_SR is None:
                    log("  PC 语音: 模块没载入")
                elif PC_SR.available():
                    log("  PC 语音: 可用  语言=%s  脚本=%s"
                        % (PC_SR.langs(), os.path.basename(PC_SR.PS_FILE)))
                else:
                    log("  PC 语音: 不可用（没有中文识别器）")
            except Exception as _e:
                log("  PC 语音: 检查失败 %s" % _e)
            try:
                # ★ 2026-10-03: 8 秒不够 —— 板子刚重启时 cloud-api
                #   冷启动要十几秒，结果界面一直显示"未连接"，
                #   但文件页其实能正常列目录。改成 20 秒。
                d = self.brd.call("/info", timeout=20)
                log("  /info -> ok=%s err=%s" % (d.get("ok"),
                                                 str(d.get("error"))[:60]))
                if not d.get("ok") and not self.brd.token:
                    # ★★★ 2026-10-03：这就是"exe 连不上板子"的真正原因 ——
                    #   板子的 /health 不需要认证（所以"扫一扫"能找到它），
                    #   但 /info、/infer、/voice 都要 token。
                    #   配置里 token 为空时，一调 /info 就 unauthorized，
                    #   界面显示"未连接"，用户以为连不上，其实只是没认证。
                    #   ⇒ token 为空时自动试一遍常见值，通了就写回配置。
                    log("  token 为空 -> 自动探测…")
                    tk = probe_token(self.brd.host)
                    log("  探测结果: %r" % (tk,))
                    if tk is not None:
                        self.brd.set(self.brd.host, tk)
                        self.conf["token"] = tk
                        save_conf(self.conf)
                        d = self.brd.call("/info", timeout=20)
                        log("  用新 token 重试 /info -> ok=%s" % d.get("ok"))
                        if d.get("ok"):
                            self.q.put(("token_ok", tk))
                if d.get("ok"):
                    self.q.put(("info", d))
                else:
                    self.q.put(("conn", "未连接  " + str(d.get("error", ""))[:40]))
            except Exception as e:
                log("  bootstrap 异常: %s: %s" % (type(e).__name__, e))
                self.q.put(("conn", "未连接"))
            try:
                m = self.brd.call("/llm/models", timeout=20)
                if m.get("ok"):
                    self.q.put(("models", m))
            except Exception:
                pass
            try:
                c = self.brd.call("/llm/config", timeout=10)
                if c.get("ok"):
                    self.q.put(("mode", c.get("mode")))
            except Exception:
                pass
            # ★★★ 拉板子的对话记录（2026-10-03）
            #   用户报"对话和板子不一致" —— 板子侧已统一到共享文件，
            #   PC 端这里把它拉过来显示，两边就是同一份了。
            try:
                # SESS_SELECT_FIX_V1：首次同步选中板子当前会话
                n = self.sync_sessions_from_board(quiet=True,
                                                  prefer_board_cur=True)
                # ★ 日志由 sync_sessions_from_board 自己打，这里别重复打
                if n:
                    self.q.put(("sessions_synced", n))
            except Exception as e:
                log("  同步会话失败: %s" % e)
        threading.Thread(target=work, daemon=True).start()

    def _auto_refresh(self):
        """★★★ 定时从板子拉对话（2026-10-03 用户建议）

        用户："你应该要加一下实时刷新说不定可以解决"

        对。之前 PC 端只在【启动时】同步一次，之后板子上（或者别的
        客户端）聊的内容就看不到了，得重启程序。
        ⇒ 每 5 秒后台拉一次 /chat/sessions，有变化才重画。

        ★ 三个注意点：
          ① 不能太频繁 —— 板子只有 1GB 内存，还跑着别的服务
          ② 用户正在输入/正在等回复时不要重画（会把界面刷掉）
          ③ 只有【真的变了】才重画（比较会话列表的指纹）
        """
        try:
            if getattr(self, "_auto_busy", False):
                # 上一轮还没跑完（板子慢的时候会），这轮跳过
                self.root.after(5000, self._auto_refresh)
                return
            if getattr(self, "_auto_t", 0) and \
                    time.time() - self._auto_t < 5.0:
                self.root.after(5000, self._auto_refresh)
                return
            self._auto_t = time.time()
            # ★ 忙的时候（等回复/推理中）跳过，别打扰用户
            if self.busy or self.recording:
                self.root.after(5000, self._auto_refresh)
                return
            self._auto_busy = True

            def work():
                try:
                    # ★★★ 2026-10-03 加：顺手重连（板子刚重启时有用）
                    #   现象：板子重启后 cloud-api 要几秒才就绪，
                    #        而 bootstrap 只在启动时跑一次 ⇒
                    #        界面一直显示"未连接"，可其它功能其实能用
                    #        （实测：显示未连接，文件页却能列出 224 项）。
                    #   ⇒ 只要标签还显示"未连接"，每轮都补一次 /info。
                    _txt = ""
                    try:
                        _txt = str(self.lbl_conn.cget("text"))
                    except Exception:
                        pass
                    if _txt.startswith("未连接"):
                        _d = self.brd.call("/info", timeout=15)
                        if _d.get("ok"):
                            self.q.put(("info", _d))
                            log("  重连成功 -> %s" % _d.get("ip"))
                    r = self.brd.call("/chat/sessions", timeout=15)
                    if not r.get("ok"):
                        return
                    ss = r.get("sessions") or []
                    # 指纹：会话数 + 每个的条数 + 标题 + 当前项
                    fp = tuple((str(s.get("id")), s.get("msg_count"),
                                str(s.get("title")), bool(s.get("cur")))
                               for s in ss)
                    if getattr(self, "_auto_fp", None) is None:
                        # 第一次只记基线（bootstrap 刚同步过，不必重复）
                        self._auto_fp = fp
                        return
                    if fp != self._auto_fp:
                        self._auto_fp = fp
                        self.q.put(("auto_sync", True))
                except Exception:
                    pass
                finally:
                    self._auto_busy = False
            threading.Thread(target=work, daemon=True).start()
        except Exception:
            self._auto_busy = False
        self.root.after(5000, self._auto_refresh)

    def _pump(self):
        """主线程消费后台线程的结果"""
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "info":
                    d = payload
                    self.lbl_conn.configure(
                        text="● %s" % d.get("ip", ""), fg=C["ok"])
                    self.lbl_temp.configure(
                        text="%.1f°C" % (d.get("temperature_c") or 0))
                    # ★★★ 2026-10-03 修：原来只存 last_ip，
                    #   而启动时 ChatApp 读的是 conf["host"]
                    #   ⇒ 存了 A、读的是 B，"记住上次 IP" 形同虚设。
                    #   现在两个都写，并且只在本机没填过地址时才覆盖，
                    #   免得用户在设置里手填的地址被扫描结果冲掉。
                    _ip = d.get("ip", "")
                    if _ip:
                        self.conf["last_ip"] = _ip
                        if not self.conf.get("host"):
                            self.conf["host"] = _ip
                        save_conf(self.conf)
                elif kind == "token_ok":
                    # ★ 自动试出来的 token —— 告诉用户一声，免得他不知道为什么就好了
                    self.set_status("已自动配置 token（%s）" % payload)
                elif kind == "sessions_synced":
                    # ★ 板子的对话拉回来了 —— 重画会话列表和消息区
                    try:
                        self.side.render(self.store.group(), self.store.cur.id)
                        self.render_session()
                    except Exception:
                        pass
                    self.set_status("已同步板子的 %d 个对话" % payload)
                elif kind == "fs_list":
                    # ★ 文件页：目录内容画出来（在主线程，安全）
                    self._fs_show_list(payload)
                elif kind == "fs_msg":
                    self._fs_status(payload)
                    self.set_status(payload)
                elif kind == "fs_prog":
                    try:
                        self.pb.configure(value=int(payload))
                    except Exception:
                        pass
                elif kind == "fs_refresh":
                    try:
                        self.btn_up.configure(state="normal")
                        if hasattr(self, "btn_up2"):
                            self.btn_up2.configure(state="normal")
                        self.pb.configure(value=0)
                    except Exception:
                        pass
                    if self._tab == "files":
                        self.fs_list()
                elif kind == "auto_sync":
                    # ★ 定时刷新发现的变更（用户建议的"实时刷新"）
                    def _as():
                        try:
                            self.sync_sessions_from_board(
                                quiet=True,
                                include_archived=getattr(self, "_show_arch",
                                                         False))
                            self.side.render(self.store.group(),
                                             self.store.cur.id)
                            self.render_session()
                        except Exception as e:
                            log("自动刷新失败: %s" % e)
                    threading.Thread(target=_as, daemon=True).start()
                elif kind == "archive_done":
                    sid, on = payload
                    # ★ 归档完立刻刷新列表（把那条藏起来 / 放出来）
                    def _ar():
                        try:
                            self.sync_sessions_from_board(
                                quiet=True,
                                include_archived=getattr(self, "_show_arch",
                                                         False))
                            self.side.render(self.store.group(),
                                             self.store.cur.id)
                            self.render_session()
                        except Exception:
                            pass
                    threading.Thread(target=_ar, daemon=True).start()
                    self.set_status("已%s（两边同步）"
                                    % ("归档" if on else "取消归档"))
                elif kind == "infer":
                    self._show_infer(payload)
                elif kind == "conn":
                    self.lbl_conn.configure(text="● " + payload, fg=C["rec"])
                elif kind == "models":
                    ms = payload.get("models") or []
                    if ms:
                        self.models = ms
                        self.cb_model["values"] = ms
                        cur = payload.get("current") or ms[0]
                        self.v_model.set(cur)
                        self.conf["model"] = cur
                        save_conf(self.conf)
                elif kind == "mode":
                    m = payload or "auto"
                    self.v_mode.set(self.mode_names.get(m, "自动"))
                elif kind == "status":
                    self.set_status(payload)
                elif kind == "msg":
                    who, text = payload
                    self.store.cur.add(who, text)
                    self.store.save()
                    self.msg.add(who, text)
                    self.side.render(self.store.group(), self.store.cur.id)
                elif kind == "busy":
                    self._set_busy(payload)
                    self._pump_busy_ui(payload)
                elif kind == "say":
                    if self.conf.get("voice_reply", True):
                        self.speak(payload)
                elif kind == "sendtext":
                    # 语音识别完，自动发出去
                    self.lbl_rec.configure(text="")
                    self._send_text(payload)
                elif kind == "pc_asr":
                    # ★ PC 本地语音识别（Windows 自带识别器）的结果
                    self._show_pc_asr(payload)
                elif kind == "pc_part":
                    # ★ 流式的中间结果（边说边出字）
                    self._show_pc_part(payload)
                elif kind == "filltext":
                    # 语音识别完，只填进输入框（让用户确认再发）
                    self.lbl_rec.configure(text="")
                    self.txt.delete("1.0", "end")
                    self.txt.insert("1.0", payload)
                    self.txt.focus_set()
                elif kind == "rec_done":
                    self.lbl_rec.configure(text="")
                elif kind == "refresh_info":
                    def _r():
                        try:
                            d = self.brd.call("/info", timeout=15)
                            if d.get("ok"):
                                self.q.put(("info", d))
                        except Exception:
                            pass
                    threading.Thread(target=_r, daemon=True).start()
        except queue.Empty:
            pass
        self.root.after(120, self._pump)

    # ---------- 发送 ----------
    def send(self):
        """发送输入框里的内容

        ★ 2026-10-03 改：原来 busy 或空输入时【静默 return】——
          用户点了发送毫无反应，以为程序坏了（用户报的就是"发送不了"）。
          现在每种情况都给出明确提示，而且 busy 卡太久会自动放开。
        """
        text = self.txt.get("1.0", "end").strip()
        if not text:
            self.set_status("输入框是空的，先打点字")
            return
        if self.busy:
            self._check_busy_timeout()      # 卡太久就自动放开
            if self.busy:
                held = time.time() - getattr(self, "_busy_t0", time.time())
                self.set_status("上一件事还没回来（已 %.0f 秒）—— 等一下；"
                                "卡住的话点状态栏的「强制解开」" % held)
                return
        self.txt.delete("1.0", "end")
        self._send_text(text)

    def _set_busy(self, v):
        """统一设置 busy（记时间戳，给看门狗用）"""
        self.busy = bool(v)
        if v:
            self._busy_t0 = time.time()

    def _check_busy_timeout(self):
        """★ busy 看门狗：卡超过 BUSY_MAX 秒就自动放开

        为什么要它：网络请求最长 180 秒超时，中途用户点发送毫无反应；
        更糟的是 do_infer 直接赋值 busy，万一回调没跑到就永久卡死
        ⇒ 界面上表现成"发送按钮灰着、点了没反应"。
        """
        if not self.busy:
            return
        held = time.time() - getattr(self, "_busy_t0", 0)
        if held > BUSY_MAX:
            log("busy 卡了 %.0f 秒 -> 自动解开" % held)
            self._set_busy(False)
            self._pump_busy_ui(False)
            self.set_status("上一件事卡了 %.0f 秒，已自动解开，可以再发了"
                            % held)

    def force_unbusy(self):
        """手动解开 busy（状态栏上的应急按钮）"""
        self._set_busy(False)
        self._pump_busy_ui(False)
        self.set_status("已强制解开，可以再发了")

    def _pump_busy_ui(self, busy):
        """按 busy 状态刷新发送按钮"""
        try:
            self.btn_send.configure(state="disabled" if busy else "normal",
                                    text="…" if busy else "发送")
        except Exception:
            pass

    def _send_text(self, text):
        self.store.cur.add("user", text)
        self.store.save()
        self.msg.add("user", text)
        self.side.render(self.store.group(), self.store.cur.id)
        self.q.put(("busy", True))
        self.set_status("思考中…")

        def work():
            try:
                r = self.brd.call("/voice", "POST", {"text": text}, timeout=180)
                reply = r.get("reply") or r.get("error") or "（没有回复）"
                self.q.put(("msg", ("ai", reply)))
                self.q.put(("say", reply))
                self.q.put(("status", "就绪   %.1fs" % (r.get("elapsed") or 0)))
            except Exception as e:
                self.q.put(("msg", ("sys", "请求失败：%s" % e)))
                self.q.put(("status", "请求失败"))
            finally:
                self.q.put(("busy", False))
                self.q.put(("refresh_info", True))
        threading.Thread(target=work, daemon=True).start()

    # ---------- 模型 ----------
    def set_model(self, m, quiet=False):
        if not m:
            return
        self.conf["model"] = m
        save_conf(self.conf)
        if quiet:
            return
        self.set_status("切模型 → %s …" % m)

        def work():
            try:
                r = self.brd.call("/llm/model", "POST", {"model": m}, timeout=20)
                self.q.put(("status", "模型已切到 %s%s"
                            % (m, "" if r.get("ok") else
                               "  ✗ " + str(r.get("error")))))
            except Exception as e:
                self.q.put(("status", "切模型失败: %s" % e))
        threading.Thread(target=work, daemon=True).start()

    def reload_conf(self):
        self.conf = load_conf()
        self.brd.set(self.conf.get("host", ""), self.conf.get("token", ""))
        self._sync_spk()

    # ---------- 语音 ----------
    def toggle_rec(self):
        """语音按钮

        ★★★ 2026-10-03 改（用户建议）：
             "语音输入完全可以接电脑自己的语音输入啊，对吧，电脑软件好处理吧"

        原来：PC 录音 → base64 传给板子 → 板子转发百度 → 返回文字
              绕一大圈，还要板子联网、百度 key 有效。
        现在：★ 优先用 Windows 自带的中文识别器（离线、亚秒级），
              识别器不可用时才退回原来那条路。
        """
        if self.recording:
            self.stop_rec()
            return
        if PC_SR and PC_SR.available():
            self.pc_listen()
        else:
            self.start_rec()

    def pc_listen(self):
        """★ 用 Windows 自带识别器听一句（后台线程，不阻塞界面）

        ★★★ 2026-10-03 改成【流式】：边说边出字
          用户要的"流式语音输入"（路线图 P1 第 1a 项）。
          之前是 Recognize() 阻塞到你说完，干等；
          现在 Windows 每猜一点就吐一个中间结果，我们边读边刷输入框。

        ★ 中间结果会反复变（"现在" → "现在脱下" → "现在脱下肚"），
          所以 UI 是【替换】输入框中那一段，不是往后追加。
        """
        self.set_status("正在听（流式，边说边出字）…")
        self.recording = True
        self.btn_mic.configure(fg=C["rec"], text="■ 听着…")
        self.lbl_rec.configure(text="说完会自动断句")
        # ★ 记下"流式开始前输入框里已有什么" —— 中间结果要拼在它后面
        try:
            self._stream_base = self.txt.get("1.0", "end-1c")
        except Exception:
            self._stream_base = ""

        def on_part(t):
            self.q.put(("pc_part", t))

        def on_final(t, c):
            self.q.put(("pc_asr", {"text": t, "error": None, "conf": c}))

        def done(t, e):
            # 只处理"没走到 on_final"的情况（比如超时/出错）
            if e:
                self.q.put(("pc_asr", {"text": None, "error": e}))

        PC_SR.listen_stream_async(on_part=on_part, on_final=on_final,
                                  done=done, init_secs=6, total_secs=15)

    def _show_pc_part(self, t):
        """★ 主线程：把流式的【中间结果】刷进输入框（替换，不追加）"""
        try:
            base = getattr(self, "_stream_base", "")
            self.txt.delete("1.0", "end")
            self.txt.insert("1.0", (base + t) if base else t)
            self.txt.see("end")
            self.set_status("听到：%s（还在识别…）" % t)
        except Exception:
            pass

    def _show_pc_asr(self, p):
        """主线程：PC 识别【最终】结果"""
        self.recording = False
        self.btn_mic.configure(fg=C["text"], text="🎤 说一句")
        self.lbl_rec.configure(text="")
        err = p.get("error")
        txt = (p.get("text") or "").strip()
        if err or not txt:
            self.set_status("没听清：%s" % (err or "空结果"))
            # ★ 流式失败时把中间结果留在输入框里，别让用户白说
            if getattr(self, "_stream_base", "") != self.txt.get("1.0", "end-1c"):
                self.set_status("没听清，但输入框里留了中间结果，可手动改")
            return
        self.set_status("听到：%s" % txt)
        # 和原来一致：自动发送 或 只填进输入框
        if self.conf.get("voice_auto_send", True):
            # ★ 自动发送时，先把流式中间结果清掉（避免发出去两份）
            self.txt.delete("1.0", "end")
            self.txt.insert("1.0", (getattr(self, "_stream_base", "") or "")
                            + txt)
            self._send_text(((getattr(self, "_stream_base", "") or "")
                             + txt).strip())
        else:
            self.txt.delete("1.0", "end")
            self.txt.insert("1.0", (getattr(self, "_stream_base", "") or "")
                            + txt)

    def start_rec(self):
        try:
            self.rec.start()
        except Exception as e:
            messagebox.showerror("录音失败", str(e))
            return
        self.recording = True
        self.btn_mic.configure(fg=C["rec"], text="■ 停止录音")
        self._tick_rec()

    def _tick_rec(self):
        if not self.recording:
            return
        s = self.rec.elapsed()
        lv = self.rec.level()
        bar = "▮" * int(lv * 10)
        self.lbl_rec.configure(text="录音中 %.1fs  %s" % (s, bar))
        # ★ 60 秒自动停（免得忘了）
        if s >= 60:
            self.stop_rec()
            return
        self.root.after(120, self._tick_rec)

    def stop_rec(self):
        self.recording = False
        self.btn_mic.configure(fg=C["text"], text="🎤 说一句")
        self.lbl_rec.configure(text="")
        try:
            path, secs = self.rec.stop()
        except Exception as e:
            messagebox.showerror("录音失败", str(e))
            return
        if not path or secs < 0.4:
            self.set_status("录得太短，重来")
            return
        self.set_status("识别中…（%.1fs 录音）" % secs)
        self.lbl_rec.configure(text="识别中…")

        def work():
            try:
                b64 = A.wav_to_b64(path)
                r = self.brd.call("/asr", "POST",
                                  {"audio": b64, "rate": A.TARGET_RATE},
                                  timeout=120)
                if r.get("ok") and r.get("text"):
                    txt = r["text"].strip()
                    self.q.put(("status", "听到：%s" % txt))
                    if self.conf.get("voice_auto_send", True):
                        self.q.put(("sendtext", txt))
                    else:
                        self.q.put(("filltext", txt))
                else:
                    self.q.put(("status", "没听清（%s）"
                                % (r.get("error") or "空结果")))
            except Exception as e:
                self.q.put(("status", "识别失败：%s" % e))
            finally:
                self.q.put(("rec_done", True))
        threading.Thread(target=work, daemon=True).start()

    def speak(self, text):
        """让【板子的喇叭】说（演示时更有说服力）"""
        if not text:
            return

        def work():
            try:
                self.brd.call("/say", "POST", {"text": text[:400]}, timeout=90)
            except Exception:
                pass
        threading.Thread(target=work, daemon=True).start()

    # ---------- 设置 ----------
    def open_settings(self):
        SettingsDialog(self)

    def on_close(self):
        try:
            if self.recording:
                self.rec.cancel()
        except Exception:
            pass
        self.root.destroy()


# ══════════════════════════════════════════════════════════════════
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="")
    ap.add_argument("--token", default="")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        return selftest()

    root = tk.Tk()
    app = ChatApp(root, a.host, a.token)
    app._sync_spk()
    root.mainloop()
    return 0


def selftest():
    """不带界面，跑一遍逻辑"""
    print("=" * 70)
    print(" 聊天客户端 · 逻辑自测")
    print("=" * 70)
    ok = True

    def chk(c, m, d=""):
        nonlocal ok
        print("   %s %s%s" % ("✓" if c else "✗", m, ("   " + d) if d else ""))
        ok = ok and c

    print()
    print("【1】依赖")
    chk(A.HAS_SD, "录音后端 sounddevice 可用",
        "" if A.HAS_SD else A.SD_WHY)
    try:
        import winsound  # noqa: F401
        chk(True, "放音 winsound 可用")
    except Exception as e:
        chk(False, "winsound", str(e))

    print()
    print("【2】会话存储")
    import tempfile
    d = tempfile.mkdtemp(prefix="xbchat_")
    st = SessionStore(d)
    chk(len(st.sessions) == 1, "初始有一个空会话")
    st.cur.add("user", "现在多少度")
    chk(st.cur.title == "现在多少度", "标题自动取第一条用户消息",
        st.cur.title)
    st.new()
    chk(len(st.sessions) == 2, "能新建会话")
    chk(len(st.group()) >= 1, "能分组")
    st.delete(st.cur)
    chk(len(st.sessions) == 1, "能删除会话")

    print()
    print("【3】配置读写")
    c = load_conf()
    chk(isinstance(c, dict), "load_conf 返回 dict")
    chk("voice_reply" in c, "含语音开关")

    print()
    print("【4】录音器接口")
    r = A.Recorder()
    chk(not r.active, "初始未录音")
    chk(hasattr(r, "level"), "有 level()（画音量条用）")

    print()
    print("=" * 70)
    print(" 总体: %s" % ("★ 全部通过" if ok else "★ 有问题"))
    print("=" * 70)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main() or 0)
