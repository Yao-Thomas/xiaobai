#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI 波形识别（服务卡片之一）

链路：
  双通道示波器 PL 采样 → waveform_ai 时频图 → PL CNN → 类别+置信度

★ 两种引擎（顶部可切换）：
  · 本地 CNN  —— PL 硬件加速器（0x43CD0000/0x43CE0000）
                 快（~10ms）、离线、8 类判别 + 概率条
  · 云端 API  —— 板载 agent 的 /intent（纯 LLM、不带工具）
                 把波形统计特征组织成文字问大模型，返回自然语言分析
                 慢（数秒）、需联网、能给"是否正常/可能的问题"这类解释

只用确定存在的接口：
  scope_dual.ScopeDual().read_frame_locked()   -> (ch1, ch2, info)
  infer_local.infer_waveform(data)             -> {"label","confidence","detail"}
  POST http://127.0.0.1:8765/intent {"system":...,"text":...} -> {"reply":...}
"""
import time

# ★ 修复：infer_local.py 在 /home/zynq/，而 app 跑在 /home/zynq/ui/
import sys as _sys
for _p in ("/home/zynq", "/home/zynq/ui"):
    if _p not in _sys.path:
        _sys.path.insert(0, _p)

import urllib.request
import json as _json
from fbui import hit, back_hit

W, H = 1024, 600
TOP_H = 40
C_BG = (12, 16, 32)
C_TITLE = (210, 228, 255)
C_SUB = (140, 165, 200)
C_OK = (90, 220, 150)
C_BAR = (70, 150, 230)
C_WARN = (235, 150, 60)
C_AI = (165, 120, 235)

# 顶部引擎切换
E_LOCAL = [24, 48, 224, 88]
E_CLOUD = [232, 48, 432, 88]

# 底部按钮
B_RE = [24, H - 62, 250, H - 16]
B_CH = [274, H - 62, 500, H - 16]
B_BK = [524, H - 62, 700, H - 16]

# ★ 云端通道用 agent 的 /intent（纯 LLM、不带工具）
#   /chat 是完整 agent（调工具、读知识库），问波形会跑偏，而且 17s；
#   /intent 可自带 system 提示词，实测 1.5s 返回纯中文结论。
INTENT_URL = "http://127.0.0.1:8765/intent"
SETTINGS_URL = "http://127.0.0.1:8765/llm/settings"

WAVE_SYSTEM = (
    "你是一个嵌入式示波器的波形分析助手。"
    "用户会给你一组波形统计数据和本地 CNN 的判别结果。"
    "请用不超过 70 个中文字直接给结论："
    "这是什么信号、是否正常、有没有值得注意的问题。"
    "不要客套、不要对列点、不要说废话。"
)


def _cur_model():
    """读 agent 当前用的模型名"""
    try:
        r = urllib.request.urlopen(SETTINGS_URL, timeout=5)
        return _json.loads(r.read().decode("utf-8", "replace")).get("model")
    except Exception:
        return None


def _btn(scr, r, text, active=True, size=20):
    scr.rrect(r, 8, fill=(40, 54, 76) if active else (26, 32, 42),
              outline=(90, 130, 190) if active else (58, 68, 86), width=2)
    scr.text(((r[0] + r[2]) // 2, (r[1] + r[3]) // 2), text, size,
             (220, 235, 255) if active else (120, 130, 150), anchor="mm", cn=True)


def _wrap(s, n):
    """按字符数粗略折行（中文用）"""
    out, cur = [], ""
    for ch in str(s):
        cur += ch
        if ch == "\n" or len(cur) >= n:
            out.append(cur.rstrip("\n")); cur = ""
    if cur:
        out.append(cur)
    return out


def _cloud_ask(text, timeout=40):
    """走 agent 的 /intent：纯 LLM、不带工具，自带 system 提示词"""
    body = _json.dumps({"system": WAVE_SYSTEM, "text": text,
                        "tools": False, "stateless": True}).encode("utf-8")
    req = urllib.request.Request(INTENT_URL, data=body,
                                 headers={"Content-Type": "application/json"})
    r = urllib.request.urlopen(req, timeout=timeout)
    d = _json.loads(r.read().decode("utf-8", "replace"))
    rep = d.get("reply") or (((d.get("choices") or [{}])[0].get("message") or {}).get("content"))
    if not rep:
        raise RuntimeError(d.get("error") or "云端没回复")
    return str(rep).strip(), float(d.get("elapsed") or 0.0)


def _feat_prompt(data, local_res):
    """把波形统计组织成给大模型的提问"""
    try:
        mn, mx = min(data), max(data)
        pp = (mx - mn) * (10.0 / 1024.0)
        mid = (mx + mn) / 2.0
    except Exception:
        mn = mx = pp = mid = 0.0
    lab = (local_res or {}).get("label") or "未判别"
    conf = float((local_res or {}).get("confidence") or 0.0)
    return ("示波器采到：峰峰值 %.3f V，最高码 %d，"
            "最低码 %d，中点码 %.0f；"
            "本地 CNN 判别：%s（置信度 %.0f%%）。"
            "请给结论。") % (pp, mx, mn, mid, lab, conf * 100)


def _draw(scr, engine, ch, res=None, reply=None, busy=None, err=None):
    scr.clear(C_BG)
    scr.rect([0, 0, W, TOP_H], fill=(18, 24, 40))
    scr.text((20, TOP_H // 2), "AI 波形识别", 20, C_TITLE, anchor="lm", cn=True)
    _mdl = getattr(scr, "_wave_ai_model", "?")
    scr.text((W - 16, TOP_H // 2),
             ("云端：" + str(_mdl)) if engine == "cloud"
             else "本地 PL CNN 加速器",
             15, C_SUB, anchor="rm", cn=True)

    # 引擎切换
    _btn(scr, E_LOCAL, "本地 CNN", active=(engine == "local"), size=20)
    _btn(scr, E_CLOUD, "云端 API", active=(engine == "cloud"), size=20)

    if busy:
        scr.text((W // 2, 210), busy, 28, C_SUB, anchor="mm", cn=True)
    elif err:
        scr.text((W // 2, 180), "失败", 28, C_WARN, anchor="mm", cn=True)
        for i, ln in enumerate(_wrap(err, 46)[:3]):
            scr.text((W // 2, 225 + i * 26), ln, 16, C_SUB, anchor="mm", cn=True)
    elif engine == "local" and res:
        lab = res.get("label") or "?"
        conf = float(res.get("confidence") or 0.0)
        scr.text((W // 2, 148), lab, 64, C_OK, anchor="mm", cn=True)
        scr.text((W // 2, 210), "置信度 %.1f%%   ·   %s ms   ·   CH%d"
                 % (conf * 100, res.get("elapsed_ms", 0), ch + 1),
                 19, C_SUB, anchor="mm", cn=True)
        d = res.get("detail") or {}
        probs = d.get("probs") or []
        names = d.get("classes") or []
        best = 0
        try:
            best = max(range(len(probs)), key=lambda i: probs[i])
        except Exception:
            pass
        x0, y0, bw, bh = 120, 250, 720, 22
        for i, p in enumerate(probs[:8]):
            y = y0 + i * (bh + 5)
            nm = names[i] if i < len(names) else str(i)
            scr.text((x0 - 14, y + bh // 2), nm, 15,
                     C_OK if i == best else C_SUB, anchor="rm", cn=True)
            scr.rect([x0, y, x0 + bw, y + bh], fill=(24, 32, 46))
            frac = max(0.0, min(1.0, float(p)))
            if frac > 0.002:
                scr.rect([x0, y, x0 + int(bw * frac), y + bh],
                         fill=C_OK if i == best else C_BAR)
            scr.text((x0 + bw + 10, y + bh // 2), "%.1f%%" % (float(p) * 100), 14,
                     C_SUB, anchor="lm")
    elif engine == "cloud" and reply:
        scr.text((W // 2, 120), "云端分析", 22, C_AI, anchor="mm", cn=True)
        for i, ln in enumerate(_wrap(reply, 40)[:11]):
            scr.text((60, 165 + i * 32), ln, 21, (220, 232, 255), anchor="lm", cn=True)

    _btn(scr, B_RE, "重新分析")
    _btn(scr, B_CH, "切换通道 (CH%d)" % (ch + 1))
    _btn(scr, B_BK, "返回")
    scr.flush()


def run(scr, touch):
    try:
        return _run_inner(scr, touch)
    except Exception as e:
        import traceback as _tb
        print("[AIAPP-DBG] run crashed: %s: %s" % (type(e).__name__, e))
        _tb.print_exc()
        try:
            scr.clear((12, 16, 32))
            scr.text((512, 300), "AI 识别启动失败: %s" % e, 20, (235, 150, 60),
                     anchor="mm", cn=True)
            scr.flush()
            import time as _t
            _t.sleep(4)
        except Exception:
            pass
        return


def _run_inner(scr, touch):
    import scope_dual
    hw = scope_dual.ScopeDual()
    engine = "local"
    ch = 0
    res = reply = err = None

    def analyze():
        """采一帧 -> 按当前引擎分析"""
        nonlocal res, reply, err
        res = reply = err = None
        _draw(scr, engine, ch, busy=("正在采样并推理 …" if engine == "local"
                                     else "正在询问云端…（可能数秒）"))
        try:
            a1, a2, _info = hw.read_frame_locked()
            data = a1 if ch == 0 else a2
            if engine == "local":
                import infer_local
                res = infer_local.infer_waveform(data)
            else:
                # 云端：先本地判别（作为上下文），再把统计特征发给大模型
                import infer_local
                try:
                    loc = infer_local.infer_waveform(data)
                except Exception:
                    loc = None
                reply, _el = _cloud_ask(_feat_prompt(data, loc))
        except Exception as e:
            err = "%s: %s" % (type(e).__name__, e)
            import traceback as _tb
            print("[AIAPP-DBG] analyze failed: %s: %s" % (type(e).__name__, e))
            _tb.print_exc()
        _draw(scr, engine, ch, res=res, reply=reply, err=err)

    # ★ 查一次当前模型名（供顶栏显示）
    try:
        scr._wave_ai_model = _cur_model() or "?"
    except Exception:
        scr._wave_ai_model = "?"
    analyze()
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
            if kind == "move":
                pass
            elif x < 90 and y < TOP_H + 20:
                try:
                    hw.close()
                except Exception:
                    pass
                return
            else:
                try:
                    if back_hit(x, y):
                        hw.close(); return
                except Exception:
                    pass
                if hit(B_BK, x, y):
                    hw.close(); return
                if hit(E_LOCAL, x, y) and engine != "local":
                    engine = "local"; analyze()
                elif hit(E_CLOUD, x, y) and engine != "cloud":
                    engine = "cloud"; analyze()
                elif hit(B_RE, x, y):
                    analyze()
                elif hit(B_CH, x, y):
                    ch = 1 - ch; analyze()
        time.sleep(0.02)
