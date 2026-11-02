#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""xb_client.py —— 系统管家小白 · 云协同客户端（原生 Windows 程序）

════════════════════════════════════════════════════════════════════
★ 为什么是 tkinter 而不是 HTML
════════════════════════════════════════════════════════════════════
我第一版把界面写成 HTML，然后说"用 pywebview 包一层就是 exe"。
那是错的交付 —— HTML 就是网页，用户要的是能双击运行的 exe。

现在这一版：
    · 纯 tkinter（Python 自带，零第三方依赖）
    · 原生 Windows 窗口、原生控件、原生菜单
    · ★ 没有 HTML、没有浏览器、没有本地 web 服务
    · 用 PyInstaller 打成单个 .exe

════════════════════════════════════════════════════════════════════
功能（对着《10_云协同接口约定单.md》）
════════════════════════════════════════════════════════════════════
    ① 设备信息   主机名/IP/温度/服务/bitstream
    ② 文件传输   上传（分块+md5+进度条）、下载、删除、列目录
    ③ 硬件       读寄存器、启停服务、看日志
    ④ 变更历史   列表 + 一键回滚
    ⑤ 对话       多轮对话
    ⑥ 工具       28 个工具列表 + 直接调用

用法:
    python xb_client.py                   # 直接跑
    python xb_client.py --host 192.168.110.144 --token xxxx
"""
import argparse
import base64
import hashlib
import json
import os
import re               # ★ 解析 ipconfig 用
import socket
import subprocess       # ★ 调 ipconfig / hostname 用
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

try:
    import urllib.request
    import urllib.error
    import urllib.parse
except Exception:
    pass

# ★ 让中文字体正常显示
APP_TITLE = "系统管家小白 · 云协同"
DEFAULT_PORT = 8768
DISCOVER_PORT = 8769
DISCOVER_MSG = b"XIAOBAI_DISCOVER"

CONF = os.path.join(os.path.expanduser("~"), ".xiaobai_client.json")


def load_conf():
    try:
        # ★ 用 utf-8-sig：吃掉落 BOM。
        #   踩过：配置带 BOM 时 json.load 抛错，被吞掉后返回 {}，
        #   表现就是"地址明明填了却显示未连接"，非常难查。
        #   （Windows 记事本"另存为 UTF-8"就会带 BOM）
        with open(CONF, encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return {}


def save_conf(host, token):
    try:
        with open(CONF, "w", encoding="utf-8") as f:
            json.dump({"host": host, "token": token}, f, ensure_ascii=False)
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════
#  和板子通信
# ══════════════════════════════════════════════════════════════════
class Board(object):
    def __init__(self, host="", token=""):
        self.host = host
        self.token = token

    def set(self, host, token):
        self.host = host.strip().replace("http://", "").replace("https://", "")
        self.host = self.host.rstrip("/")
        self.token = token.strip()

    def _url(self, path):
        h = self.host
        if ":" not in h.split("/")[0]:
            h = "%s:%d" % (h, DEFAULT_PORT)
        sep = "&" if "?" in path else "?"
        return "http://%s%s%s%s" % (h, path, sep,
                                    urllib.parse.urlencode({"token": self.token}))

    def call(self, path, method="GET", body=None, timeout=20):
        """★ 永远返回 dict（连不上也包成 ok=False）"""
        if not self.host:
            return {"ok": False, "error": "还没填板子地址"}
        data = json.dumps(body).encode() if body is not None else None
        h = {"Authorization": "Bearer " + self.token}
        if data:
            h["Content-Type"] = "application/json"
        req = urllib.request.Request(self._url(path), data=data,
                                     headers=h, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                b = r.read()
            d = json.loads(b.decode("utf-8", "replace"))
            return d if isinstance(d, dict) else {"ok": True, "result": d}
        except urllib.error.HTTPError as e:
            try:
                return json.loads(e.read().decode("utf-8", "replace"))
            except Exception:
                return {"ok": False, "error": "HTTP %d" % e.code}
        except Exception as e:
            return {"ok": False, "error": "%s: %s" % (type(e).__name__, e)}

    def raw(self, path, timeout=60):
        """下载文件用（拿二进制）"""
        req = urllib.request.Request(
            self._url(path), headers={"Authorization": "Bearer " + self.token})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()


def local_ipv4_addrs():
    """枚举本机 IPv4 地址 —— ★ 多种方法兜底

    ══════════════════════════════════════════════════════════════
    ★★★ 为什么要写这么啰嗦（踩过的坑，2026-10-02）★★★
    ══════════════════════════════════════════════════════════════
    原来的代码是：
        socket.gethostbyname_ex(socket.gethostname())[2]
    然后取前三段拼 ".255" 当广播地址。

    实测：这台机器上它【拿不到 192.168.110.21】——
    返回的要么是 127.0.0.1，要么是虚拟网卡的地址。
    ⇒ 于是 targets 里只剩 "255.255.255.255"，
      而 Windows 上【受限广播】走"默认路由接口"——
      这台机器有 192.168.56.1（虚拟网卡），广播就从错的网卡出去了，
      板子根本收不到。

    实测三种发法（板子 192.168.110.144）：
        ✗ 255.255.255.255      → 超时
        ✓ 192.168.110.255      → 收到（子网定向广播）
        ✓ 192.168.110.144 单播 → 收到

    ⇒ 所以必须拿到【真实的网段】，用定向广播。
      下面几种方法都用上，哪个成算哪个。
    """
    out = []

    def add(ip):
        if ip and ip not in out and not ip.startswith("127."):
            out.append(ip)

    # ① ★ 最可靠：UDP connect 技巧（不真的发包，只让内核选路由）
    #    内核会把源地址填成"默认路由那张网卡"的地址
    for probe in ("8.8.8.8", "223.5.5.5", "1.1.1.1", "114.114.114.114"):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0.3)
            s.connect((probe, 80))
            add(s.getsockname()[0])
            s.close()
        except Exception:
            pass

    # ② 主机名解析（原来那条路，留着兜底）
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            add(ip)
    except Exception:
        pass

    # ③ ★ Windows 上解析 ipconfig —— 能把所有网卡（含 WiFi）都列出来
    if os.name == "nt":
        try:
            # ★★ 中文 Windows 的 ipconfig 输出是 GBK（cp936），
            #    用默认的 utf-8 解码会抛 UnicodeDecodeError ——
            #    而且那个异常发生在 subprocess 的【读线程】里，
            #    不会被这里的 except 接住，会在控制台刷一堆栈。
            #    所以显式指定 gbk + errors="replace"。
            r = subprocess.run(["ipconfig"], capture_output=True,
                               encoding="gbk", errors="replace",
                               timeout=6,
                               creationflags=getattr(subprocess,
                                                     "CREATE_NO_WINDOW", 0))
            for m in re.finditer(r"(?:IPv4[^\d]*|IP Address[^\d]*)"
                                 r"(\d+\.\d+\.\d+\.\d+)", r.stdout or ""):
                add(m.group(1))
        except Exception:
            pass

    # ④ Linux/Mac 兜底
    if os.name != "nt":
        try:
            r = subprocess.run(["hostname", "-I"], capture_output=True,
                               encoding="utf-8", errors="replace", timeout=4)
            for ip in (r.stdout or "").split():
                add(ip)
        except Exception:
            pass

    return out


def broadcast_targets():
    """算出发发现包该往哪些地址发（顺序 = 优先级）"""
    targets = []
    for ip in local_ipv4_addrs():
        p = ip.split(".")
        if len(p) == 4 and not ip.startswith("169.254."):
            t = ".".join(p[:3]) + ".255"
            if t not in targets:
                targets.append(t)
    # 常见内网段兜底（板子可能在别的网段）
    for c in ("192.168.110", "192.168.1", "192.168.0", "192.168.4",
              "192.168.31", "10.0.0", "172.16.0"):
        t = c + ".255"
        if t not in targets:
            targets.append(t)
    # ★ 受限广播放最后 —— 它在 Windows 上不可靠（会走错网卡），但万一能通
    targets.append("255.255.255.255")
    return targets


def subnet_sweep(timeout=2.5):
    """★★★ 本网段逐 IP 单播扫描（2026-10-03 加）

    为什么需要它
    ────────────────────────────────────────────────────────────
    用户反馈："云端连接还有问题" —— 其实是**扫不到板子**。

    check_cloud_from_pc.py 实测结果：
        ① UDP 广播（255.255.255.255 / x.x.x.255）  -> ✗ 超时
        ② UDP 单播（直接发 192.168.110.144）        -> ✓ 立刻收到

    ⇒ 板子在听，是【路由器/AP 不透传 UDP 广播】（很常见，尤其手机
      热点和企业 AP）。而 discover() 原来只发广播 + 上次连过的 IP，
      所以【第一次使用】（extra_ips 为空）必然扫不到板子。

    做法
    ────────────────────────────────────────────────────────────
    把本机所在网段的 .1 ~ .254 全部单播问一遍。
    254 个 UDP 包在局域网里发完 < 1 秒，代价极小，
    但换来"第一次用也能扫到"，不用让用户去路由器上开广播转发。

    返回: [(ip, info_dict), ...]（按响应先到先得）
    """
    hits = {}
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.25)
        s.bind(("", 0))

        # 本机所有非 169.254 的 IPv4 -> 取 /24 前缀
        prefixes = []
        for ip in local_ipv4_addrs():
            if ip.startswith("169.254."):
                continue
            p = ip.split(".")
            if len(p) == 4:
                pre = ".".join(p[:3])
                if pre not in prefixes:
                    prefixes.append(pre)
        # 兜底：板子常见网段（万一本机读不到 IP）
        for pre in ("192.168.110", "192.168.1", "192.168.0", "192.168.4"):
            if pre not in prefixes:
                prefixes.append(pre)

        # ★ 逐个单播发出去（不等回复，先全部发完再收）
        for pre in prefixes:
            for host in range(1, 255):
                try:
                    s.sendto(DISCOVER_MSG, ("%s.%d" % (pre, host),
                                            DISCOVER_PORT))
                except Exception:
                    pass

        # 收回复
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                data, addr = s.recvfrom(4096)
                j = json.loads(data.decode("utf-8", "replace"))
                j["ip"] = addr[0]
                hits[addr[0]] = j
            except socket.timeout:
                break
            except Exception:
                pass
        s.close()
    except Exception:
        pass
    return list(hits.values())


def discover(timeout=2.5, extra_ips=(), sweep=True):
    """UDP 找板子 —— ★ 这是原生程序能做到、网页做不到的事

    ★ 修过的点（2026-10-02）：
      原来只发 255.255.255.255，Windows 上会从错误的网卡出去，
      所以"扫不到板子"。现在改成【子网定向广播优先】+ 常见网段兜底
      + 支持记住上次成功的 IP（extra_ips，直接单播问）。

    ★ 修过的点（2026-10-03）：
      广播这条路在**不透传广播的路由器/AP** 上完全走不通
      （用户实测：广播超时，单播秒回）。
      ⇒ 加了 subnet_sweep()：本网段 .1~.254 逐个单播问一遍。
        这样"第一次用、又碰上挡广播的路由器"也能扫到板子。

    extra_ips: 额外要试的地址（比如上次连上的板子 IP）
    sweep:     广播没结果时，要不要再做一次全网段单播扫描
    """
    hits = {}
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.settimeout(0.4)
        s.bind(("", 0))

        targets = broadcast_targets()
        # ★ 上次连上的 IP 直接单播 —— 最快最可靠
        for ip in (extra_ips or ()):
            if ip and ip not in targets:
                targets.insert(0, ip)

        t0 = time.time()
        sent = set()
        while time.time() - t0 < timeout:
            for t in targets:
                # 前 60% 时间每个目标只发一次；快超时了再补一轮
                if t in sent and time.time() - t0 < timeout * 0.6:
                    continue
                try:
                    s.sendto(DISCOVER_MSG, (t, DISCOVER_PORT))
                    sent.add(t)
                except Exception:
                    pass
            try:
                data, addr = s.recvfrom(4096)
                j = json.loads(data.decode("utf-8", "replace"))
                j["ip"] = addr[0]
                hits[addr[0]] = j
            except socket.timeout:
                pass
            except Exception:
                pass
            time.sleep(0.1)
        s.close()
    except Exception:
        pass

    # ★ 广播一条都没回 -> 大概率是路由器挡了广播，走单播兜底
    if not hits and sweep:
        for j in subnet_sweep(2.5):
            hits[j["ip"]] = j

    return list(hits.values())


# ══════════════════════════════════════════════════════════════════
#  主窗口
# ══════════════════════════════════════════════════════════════════
class App(object):
    def __init__(self, root, host="", token=""):
        self.root = root
        self.brd = Board(host, token)
        self.info = None
        self.fs_path = tk.StringVar(value="/home/zynq/Music")
        self.status = tk.StringVar(value="就绪")

        root.title(APP_TITLE)
        root.geometry("980x660")
        root.minsize(760, 520)

        self._build_menu()
        self._build_top()
        self._build_tabs()
        self._build_status()

        if self.brd.host:
            self.refresh_info()

from tkinter import font as tkfont   # noqa: E402


def _charset_ok(root):
    """让中文字体别变成方块"""
    try:
        for name in ("Microsoft YaHei UI", "Microsoft YaHei", "SimHei"):
            f = tkfont.nametofont("TkDefaultFont")
            f.configure(family=name, size=10)
            for k in ("TkTextFont", "TkMenuFont", "TkHeadingFont"):
                try:
                    tkfont.nametofont(k).configure(family=name)
                except Exception:
                    pass
            break
    except Exception:
        pass


# ---- 把方法挂到 App 上（写成函数太长，分块加更清楚）----
def _build_menu(self):
    m = tk.Menu(self.root)
    fm = tk.Menu(m, tearoff=0)
    fm.add_command(label="连接设置…", command=self.dlg_connect)
    fm.add_separator()
    fm.add_command(label="退出", command=self.root.quit)
    m.add_cascade(label="文件", menu=fm)

    hm = tk.Menu(m, tearoff=0)
    hm.add_command(label="扫描局域网（UDP）", command=self.do_discover)
    hm.add_command(label="刷新设备信息", command=self.refresh_info)
    m.add_cascade(label="板子", menu=hm)

    am = tk.Menu(m, tearoff=0)
    am.add_command(label="关于", command=lambda: messagebox.showinfo(
        "关于", "系统管家小白 · 云协同客户端\n\n"
                "Zynq-7020 板载自主助手\n"
                "纯 tkinter 原生程序，无网页、无浏览器"))
    m.add_cascade(label="帮助", menu=am)
    self.root.config(menu=m)


def _build_top(self):
    top = ttk.Frame(self.root, padding=(10, 8))
    top.pack(fill="x")
    self.lbl_dot = tk.Label(top, text="●", fg="#999", font=("", 14))
    self.lbl_dot.pack(side="left")
    self.lbl_name = ttk.Label(top, text="未连接", font=("", 11, "bold"))
    self.lbl_name.pack(side="left", padx=(4, 14))
    self.lbl_meta = ttk.Label(top, text="", foreground="#555")
    self.lbl_meta.pack(side="left")
    ttk.Button(top, text="连接设置", command=self.dlg_connect).pack(side="right")
    ttk.Button(top, text="刷新", command=self.refresh_info).pack(
        side="right", padx=6)


def _build_tabs(self):
    nb = ttk.Notebook(self.root)
    nb.pack(fill="both", expand=True, padx=10, pady=(0, 6))
    self.nb = nb

    # ① 设备信息
    t1 = ttk.Frame(nb)
    nb.add(t1, text=" 设备信息 ")
    self.txt_info = scrolledtext.ScrolledText(t1, wrap="word",
                                              font=("Consolas", 10))
    self.txt_info.pack(fill="both", expand=True, padx=6, pady=6)
    self.txt_info.configure(state="disabled")

    # ② 文件传输
    t2 = ttk.Frame(nb)
    nb.add(t2, text=" 文件传输 ")
    bar = ttk.Frame(t2)
    bar.pack(fill="x", padx=6, pady=6)
    ttk.Label(bar, text="路径").pack(side="left")
    e = ttk.Entry(bar, textvariable=self.fs_path)
    e.pack(side="left", fill="x", expand=True, padx=6)
    e.bind("<Return>", lambda _: self.fs_list())
    ttk.Button(bar, text="打开", command=self.fs_list).pack(side="left")
    ttk.Button(bar, text="上一层", command=self.fs_up).pack(side="left", padx=4)
    bar2 = ttk.Frame(t2)
    bar2.pack(fill="x", padx=6)
    ttk.Button(bar2, text="上传到当前目录…", command=self.fs_upload).pack(
        side="left")
    ttk.Label(bar2, text="").pack(side="left", fill="x", expand=True)
    self.pb = ttk.Progressbar(bar2, mode="determinate", length=220)
    self.pb.pack(side="right")
    cols = ("name", "type", "size", "time")
    self.tree_fs = ttk.Treeview(t2, columns=cols, show="headings")
    for c, w, t in (("name", 340, "名称"), ("type", 70, "类型"),
                    ("size", 100, "大小"), ("time", 150, "修改时间")):
        self.tree_fs.heading(c, text=t)
        self.tree_fs.column(c, width=w, anchor="w")
    self.tree_fs.pack(fill="both", expand=True, padx=6, pady=6)
    self.tree_fs.bind("<Double-1>", self._fs_dbl)
    mb = ttk.Frame(t2)
    mb.pack(fill="x", padx=6, pady=(0, 6))
    ttk.Button(mb, text="下载选中", command=self.fs_download).pack(side="left")
    ttk.Button(mb, text="删除选中", command=self.fs_delete).pack(
        side="left", padx=6)

    # ③ 硬件
    t3 = ttk.Frame(nb)
    nb.add(t3, text=" 硬件 ")
    r1 = ttk.Frame(t3)
    r1.pack(fill="x", padx=6, pady=6)
    ttk.Button(r1, text="读所有 IP 的 VERSION",
               command=self.hw_read_all).pack(side="left")
    self.txt_hw = scrolledtext.ScrolledText(t3, height=10, wrap="word",
                                            font=("Consolas", 10))
    self.txt_hw.pack(fill="both", expand=True, padx=6)
    r2 = ttk.LabelFrame(t3, text="读/写单个寄存器")
    r2.pack(fill="x", padx=6, pady=6)
    self.cb_base = ttk.Combobox(r2, values=[
        "scope_0", "gpu_0", "cnn_conv_pool", "cnn_fc", "audio_fmt",
        "i2s_rx", "i2s_tx", "lcd_id", "pwm_backlight", "axi_gpio"],
        width=18, state="readonly")
    self.cb_base.current(0)
    self.cb_base.pack(side="left", padx=4)
    self.e_off = ttk.Entry(r2, width=10)
    self.e_off.insert(0, "0x34")
    self.e_off.pack(side="left")
    ttk.Button(r2, text="读", command=self.hw_read_one).pack(side="left", padx=4)
    self.e_val = ttk.Entry(r2, width=12)
    self.e_val.pack(side="left", padx=(14, 4))
    ttk.Button(r2, text="写", command=self.hw_write).pack(side="left")
    r3 = ttk.LabelFrame(t3, text="服务")
    r3.pack(fill="x", padx=6, pady=(0, 6))
    self.svc_frame = r3

    # ④ 变更历史
    t4 = ttk.Frame(nb)
    nb.add(t4, text=" 变更历史 ")
    r4 = ttk.Frame(t4)
    r4.pack(fill="x", padx=6, pady=6)
    ttk.Button(r4, text="刷新", command=self.chg_load).pack(side="left")
    for txt, k in (("全部", None), ("HDL", "hdl"), ("构建", "build"),
                   ("刷流", "bitstream"), ("回滚", "rollback")):
        ttk.Button(r4, text=txt,
                   command=lambda kk=k: self.chg_load(kk)).pack(
            side="left", padx=2)
    cols4 = ("ts", "kind", "detail", "result", "rb")
    self.tree_chg = ttk.Treeview(t4, columns=cols4, show="headings")
    for c, w, t in (("ts", 130, "时间"), ("kind", 70, "类型"),
                    ("detail", 400, "做了什么"), ("result", 180, "结果"),
                    ("rb", 70, "可回滚")):
        self.tree_chg.heading(c, text=t)
        self.tree_chg.column(c, width=w, anchor="w")
    self.tree_chg.pack(fill="both", expand=True, padx=6)
    r5 = ttk.Frame(t4)
    r5.pack(fill="x", padx=6, pady=6)
    ttk.Button(r5, text="回滚选中", command=self.chg_rollback).pack(side="left")
    ttk.Label(r5, text="★ 只对「可回滚=是」的记录有效").pack(
        side="left", padx=10)

    # ⑤ 对话
    t5 = ttk.Frame(nb)
    nb.add(t5, text=" 对话 ")
    self.txt_chat = scrolledtext.ScrolledText(t5, wrap="word",
                                              font=("Microsoft YaHei", 10))
    self.txt_chat.pack(fill="both", expand=True, padx=6, pady=6)
    self.txt_chat.configure(state="disabled")
    r6 = ttk.Frame(t5)
    r6.pack(fill="x", padx=6, pady=(0, 8))
    self.e_chat = ttk.Entry(r6)
    self.e_chat.pack(side="left", fill="x", expand=True)
    self.e_chat.bind("<Return>", lambda _: self.chat_send())
    ttk.Button(r6, text="发送", command=self.chat_send).pack(
        side="left", padx=6)

    # ⑥ 工具
    t6 = ttk.Frame(nb)
    nb.add(t6, text=" 工具 ")
    r7 = ttk.Frame(t6)
    r7.pack(fill="x", padx=6, pady=6)
    ttk.Button(r7, text="列出全部工具", command=self.tool_load).pack(side="left")
    ttk.Label(r7, text="过滤").pack(side="left", padx=(14, 4))
    self.e_filter = ttk.Entry(r7, width=22)
    self.e_filter.pack(side="left")
    self.e_filter.bind("<KeyRelease>", lambda _: self.tool_render())
    self.tree_tool = ttk.Treeview(t6, columns=("name", "desc"),
                                  show="headings")
    self.tree_tool.heading("name", text="工具")
    self.tree_tool.column("name", width=230, anchor="w")
    self.tree_tool.heading("desc", text="说明")
    self.tree_tool.column("desc", width=600, anchor="w")
    self.tree_tool.pack(fill="both", expand=True, padx=6)
    self.tree_tool.bind("<Double-1>", lambda _: self.tool_run())
    ttk.Label(t6, text="★ 双击一行调这个工具").pack(anchor="w", padx=8, pady=4)

    self.tools = []
    self.chg_items = []


def _build_status(self):
    bar = ttk.Frame(self.root)
    bar.pack(fill="x", side="bottom")
    ttk.Separator(bar).pack(fill="x")
    ttk.Label(bar, textvariable=self.status, anchor="w").pack(
        fill="x", padx=10, pady=3)


# ────────────── 连接 ──────────────
def dlg_connect(self):
    w = tk.Toplevel(self.root)
    w.title("连接设置")
    w.geometry("420x260")
    w.transient(self.root)
    w.grab_set()
    ttk.Label(w, text="板子地址（IP 或 IP:端口）").pack(anchor="w", padx=14,
                                                pady=(14, 2))
    e_host = ttk.Entry(w, width=40)
    e_host.pack(padx=14, fill="x")
    e_host.insert(0, self.brd.host or "192.168.110.144")
    ttk.Label(w, text="口令（token）").pack(anchor="w", padx=14, pady=(10, 2))
    e_tok = ttk.Entry(w, width=40)
    e_tok.pack(padx=14, fill="x")
    e_tok.insert(0, self.brd.token)

    info = ttk.Label(w, text="", foreground="#666", wraplength=380)
    info.pack(anchor="w", padx=14, pady=8)

    def do_scan():
        info.config(text="正在广播找板子…")
        w.update()

        def work():
            r = discover(2.5)
            def upd():
                if not r:
                    info.config(text="没找到。手动填 IP（手机/PC 要同一个 WiFi）")
                    return
                e_host.delete(0, "end")
                e_host.insert(0, r[0]["ip"])
                info.config(text="找到：%s  %s  %s°C"
                                 % (r[0]["ip"], r[0].get("hostname", ""),
                                    r[0].get("temperature_c", "?")))
            w.after(0, upd)
        threading.Thread(target=work, daemon=True).start()

    def do_ok():
        self.brd.set(e_host.get(), e_tok.get())
        save_conf(self.brd.host, self.brd.token)
        w.destroy()
        self.refresh_info()

    b = ttk.Frame(w)
    b.pack(fill="x", padx=14, pady=10)
    ttk.Button(b, text="扫描局域网", command=do_scan).pack(side="left")
    ttk.Button(b, text="取消", command=w.destroy).pack(side="right")
    ttk.Button(b, text="连接", command=do_ok).pack(side="right", padx=6)


def do_discover(self):
    def work():
        # ★ 2026-10-03：把"上次连上的 IP"也带上 —— 原来这里是 discover(2.5)，
        #   没传 extra_ips，所以每次都是从头广播扫；碰上挡广播的路由器
        #   就永远扫不到（用户反馈"云端连接有问题"就是这个）。
        #   现在：先单播问上次的 IP（最快），再广播，最后全网段兜底。
        old = (self.brd.host or "").strip()
        r = discover(2.5, extra_ips=[old] if old else [])

        def upd():
            if not r:
                messagebox.showinfo("扫描", "没找到板子。\n\n"
                                    "· 板子的 cloud-api 在跑吗？\n"
                                    "· 同一个 WiFi 吗？\n"
                                    "· 也可以直接在地址栏里手动填板子 IP")
                return
            self.brd.set(r[0]["ip"], self.brd.token)
            save_conf(self.brd.host, self.brd.token)
            self.refresh_info()
            messagebox.showinfo("扫描", "找到 %d 个板子，已连第一个：%s"
                                % (len(r), r[0]["ip"]))
        self.root.after(0, upd)
    threading.Thread(target=work, daemon=True).start()


def set_status(self, s):
    self.status.set(s)


def _set_text(widget, s):
    widget.configure(state="normal")
    widget.delete("1.0", "end")
    widget.insert("1.0", s)
    widget.configure(state="disabled")


def refresh_info(self):
    if not self.brd.host:
        self.dlg_connect()
        return

    def work():
        d = self.brd.call("/info", timeout=12)
        def upd():
            if not d.get("ok"):
                self.lbl_dot.config(fg="#d33")
                self.lbl_name.config(text="连不上")
                self.lbl_meta.config(text=str(d.get("error", ""))[:60])
                _set_text(self.txt_info, "连不上板子：\n%s\n\n"
                          "点「文件 → 连接设置」，或「板子 → 扫描局域网」。"
                          % d.get("error", ""))
                return
            self.info = d
            self.lbl_dot.config(fg="#2a2")
            self.lbl_name.config(text=d.get("name", "板子"))
            self.lbl_meta.config(
                text="%s   %s°C   %s" % (d.get("ip", ""),
                                         d.get("temperature_c", "?"),
                                         d.get("thermal_level", "")))
            svc = d.get("services") or {}
            b = d.get("bitstream") or {}
            lines = [
                "主机名      %s" % d.get("hostname"),
                "IP          %s" % d.get("ip"),
                "MAC         %s" % d.get("mac"),
                "型号        %s" % d.get("model"),
                "内核        %s" % d.get("kernel"),
                "已运行      %s" % d.get("uptime_human"),
                "",
                "温度        %s °C   等级 %s" % (d.get("temperature_c"),
                                              d.get("thermal_level")),
                "工具数      %s" % d.get("tools_count"),
                "静音锁      %s" % ("已锁" if d.get("silent_locked") else "未锁"),
                "",
                "--- 服务 ---",
            ]
            for k, v in svc.items():
                lines.append("  %-18s %s" % (k, v))
            lines += [
                "",
                "--- bitstream ---",
                "  文件      %s" % b.get("file", "—"),
                "  大小      %s 字节" % b.get("size", "—"),
                "  md5       %s" % b.get("md5", "—"),
                "  时间      %s" % b.get("mtime", "—"),
            ]
            _set_text(self.txt_info, "\n".join(lines))
            self.set_status("已连接 %s" % d.get("ip"))
        self.root.after(0, upd)
    threading.Thread(target=work, daemon=True).start()


# ────────────── 文件 ──────────────
def fs_list(self):
    p = self.fs_path.get().strip() or "/home/zynq"

    def work():
        d = self.brd.call("/fs/list?path=" + urllib.parse.quote(p))
        def upd():
            if not d.get("ok"):
                self.set_status("列目录失败：" + str(d.get("error"))[:80])
                return
            self.fs_path.set(d.get("path", p))
            self.tree_fs.delete(*self.tree_fs.get_children())
            for it in d.get("items", []):
                sz = "" if it["type"] == "dir" else _fmt_size(it["size"])
                self.tree_fs.insert("", "end", values=(
                    it["name"], "目录" if it["type"] == "dir" else "文件",
                    sz, it.get("mtime", "")))
            self.set_status("%s  共 %d 项  剩余 %s"
                            % (d.get("path"), len(d.get("items", [])),
                               _fmt_size(d.get("free_bytes"))))
        self.root.after(0, upd)
    threading.Thread(target=work, daemon=True).start()


def fs_up(self):
    p = self.fs_path.get().rstrip("/")
    i = p.rfind("/")
    self.fs_path.set(p[:i] if i > 0 else "/")
    self.fs_list()


def _fs_sel(self):
    s = self.tree_fs.selection()
    if not s:
        return None, None
    v = self.tree_fs.item(s[0], "values")
    return v[0], v[1]


def _fs_dbl(self, ev):
    name, typ = self._fs_sel()
    if name and typ == "目录":
        self.fs_path.set(self.fs_path.get().rstrip("/") + "/" + name)
        self.fs_list()


def fs_download(self):
    name, typ = self._fs_sel()
    if not name or typ != "文件":
        self.set_status("先选一个文件")
        return
    dst = filedialog.asksaveasfilename(initialfile=name)
    if not dst:
        return
    p = self.fs_path.get().rstrip("/") + "/" + name

    def work():
        try:
            b = self.brd.raw("/fs/download?path=" + urllib.parse.quote(p))
            with open(dst, "wb") as f:
                f.write(b)
            self.root.after(0, lambda: self.set_status(
                "下载完成：%s（%s）" % (dst, _fmt_size(len(b)))))
        except Exception as e:
            self.root.after(0, lambda: self.set_status("下载失败：%s" % e))
    self.set_status("正在下载 %s …" % name)
    threading.Thread(target=work, daemon=True).start()


def fs_delete(self):
    name, typ = self._fs_sel()
    if not name:
        return
    if not messagebox.askyesno("删除", "确定删除？\n%s" % name):
        return
    p = self.fs_path.get().rstrip("/") + "/" + name

    def work():
        d = self.brd.call("/fs/delete", "POST", {"path": p})
        self.root.after(0, lambda: (
            self.set_status("已删除" if d.get("ok")
                            else "删除失败：" + str(d.get("error"))[:70]),
            self.fs_list()))
    threading.Thread(target=work, daemon=True).start()


def fs_upload(self):
    fp = filedialog.askopenfilename()
    if not fp:
        return
    name = os.path.basename(fp)
    size = os.path.getsize(fp)
    target = self.fs_path.get().rstrip("/") + "/" + name
    if not messagebox.askyesno("上传", "上传 %s（%s）到\n%s ？"
                               % (name, _fmt_size(size), self.fs_path.get())):
        return

    def work():
        try:
            h = hashlib.md5()
            with open(fp, "rb") as f:
                for c in iter(lambda: f.read(1 << 20), b""):
                    h.update(c)
            md5 = h.hexdigest()
            self.root.after(0, lambda: self.set_status("正在开始上传…"))
            b = self.brd.call("/fs/upload/begin", "POST",
                              {"path": target, "size": size, "md5": md5})
            if not b.get("ok"):
                self.root.after(0, lambda: self.set_status(
                    "开始上传失败：" + str(b.get("error"))[:70]))
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
                        timeout=120)
                    if not r.get("ok"):
                        self.root.after(0, lambda: self.set_status(
                            "传到一半失败：" + str(r.get("error"))[:70]))
                        return
                    off += len(piece)
                    pct = int(off * 100 / size)
                    self.root.after(0, lambda p=pct: (
                        self.pb.configure(value=p),
                        self.set_status("上传 %d%%（%s / %s）"
                                        % (p, _fmt_size(off),
                                           _fmt_size(size)))))
            e = self.brd.call("/fs/upload/end", "POST",
                              {"upload_id": uid}, timeout=120)
            self.root.after(0, lambda: (
                self.pb.configure(value=100 if e.get("ok") else 0),
                self.set_status("上传完成，md5 校验通过" if e.get("ok")
                                else "校验失败：" + str(e.get("error"))[:60]),
                self.fs_list()))
        except Exception as ex:
            self.root.after(0, lambda: self.set_status("上传出错：%s" % ex))
    threading.Thread(target=work, daemon=True).start()


def _fmt_size(n):
    if n is None:
        return "—"
    try:
        n = float(n)
    except Exception:
        return str(n)
    for u, d in (("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10)):
        if n >= d:
            return "%.1f %s" % (n / d, u)
    return "%d B" % int(n)


# ────────────── 硬件 ──────────────
PL_ALL = ["lcd_id", "axi_gpio", "gpu_0", "scope_0", "cnn_conv_pool",
          "cnn_fc", "audio_fmt", "i2s_rx", "i2s_tx", "pwm_backlight"]


def hw_read_all(self):
    self._hw_line("正在读所有 IP 的 VERSION…")

    def work():
        out = ["%-18s %-12s %s" % ("IP", "地址偏移", "值"),
               "-" * 44]
        for p in PL_ALL:
            d = self.brd.call("/hw/regs?base=%s&offset=0x34" % p, timeout=8)
            if d.get("ok") and d.get("regs"):
                out.append("%-18s 0x34         %s"
                           % (p, d["regs"][0]["value"]))
            else:
                out.append("%-18s 0x34         读不到" % p)
        self.root.after(0, lambda: self._hw_line("\n".join(out)))
    threading.Thread(target=work, daemon=True).start()


def _hw_line(self, s):
    self.txt_hw.configure(state="normal")
    self.txt_hw.delete("1.0", "end")
    self.txt_hw.insert("1.0", s)
    self.txt_hw.configure(state="disabled")
    self.set_status(s.split("\n")[0][:80])


def hw_read_one(self):
    b, o = self.cb_base.get(), self.e_off.get().strip() or "0x34"

    def work():
        d = self.brd.call("/hw/regs?base=%s&offset=%s" % (b, o))
        self.root.after(0, lambda: self._hw_line(json.dumps(
            d, ensure_ascii=False, indent=1)))
    threading.Thread(target=work, daemon=True).start()


def hw_write(self):
    b, o, v = self.cb_base.get(), self.e_off.get().strip(), self.e_val.get().strip()
    if not v:
        self.set_status("要先填要写的值")
        return
    if not messagebox.askyesno("写寄存器",
                               "确定要写？\n\n%s + %s = %s\n\n"
                               "★ 写错可能让硬件不工作" % (b, o, v)):
        return

    def work():
        d = self.brd.call("/hw/reg", "POST",
                          {"base": b, "offset": o, "value": v})
        self.root.after(0, lambda: self._hw_line(json.dumps(
            d, ensure_ascii=False, indent=1)))
    threading.Thread(target=work, daemon=True).start()


def hw_load_svc(self):
    for w in self.svc_frame.winfo_children():
        w.destroy()

    def work():
        d = self.brd.call("/hw/services")
        def upd():
            if not d.get("ok"):
                ttk.Label(self.svc_frame, text="读不到").pack(anchor="w", padx=6)
                return
            for k, v in (d.get("services") or {}).items():
                row = ttk.Frame(self.svc_frame)
                row.pack(fill="x", padx=6, pady=1)
                ttk.Label(row, text=k, width=20).pack(side="left")
                ttk.Label(row, text=v,
                          foreground="#2a2" if v == "active" else "#d33",
                          width=10).pack(side="left")
                ttk.Button(row, text="重启",
                           command=lambda kk=k: self.hw_svc(kk, "restart")
                           ).pack(side="left", padx=2)
                if v == "active":
                    ttk.Button(row, text="停",
                               command=lambda kk=k: self.hw_svc(kk, "stop")
                               ).pack(side="left")
                else:
                    ttk.Button(row, text="起",
                               command=lambda kk=k: self.hw_svc(kk, "start")
                               ).pack(side="left")
        self.root.after(0, upd)
    threading.Thread(target=work, daemon=True).start()


def hw_svc(self, name, action):
    if action != "restart" and not messagebox.askyesno(
            "服务", "确定要 %s %s ？" % (action, name)):
        return

    def work():
        d = self.brd.call("/hw/service", "POST",
                          {"name": name, "action": action}, timeout=40)
        self.root.after(0, lambda: (
            self.set_status(("%s %s 成功" % (name, action)) if d.get("ok")
                            else str(d.get("error"))[:80]),
            self.root.after(1200, self.hw_load_svc)))
    threading.Thread(target=work, daemon=True).start()


# ────────────── 变更历史 ──────────────
KIND_CN = {"hdl": "HDL", "bd": "BD", "bitstream": "刷流", "build": "构建",
           "driver": "驱动", "dataset": "数据集", "rollback": "回滚"}


def chg_load(self, filt=None):
    self._chg_filt = filt

    def work():
        d = self.brd.call("/hw/changes?limit=80")
        def upd():
            if not d.get("ok"):
                self.set_status("读变更单失败：" + str(d.get("error"))[:70])
                return
            items = d.get("changes") or []
            if filt:
                items = [x for x in items if x.get("kind") == filt]
            self.chg_items = items
            self.tree_chg.delete(*self.tree_chg.get_children())
            for c in items:
                self.tree_chg.insert("", "end", values=(
                    (c.get("ts") or "")[5:16],
                    KIND_CN.get(c.get("kind"), c.get("kind")),
                    (c.get("detail") or "")[:70],
                    (c.get("result") or "")[:40],
                    "是" if c.get("rollbackable") else "否"))
            n = len([x for x in items if x.get("rollbackable")])
            self.set_status("共 %d 条，其中 %d 条可回滚" % (len(items), n))
        self.root.after(0, upd)
    threading.Thread(target=work, daemon=True).start()


def chg_rollback(self):
    s = self.tree_chg.selection()
    if not s:
        self.set_status("先选一条")
        return
    idx = self.tree_chg.index(s[0])
    c = self.chg_items[idx]
    if not c.get("rollbackable"):
        messagebox.showinfo("回滚", "这条不可回滚。\n\n"
                            "（没有快照，或者备份文件已经不在了）")
        return
    if not messagebox.askyesno("回滚",
                               "确定要回滚这条变更？\n\n%s\n\nid: %s\n\n"
                               "★ 会把相关文件恢复到改动前"
                               % (c.get("detail"), c.get("id"))):
        return

    def work():
        d = self.brd.call("/hw/rollback", "POST", {"id": c["id"]}, timeout=60)
        self.root.after(0, lambda: (
            self.set_status("回滚成功" if d.get("ok")
                            else "回滚失败：" + str(d.get("error"))[:70]),
            self.root.after(800, lambda: self.chg_load(getattr(
                self, "_chg_filt", None)))))
    self.set_status("正在回滚…")
    threading.Thread(target=work, daemon=True).start()


# ────────────── 对话 ──────────────
def chat_put(self, who, text):
    self.txt_chat.configure(state="normal")
    self.txt_chat.insert("end", "%s：\n%s\n\n" % (who, text))
    self.txt_chat.see("end")
    self.txt_chat.configure(state="disabled")


def chat_send(self):
    t = self.e_chat.get().strip()
    if not t:
        return
    self.e_chat.delete(0, "end")
    self.chat_put("我", t)
    self.set_status("小白在想…")

    def work():
        d = self.brd.call("/voice", "POST", {"text": t}, timeout=150)
        self.root.after(0, lambda: (
            self.chat_put("小白", d.get("reply") or d.get("error") or "（无回复）"),
            self.set_status("就绪")))
    threading.Thread(target=work, daemon=True).start()


# ────────────── 工具 ──────────────
def tool_load(self):
    def work():
        d = self.brd.call("/tools")
        def upd():
            if not d.get("ok"):
                self.set_status("读工具失败：" + str(d.get("error"))[:70])
                return
            self.tools = d.get("tools") or []
            self.tool_render()
        self.root.after(0, upd)
    threading.Thread(target=work, daemon=True).start()


def tool_render(self):
    f = self.e_filter.get().lower()
    self.tree_tool.delete(*self.tree_tool.get_children())
    n = 0
    for t in self.tools:
        name = t.get("name", "") if isinstance(t, dict) else str(t)
        desc = t.get("desc", "") if isinstance(t, dict) else ""
        if f and f not in name.lower() and f not in desc.lower():
            continue
        self.tree_tool.insert("", "end", values=(name, desc[:110]))
        n += 1
    self.set_status("显示 %d / %d 个工具" % (n, len(self.tools)))


def tool_run(self):
    s = self.tree_tool.selection()
    if not s:
        return
    name = self.tree_tool.item(s[0], "values")[0]
    d = tk.Toplevel(self.root)
    d.title("调 %s" % name)
    d.geometry("460x300")
    d.transient(self.root)
    ttk.Label(d, text="参数（JSON）").pack(anchor="w", padx=12, pady=(12, 2))
    e = tk.Text(d, height=8, font=("Consolas", 10))
    e.pack(fill="both", expand=True, padx=12)
    e.insert("1.0", "{}")
    out = scrolledtext.ScrolledText(d, height=7, font=("Consolas", 9))
    out.pack(fill="both", expand=True, padx=12, pady=6)
    out.configure(state="disabled")

    def go():
        try:
            args = json.loads(e.get("1.0", "end").strip() or "{}")
        except Exception as ex:
            messagebox.showerror("参数", "JSON 格式不对：%s" % ex)
            return
        out.configure(state="normal")
        out.delete("1.0", "end")
        out.insert("1.0", "执行中…")
        out.configure(state="disabled")

        def work():
            r = self.brd.call("/tool", "POST",
                              {"name": name, "args": args}, timeout=150)
            def upd():
                out.configure(state="normal")
                out.delete("1.0", "end")
                out.insert("1.0", str(r.get("result") or r.get("error")
                                      or json.dumps(r, ensure_ascii=False)))
                out.configure(state="disabled")
            self.root.after(0, upd)
        threading.Thread(target=work, daemon=True).start()

    ttk.Button(d, text="执行", command=go).pack(pady=(0, 12))


# ══════════════════════════════════════════════════════════════════
#  组装
# ══════════════════════════════════════════════════════════════════
for _fn in (_build_menu, _build_top, _build_tabs, _build_status,
            dlg_connect, do_discover, set_status, refresh_info,
            fs_list, fs_up, _fs_sel, _fs_dbl, fs_download, fs_delete,
            fs_upload, hw_read_all, _hw_line, hw_read_one, hw_write,
            hw_load_svc, hw_svc, chg_load, chg_rollback,
            chat_put, chat_send, tool_load, tool_render, tool_run):
    setattr(App, _fn.__name__, _fn)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="")
    ap.add_argument("--token", default="")
    ap.add_argument("--discover", action="store_true",
                    help="命令行扫描一次就退出")
    a = ap.parse_args()

    if a.discover:
        print("正在广播找板子（最多 3 秒）…")
        r = discover(3)
        if not r:
            print("  没找到")
            return 1
        for x in r:
            print("  %s  %s  %s°C  工具 %s"
                  % (x.get("ip"), x.get("hostname"), x.get("temperature_c"),
                     x.get("tools_count")))
        return 0

    c = load_conf()
    host = a.host or c.get("host", "")
    token = a.token or c.get("token", "")

    root = tk.Tk()
    _charset_ok(root)
    app = App(root, host, token)
    # 连上后顺手加载一次服务列表和工具
    def after_start():
        if app.brd.host:
            app.hw_load_svc()
            app.tool_load()
    root.after(1200, after_start)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
