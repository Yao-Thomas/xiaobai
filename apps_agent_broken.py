#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""apps_agent.py —— 系统管家小白（板载 Agent 桌面入口）

* 打字提问 -> 板载 Agent 服务 (127.0.0.1:8765 /voice) -> 回复
* 「朗读」用百度 TTS 合成后交给板载音频服务从喇叭放出来
* 「听」开麦克风录几秒 -> 百度 ASR -> 填进输入框
* 「自检」放音同时录音，验证喇叭和麦克风

★ 所有网络/录音都在后台线程里跑，主循环绝不阻塞 ——
  这是之前"点了没反应"的教训（网络超时把界面卡死）。
"""
import os
import json
import time
import queue
import threading
import urllib.request

from fbui import header, back_hit, btn, hit, MiniKeyboard

AGENT_URL = os.environ.get("AGENT_SVC", "http://127.0.0.1:8765")
AUDIO_URL = os.environ.get("AUDIO_SVC", "http://127.0.0.1:8767")

# ★ 系统级静音锁
#   和 agent/tools.py 里的 SILENT_FLAG 是【同一个路径】——
#   存在时，agent 的工具层会拦住所有发声（speak / say）。
#   界面上的喇叭按钮会同时切【这个文件】和【self.muted】，
#   不然会出现"图标显示有声、但实际不响"的怪现象。
SILENT_FLAG = "/etc/zynq-silent"
# ★ 对话记录落盘（退出 App / 桌面重启都不丢）
SESS_FILE = os.environ.get("AGENT_CHATS", "/home/zynq/.agent_chats.json")

# ══════════════════════════════════════════════════════════════════
#  ★★★ 布局（2026-10-03 重做，对齐 PC 客户端）
# ══════════════════════════════════════════════════════════════════
# 用户的要求是【和 PC 端一样的布局】：
#
#   ┌──────────┬───────────────────────────────────────────────┐
#   │          │ [←] 系统管家小白                    🔊        │ 60
#   │ ＋新对话  ├───────────────────────────────────────────────┤
#   │ ─────    │  消息区（气泡）                                │
#   │ 今天      │                                               │
#   │  现在多少度│                                               │
#   │ 昨天      │                                               │
#   │          │                                               │
#   │          ├───────────────────────────────────────────────┤
#   │          │  > 输入的文字_                                │ 36
#   │          ├───────────────────────────────────────────────┤
#   │          │  [按住说话] [模型▾] [模式▾]          [发送]    │ 34
#   │          ├───────────────────────────────────────────────┤
#   │ ⚙ 设置   │  回车发送 · 点输入框弹键盘                     │
#   └──────────┴───────────────────────────────────────────────┘
#     ↑
#     ★★★ 左侧栏【一直通到屏幕最底】（原来只到 470 就断了，
#         设置悬在半空、底下留一大片空白 —— 用户指出很难看）
#
# 高度账（屏 1024x600）：
#   header      0   ~ 60
#   左侧栏      62  ~ 600   ← 通到底
#   消息区      62  ~ 470
#   输入框      474 ~ 510
#   按钮排      514 ~ 548
#   提示条      552 ~ 574
#   设置按钮    ~558 ~ 594  ← 真正的最底下
#
#   键盘弹出时（覆盖 428~600）：
#     消息区压缩到 62~336，输入框/候选栏上移，
#     设置按钮也上移到 382~416（不然被全屏宽的键盘盖住）

HEADER_H = 60
BODY_Y0 = 62
BODY_Y1 = 470          # 消息区底部（不是左侧栏底部！）

# ★ 左侧「对话记录栏」——通到屏幕最底
SIDE_RECT = [0, BODY_Y0, 168, 600]
SIDE_NEW = [8, BODY_Y0 + 6, 160, BODY_Y0 + 40]      # ＋新对话 按钮
SIDE_LIST_Y = BODY_Y0 + 48                           # 会话列表起始 y
SIDE_ROW_H = 34
# ★★★ 设置按钮放在【左侧栏最底部】= 屏幕真正的左下角
SIDE_SET = [8, 552, 160, 592]
# 键盘弹出时：上移到键盘上方（左侧栏可见区域只剩 62~428）
SIDE_SET_KB = [8, 382, 160, 416]

# 右侧消息区
LOG_RECT = [172, BODY_Y0, 1020, BODY_Y1]

# ══════════════════════════════════════════════════════════════════
#  ★★★ 键盘收起 / 弹出 —— 两套坐标（2026-10-03 修输入 bug）
# ══════════════════════════════════════════════════════════════════
# 用户报的 bug：
#   "有时候在键盘输入，键盘会退掉；有时候没开键盘也会输入"
#
# 根因（两个 bug 一个原因）：
#   键盘的【第 3、4 行】和输入框 IN_RECT 的位置重叠了：
#       键盘: KB_Y=400, 键高30, 间隔4
#         行1 400-430  行2 434-464  行3 468-498  行4 502-532
#       输入框: 474-510              ← ★ 和行3、行4 重叠
#   而 run() 里【先判输入框】再判键盘：
#       ⇒ 点键盘第 3 行 → 被输入框抢走 → kb_open 翻成 False → 键盘消失
#   同时 kb.press() 是纯几何判断，跟 kb_open 无关：
#       ⇒ 键盘没打开时点那块区域，照样输入
#
# 修法：
#   ① 键盘弹出时，输入框【上移】到候选栏上方，两边不再重叠
#   ② 键盘/候选栏只在 kb_open 时参与命中测试
# ══════════════════════════════════════════════════════════════════
# ══════════════════════════════════════════════════════════════════
#  ★★★ 输入框 / 按钮排 —— 只占【右侧】，和消息区对齐
# ══════════════════════════════════════════════════════════════════
# 用户的要求：
#     "你输入文字的那个框能不能不要那么长，你不是左右分开了吗，
#      你就放右边啊"
#
# 原来输入框和按钮排是【横贯全屏】的（10 ~ 1014），
# 从左侧栏底下穿过去，看起来跟"左右分栏"的布局不搭。
#
# ⇒ 现在和消息区用同一套左右边界：
#     消息区 LOG_RECT = [172, 62, 1020, 470]
#     往里收 18px  →  [190, ..., 1002, ...]
#     输入框和按钮排也用 190 ~ 1002
#
# ★ 键盘仍然是全屏宽的（0~1024）—— 键盘本来就该占满底部，
#   而且它盖住的是"两个区"的下方，看起来也自然。
MAIN_X0 = 190          # 右侧区域的左边界（= 172 + 18，和消息区一致）
MAIN_X1 = 1002         # 右侧区域的右边界（= 1020 - 18）

# 键盘收起时
IN_RECT = [MAIN_X0, 474, MAIN_X1, 510]         # 输入框
BAR_RECT = [MAIN_X0, 514, MAIN_X1, 548]        # 按钮排（含模型/模式/发送）
HINT_Y = 560                                    # 底部提示条

# 键盘弹出时（下半屏给键盘，输入框和候选栏往上挪）
#
# ★ 高度账（必须算准，不然最后一行跑出屏幕）：
#   MiniKeyboard 有 4 行字母数字 + 1 行特殊键 = 5 行
#   每行占 (KB_KH + KB_GAP) = 34
#   ⇒ 键盘总高 170px
#   ⇒ KB_TOP 必须 <= 600 - 170 = 430
KB_TOP = 428                            # 键盘顶部
KB_KH = 30
KB_GAP = 4
IN_RECT_KB = [MAIN_X0, 342, MAIN_X1, 378]       # ★ 输入框（键盘弹出时）
CAND_RECT_KB = [MAIN_X0, 384, MAIN_X1, 424]     # 候选栏（紧贴键盘上方）
LOG_RECT_KB = [172, BODY_Y0, 1020, 336]         # 消息区（被键盘压扁）

# ★ 兼容旧名字
BTN_Y = BAR_RECT[1]
BTN_H = BAR_RECT[3] - BAR_RECT[1]
KB_Y = KB_TOP
CAND_RECT = CAND_RECT_KB

# ★★★ 右上角喇叭（用户要求的位置）
SPEAKER_RECT = [932, 6, 1004, 56]


# ══════════════════════════════════════════════════════════════════
#  ★★★ 输入方式（统一输入面板，2026-10-03）
# ══════════════════════════════════════════════════════════════════
# 用户："语音和手写是不是可以一起，毕竟同一套"
#  三种输入方式共用：输入框 self.cur / 提交路径 / 取消语义 / down-up 事件
#  只有"怎么把动作变成文字"不同，所以按 in_mode 分发就行。
IN_KB = "kb"          # 键盘：候选栏 + 软键盘
IN_VOICE = "voice"    # 语音：按住说话 -> 百度 ASR
IN_HAND = "hand"      # 手写：画板 -> 百度手写 OCR
IN_MODES = (IN_KB, IN_VOICE, IN_HAND)
IN_MODE_LABEL = {IN_KB: "键盘", IN_VOICE: "语音", IN_HAND: "手写"}


def rect_in(scr, kb_open):
    """输入框的矩形（随键盘状态变）"""
    return IN_RECT_KB if kb_open else IN_RECT


def cand_rect(kb_open):
    return CAND_RECT_KB if kb_open else [10, 0, 1014, 0]   # 收起时给个空矩形


def log_rect(kb_open):
    return LOG_RECT_KB if kb_open else LOG_RECT


def side_set(kb_open):
    """设置按钮的位置（键盘弹出时上移，免得被键盘盖住）"""
    return SIDE_SET_KB if kb_open else SIDE_SET


def draw_speaker(scr, rect, muted):
    """画喇叭图标（豆包式）

    muted=False → 喇叭 + 两道声波弧线
    muted=True  → 喇叭 + 一道红色斜杠（声波不画）

    ★ 用 PIL 原语手绘（scr.d 就是 ImageDraw）：
        喇叭体 = 矩形（后腔）+ 梯形（喇叭口，用 polygon）
        声波   = 两段 arc
        斜杠   = 一条粗 line
      不用 emoji 是因为板子的中文位图字体里没有 🔊，画出来是方框。
    """
    x0, y0, x1, y1 = rect
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    scr.rrect(rect, 10, fill=(96, 52, 58) if muted else (52, 70, 120))
    col = (255, 160, 160) if muted else (239, 239, 239)

    a = 6
    scr.d.rectangle([cx - 12, cy - a, cx - 5, cy + a], fill=col)
    scr.d.polygon([(cx - 5, cy - a), (cx + 5, cy - 14),
                   (cx + 5, cy + 14), (cx - 5, cy + a)], fill=col)
    if muted:
        scr.d.line([cx - 16, cy + 15, cx + 17, cy - 15],
                   fill=(255, 90, 90), width=4)
    else:
        scr.d.arc([cx + 2, cy - 10, cx + 16, cy + 10], -60, 60,
                  fill=col, width=2)
        scr.d.arc([cx + 6, cy - 16, cx + 26, cy + 16], -55, 55,
                  fill=col, width=2)


def draw_gear(scr, rect, active=False):
    """画设置按钮（左侧栏底部）

    ★★ 用户明确要求：**"设置按钮就叫设置不行吗"**
       —— 原来只有三条滑块的图标，没有文字，认不出来。

    ⇒ 现在照 Harness 的样子：左边一个小齿轮/滑块图标 + 右边「设置」两个字。

    ★ 齿轮不画真齿轮（小尺寸下糊成一团），用「三条滑块」样式，
      清楚也好认，和 Harness 的气质也接近。
    """
    scr.rrect(rect, 8, fill=(40, 90, 150) if active else (41, 41, 41),
              outline=(80, 120, 180) if active else (67, 67, 67))
    x0, y0, x1, y1 = rect
    cy = (y0 + y1) // 2
    col = (241, 241, 241)

    # ── 左边：滑块图标 ──
    ix = x0 + 20
    for i, dy in enumerate((-7, 0, 7)):
        scr.d.line([ix - 11, cy + dy, ix + 11, cy + dy],
                   fill=(110, 130, 165), width=2)
        dx = (-6, 5, -2)[i]
        scr.d.ellipse([ix + dx - 4, cy + dy - 4, ix + dx + 4, cy + dy + 4],
                      fill=col)

    # ── 右边：文字「设置」──
    scr.text((ix + 22, cy), "设置", 17,
             (255, 255, 255) if active else (215, 215, 215),
             anchor="lm", cn=True)


# 常用指令：拼音缓冲为空时显示在候选栏上，点一下就发
QUICK = ["现在几点", "今天天气", "播放音乐", "你好", "介绍一下你自己",
         "停止播放", "看一看时间"]


def _post(url, obj, timeout=180):
    req = urllib.request.Request(
        url, data=json.dumps(obj).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _get(url, timeout=8):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _send_mode(app):
    """把 app.mode 同步到 agent（设置页里切模式用）

    ★ 为什么单独抽出来：
      设置页的「推理模式」是三个小按钮，点了要立刻告诉 agent，
      但那段代码在 run() 里（模块级函数），拿不到 AgentApp 的方法，
      所以做成一个模块级辅助函数。
    """
    m = getattr(app, "mode", "auto")

    def fn():
        try:
            _post(AGENT_URL + "/llm/config", {"mode": m}, timeout=15)
            return "模式切到【%s】" % {"auto": "自动", "cloud": "云端",
                                       "local": "本地"}.get(m, m)
        except Exception as e:
            return "切模式失败: %s" % e
    app._bg("mode", fn)


class AgentApp(object):
    def __init__(self):
        # ★ 消息改成 (角色, 文字)：user=我说的 / bot=小白说的 / sys=系统提示
        self.msgs = [("bot", "我是系统管家小白 —— 这块板子的系统管家。"),
                     ("sys", "打字后按回车问我；也可以点「听」用说的。")]
        self.lines = ["我是系统管家小白 —— 这块板子的系统管家。",
                      "打字后按回车问我；也可以点「听」用说的。"]
        self.cur = ""
        # ★★★ 光标（2026-10-03）—— 用户："可以有个闪烁的竖线可以调整输入位置，
        #     这个你参考苹果的平板"
        #   原来只有 self.cur 一个字符串，所有输入都是 cur += x，
        #   等于光标永远钉在末尾：退格只能删最后一个字，想改中间的字
        #   只能全删重打。现在加 cur_pos 之后，打字/语音/手写的结果
        #   都插在光标处，← → 能移，输入框里画一条闪烁的竖线。
        self.cur_pos = 0               # 光标在 cur 里的位置 0..len(cur)
        self.caret_on = True           # 光标当前是否显示（闪烁用）
        self.caret_t = 0.0             # 上次翻转时间
        # ★ arrows=True：底部多一对 ◀ ▶（专门给光标移动）
        self.kb = MiniKeyboard(y0=KB_Y, key_w=76, key_h=KB_KH, gap=KB_GAP,
                               arrows=True)
        # ★ 本地中文输入法（不联网）。数据表由 PC 上的 build_ime_data.py 生成。
        self.ime = None
        try:
            from ime_cn import IME
            self.ime = IME()
        except Exception as e:
            print("IME 加载失败:", e, flush=True)
        self.py = ""            # 拼音缓冲（还没上屏的字母）
        self.cands = []         # 当前候选 [(文本, kind)]
        self.pinyin = True      # 拼音 / 英文
        self.quick = 0          # 常用指令滚动位置
        # ★ 待批准的危险动作（来自 Agent 权限层 /pending）
        self.pending = []
        self._pend_t = 0.0
        # ★ 屏幕上**实际画出来**的候选栏/批准栏条目。
        #   点击只跟这份对，避免"画的"和"点的"不是同一份。
        self.bar_rendered = []
        self.q = queue.Queue()
        self.busy = ""
        self.last_reply = ""

        # ══════════════════════════════════════════════════════════
        #  ★★★ 2026-10-03 新增状态：喇叭 / 设置页
        # ══════════════════════════════════════════════════════════
        # muted：静音开关。
        #   ★ 板子上的"静音"有两层含义，这里都管：
        #     ① 界面层：self.muted —— 控制【回复后要不要自动朗读】
        #     ② 系统层：/etc/zynq-silent —— agent 的工具层会拦住所有发声
        #   点喇叭时两个一起切（不然只切一个会出现"看着开但没声"）。
        self.muted = os.path.exists(SILENT_FLAG)
        self.settings_open = False
        self.settings_page = 0          # 0=主设置
        self.settings_hit = {}          # 设置页上画出来的可点区域
        self.models = []                # 从板子 /llm/models 拉的模型列表
        self.cur_model = ""
        self.has_key = False
        self.api_base = ""
        self._settings_dirty = True     # 需要重新拉配置
        self._rec_until = 0.0           # 录音倒计时（画进度用）
        self.await_key = False          # ★ 正在等用户输入 API Key（兼容旧字段）
        self.model_page = 0            # ★ 模型列表翻到第几页
        # ★ 按住说话的状态
        self.recording = False         # 正在录音
        self.rec_cancel = False        # 手指移出按钮 -> 松手取消
        self.rec_t0 = 0.0
        self.await_text = None          # ★ 等什么：None / "key" / "model"

        # ★★★ 2026-10-03 布局重做后新增的状态
        #
        # ★ 教训：这几个属性我第一次是用 PowerShell 的字符串替换加的，
        #   那个替换【静默失败】了（没匹配到），结果 draw_sidebar() 里
        #   访问 self.sessions 直接 AttributeError，App 一打开就崩。
        #   ⇒ 以后再改这种关键初始化，一律用 edit 工具，不要用文本替换。
        self.mode = "auto"              # auto / cloud / local（点按钮轮换）
        self.kb_open = False            # ★ 面板展开（旧名保留：三种输入共用）
        # ══════════════════════════════════════════════════════════
        #  ★★★ 统一输入面板状态（2026-10-03）
        #     in_mode 决定面板展开时【显示哪一套】：
        #       "kb" 键盘 / "voice" 语音 / "hand" 手写
        #     三者共用 self.cur 和提交路径，只有采集方式不同。
        # ══════════════════════════════════════════════════════════
        self.in_mode = IN_KB
        self.hand_strokes = []       # 手写：[[(x,y),...], ...] 每一笔
        self.hand_cur = None         # 当前正在画的那一笔
        self.hand_msg = ""           # 手写区提示
        # ★★★ 多会话：结构是 [{"title": str, "msgs": [(role,text), ...]}, ...]
        #   ★ self.msgs 始终【指向】当前会话的 msgs 列表对象 ——
        #     这样切换会话才是真的换记录，而不是只挪一下高亮。
        #   （原来是个 [(标题, "")] 的元组列表，只有标题没有内容。）
        self.sessions = []
        self.cur_session = -1
        self.sess_del = []              # 绘制时存的 [(下标, ×的矩形)]

        # ★★★ 启动时把上次的对话读回来
        #   用户："退出 agent 以后对话会直接消失"
        #   读到了就接着聊；读不到（第一次跑 / 文件坏了）就开一个新的。
        if not self.load_sessions():
            self.new_session()

        self.out("正在检查 Agent / 音频服务 ...")
        self._probe()

    # ---- 日志 ----
    # ══════════════════════════════════════════════════════════════
    #  ★★★ 多会话管理（2026-10-03 新增）
    # ══════════════════════════════════════════════════════════════
    # 用户报的两个问题：
    #   "干嘛老是有那个切换对话出现，出现完还把记录删了"
    #   "不能加一个删除对话的功能吗"
    #
    # 根因：
    #   ① 原来的 sessions 是 [(标题, "")] —— 只有标题，没有消息内容，
    #      所谓"切换会话"只是把高亮挪一下，消息区根本没变，
    #      却还 out("切到会话：xxx") 往【消息区】写一条 sys 消息。
    #   ② 点侧栏【任意位置】（包括空白处）都会命中这个分支。
    #   ③ out() 里 self.msgs = self.msgs[-200:] 是【重新绑定】，
    #      多写几条就把真正的对话挤出去了 ⇒ 看起来像"记录被删了"。
    #
    # 修法：
    #   · 会话结构升级成 dict：{"title": ..., "msgs": [...]}
    #   · self.msgs 始终【指向】当前会话的 msgs 列表对象，切换就是真切换
    #   · out() 改成【原地】截断（del msgs[:-200]），不再重新绑定
    #   · 点侧栏空白不做任何事；切换/新建不再往消息区写日志
    #   · 每个会话条目右侧加一个 × 删除键
    # ══════════════════════════════════════════════════════════════
    # ══════════════════════════════════════════════════════════════
    #  ★★★ 会话落盘（2026-10-03 新增）
    # ══════════════════════════════════════════════════════════════
    # 用户报："退出 agent 以后对话会直接消失"
    #
    # 原因：sessions 只存在内存里，App 一退（或者桌面重启）就全没了。
    #
    # 修法：存成 JSON 到 /home/zynq/.agent_chats.json
    #   · 每次改会话（新建/切换/删除/问完一句）就存一次（数据很小）
    #   · run() 退出时（finally）再存一次兜底
    #   · 启动时读回来，接着上次继续聊
    #   · 写临时文件再 os.replace，避免断电/被杀时留下半个文件
    # ══════════════════════════════════════════════════════════════
    def save_sessions(self):
        """把会话存到磁盘（失败就算了，不能因为存盘崩掉 App）"""
        try:
            data = {"cur": self.cur_session,
                    "sessions": [{"title": self.sess_title(i),
                                  "msgs": [[m[0], m[1]]
                                           for m in self.sessions[i].get(
                                               "msgs", [])]}
                                 for i in range(len(self.sessions))]}
            tmp = SESS_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(tmp, SESS_FILE)
            try:
                os.chmod(SESS_FILE, 0o644)
            except Exception:
                pass
        except Exception:
            pass

    def load_sessions(self):
        """启动时把上次的会话读回来"""
        try:
            with open(SESS_FILE, encoding="utf-8") as f:
                d = json.load(f)
        except Exception:
            return False
        try:
            out = []
            for s in (d.get("sessions") or []):
                msgs = [(str(m[0]), str(m[1]))
                        for m in (s.get("msgs") or []) if len(m) >= 2]
                out.append({"title": s.get("title") or "新对话",
                            "msgs": msgs})
            if not out:
                return False
            self.sessions = out
            self.cur_session = max(0, min(int(d.get("cur", 0)),
                                          len(out) - 1))
            # ★ msgs 必须指向当前会话的列表对象
            self.msgs = self.sessions[self.cur_session]["msgs"]
            return True
        except Exception:
            return False

    def new_session(self):
        """新建一个空会话并切过去"""
        self.sessions.append({"title": "新对话", "msgs": []})
        self.cur_session = len(self.sessions) - 1
        self.msgs = self.sessions[self.cur_session]["msgs"]
        self.lines = []
        self.save_sessions()

    def switch_session(self, i):
        """切到第 i 个会话（真正把消息区换成那一条的记录）"""
        if not (0 <= i < len(self.sessions)):
            return
        if i == self.cur_session:
            return
        # ★ 先把当前消息存回它自己的会话里（保险，因为 msgs 本来就是引用）
        if 0 <= self.cur_session < len(self.sessions):
            self.sessions[self.cur_session]["msgs"] = self.msgs
        self.cur_session = i
        self.msgs = self.sessions[i]["msgs"]
        self.save_sessions()

    def del_session(self, i):
        """删除第 i 个会话"""
        if not (0 <= i < len(self.sessions)):
            return
        del self.sessions[i]
        if not self.sessions:
            # 全删光了 -> 自动建一个空的，免得界面一片空白
            self.sessions.append({"title": "新对话", "msgs": []})
            self.cur_session = 0
        elif i < self.cur_session:
            self.cur_session -= 1
        elif i == self.cur_session:
            # 删的是当前会话 -> 落到最后一个
            self.cur_session = min(i, len(self.sessions) - 1)
        self.msgs = self.sessions[self.cur_session]["msgs"]
        self.lines = []
        self.save_sessions()

    def sess_title(self, i):
        """取会话标题（dict 结构，兼容老的元组，避免历史代码崩）"""
        try:
            s = self.sessions[i]
        except Exception:
            return ""
        if isinstance(s, dict):
            return s.get("title", "")
        return s[0] if s else ""

    def out(self, s):
        """加一条消息。按前缀判断角色（保持旧调用不变）。"""
        for raw in str(s).split("\n"):
            ln = raw.strip()
            if not ln:
                continue
            if ln.startswith("我>"):
                self.msgs.append(("user", ln[2:].strip()))
            elif ln.startswith("小白>"):
                self.msgs.append(("bot", ln[3:].strip()))
            else:
                self.msgs.append(("sys", ln))
            self.lines.append(ln[:118])
        # ★★★ 必须【原地】截断，不能 self.msgs = self.msgs[-200:]
        #   后者会把 msgs 重新绑到一个新列表上，
        #   断开它和 sessions[cur]["msgs"] 的引用关系 ——
        #   一截断，当前会话的存档就"丢"了（用户看到的"记录被删"）。
        if len(self.lines) > 300:
            del self.lines[:-300]
        if len(self.msgs) > 200:
            del self.msgs[:-200]

    # ══════════════════════════════════════════════════════════
    #  气泡排版（参考 Harness / 现代聊天界面）
    # ══════════════════════════════════════════════════════════
    @staticmethod
    def _wrap(scr, text, size, maxw):
        """中文自动换行。中文没空格，必须逐字量宽。"""
        out, cur = [], ""
        for ch in text:
            if ch == "\n":
                out.append(cur)
                cur = ""
                continue
            t = cur + ch
            if cur and scr.tw(t, size, cn=True) > maxw:
                out.append(cur)
                cur = ch
            else:
                cur = t
        if cur:
            out.append(cur)
        return out or [""]

    def layout(self, scr):
        """从**底部往上**排版所有气泡，返回 [(role, lines, rect, h)]。

        底部优先 -> 最新消息永远可见，旧的自动被挤出去。
        """
        # ★ 动态消息区：键盘弹出时会被压扁
        _lr = log_rect(getattr(self, "kb_open", False))
        # ★ 和 draw_bubbles() 用【同一套往里收的边距】，
        #   否则排版算出来的气泡位置会跑到卡片外面去
        PAD_X, PAD_Y = 18, 10
        x0, y0 = _lr[0] + PAD_X, _lr[1] + PAD_Y
        x1, y1 = _lr[2] - PAD_X, _lr[3] - PAD_Y
        pad = 12
        avail_w = (x1 - x0) - 2 * pad
        maxw = int(avail_w * 0.62)          # 气泡最大宽 62%，像手机聊天
        size = 17
        lh = 22                              # 行高
        items = []
        ybot = y1 - pad
        for role, text in reversed(self.msgs):
            if role == "sys":
                w = min(avail_w, scr.tw(text, 14, cn=True) + 16)
                lw = maxw if False else avail_w
                lines = self._wrap(scr, text, 14, avail_w - 16)
                h = len(lines) * 19 + 8
                x = x0 + pad + (avail_w - w) // 2
                r = [x, ybot - h, x + w, ybot]
            elif role == "user":
                lines = self._wrap(scr, text, size, maxw - 24)
                w = max(scr.tw(x, size, cn=True) for x in lines) + 24
                h = len(lines) * lh + 18
                r = [x1 - pad - w, ybot - h, x1 - pad, ybot]
            else:                            # bot
                lines = self._wrap(scr, text, size, maxw - 46)
                w = max(scr.tw(x, size, cn=True) for x in lines) + 46
                h = len(lines) * lh + 18
                r = [x0 + pad, ybot - h, x0 + pad + w, ybot]
            if r[1] < y0 + 2:                # 超出上边界就停（更旧的看不见）
                break
            items.append((role, lines, r, h))
            ybot = r[1] - 8                  # 气泡间距
        items.reverse()
        return items

    def draw_bubbles(self, scr):
        """画消息气泡 + 头像 + 正在输入指示

        ★★ 用户说「对话框不要通到左边，有点丑」——
          原来消息区紧贴左侧栏（x=172）和屏幕右边（x=1020），
          气泡的底框顶到边上，看起来像没做完。
        ⇒ 现在整个消息区往里收：左右各留 18px，上下各留 10px，
          圆角加大到 12，看起来像个独立的卡片。
        """
        _lr = log_rect(getattr(self, "kb_open", False))
        PAD_X, PAD_Y = 18, 10
        x0, y0 = _lr[0] + PAD_X, _lr[1] + PAD_Y
        x1, y1 = _lr[2] - PAD_X, _lr[3] - PAD_Y
        scr.rrect([x0, y0, x1, y1], 12, fill=(28, 18, 15),
                  outline=(47, 47, 47))
        items = self.layout(scr)
        for role, lines, r, h in items:
            if role == "user":
                scr.rrect(r, 10, fill=(48, 96, 168))          # 蓝色：我说的
                tx, col = r[0] + 12, (245, 245, 245)
                for i, ln in enumerate(lines):
                    scr.text((tx, r[1] + 9 + i * 22), ln, 17, col, cn=True)
            elif role == "bot":
                scr.rrect(r, 10, fill=(50, 36, 30))           # 深灰：小白说的
                # 头像（圆形，左上角，和 Harness 一样有身份感）
                ax, ay, ar = r[0] + 20, r[1] + 20, 11
                scr.d.ellipse([ax - ar, ay - ar, ax + ar, ay + ar],
                              fill=(74, 128, 210))
                scr.text((ax, ay), "白", 14, (255, 255, 255), anchor="mm",
                         cn=True)
                tx = r[0] + 40
                for i, ln in enumerate(lines):
                    scr.text((tx, r[1] + 9 + i * 22), ln, 17,
                             (233, 233, 233), cn=True)
            else:                                             # sys
                for i, ln in enumerate(lines):
                    scr.text((r[0] + 8, r[1] + 4 + i * 19), ln, 14,
                             (122, 138, 168), cn=True)

        # ---- 正在思考：三个跳动的点 ----
        if self.busy:
            import math as _m
            import time as _t
            bx, by = x0 + 40, y0 + 22
            h2 = 34
            scr.rrect([x0 + 10, y0 + 6, x0 + 96, y0 + 6 + h2], 10,
                      fill=(50, 36, 30))
            ax, ay, ar = x0 + 30, y0 + 23, 10
            scr.d.ellipse([ax - ar, ay - ar, ax + ar, ay + ar],
                          fill=(74, 128, 210))
            scr.text((ax, ay), "白", 13, (255, 255, 255), anchor="mm", cn=True)
            ph = _t.time() * 4.0
            for k in range(3):
                rr = 3.0 + 1.8 * (1 + _m.sin(ph - k * 0.9)) / 2.0
                cx = x0 + 56 + k * 13
                scr.d.ellipse([cx - rr, ay - rr, cx + rr, ay + rr],
                              fill=(150, 180, 230))

    def _bg(self, name, fn):
        if self.busy:
            return False      # ★ 上一件事还没做完
        self.busy = name

        def wrap():
            try:
                self.q.put((name, fn()))
            except Exception as e:
                self.q.put((name, "错误: %s: %s" % (type(e).__name__, e)))
        threading.Thread(target=wrap, daemon=True).start()
        return True


    def _probe(self):
        def fn():
            out = []
            try:
                h = _get(AGENT_URL + "/health", timeout=5)
                out.append("Agent 服务: %s" % ("在线" if h.get("ok") is not False
                                              else h))
            except Exception as e:
                out.append("Agent 服务: 不在线（%s）" % e)
            try:
                h = _get(AUDIO_URL + "/health", timeout=5)
                out.append("音频服务: %s port=%s" % (h.get("name"), h.get("port")))
            except Exception:
                # ★ 不要把 Python 异常原文甩给用户（"urlopen error [Errno 111]"
                #   又长又丑）。音频服务被停掉时给一句人话。
                out.append("音频服务: 已停止（放音和录音都不可用）")
            return "\n".join(out)
        self._bg("probe", fn)

    # ══════════════════════════════════════════════════════════════
    #  ★★★ 设置（声音模式 / 模型 / API Key / 工具）
    # ══════════════════════════════════════════════════════════════
    def load_settings(self):
        """后台拉：模型列表 + 当前模型 + 有没有 key + 静音状态"""
        def fn():
            d = {}
            try:
                d["models"] = _get(AGENT_URL + "/llm/models", timeout=25)
            except Exception as e:
                d["models_err"] = str(e)[:60]
            try:
                d["cfg"] = _get(AGENT_URL + "/llm/settings", timeout=12)
            except Exception as e:
                d["cfg_err"] = str(e)[:60]
            d["muted"] = os.path.exists(SILENT_FLAG)
            return d
        self._bg("settings", fn)

    def set_muted(self, muted):
        """切静音（★ 界面层 + 系统层一起切）"""
        def fn():
            self.muted = muted
            try:
                if muted:
                    os.system("touch %s 2>/dev/null" % SILENT_FLAG)
                else:
                    os.system("rm -f %s 2>/dev/null" % SILENT_FLAG)
            except Exception:
                pass
            # 也告诉 agent（这样规则层的"静音/解除静音"和界面保持一致）
            try:
                _post(AGENT_URL + "/voice",
                      {"text": "进入静音模式" if muted else "解除静音"},
                      timeout=20)
            except Exception:
                pass
            return "已静音（不会出声）" if muted else "已解除静音（能出声了）"
        self._bg("mute", fn)

    def set_model(self, name):
        def fn():
            try:
                _post(AGENT_URL + "/llm/model", {"model": name}, timeout=20)
                self.cur_model = name
                return "模型已切到 %s" % name
            except Exception as e:
                return "切模型失败: %s" % e
        self._bg("model", fn)

    def start_key_input(self):
        """进入「API Key 输入模式」（兼容旧调用）"""
        self.start_text_input("key")

    def start_text_input(self, what):
        """进入「文本输入模式」—— what = "key"（API Key）或 "model"（加模型）

        ★★★ 为什么原来不可用（用户："你那个点击完，能不能真的能配置"）
        ────────────────────────────────────────────────────────────
        原来的实现只做了两件事：
            self.await_key = True
            self.out("在下面输入框里打 API Key（或让 PC 客户端配）")
        于是有四个问题：
          ① 键盘没自动弹出来 —— 用户还得自己再点一下输入框
          ② 除了消息区一行小字，界面上没有任何"正在等你输入"的提示
          ③ ★ 拼音模式还开着：打字母进的是【拼音缓冲】而不是输入框，
             打出来的 key 变成一串拼音，完全不是那回事
          ④ ★ 回车时 commit_first() 优先：只要拼音缓冲非空，
             就先上屏候选字，根本走不到 set_key 那一支
        ⇒ 结果就是"点了没反应 / 配不上"。

        现在进入模式时把这几件事一次做掉：
          · 弹出键盘
          · 强制关拼音（Key / 模型名要的是原样字符，不是拼音）
          · 清空输入框和拼音缓冲
          · 记住原来的拼音开关，提交/取消后还原

        ★ 2026-10-03 推广成通用的：加模型名走同一套 UI，只是 what 不同。
        """
        self.await_text = what        # "key" / "model"
        self.await_key = (what == "key")   # 兼容旧字段
        self._pinyin_backup = bool(getattr(self, "pinyin", True))
        self.pinyin = False
        self.py = ""
        self.cur = ""
        self.kb_open = True           # ★ 自动弹键盘
        self.settings_open = False

    def cancel_key_input(self):
        """取消输入（把拼音开关还原）"""
        if getattr(self, "await_text", None) or getattr(self, "await_key",
                                                        False):
            self.await_text = None
            self.await_key = False
            self.pinyin = bool(getattr(self, "_pinyin_backup", True))
            self.py = ""
            self.cur = ""

    def add_model(self, name):
        """★ 把一个自定义模型名加进配置（用户："能添加模型吗"）"""
        name = (name or "").strip()
        if not name:
            return
        # ★ 重名不重复加
        if name in (self.models or []):
            self.out("模型「%s」已经在列表里了" % name)
            return

        def fn():
            try:
                # 先读现有的，再追加（不能直接覆盖，否则会丢掉之前加的）
                try:
                    d = _get(AGENT_URL + "/llm/settings", timeout=12)
                    old = []
                except Exception:
                    old = []
                try:
                    r = _post(AGENT_URL + "/llm/settings",
                              {"extra_models": None}, timeout=5)
                except Exception:
                    r = {}
                # ★ 直接读覆盖文件拿现有 extra_models 更稳
                import json as _j
                cur = []
                try:
                    with open("/home/zynq/.agent_settings.json",
                              encoding="utf-8") as f:
                        cur = _j.load(f).get("extra_models") or []
                except Exception:
                    pass
                if name not in cur:
                    cur.append(name)
                _post(AGENT_URL + "/llm/settings",
                      {"extra_models": cur}, timeout=20)
                if name not in self.models:
                    self.models.append(name)
                return "已添加模型「%s」（列表里现在有 %d 个）" % (
                    name, len(self.models))
            except Exception as e:
                return "添加失败: %s" % e
        self._bg("model", fn)

    def set_key(self, key):
        def fn():
            try:
                _post(AGENT_URL + "/llm/settings", {"api_key": key}, timeout=20)
                self.has_key = bool(key)
                return ("API Key 已保存（%d 位）—— 云端模型现在可以用了"
                        % len(key))
            except Exception as e:
                return "写 Key 失败: %s" % e
        self._bg("key", fn)

    def ask(self, text):
        # ★★★ 问一句就记进左侧「对话记录栏」
        #   踩过：一开始只在点「＋ 新对话」时才往 sessions 里加东西，
        #   结果问了一堆问题，左边那栏还是空的 —— 那不叫对话记录。
        #
        # ★ 现在：如果当前会话还是空的（标题是"新对话"），
        #   就用这句话当标题；否则不动标题。
        try:
            if not self.sessions:
                self.new_session()
            i = self.cur_session
            if 0 <= i < len(self.sessions):
                s = self.sessions[i]
                if isinstance(s, dict):
                    if s.get("title") in ("", "新对话"):
                        s["title"] = str(text)[:24]
                    # ★ 把 msgs 的引用保持住（switch 时靠它）
                    s["msgs"] = self.msgs
        except Exception:
            pass

        def fn():
            d = _post(AGENT_URL + "/voice", {"text": text}, timeout=300)
            self.last_reply = d.get("reply") or "(空回复)"
            return "小白> " + self.last_reply + \
                   "\n      (%s 轮, %ss)" % (d.get("rounds"), d.get("elapsed"))
        self._bg("ask", fn)
        self.save_sessions()   # ★ 问完立刻落盘

    def say(self):
        if not self.last_reply:
            self.out("还没有可朗读的回复。")
            return
        txt = self.last_reply

        def fn():
            # 优先让板上 tts 模块做（它知道百度密钥在哪）
            import sys
            if "/home/zynq/agent" not in sys.path:
                sys.path.insert(0, "/home/zynq")
            try:
                from agent import tts
                p, secs = tts.speak(txt[:300])
                return "已朗读 %.1f 秒" % secs
            except Exception as e:
                raise RuntimeError("朗读失败: %s: %s" % (type(e).__name__, e))
        self._bg("say", fn)

    def listen(self, secs=4.0):
        def fn():
            import sys
            if "/home/zynq" not in sys.path:
                sys.path.insert(0, "/home/zynq")
            from agent import tts
            text, p = tts.listen(secs=secs)
            if text:
                self.cur = text
            return "听到: " + (text or "(没听清)") + "   [" + p + "]"
        self._bg("listen", fn)

    # ══════════════════════════════════════════════════════════════
    #  ★★★ 真正的「按住说话」（2026-10-03）
    # ══════════════════════════════════════════════════════════════
    # 用户："他并不是按住说话，而是点击，然后我说完了也不能取消"
    #
    # 原来 voice() 是点一下 -> 固定录 4 秒，跟按住多久无关。
    # 现在：
    #   down 在按钮上 -> voice_begin()  让音频服务【立刻开始采集】
    #   move 移出按钮 -> 标记"松手就取消"（按钮变灰提示）
    #   up  还在按钮 -> voice_end()     停 + 识别 + 问 agent
    #   up  已在按钮外 -> voice_end(cancel=True) 丢弃这段
    #
    # ★ 为什么必须"按下就开始录"：等松开再录的话，
    #   用户说的那句话根本没被采到。
    # ══════════════════════════════════════════════════════════════
    def voice_rect(self, scr):
        """「按住说话」按钮的矩形（没找到返回 None）

        ★ 2026-10-03 统一输入面板之后改了：
          原来这个按钮在**底部按钮排**上（act == "voice"）；
          现在按钮排换成三个「输入方式切换」，而"按住说话"变成了
          **语音面板里那个大按钮**（self.voice_big，由 draw_voice_panel 画）。
          ⇒ 必须同时满足：in_mode == "voice" 且面板展开。
        """
        if getattr(self, "in_mode", IN_KB) != IN_VOICE:
            return None
        if not getattr(self, "kb_open", False):
            return None
        return getattr(self, "voice_big", None)

    def voice_begin(self):
        """按下：开始录音 + 启动「边说边出字」的后台识别循环

        ★★★ 2026-10-03 改（用户："先搞语音转文字的语音输入"）
        ────────────────────────────────────────────────────────────
        原来：按下开始录 -> 松开才拿到整段音频 -> 那时才去识别。
              中间那几秒界面上什么都不显示，用户不知道在不在录，
              而且是"说完再等 1~2 秒"，体验很差。

        现在：按下就开始【累积式分段识别】——
              后台线程每 1.2 秒做一次：
                ① 向音频服务要"当前录音快照"（/record/snapshot，不停止录音）
                ② 把【从头到现在】的整段送百度 ASR
                ③ 用最新结果覆盖输入框
              松开时做最后一次完整识别，然后发送。

        ★ 为什么每次送"从头到现在"而不是只送最近 1.2 秒：
          切在词中间会识别错（"现在几" + "点"）。给完整上下文，
          百度每次都能给正确结果，我们只取最新那次覆盖显示。
        ★ 音频服务那边的快照转换已经优化成 C 层操作（0.03~0.09 秒），
          所以这个循环不会拖慢录音。
        ────────────────────────────────────────────────────────────
        """
        self.recording = True
        self.rec_cancel = False
        self.rec_t0 = time.time()
        self.voice_text = ""          # 累积识别出来的文字
        self.voice_seq = 0            # 每次结果递增，用来判断"是不是更新的"
        # ★ 记住录音前输入框里已有的内容 —— 流式结果是【整段替换】的，
        #   不能把用户之前打的字（或手写的字）覆盖掉。
        self._voice_prefix = self.cur
        self._voice_at = getattr(self, "cur_pos", len(self.cur))

        def fn():
            try:
                _post(AUDIO_URL + "/record/start", {}, timeout=15)
                return None            # 开始成功，不写日志
            except Exception as e:
                return "录音启动失败: %s" % e
        self._bg("rec_start", fn)
        self.out("● 正在聆听…（边说边出字；松开发送 · 上滑到按钮外取消）")

        # ★ 启动后台识别循环
        import threading as _th
        self._voice_stop = _th.Event()

        def loop():
            import sys as _s
            import urllib.request as _u
            if "/home/zynq" not in _s.path:
                _s.path.insert(0, "/home/zynq")
            try:
                from agent import asr as _asr
            except Exception:
                return
            last = ""
            while not self._voice_stop.is_set():
                # 可中断的等待
                if self._voice_stop.wait(1.2):
                    break
                if not self.recording:
                    break
                try:
                    req = _u.Request(
                        AUDIO_URL + "/record/snapshot",
                        data=json.dumps({"rate": 16000}).encode(),
                        headers={"Content-Type": "application/json"},
                        method="POST")
                    with _u.urlopen(req, timeout=12) as r:
                        wav = r.read()
                    if wav[:4] != b"RIFF":
                        continue
                    with open("/tmp/xiaobai_stream.wav", "wb") as f:
                        f.write(wav)
                    txt, _eng = _asr.recognize("/tmp/xiaobai_stream.wav",
                                              rate=16000)
                    # ★ 太短的时候百度会返回空/噪声，忽略
                    if txt and txt != last:
                        last = txt
                        self.voice_text = txt
                        # ★ 实时上屏：整段替换（保留录音前已有的文字）
                        _pre = getattr(self, "_voice_prefix", "")
                        self.cur = _pre + txt
                        self.cur_pos = len(self.cur)
                        self.caret_t = time.time()
                        self.caret_on = True
                        self.voice_seq += 1
                except Exception:
                    continue
        _th.Thread(target=loop, daemon=True).start()

    def voice_move(self, inside):
        """手指移动：移出按钮就标记为『松手取消』"""
        self.rec_cancel = (not inside)

    def voice_end(self, cancel=False):
        """松开：停录音 -> 最后识别一次 -> 交给 agent"""
        if not self.recording:
            return
        self.recording = False
        cancel = bool(cancel or self.rec_cancel)
        self.rec_cancel = False
        held = time.time() - getattr(self, "rec_t0", time.time())

        # ★ 停掉流式循环
        try:
            self._voice_stop.set()
        except Exception:
            pass

        # ★ 太短（<0.4s）当误触，直接丢
        if held < 0.4 and not cancel:
            cancel = True

        def fn():
            import sys as _s
            try:
                # ① 停录音，拿 wav
                req = urllib.request.Request(
                    AUDIO_URL + "/record/stop",
                    data=json.dumps({"cancel": cancel,
                                     "rate": 16000}).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST")
                with urllib.request.urlopen(req, timeout=30) as r:
                    raw = r.read()
                    ctype = r.headers.get("Content-Type", "")
                if cancel:
                    return "已取消（按住 %.1fs）" % held
                if "audio" not in (ctype or ""):
                    return "录音没拿到音频: %s" % raw[:120]

                # ② 存盘
                wav = "/tmp/xiaobai_hold.wav"
                with open(wav, "wb") as f:
                    f.write(raw)

                # ③ 识别（★ 优先用流式循环已经累积出来的结果）
                #   为什么还要再识别一次：流式循环最多只做到松开前 1.2 秒，
                #   最后那截（以及可能的修正）用完整段再跑一次，
                #   这样"最后两个字"不会被吞掉。
                if "/home/zynq" not in _s.path:
                    _s.path.insert(0, "/home/zynq")
                from agent import asr
                text, eng = asr.recognize(wav, rate=16000)
                streamed = (getattr(self, "voice_text", "") or "").strip()
                # ★ 完整段识别为空时，退回流式结果（别让用户白说）
                if not text:
                    text = streamed
                    if text:
                        eng = eng + "+流式"
                if not text:
                    return ("没听清（引擎 %s，按住 %.1fs）—— "
                            "靠近麦克风、说清楚一点再试" % (eng, held))

                # ★★★ 2026-10-03 改：松开【只把文字填进输入框】，不发送
                # ────────────────────────────────────────────────────
                # 用户："不要松开就发送，是松开就把这一段文字输入，
                #       你无论哪种输入法都是输文字，最后点回车才能发送"
                # ────────────────────────────────────────────────────
                # 这才是对的交互：语音/手写/键盘都只是"往里打字"的三种方式，
                # 打完了用户自己检查、改，最后统一按回车发送。
                # 原来这里直接 POST /voice 给 agent，等于"说完就发"，
                # 用户连改的机会都没有。
                # ★ 保留录音前已有的文字（流式是整段替换，别覆盖用户打的字）
                _pre = getattr(self, "_voice_prefix", "")
                self.cur = _pre + text
                self.cur_pos = len(self.cur)
                self.caret_t = time.time()
                self.caret_on = True
                return ("语音输入: %s\n      （%s · 按住 %.1fs）"
                        "—— 检查后按【回车】发送"
                        % (text, eng, held))
            except Exception as e:
                return "语音失败: %s: %s" % (type(e).__name__, e)
        self._bg("voice", fn)

    def voice(self, secs=4.0):
        """★ 完整语音闭环：麦克风 -> ASR -> Agent -> TTS -> 喇叭"""
        def fn():
            import sys
            if "/home/zynq" not in sys.path:
                sys.path.insert(0, "/home/zynq")
            from agent.voice_loop import VoiceLoop
            lines = []
            v = VoiceLoop(verbose=False, on_state=lambda s: lines.append("状态: " + s))
            t, r = v.once(secs=secs)
            if r:
                self.last_reply = r
            out = "\n".join(lines + v.log)
            return out if out else "（没有有效语音输入）"
        self._bg("voice", fn)

    def selftest(self):
        def fn():
            d = _post(AUDIO_URL + "/selftest", {"freq": 1000, "secs": 1.2},
                      timeout=240)
            return "自检: %s\n  @%.0fHz 静音 %.1f -> 放音 %.1f (%.1f dB)" % (
                d.get("verdict"), d.get("freq", 1000), d.get("goe_quiet", 0),
                d.get("goe_tone", 0), d.get("ratio_db", 0))
        self._bg("selftest", fn)

    def pump(self):
        while True:
            try:
                name, res = self.q.get_nowait()
            except queue.Empty:
                break
            self.busy = ""

            # ★★★ 新增的几个后台任务，结果不是"聊天消息"，要分开处理
            #   （否则模型列表那个 dict 会被 out() 打成一大坨文字）
            if name == "settings":
                if isinstance(res, dict):
                    m = res.get("models")
                    if isinstance(m, dict):
                        self.models = m.get("models") or []
                        if m.get("current"):
                            self.cur_model = m["current"]
                    c = res.get("cfg")
                    if isinstance(c, dict):
                        self.has_key = bool(c.get("has_key"))
                        self.api_base = c.get("api_base") or ""
                        if c.get("model"):
                            self.cur_model = c["model"]
                    self.muted = bool(res.get("muted", self.muted))
                    self._settings_dirty = False
                continue
            if name == "mute":
                # ★ 静音状态可能刚被切过，重新读一次文件为准
                self.muted = os.path.exists(SILENT_FLAG)
                self.out(str(res))
                continue
            if name in ("model", "key"):
                self.out(str(res))
                continue

            self.out(res)

        # ★ 每 2 秒轮询一次待批准队列（直接 HTTP，很快）
        import time as _t
        if _t.time() - self._pend_t > 2.0:
            self._pend_t = _t.time()
            try:
                d = _get(AGENT_URL + "/pending", timeout=2)
                self.pending = d.get("pending") or []
            except Exception:
                pass

    def _approve(self, rid, ok):
        """同意 / 拒绝一个待批准动作"""
        def fn():
            try:
                d = _post(AGENT_URL + "/approve",
                          {"id": rid, "ok": ok}, timeout=10)
                self.pending = []
                if ok:
                    it = d.get("resolved") or {}
                    return ("已同意: %s  —— 5 分钟内同一条命令可直接执行"
                            % it.get("payload", rid))
                return "已拒绝: %s" % rid
            except Exception as e:
                return "操作失败: %s" % e
        self._bg("approve", fn)

    # ---- 拼音输入 ----
    def refresh_cands(self):
        """重算候选。缓冲为空 -> 用常用指令填满候选栏"""
        if not self.pinyin:
            self.cands = []
            return
        if self.py and self.ime and self.ime.ok:
            self.cands = self.ime.candidates(self.py, limit=8)
        else:
            self.cands = []

    def commit(self, text):
        """把候选/指令上屏，清掉拼音缓冲"""
        self.cur += text
        self.py = ""
        self.refresh_cands()

    def commit_first(self):
        """空格/回车：优先上屏第一个候选，没有候选就把字母原样上屏"""
        if self.py:
            if self.cands:
                self.commit(self.cands[0][0])
            else:
                self.cur += self.py
                self.py = ""
                self.refresh_cands()
            return True
        return False

    def bar_items(self, scr):
        """返回候选栏上要画的东西 [(文本, 动作, 矩形)]

        有拼音缓冲 -> 候选字/词；没有 -> 常用指令
        """
        items = []
        # ★ 候选栏自己占一整行（设置键已经挪到左侧栏底部，不再抢这里的位置）
        #   y 坐标也跟着键盘状态走：键盘弹出时候选栏在 398~438
        _cr = CAND_RECT_KB if self.kb_open else CAND_RECT
        x = _cr[0] + 6
        y0, y1 = _cr[1] + 4, _cr[3] - 4
        h = y1 - y0

        # ★★ 优先级最高：有待批准的危险动作 -> 显示批准条
        if self.pending:
            it = self.pending[0]
            act = str(it.get("payload") or "")
            if len(act) > 42:
                act = act[:40] + "..."
            items.append(("[!] 同意? " + act, "none",
                          [x, y0, x + 500, y1]))
            x += 506
            items.append(("同意", "approve:%s:1" % it["id"],
                          [x, y0, x + 76, y1]))
            x += 80
            items.append(("拒绝", "approve:%s:0" % it["id"],
                          [x, y0, x + 76, y1]))
            x += 80
            if len(self.pending) > 1:
                items.append(("全部拒绝", "approve:all:0",
                              [x, y0, x + 104, y1]))
            return items

        # 左侧：模式切换
        mw = 66
        items.append(("拼音" if self.pinyin else "英文", "mode",
                      [x, y0, x + mw, y1]))
        x += mw + 6
        if self.py and self.cands:
            for i, (t, kind) in enumerate(self.cands):
                w = max(46, scr.tw(t, 20, cn=True) + 22)
                if x + w > _cr[2] - 8:
                    break
                # 第一个候选给个高亮边框提示"空格可上屏"
                items.append((t, "cand:%d" % i, [x, y0, x + w, y1]))
                x += w + 4
        elif not self.py:
            # 常用指令（点一下就发）
            for i, q in enumerate(QUICK):
                w = max(60, scr.tw(q, 16, cn=True) + 18)
                if x + w > _cr[2] - 8:
                    break
                items.append((q, "quick:%s" % q, [x, y0, x + w, y1]))
                x += w + 4
        return items

    # ---- 绘制 ----
    def buttons(self, scr):
        """底部按钮排 —— ★ 对齐 PC 端

        PC 端输入框下面那排是：
            [● 按住说话]  ...  [模型 ▾] [模式 ▾] [朗读] [发送]
        板载版照着来（空间小，朗读收进设置、设置键放最左）：
            [⚙] [按住说话]  [模型 ▾] [模式 ▾]  [发送]

        ★ 模型/模式直接在按钮排上，不用点进设置 —— 这是用户明确要求的：
          "模型切换在输入栏右下角，模式切换你放你要的位置"
        """
        b = []
        y0, y1 = BAR_RECT[1] + 2, BAR_RECT[3] - 2

        # ① ★★★ 三个输入方式切换（键盘 / 语音 / 手写）
        #     2026-10-03 统一输入面板：原来是写死的「按住说话」按钮，
        #     现在三种方式平等并列。点哪个就切到哪个面板。
        #     （语音的"按住说话"大按钮在语音面板里，不占这里的位置）
        x = BAR_RECT[0] + 6
        _cur = getattr(self, "in_mode", IN_KB)
        for m in IN_MODES:
            lab = IN_MODE_LABEL[m]
            w = scr.tw(lab, 15, cn=True) + 20
            b.append((lab, "inmode:" + m, [x, y0, x + w, y1]))
            x += w + 5
        x += 8

        # ② 模型（显示当前模型名）
        mname = self.cur_model or "模型"
        if len(mname) > 17:
            mname = mname[:16] + "…"
        w = scr.tw(mname, 15, cn=True) + 34
        b.append((mname, "model", [x, y0, x + w, y1]))
        x += w + 8

        # ③ 模式（自动 / 云端 / 本地）
        mlabel = "模式:" + self.mode_label()
        w = scr.tw(mlabel, 15, cn=True) + 26
        b.append((mlabel, "mode", [x, y0, x + w, y1]))

        # ④ 发送（靠右）
        sw = scr.tw("发送", 18, cn=True) + 34
        b.append(("发送", "ask",
                  [BAR_RECT[2] - sw - 4, y0, BAR_RECT[2] - 4, y1]))
        return b

    def mode_label(self):
        return {"auto": "自动", "cloud": "云端",
                "local": "本地"}.get(getattr(self, "mode", "auto"), "自动")

    def cycle_mode(self):
        """点一下模式按钮就轮换：自动 -> 云端 -> 本地 -> 自动"""
        order = ("auto", "cloud", "local")
        cur = getattr(self, "mode", "auto")
        try:
            nxt = order[(order.index(cur) + 1) % len(order)]
        except Exception:
            nxt = "auto"
        self.mode = nxt

        def fn():
            try:
                _post(AGENT_URL + "/llm/config", {"mode": nxt}, timeout=15)
                return "模式切到【%s】" % self.mode_label()
            except Exception as e:
                return "切模式失败: %s" % e
        self._bg("mode", fn)

    def cycle_model(self):
        """点一下模型按钮就换下一个（列表是 /llm/models 拉的）"""
        if not self.models:
            self.load_settings()
            return
        try:
            i = self.models.index(self.cur_model)
        except ValueError:
            i = -1
        nxt = self.models[(i + 1) % len(self.models)]
        self.set_model(nxt)

    # ══════════════════════════════════════════════════════════════
    #  ★★★ 设置页（覆盖层）
    # ══════════════════════════════════════════════════════════════
    def draw_settings(self, scr):
        """画设置页（照 Harness 的样子重做）

        ★★★ 2026-10-03 重做。用户的原话：
            "设置点开，也太粗糙了，你好好看看 hardness 的那个设置点开长什么样"

        Harness 的设置页是这样：
            ┌────────────────────────────────────────────────┐
            │ 设置                            [按钮]     ×   │
            ├──────────┬─────────────────────────────────────┤
            │ ⚙ 通用设置│  权限                               │
            │ □ 模型    │  选择新会话的默认权限模式  [工作区…▾] │
            │ # 内置插件│                                     │
            │ ⚙ Agent预设│  语言                              │
            │          │                    [中文 ▾]         │
            │          │  外观                               │
            │          │  ┌────┐┌────┐┌────────┐             │
            │          │  │浅色││深色││跟随系统│             │
            │          │  └────┘└────┘└────────┘             │
            └──────────┴─────────────────────────────────────┘

        要点（我都照做了）：
            · 大圆角卡片
            · 【左侧导航】分三类，点着切
            · 右侧每项 = 粗体标题 + 小灰字说明 + 右侧控件
            · 开关用滑块样式（不是两个按钮）
            · 每项之间一条细线分隔
        """
        h = {}
        # 遮罩
        scr.rect([0, 62, scr.w, scr.h], fill=(18, 10, 8))

        # ── 卡片 ──
        P = [72, 72, 952, 560]
        scr.rrect(P, 16, fill=(44, 29, 24), outline=(108, 74, 58), width=2)
        NAV_W = 186

        # 标题栏
        scr.text((P[0] + 24, P[1] + 32), "设置", 25, (245, 245, 245),
                 anchor="lm", cn=True)
        h["close"] = [P[2] - 62, P[1] + 12, P[2] - 14, P[1] + 52]
        btn(scr, h["close"], "×", fill=(72, 44, 52), size=22, radius=9)
        scr.d.line([P[0], P[1] + 64, P[2], P[1] + 64],
                   fill=(52, 64, 92), width=1)

        # ── 左侧导航 ──
        nav = (("general", "通用设置"), ("model", "模型"), ("tools", "工具"))
        ny = P[1] + 80
        for key, label in nav:
            r = [P[0] + 10, ny, P[0] + NAV_W, ny + 40]
            h["nav:%s" % key] = r
            on = (getattr(self, "settings_page", 0) ==
                  {"general": 0, "model": 1, "tools": 2}[key])
            scr.rrect(r, 9, fill=(44, 74, 122) if on else (36, 36, 36))
            # 小图标（三个小方块/横线，区分一下）
            ic = r[0] + 20
            cyi = (r[1] + r[3]) // 2
            if key == "general":
                for k, dy in enumerate((-7, 0, 7)):
                    scr.d.line([ic - 8, cyi + dy, ic + 8, cyi + dy],
                               fill=(150, 175, 215), width=2)
                    scr.d.ellipse([ic + (-4, 3, -2)[k] - 3, cyi + dy - 3,
                                   ic + (-4, 3, -2)[k] + 3, cyi + dy + 3],
                                  fill=(230, 230, 230))
            elif key == "model":
                scr.rrect([ic - 8, cyi - 8, ic + 8, cyi + 8], 4,
                          outline=(150, 175, 215), width=2)
                scr.d.line([ic - 8, cyi, ic + 8, cyi], fill=(150, 175, 215),
                           width=1)
            else:
                scr.d.ellipse([ic - 8, cyi - 8, ic + 8, cyi + 8],
                              outline=(150, 175, 215), width=2)
                scr.d.ellipse([ic - 3, cyi - 3, ic + 3, cyi + 3],
                              fill=(150, 175, 215))
            scr.text((ic + 20, cyi), label, 18,
                     (249, 249, 249) if on else (196, 196, 196),
                     anchor="lm", cn=True)
            ny += 48

        # 导航和内容之间竖线
        scr.d.line([P[0] + NAV_W + 6, P[1] + 72, P[0] + NAV_W + 6, P[3] - 12],
                   fill=(59, 59, 59), width=1)

        # ── 右侧内容 ──
        cx = P[0] + NAV_W + 26          # 内容左边界
        cw = P[2] - cx - 26             # 内容宽
        page = getattr(self, "settings_page", 0)

        def sep(yy):
            scr.d.line([cx, yy, cx + cw, yy], fill=(57, 57, 57), width=1)

        def item(yy, title, desc, **kw):
            """一项：粗体标题 + 小灰字说明；返回标题的 y"""
            scr.text((cx, yy), title, 19, (243, 243, 243), anchor="lm",
                     cn=True)
            scr.text((cx, yy + 24), desc, 14, (132, 148, 176), anchor="lm",
                     cn=True)
            return yy

        if page == 0:
            # ═══ 通用设置 ═══
            y = P[1] + 88
            item(y, "声音", "收到回复后是否从喇叭朗读出来")
            on = not self.muted
            # ★ 开关样式（滑块），照 Harness
            sw = [cx + cw - 96, y + 2, cx + cw - 16, y + 40]
            h["sound_on"] = sw
            scr.rrect(sw, 19, fill=(38, 140, 88) if on else (65, 65, 65))
            kx = (sw[2] - 34) if on else (sw[0] + 4)
            scr.d.ellipse([kx, sw[1] + 4, kx + 30, sw[3] - 4],
                          fill=(249, 249, 249))
            scr.text((cx + cw - 110, y + 21),
                     "有声" if on else "静音", 15,
                     (150, 220, 180) if on else (230, 150, 150),
                     anchor="rm", cn=True)
            y += 62
            sep(y - 12)

            item(y, "拼音输入法", "打开时键盘打字母进拼音缓冲，空格上屏候选")
            pn = bool(getattr(self, "pinyin", True))
            sw2 = [cx + cw - 96, y + 2, cx + cw - 16, y + 40]
            h["pinyin"] = sw2
            scr.rrect(sw2, 19, fill=(38, 140, 88) if pn else (65, 65, 65))
            kx2 = (sw2[2] - 34) if pn else (sw2[0] + 4)
            scr.d.ellipse([kx2, sw2[1] + 4, kx2 + 30, sw2[3] - 4],
                          fill=(249, 249, 249))
            scr.text((cx + cw - 110, y + 21), "开" if pn else "关", 15,
                     (150, 220, 180) if pn else (204, 204, 204),
                     anchor="rm", cn=True)
            y += 62
            sep(y - 12)

            # 模式
            item(y, "推理模式", "云端 / 本地 / 自动（云端不通会自动降级）")
            modes = (("auto", "自动"), ("cloud", "云端"), ("local", "本地"))
            mx = cx + cw - 300
            cur_mode = getattr(self, "mode", "auto")
            for key, label in modes:
                r = [mx, y + 2, mx + 92, y + 40]
                h["mode:%s" % key] = r
                onk = (key == cur_mode)
                btn(scr, r, label,
                    fill=(44, 104, 168) if onk else (45, 45, 45),
                    size=16, cn=True, radius=8,
                    outline=(110, 170, 235) if onk else None)
                mx += 98

        elif page == 1:
            # ═══ 模型 ═══
            y = P[1] + 88
            item(y, "默认模型", "新对话用哪个；也可以点主界面上的模型按钮切换")
            y += 44
            if not self.models:
                scr.text((cx, y + 16), "（还没拉到模型列表 —— 打开设置会自己拉）",
                         15, (151, 151, 151), anchor="lm", cn=True)
                y += 44
            # ★★★ 模型列表【分页】显示（用户："好像只能显示四个？加个翻页？"）
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
                if m not in ("deepseek-flash", "deepseek-v4-pro") \
                        and "本地" not in m:
                    nm = m + "  （自定义）"
                scr.text((cc + 18, ccy), nm, 16,
                         (245, 245, 245) if onm else (206, 206, 206),
                         anchor="lm", cn=True)
                y += 38
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
                y += 34
            # ★★★ 「＋ 添加模型」（用户："能添加模型吗"）
            #   点它进入文本输入模式（复用 API Key 那套 UI），
            #   打完回车写进 extra_models，列表立刻多一项。
            h["addmodel"] = [cx, y, cx + 190, y + 34]
            btn(scr, h["addmodel"], "＋ 添加模型", fill=(40, 96, 70),
                size=16, cn=True, radius=9)
            scr.text((cx + 202, y + 17), "输入模型名，如 deepseek-chat",
                     13, (140, 152, 176), anchor="lm", cn=True)
            y += 38
            sep(y - 6)

            item(y, "API Key", "云端推理用的密钥；不配置就只能用本地")
            y += 44
            scr.text((cx, y + 16),
                     ("已配置" if self.has_key else "没配置"),
                     16, (140, 220, 170) if self.has_key else (245, 170, 110),
                     anchor="lm", cn=True)
            scr.d.ellipse([cx + 74, y + 10, cx + 86, y + 22],
                          fill=(90, 220, 150) if self.has_key
                          else (230, 130, 90))
            h["key"] = [cx + cw - 160, y, cx + cw - 20, y + 38]
            btn(scr, h["key"], "重新输入", fill=(46, 62, 104), size=16,
                cn=True, radius=9)
            y += 56
            sep(y - 12)

            item(y, "云端地址", getattr(self, "api_base", "") or
                 "https://api.deepseek.com")

        else:
            # ═══ 工具 ═══
            y = P[1] + 88
            item(y, "诊断与维护", "点一下就跑，结果会打到消息区")
            y += 52
            tools = (("selftest", "声学自检", "放音同时录音，验证喇叭和麦克风"),
                     ("probe", "服务状态", "重新检查 agent 和音频服务"),
                     ("say", "朗读上次", "把上一条回复从喇叭念出来"),
                     ("clear", "清屏", "清空消息区（不动对话记录）"))
            for act, label, desc in tools:
                r = [cx, y, cx + cw - 20, y + 48]
                h["tool:%s" % act] = r
                scr.rrect(r, 9, fill=(41, 41, 41), outline=(63, 63, 63))
                scr.text((cx + 16, y + 17), label, 17, (237, 237, 237),
                         anchor="lm", cn=True)
                scr.text((cx + 16, y + 35), desc, 13, (128, 142, 170),
                         anchor="lm", cn=True)
                # 右边一个箭头，暗示可点
                scr.text((r[2] - 14, y + 24), ">", 18, (110, 130, 165),
                         anchor="rm", cn=True)
                y += 56

        self.settings_hit = h

    def draw_sidebar(self, scr):
        """左侧「对话记录栏」—— 对齐 PC 端

        ★ PC 端左边就有一列会话记录，用户明确要求板子也要有。
        板子上按 Enter 发一条消息就存一条，列表里能点着回看。
        （不做多会话文件持久化 —— 板子内存小，而且这个 App 的角色是
          "随时问一句"，不是重型 IM。留 12 条滚动。）
        """
        x0, y0, x1, y1 = SIDE_RECT
        scr.rect([x0, y0, x1, y1], fill=(34, 22, 18))
        scr.d.line([x1, y0, x1, y1], fill=(57, 57, 57), width=1)

        # ── 「＋ 新对话」 ──
        #
        # ★★★ 这里原来还有一行标题「对话记录」画在 y=y0+14 的地方，
        #   而「＋ 新对话」按钮的矩形是 y0+6 ~ y0+40 —— 【两者重叠】，
        #   按钮把标题盖掉大半，只露出上面一小截黑边，
        #   看上去就像按钮底下/上面爬了一行莫名其妙的字。
        #   用户："这个加新对话按钮底下有字，是什么字，能不能删了"
        #   ⇒ 删掉标题。按钮上已经写着「＋ 新对话」，不需要再标"对话记录"。
        btn(scr, SIDE_NEW, "＋ 新对话", fill=(40, 70, 120), size=16, cn=True,
            radius=7)

        # 会话列表
        #
        # ★ 列表底部要停在【设置按钮上方】——
        #   左侧栏现在通到屏幕最底（600），不拦一下的话
        #   会话条目会画到设置按钮上面去。
        #
        # ★★★ 每个条目右侧画一个 × 删除键（用户要的功能）
        items = self.sessions[-12:]
        y = SIDE_LIST_Y
        stop_y = side_set(self.kb_open)[1] - 8
        self.sess_del = []          # [(下标, 矩形)]，给点击用
        for i, _s in enumerate(reversed(items)):
            r = [8, y, x1 - 8, y + SIDE_ROW_H - 4]
            idx = len(self.sessions) - 1 - i
            on = (idx == self.cur_session)
            scr.rrect(r, 7, fill=(38, 62, 108) if on else (48, 32, 26))
            title = self.sess_title(idx)
            # ★ 标题区留出右边的 × 位置
            dr = [r[2] - 30, r[1] + 4, r[2] - 4, r[3] - 2]
            self.sess_del.append((idx, dr))
            t = title if len(title) <= 8 else title[:7] + "…"
            scr.text((r[0] + 8, (r[1] + r[3]) // 2), t, 15,
                     (242, 242, 242) if on else (194, 194, 194),
                     anchor="lm", cn=True)
            # × 删除键
            scr.rrect(dr, 5, fill=(96, 48, 48) if on else (62, 38, 38))
            scr.d.line([dr[0] + 6, dr[1] + 6, dr[2] - 6, dr[3] - 6],
                       fill=(240, 190, 190), width=2)
            scr.d.line([dr[0] + 6, dr[3] - 6, dr[2] - 6, dr[1] + 6],
                       fill=(240, 190, 190), width=2)
            y += SIDE_ROW_H
            if y + SIDE_ROW_H > stop_y:
                break

    def kb_click(self, x, y):
        """处理【候选栏 + 软键盘】的点击；吃掉了返回 True

        ★★★ 为什么抽成方法（用户报的 bug："键盘的 1qaz 点不了"）
        ────────────────────────────────────────────────────────────
        软键盘是【全屏宽】画的（x 从 0 到 1024），最左那一列
        （1 / q / a / z）落在 x ≈ 0~76。

        而左侧栏 SIDE_RECT = [0, 62, 168, 600] 正好盖住 x < 168。

        原来 run() 里的判定顺序是：
            设置键 -> 输入框 -> ★ 侧栏 -> 按钮排 -> 候选栏 -> 键盘
        于是点 1/q/a/z 会先命中侧栏，键盘永远轮不到 —— 整列点不动。

        ★ 修法：把候选栏 + 键盘的判定【提到侧栏前面】，抽成这个方法。
          这也和图层顺序一致（draw() 里键盘是画在侧栏上面的）。
        ────────────────────────────────────────────────────────────
        """
        if not self.kb_open:
            return False

        # ── ① 候选栏 / 常用指令 / 模式切换 ──
        for label, act, r in self.bar_rendered:
            if not hit(r, x, y):
                continue
            if act == "none":
                pass
            elif act.startswith("approve:"):
                _, rid, okf = act.split(":")
                self._approve(rid, okf == "1")
            elif act == "mode":
                self.pinyin = not self.pinyin
                self.py = ""
                self.refresh_cands()
            elif act.startswith("cand:"):
                self.commit(label)
            elif act.startswith("quick:"):
                q = act[6:]
                if not self.busy:
                    self.out("我> " + q)
                    self.ask(q)
                    self.cur = ""
            return True

        # ── ② 软键盘 ──
        k = self.kb.press(x, y)
        if k is None:
            return False
        if k == "<BS>":
            self.backspace()          # ★ 删光标前面的字（不再是"删最后一个"）
        elif k == "<ENTER>":
            # ★★★ 等文本输入时【优先】走这条分支
            #   原来 commit_first() 排在前面，只要拼音缓冲非空就先上屏候选字，
            #   根本轮不到提交 Key —— 这也是"点了配不上"的原因之一。
            _aw = getattr(self, "await_text", None) or (
                "key" if getattr(self, "await_key", False) else None)
            if _aw and self.cur.strip():
                txt = self.cur.strip()
                self.cur = ""
                self.await_text = None
                self.await_key = False
                # ★ 还原进入输入模式前的拼音开关
                self.pinyin = bool(getattr(self, "_pinyin_backup", True))
                self.py = ""
                if _aw == "model":
                    self.add_model(txt)
                else:
                    self.set_key(txt)
            elif self.commit_first():         # 有拼音 -> 先上屏
                pass
            elif self.cur.strip() and not self.busy:
                self.out("我> " + self.cur)
                self.ask(self.cur.strip())
                self.cur = ""
        elif k == " ":
            # ★ 空格键：MiniKeyboard 返回的是【一个空格 " "】，
            #   不是 "<SPACE>" —— 我第一次写成 "<SPACE>" 永远不匹配，
            #   结果有拼音时按空格不会上屏候选字。
            if not self.commit_first():       # 有拼音 -> 先上屏首个候选
                self.insert_text(" ")
        elif k == "<LEFT>":
            # ★ 光标左移（2026-10-03：用户要"闪烁的竖线可以调整输入位置"）
            if self.py:
                self.py = self.py[:-1]
                self.refresh_cands()
            else:
                self.cur_pos = max(0, getattr(self, "cur_pos",
                                              len(self.cur)) - 1)
        elif k == "<RIGHT>":
            self.cur_pos = min(len(self.cur),
                               getattr(self, "cur_pos", len(self.cur)) + 1)
        else:
            # ★ 字母/数字键：拼音模式进拼音缓冲，否则直接进输入框
            if self.pinyin and k.isalnum():
                self.py += k.lower()
                self.refresh_cands()
            else:
                self.insert_text(k)
        return True

    # ══════════════════════════════════════════════════════════════
    #  ★★★ 光标 / 文本插入（2026-10-03）
    # ══════════════════════════════════════════════════════════════
    # 用户："可以有个闪烁的竖线可以调整输入位置，这个你参考苹果的平板"
    #
    # 原来只有 self.cur 一个字符串，所有输入都是 self.cur += x
    # —— 等于光标永远钉在末尾，退格只能删最后一个字，
    #   想改中间的字只能全删重打。
    #
    # 现在加 self.cur_pos（0..len(cur)）：
    #   · 打字/语音/手写的结果都插在 cur_pos 处
    #   · ← → 键移动它
    #   · 退格删它前面那个字
    #   · 输入框里画一条闪烁的竖线标出它
    # ══════════════════════════════════════════════════════════════
    def insert_text(self, s):
        """把 s 插到光标处（所有输入方式都走这里）"""
        if not s:
            return
        p = getattr(self, "cur_pos", None)
        if p is None:
            p = len(self.cur)
        p = max(0, min(int(p), len(self.cur)))
        self.cur = self.cur[:p] + s + self.cur[p:]
        self.cur_pos = p + len(s)
        self.caret_t = time.time()
        self.caret_on = True

    def backspace(self):
        """退格：删光标【前面】那个字（拼音缓冲还非空时先删拼音）"""
        if self.py:
            self.py = self.py[:-1]
            self.refresh_cands()
            return
        p = max(0, min(getattr(self, "cur_pos", len(self.cur)),
                       len(self.cur)))
        if p > 0:
            self.cur = self.cur[:p - 1] + self.cur[p:]
            self.cur_pos = p - 1
            self.caret_t = time.time()
            self.caret_on = True

    def caret_visible(self):
        """光标当前该不该显示（500ms 闪烁一次）"""
        now = time.time()
        if now - getattr(self, "caret_t", 0.0) > 0.5:
            self.caret_t = now
            self.caret_on = not getattr(self, "caret_on", True)
        return getattr(self, "caret_on", True)

    def draw(self, scr, btns):
        scr.clear((22, 12, 10))        # ★ 暖色背景（原先观感）
        header(scr, "系统管家小白")

        # ★★★ 右上角喇叭（豆包式：点一下静音加斜杠，再点恢复）
        draw_speaker(scr, SPEAKER_RECT, self.muted)

        # ★★★ 左侧对话记录栏
        self.draw_sidebar(scr)

        # 消息区
        self.draw_bubbles(scr)

        # ★ 输入框
        _ir = rect_in(scr, self.kb_open)
        # ★★★ 等输入（Key / 模型名）时：整条输入框换个显眼的样子
        #   原来只往消息区写一行小字，界面上完全看不出"现在该你输入了"。
        _aw = getattr(self, "await_text", None) or (
            "key" if getattr(self, "await_key", False) else None)
        if _aw:
            scr.rrect(_ir, 8, fill=(52, 40, 16), outline=(240, 190, 90),
                      width=2)
            if _aw == "model":
                # ★ 模型名要看得见（不像 Key 要打码）—— 打错了要能核对
                lbl = "新模型名: " + self.cur + "_"
            else:
                lbl = "API Key: " + ("*" * min(len(self.cur), 40)) + "_"
            scr.text((_ir[0] + 10, (_ir[1] + _ir[3]) // 2), lbl,
                     18, (255, 226, 170), anchor="lm", cn=True)
            scr.text((_ir[2] - 10, (_ir[1] + _ir[3]) // 2),
                     "回车提交 · 点设置键取消", 14, (250, 200, 120),
                     anchor="rm", cn=True)
        else:
            scr.rrect(_ir, 8, fill=(44, 26, 20), outline=(160, 100, 70))
            # ★★★ 带光标的绘制（2026-10-03）
            #   用户："可以有个闪烁的竖线可以调整输入位置，参考苹果的平板"
            #   做法：把 cur 拆成【光标前】+【光标后】两段画，
            #        中间留出竖线的位置，竖线每 500ms 闪一次。
            cy_txt = (_ir[1] + _ir[3]) // 2
            x_txt = _ir[0] + 10
            prefix = "> "
            p = max(0, min(getattr(self, "cur_pos", len(self.cur)),
                           len(self.cur)))
            # ★ 太长时只显示靠近光标的那一段（免得文字跑出输入框）
            MAXW = 720
            head, tail = self.cur[:p], self.cur[p:]
            shown_head, shown_tail = head, tail
            while (scr.tw(prefix + shown_head + shown_tail, 18, cn=True)
                   > MAXW and (shown_head or shown_tail)):
                if len(shown_head) > len(shown_tail):
                    shown_head = shown_head[1:]
                else:
                    shown_tail = shown_tail[:-1]
            if len(shown_head) < len(head):
                shown_head = "\u2026" + shown_head[1:]
            if len(shown_tail) < len(tail):
                shown_tail = shown_tail[:-1] + "\u2026"
            scr.text((x_txt, cy_txt), prefix + shown_head, 18, (238, 238, 238),
                     anchor="lm", cn=True)
            w_head = scr.tw(prefix + shown_head, 18, cn=True)
            # ★ 闪烁的竖线
            if self.caret_visible():
                cxx = x_txt + w_head + 1
                scr.d.line([cxx, _ir[1] + 6, cxx, _ir[3] - 6],
                           fill=(255, 190, 120), width=2)
            scr.text((x_txt + w_head + 6, cy_txt), shown_tail, 18,
                     (238, 238, 238), anchor="lm", cn=True)
            if self.py:
                scr.text((x_txt + w_head + 6
                          + scr.tw(shown_tail, 18, cn=True), cy_txt),
                         "  [ " + self.py + " ]", 18, (200, 200, 150),
                         anchor="lm", cn=True)
            # 输入框右侧提示：点一下弹键盘
            scr.text((_ir[2] - 10, cy_txt),
                     "点这里打字" if not self.kb_open else "收起键盘",
                     14, (120, 135, 165), anchor="rm", cn=True)

        # ★★★ 左下角设置键
        draw_gear(scr, side_set(self.kb_open), active=self.settings_open)

        # 按钮排（三个输入方式 + 模型 / 模式 / 发送）
        _curmode = getattr(self, "in_mode", IN_KB)
        for name, act, r in btns:
            on = (self.busy == act)
            fill = (150, 90, 40) if on else (52, 70, 120)
            if act.startswith("inmode:"):
                # ★ 当前输入方式高亮，没选中的暗一点
                _m = act.split(":", 1)[1]
                fill = (140, 96, 40) if _m == _curmode else (44, 52, 70)
            elif act == "ask":
                fill = (40, 110, 70) if not on else (150, 90, 40)
            elif act == "mode":
                fill = (44, 74, 108)
            btn(scr, r, name, fill=fill, size=16, cn=True, radius=8)

        if getattr(self, "recording", False):
            _held = time.time() - getattr(self, "rec_t0", time.time())
            scr.text((BAR_RECT[0] + 4, HINT_Y),
                     "● 正在聆听 %.1fs（松开发送 · 移出按钮取消）" % _held,
                     15, (255, 120, 120), anchor="lm", cn=True)
        elif self.busy:
            scr.text((BAR_RECT[0] + 4, HINT_Y), "工作中:" + self.busy,
                     15, (250, 200, 120), anchor="lm", cn=True)
        elif self.pending:
            scr.text((BAR_RECT[0] + 4, HINT_Y),
                     "★ 小白想做上面的操作，等你点头", 15, (250, 190, 110),
                     anchor="lm", cn=True)
        else:
            scr.text((BAR_RECT[0] + 4, HINT_Y),
                     "回车发送 · 点输入框弹键盘", 14, (110, 125, 155),
                     anchor="lm", cn=True)

        # ★★★ 输入面板【只在展开时显示】，按 in_mode 决定画哪一套
        #   600px 高的屏，常驻一个 160px 的软键盘，消息区就只剩 270px 了。
        #   所以默认收起，点输入框才弹（弹出时盖住下半屏）。
        #
        #   ★ 2026-10-03 统一输入面板：原来是写死的键盘，现在按
        #     self.in_mode 分发到 draw_keyboard_panel / draw_voice_panel /
        #     draw_hand_panel。键盘那段代码一行没改，只是搬了家。
        if self.kb_open:
            self.draw_input_panel(scr)
        else:
            self.bar_rendered = []

        # ★★★ 设置页盖在最上层
        if self.settings_open:
            self.draw_settings(scr)

    # ══════════════════════════════════════════════════════════════
    #  ★★★ 统一输入面板（2026-10-03）
    # ══════════════════════════════════════════════════════════════
    def set_input_mode(self, m):
        """切换输入方式（按钮排上的三个小按钮）"""
        if m not in IN_MODES:
            return
        self.in_mode = m
        if m in (IN_VOICE, IN_HAND):
            self.kb_open = True        # 语音/手写也要占下半屏
            self.pinyin = False        # 别让拼音缓冲捣乱
            self.py = ""
        if m == IN_VOICE:
            # ★ 立刻算好大按钮位置 —— 否则"切过去的第一帧"里
            #   voice_rect() 还是 None（那个值本来要等 draw 才设），
            #   手指快的话这一帧的按下就丢了。
            self.voice_big = [312, KB_Y + 6, 712, 588]
            self.hand_msg = ""
        elif m == IN_HAND:
            self.hand_msg = "在白色区域写字，写完点「识别」"
        else:
            self.hand_msg = ""

    def draw_input_panel(self, scr):
        """按当前输入方式画下半屏面板（三者共用同一块区域）"""
        m = getattr(self, "in_mode", IN_KB)
        if m == IN_HAND:
            self.draw_hand_panel(scr)
        elif m == IN_VOICE:
            self.draw_voice_panel(scr)
        else:
            self.draw_keyboard_panel(scr)

    def input_panel_click(self, x, y):
        """把点击分发给当前输入方式；True = 这次点击被面板消费掉了"""
        m = getattr(self, "in_mode", IN_KB)
        if m == IN_HAND:
            return self.hand_click(x, y)
        if m == IN_VOICE:
            return False        # 语音靠 down/up（按住说话），不走"点击"
        return self.kb_click(x, y)

    def draw_keyboard_panel(self, scr):
        """★ 键盘面板 —— 从 draw() 原样搬过来（逻辑一行没动）"""
        if self.kb_open:
            scr.rect([0, KB_Y - 44, scr.w, scr.h], fill=(26, 16, 12))
            scr.rrect(CAND_RECT_KB, 8, fill=(32, 20, 16),
                      outline=(61, 61, 61))
            items = self.bar_items(scr)
            self.bar_rendered = items
            for i, (label, act, r) in enumerate(items):
                if act == "none":
                    scr.rrect(r, 7, fill=(92, 62, 22),
                              outline=(210, 150, 60))
                    scr.text((r[0] + 10, (r[1] + r[3]) // 2), label, 15,
                             (255, 226, 170), anchor="lm", cn=True)
                elif act == "approve:all:0":
                    btn(scr, r, label, fill=(120, 60, 60), size=15, cn=True,
                        radius=7)
                elif act.startswith("approve:"):
                    got = act.endswith(":1")
                    btn(scr, r, label,
                        fill=(36, 130, 78) if got else (140, 64, 60),
                        size=17, cn=True, radius=7)
                elif act == "mode":
                    btn(scr, r, label, fill=(40, 90, 150), size=16, cn=True,
                        radius=7)
                elif act.startswith("cand:"):
                    on = act == "cand:0"
                    btn(scr, r, label,
                        fill=(90, 70, 30) if on else (44, 56, 84),
                        size=19, cn=True, radius=7,
                        outline=(240, 190, 90) if on else (70, 82, 110))
                else:
                    btn(scr, r, label, fill=(36, 62, 52), size=15, cn=True,
                        radius=7, outline=(60, 110, 90))
            self.kb.draw(scr)

    # ──────────────────────────────────────────────────────────────
    #  语音面板
    # ──────────────────────────────────────────────────────────────
    def voice_panel_rect(self):
        """语音面板占的区域（和键盘一样：下半屏）"""
        return [0, KB_Y - 44, 1024, 600]

    def draw_voice_panel(self, scr):
        """语音面板：大号按住说话 + 状态提示

        ★ 真正的按下/松开逻辑在 run() 里（靠 Touch 的 down/up 事件），
          这里只负责画。
        """
        scr.rect([0, KB_Y - 44, 1024, 600], fill=(26, 16, 12))
        rec = getattr(self, "recording", False)
        cancel = getattr(self, "rec_cancel", False)

        # 状态条（复用候选栏那条位置）
        cr = [190, KB_Y - 40, 1002, KB_Y - 4]
        scr.rrect(cr, 8, fill=(38, 22, 18), outline=(70, 50, 40))
        if rec:
            held = time.time() - getattr(self, "rec_t0", time.time())
            if cancel:
                tip, col = "松开取消（手指已移出按钮）", (255, 210, 140)
            else:
                tip, col = ("● 正在聆听 %.1fs  松开发送" % held,
                            (255, 140, 140))
        else:
            tip, col = ("按住下面的大按钮说话；手指上滑到按钮外松手 = 取消",
                        (200, 200, 205))
        scr.text((cr[0] + 12, (cr[1] + cr[3]) // 2), tip, 16, col,
                 anchor="lm", cn=True)

        # 大号"按住说话"
        self.voice_big = [312, KB_Y + 6, 712, 588]
        br = self.voice_big
        if rec:
            fill = (90, 90, 90) if cancel else (170, 55, 55)
            label = "松开取消" if cancel else "● 聆听中…"
            outline = (200, 120, 120)
        else:
            fill, label, outline = (46, 96, 72), "按住 说 话", (90, 170, 130)
        scr.rrect(br, 24, fill=fill, outline=outline, width=3 if rec else 2)
        scr.text(((br[0] + br[2]) // 2, (br[1] + br[3]) // 2 - 8), label, 34,
                 (255, 255, 255), anchor="mm", cn=True)
        scr.text(((br[0] + br[2]) // 2, br[3] + 10),
                 "（也可点上面的输入框，切回键盘打字）", 14, (150, 150, 155),
                 anchor="mm", cn=True)

    # ──────────────────────────────────────────────────────────────
    #  手写面板
    # ──────────────────────────────────────────────────────────────
    def hand_panel_rect(self):
        """手写画板区域"""
        return [190, KB_Y - 40, 1002, 556]

    def hand_buttons(self):
        """手写面板上的按钮"""
        x0, y0, x1, y1 = self.hand_panel_rect()
        by0, by1 = y1 + 8, 594
        b = []
        x = x0
        for label, act, w in (("识 别", "hand:recog", 100),
                              ("清 除", "hand:clear", 100),
                              ("撤 销", "hand:undo", 100),
                              ("退 格", "hand:bs", 100)):
            b.append((label, act, [x, by0, x + w, by1]))
            x += w + 8
        b.append(("切回键盘", "hand:kb", [x1 - 130, by0, x1, by1]))
        return b

    def draw_hand_panel(self, scr):
        """手写面板：白底画板 + 笔迹 + 操作按钮

        ★ 识别原理：把笔迹渲染成 PNG（白底黑字），
          发给百度手写 OCR —— 和语音共用同一个 key，不用另配。
        """
        scr.rect([0, KB_Y - 44, 1024, 600], fill=(26, 16, 12))
        r = self.hand_panel_rect()
        x0, y0, x1, y1 = r
        # 白底：百度手写 OCR 对"白底黑字"识别最好
        scr.rrect(r, 10, fill=(248, 248, 246), outline=(120, 120, 125))
        scr.d.line([x0 + 24, (y0 + y1) // 2, x1 - 24, (y0 + y1) // 2],
                   fill=(226, 226, 222), width=1)

        # 已完成的笔迹
        for st in getattr(self, "hand_strokes", []):
            if len(st) >= 2:
                scr.d.line(st, fill=(18, 18, 22), width=4, joint="curve")
            elif len(st) == 1:
                px, py = st[0]
                scr.d.ellipse([px - 2, py - 2, px + 2, py + 2],
                              fill=(18, 18, 22))
        # 正在画的那一笔
        hc = getattr(self, "hand_cur", None)
        if hc and len(hc) >= 2:
            scr.d.line(hc, fill=(18, 18, 22), width=4, joint="curve")

        if not getattr(self, "hand_strokes", []) and not hc:
            scr.text(((x0 + x1) // 2, (y0 + y1) // 2 - 36),
                     "在白色区域里写字", 24, (188, 188, 188),
                     anchor="mm", cn=True)
            scr.text(((x0 + x1) // 2, (y0 + y1) // 2 + 2),
                     "写完点下面「识 别」", 17, (198, 198, 198),
                     anchor="mm", cn=True)

        if getattr(self, "hand_msg", ""):
            # ★ 画在画板【内部】底部 —— 原来放在 y0-16（画板上方），
            #   正好和输入框(342~378)撞在一起，文字叠着看不清。
            scr.text(((x0 + x1) // 2, y1 - 14), self.hand_msg, 14,
                     (150, 150, 155), anchor="mm", cn=True)

        for label, act, br in self.hand_buttons():
            if act == "hand:recog":
                fill = (40, 96, 70)
            elif act == "hand:kb":
                fill = (58, 50, 46)
            else:
                fill = (52, 62, 88)
            btn(scr, br, label, fill=fill, size=16, cn=True, radius=8)

    def hand_click(self, x, y):
        """手写面板的按钮点击；True = 消费掉了"""
        for label, act, br in self.hand_buttons():
            if hit(br, x, y):
                if act == "hand:clear":
                    self.hand_strokes = []
                    self.hand_cur = None
                    self.hand_msg = "已清除"
                elif act == "hand:undo":
                    if self.hand_strokes:
                        self.hand_strokes.pop()
                        self.hand_msg = "撤销了一笔"
                    else:
                        self.hand_msg = "没有可撤销的"
                elif act == "hand:bs":
                    self.cur = self.cur[:-1]
                    self.hand_msg = "退格（输入框少一个字）"
                elif act == "hand:recog":
                    self.hand_recognize()
                elif act == "hand:kb":
                    self.set_input_mode(IN_KB)
                return True
        return False

    def hand_begin(self, x, y):
        """落笔：开新的一笔"""
        self.hand_cur = [(x, y)]
        self.hand_msg = ""

    def hand_move(self, x, y):
        """移动：往当前笔迹加点（抽稀，点太密没意义还慢）"""
        if self.hand_cur is None:
            return
        lx, ly = self.hand_cur[-1]
        if abs(x - lx) + abs(y - ly) >= 2:
            self.hand_cur.append((x, y))

    def hand_end(self):
        """抬笔：收笔"""
        if self.hand_cur:
            self.hand_strokes.append(self.hand_cur)
            self.hand_cur = None

    def hand_recognize(self):
        """把笔迹渲染成 PNG -> 百度手写 OCR -> 回填输入框"""
        if not self.hand_strokes:
            self.hand_msg = "画板是空的，先写几个字"
            return

        def fn():
            import io as _io
            import base64 as _b64
            import urllib.parse as _up
            import urllib.request as _u
            try:
                from PIL import Image, ImageDraw
            except Exception as e:
                return "手写失败（没装 PIL）: %s" % e
            try:
                # ① 笔迹 -> 白底黑字 PNG
                xs = [p[0] for st in self.hand_strokes for p in st]
                ys = [p[1] for st in self.hand_strokes for p in st]
                if not xs:
                    return "画板是空的"
                pad = 26
                bx0, bx1 = min(xs) - pad, max(xs) + pad
                by0, by1 = min(ys) - pad, max(ys) + pad
                w, h = max(8, bx1 - bx0), max(8, by1 - by0)
                # ★ 百度要求：最短边 >= 15px，最长边别超 4096
                scale = 1.0
                if min(w, h) < 15:
                    scale = 15.0 / min(w, h)
                if max(w, h) * scale > 1400:
                    scale = 1400.0 / max(w, h)
                W2 = max(15, int(w * scale))
                H2 = max(15, int(h * scale))
                im = Image.new("RGB", (W2, H2), (255, 255, 255))
                d = ImageDraw.Draw(im)
                lw = max(2, int(4 * scale))
                for st in self.hand_strokes:
                    pts = [((px - bx0) * scale, (py - by0) * scale)
                           for px, py in st]
                    if len(pts) >= 2:
                        d.line(pts, fill=(0, 0, 0), width=lw, joint="curve")
                    elif pts:
                        d.ellipse([pts[0][0] - 2, pts[0][1] - 2,
                                   pts[0][0] + 2, pts[0][1] + 2],
                                  fill=(0, 0, 0))
                buf = _io.BytesIO()
                im.save(buf, "PNG")
                png = buf.getvalue()

                # ② 百度 token（和语音共用同一个 key）
                if "/home/zynq" not in sys.path:
                    sys.path.insert(0, "/home/zynq")
                from agent import tts
                tok = tts.token()
                url = ("https://aip.baidubce.com/rest/2.0/ocr/v1/handwriting"
                       "?access_token=" + tok)
                body = _up.urlencode(
                    {"image": _b64.b64encode(png).decode()}).encode()
                req = _u.Request(
                    url, data=body,
                    headers={"Content-Type":
                             "application/x-www-form-urlencoded"},
                    method="POST")
                # ★ 用 tts._urlopen —— 它带 CA 兜底（板子系统 CA 不全）
                with tts._urlopen(req, 30) as r:
                    d2 = json.loads(r.read().decode("utf-8", "replace"))
                if d2.get("error_code"):
                    ec = d2.get("error_code")
                    # ★ 错误码 6 = 这个百度 app 没开通该接口的权限。
                    #   实测：语音那套 key 能拿 token、ASR/TTS 都通，
                    #   但【文字识别】整类接口都返回 6 —— 控制台没勾。
                    #   这不是代码问题，去控制台开通即可，所以给一句人话。
                    if str(ec) == "6":
                        return ("手写识别没开通：请到百度智能云控制台，"
                                "给这个应用勾选「手写文字识别」"
                                "（免费额度 500 次/天，和语音共用同一个 key）")
                    return "手写识别失败: %s %s" % (ec, d2.get("error_msg"))
                words = d2.get("words_result") or []
                text = "".join(str(x.get("words", "")) for x in words)
                if not text:
                    return "没认出来（写大一点、字分开一点再试）"
                # ③ 回填输入框 —— 和键盘/语音同一个缓冲、同一个光标位置
                self.insert_text(text)
                self.hand_strokes = []
                return ("手写识别: %s —— 检查后按【回车】发送" % text)
            except Exception as e:
                return "手写失败: %s: %s" % (type(e).__name__, e)
        self._bg("hand", fn)


def run(scr, touch):
    app = AgentApp()
    while True:
        app.pump()

        # ══════════════════════════════════════════════════════════
        #  ★★★ 事件批处理（2026-10-03）—— 治"划斜线变一堆折线"
        # ══════════════════════════════════════════════════════════
        # 用户："画的也不像画板那样流畅，划斜线会变成一堆折线"
        #
        # 根因：原来一帧只取【一个】事件：
        #     ev = touch.poll(move=True)
        #     if ev: ...
        #     app.draw(); scr.flush()
        # poll() 一次 os.read 其实可能解析出好几个 move（手指快速移动时
        # 驱动一批送来多个坐标），但它只是把它们排进队列逐个返回。
        # 一帧取一个 ⇒ 其余的点要等下一帧（还要先跑完 40ms 的全屏重绘）
        # ⇒ 手指划快了，屏幕上就只剩稀疏的几个点，连起来就是折线。
        #
        # 现在改成：一帧把队列里【所有】事件都处理完，再统一重绘一次。
        # 这样移动多快都不丢点。
        # ══════════════════════════════════════════════════════════
        n_move = 0
        need_click = False
        while True:
            ev = touch.poll(move=True)
            if not ev:
                break
            kind, x, y = ev

            # ---- ★ 按住说话：单独处理 down / move / up ----
            vr = app.voice_rect(scr)
            if kind == "down":
                if vr and hit(vr, x, y) and not app.busy:
                    app.voice_begin()
                    continue
            elif kind == "move":
                if app.recording:
                    app.voice_move(hit(vr, x, y) if vr else False)
                    continue
            elif kind == "up":
                if app.recording:
                    app.voice_end(cancel=((not vr) or (not hit(vr, x, y))))
                    continue

            # ---- ★ 手写：在画板上落笔/移动/抬笔 ----
            if (getattr(app, "in_mode", "") == IN_HAND
                    and getattr(app, "kb_open", False)
                    and not app.settings_open):
                _hr = app.hand_panel_rect()
                if kind == "down":
                    if app.hand_click(x, y):
                        continue
                    if hit(_hr, x, y):
                        app.hand_begin(x, y)
                        n_move += 1
                        continue
                elif kind == "move":
                    if getattr(app, "hand_cur", None) is not None:
                        app.hand_move(x, y)     # ★ 每个点都吃，不再丢
                        n_move += 1
                        continue
                elif kind == "up":
                    if getattr(app, "hand_cur", None) is not None:
                        app.hand_end()
                        n_move += 1
                        continue

            # ---- 其它：只在"松开/点击"时触发（按下和移动跳过）----
            if kind in ("down", "move"):
                continue
            need_click = True
            _handle_click(app, scr, x, y)

        btns = app.buttons(scr)
        app.draw(scr, btns)
        # ★ 手写/语音时只刷下半屏（局部 flush 比全屏快很多）
        if n_move and getattr(app, "in_mode", "") == IN_HAND:
            scr.flush([0, KB_Y - 46, scr.w, scr.h])
        else:
            scr.flush()
        time.sleep(0.012 if n_move else 0.03)

    # ★ 退出 App 时兜底存一次对话记录
    try:
        app.save_sessions()
    except Exception:
        pass


def _handle_click(app, scr, x, y):
    """处理一次真正的"点击"（up/tap）—— 从原来的 run() 里搬出来

    ★ 2026-10-03 抽出：run() 现在要做事件批处理，
      点击逻辑整块搬进这个函数，逻辑一行没改。
    """
    if True:
        if True:
            if back_hit(x, y):
                raise _ExitApp()

            # ---- ★ 按住说话：单独处理 down / move / up ----
            vr = app.voice_rect(scr)
            if kind == "down":
                if vr and hit(vr, x, y) and not app.busy:
                    app.voice_begin()
                    continue
            elif kind == "move":
                if app.recording:
                    app.voice_move(hit(vr, x, y) if vr else False)
                    continue
            elif kind == "up":
                if app.recording:
                    app.voice_end(cancel=((not vr) or (not hit(vr, x, y))))
                    continue

            # ---- ★ 手写：在画板上落笔/移动/抬笔（2026-10-03）----
            #   和语音一样靠 down/move/up；手写面板只在 in_mode=="hand"
            #   且面板展开时才有画板区域。
            if (getattr(app, "in_mode", "") == IN_HAND
                    and getattr(app, "kb_open", False)
                    and not app.settings_open):
                _hr = app.hand_panel_rect()
                if kind == "down":
                    if app.hand_click(x, y):
                        continue
                    if hit(_hr, x, y):
                        app.hand_begin(x, y)
                        continue
                elif kind == "move":
                    if getattr(app, "hand_cur", None) is not None:
                        app.hand_move(x, y)
                        continue
                elif kind == "up":
                    if getattr(app, "hand_cur", None) is not None:
                        app.hand_end()
                        continue

            # ---- 其它按钮：只在"松开/点击"时触发（按下和移动跳过）----
            if kind in ("down", "move"):
                continue

            if back_hit(x, y):
                return

            # ══════════════════════════════════════════════════════
            #  ★★★ 设置页开着时，点击只走设置页
            #  （不然点到下面的键盘/候选栏会串味）
            # ══════════════════════════════════════════════════════
            if app.settings_open:
                H = app.settings_hit
                if hit(H.get("close", [0, 0, 0, 0]), x, y):
                    app.settings_open = False
                    continue
                # ★ 左侧导航：切页
                _nav = {"nav:general": 0, "nav:model": 1, "nav:tools": 2}
                _done = False
                for k, pg in _nav.items():
                    if hit(H.get(k, [0, 0, 0, 0]), x, y):
                        app.settings_page = pg
                        _done = True
                        break
                if _done:
                    continue
                # ★ 声音开关（滑块，点一下翻转）
                if hit(H.get("sound_on", [0, 0, 0, 0]), x, y):
                    app.set_muted(not app.muted)
                    continue
                # ★ 拼音开关
                if hit(H.get("pinyin", [0, 0, 0, 0]), x, y):
                    app.pinyin = not app.pinyin
                    app.py = ""
                    app.refresh_cands()
                    continue
                # ★ 推理模式（三个小按钮）
                for mk in ("mode:auto", "mode:cloud", "mode:local"):
                    if hit(H.get(mk, [0, 0, 0, 0]), x, y):
                        app.mode = mk.split(":")[1]
                        _send_mode(app)
                        _done = True
                        break
                if _done:
                    continue
                # ★ 模型 / API Key / 工具
                # ★ 模型列表翻页
                if hit(H.get("mpage:prev", [0, 0, 0, 0]), x, y):
                    app.model_page = max(0, getattr(app, "model_page", 0) - 1)
                    app.settings_open = True
                    continue
                if hit(H.get("mpage:next", [0, 0, 0, 0]), x, y):
                    app.model_page = getattr(app, "model_page", 0) + 1
                    app.settings_open = True
                    continue
                # ★ 添加模型：进入文本输入模式，回车写进 extra_models
                if hit(H.get("addmodel", [0, 0, 0, 0]), x, y):
                    app.start_text_input("model")
                    app.out("★ 请输入要添加的模型名，按【回车】提交"
                            "（如 deepseek-chat / 你自己的模型名）")
                    continue
                if hit(H.get("key", [0, 0, 0, 0]), x, y):
                    # ★ 进入真正可用的「API Key 输入模式」：
                    #   弹键盘 + 关拼音 + 清空输入框（见 start_key_input）
                    app.start_key_input()
                    app.out("★ 请在下面输入框输入 API Key，按【回车】提交"
                            "（点左下角设置键可取消）")
                    continue
                for k, r in list(H.items()):
                    if k.startswith("model:") and hit(r, x, y):
                        app.set_model(k[6:])
                        _done = True
                        break
                if _done:
                    continue
                for k, r in list(H.items()):
                    if not (k.startswith("tool:") and hit(r, x, y)):
                        continue
                    act = k[5:]
                    app.settings_open = False
                    if act == "selftest":
                        app.selftest()
                    elif act == "probe":
                        app.out("正在重新检查服务 ...")
                        app._probe()
                    elif act == "say":
                        app.say()
                    elif act == "clear":
                        app.msgs = []
                        app.lines = []
                    _done = True
                    break
                if _done:
                    continue
                if not hit([72, 72, 952, 560], x, y):
                    app.settings_open = False
                continue

            # ★★★ 右上角喇叭：点一下切静音（豆包式）
            if hit(SPEAKER_RECT, x, y):
                app.set_muted(not app.muted)
                continue

            # ★★★ 左下角设置键
            if hit(side_set(app.kb_open), x, y):
                # ★ 如果正在等 API Key，点设置键 = 取消（把拼音开关还原）
                if getattr(app, "await_text", None) or getattr(app, "await_key", False):
                    app.cancel_key_input()
                    app.out("已取消输入 API Key")
                    continue
                app.settings_open = True
                app.load_settings()
                continue

            # ★★★ 点输入框：弹键盘 / 收键盘
            #   （键盘默认收起，600px 高的屏常驻 160px 软键盘就没法聊天了）
            #
            # ★★ 用【当前的】输入框矩形 —— 键盘弹出时输入框上移到
            #    IN_RECT_KB，不然会和键盘抢点击（就是用户报的那个 bug）。
            if hit(rect_in(scr, app.kb_open), x, y):
                app.kb_open = not app.kb_open
                continue

            # ★★★ 键盘打开时：【候选栏 + 软键盘】优先于左侧栏
            #
            # 用户报的 bug："键盘的 1qaz 点不了"
            #   软键盘是全屏宽画的，最左列（1/q/a/z）在 x≈0~76，
            #   而左侧栏 SIDE_RECT=[0,62,168,600] 盖住了 x<168，
            #   原来侧栏的判定在键盘之前 -> 整列被侧栏抢走。
            #   ★ 提到这里判定（也和图层顺序一致：键盘画在侧栏上面）。
            #
            # ★ 2026-10-03 统一输入面板：改成按 in_mode 分发 ——
            #   键盘走 kb_click（原逻辑没变），手写走 hand_click。
            if app.input_panel_click(x, y):
                continue

            # ★★★ 点会话记录栏
            #
            # ★ 用户报的 bug：
            #   "干嘛老是有那个切换对话出现，出现完还把记录删了"
            #   根因有三条：
            #     ① 点【任意位置】（含空白处）都命中这个分支
            #     ② 切换时 out("切到会话：…") 会往【消息区】写一条 sys 消息
            #     ③ out() 里 msgs = msgs[-200:] 重新绑定，把对话挤没了
            #   ⇒ 现在：只有点到【会话条目】才切换，切换不写消息区，
            #          点空白什么都不做；每条右边还有 × 删除。
            if hit(SIDE_RECT, x, y):
                if hit(SIDE_NEW, x, y):
                    app.new_session()
                    continue
                # ── 删除键优先（它压在条目右端）──
                did_del = False
                for idx, dr in getattr(app, "sess_del", []):
                    if hit(dr, x, y):
                        app.del_session(idx)
                        did_del = True
                        break
                if did_del:
                    continue
                # ── 只有落在真实条目矩形内才切换 ──
                n_max = min(12, len(app.sessions))
                idx_in_list = (y - SIDE_LIST_Y) // SIDE_ROW_H
                if 0 <= idx_in_list < n_max:
                    real = len(app.sessions) - 1 - idx_in_list
                    app.switch_session(real)
                # ★ 点空白也不写日志（原来就是这里在刷"切到会话"）
                continue

            done = False
            for name, act, r in btns:
                if hit(r, x, y):
                    if act.startswith("inmode:"):
                        # ★ 切换输入方式（键盘 / 语音 / 手写）
                        m = act.split(":", 1)[1]
                        app.set_input_mode(m)
                        if m == IN_VOICE:
                            app.out("语音输入：按住下面的大按钮说话，"
                                    "上滑到按钮外松手 = 取消")
                        elif m == IN_HAND:
                            app.out("手写输入：在白色画板里写字，"
                                    "写完点「识 别」")
                        else:
                            app.out("键盘输入")
                    elif act == "ask":
                        if app.cur.strip() and not app.busy:
                            app.out("我> " + app.cur)
                            app.ask(app.cur.strip())
                            app.cur = ""
                    elif act == "model":
                        app.cycle_model()          # ★ 点一下换下一个模型
                    elif act == "mode":
                        app.cycle_mode()           # ★ 点一下轮换模式
                    elif act == "say":
                        app.say()
                    elif act == "listen":
                        app.listen(4.0)
                    elif act == "selftest":
                        app.selftest()
                    elif act == "probe":
                        app.out("正在重新检查服务 ...")
                        app._probe()
                    elif act == "clear":
                        app.lines = []
                    done = True
                    break
            if done:
                continue
            # ★ 候选栏 + 软键盘的判定已经【提到前面】了（见 kb_click）——
            #   原来放在这里，导致左侧栏把键盘最左列（1/q/a/z）抢走。
            #   这里不再重复判定。
        time.sleep(0.03)

    # ★ 退出 App 时兜底存一次对话记录
    try:
        app.save_sessions()
    except Exception:
        pass
