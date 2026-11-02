"""
explain.py —— 中文分析文本生成（契约 §3：纯文本、≤70 字、可直接 TTS）

★★ 设计取舍：为什么默认是"受控生成"而不是端到端大模型
   · 硬约束是 ≤70 字 + 纯文本 + 能直接朗读 + 断网可用 + 单次 ≤8 s。
   · 事实（类别/频率/峰峰/质量分/异常判据）已经在前面几步算出来了，
     语言层要做的是**把事实说准、说短**，而不是重新推理。
   · 所以默认走"模板 + 优先级裁剪"：每个数字都来自上游，零幻觉；
     同时预留 LLM 润色接口（OpenAI 兼容），配置了就把这句话改写得更自然，
     但**数字与结论不变**，超长/带格式/调用失败一律回退模板。

★ TTS 友好：单位全部用中文（伏/赫兹/微秒/分贝/纳秒），不用 µs、dB、V、%、emoji。
"""
from __future__ import annotations

import json
import os
import re
import urllib.request

MAX_DEFAULT = 70


# ---------------------------------------------------------------------------
# 数字格式化（全部中文单位）
# ---------------------------------------------------------------------------
def _num(v, nd=1):
    if v is None:
        return None
    a = abs(float(v))
    if a >= 100:
        return "%.0f" % v
    if a >= 10:
        return "%.1f" % v
    return "%.2f" % v if a < 1 else "%.1f" % v


def fmt_hz(v):
    if v is None:
        return None
    v = float(v)
    if v >= 1e6:
        return "%.2f兆赫兹" % (v / 1e6)
    if v >= 1e3:
        return "%.2f千赫兹" % (v / 1e3)
    return "%.0f赫兹" % v


def fmt_v(v):
    return None if v is None else "%.2f伏" % float(v)


def fmt_pct(v, nd=1):
    return None if v is None else ("%.*f%%" % (nd, float(v)))


def fmt_us(v):
    return None if v is None else "%.1f微秒" % float(v)


def fmt_ns(v):
    return None if v is None else "%.0f纳秒" % float(v)


def fmt_db(v):
    return None if v is None else "%.0f分贝" % float(v)


def _qual_phrase(score):
    if score is None:
        return None
    s = int(score)
    if s >= 90:
        return "质量优秀%d分" % s
    if s >= 75:
        return "质量良好%d分" % s
    if s >= 60:
        return "质量一般%d分" % s
    return "质量偏差%d分" % s


def _conf_phrase(conf):
    c = float(conf or 0.0)
    if c >= 0.85:
        return ""
    if c >= 0.65:
        return "较可能为"
    if c >= 0.50:
        return "可能为"
    return "疑似"


# 每类一句"人话描述"，让文本不只是报类别名
DESCR = {
    "sine": "连续平滑",
    "square": "高低两电平",
    "triangle": "上升下降均匀",
    "sawtooth": "单向缓变后陡降",
    "noise": "无明显周期",
    "clipping": "峰顶被限幅削平",
    "signal_loss": "出现平坦段",
    "duty_abnormal": "高低占比失衡",
    "pulse": "孤立窄脉冲",
    "step": "单次电平跳变",
    "am": "幅度被低频调制",
    "fm": "频率疏密交替",
    "ringing": "边沿后振铃",
    "double_freq": "两个频率叠加",
    "hum": "基线缓慢漂移",
    "glitch": "叠加窄脉冲毛刺",
}

# 类别自带的处理建议（非"异常"也要给一句可执行的话）
ADVICE = {
    "noise": "建议检查信号源与探头接地",
    "signal_loss": "建议检查信号源连接",
    "clipping": "建议降低增益或减小信号幅度",
    "glitch": "建议检查探头接地与走线",
    "hum": "建议检查电源纹波与地环路",
    "ringing": "建议检查阻抗匹配与探头补偿",
}


# ---------------------------------------------------------------------------
# 主体
# ---------------------------------------------------------------------------
def build_clauses(label, label_cn, confidence, info, quality, anomaly,
                  for_voice=True, want_quality=True):
    """按重要性返回子句列表（越靠前越不能删）"""
    f = info or {}
    q = quality or {}
    a = anomaly or {}
    cl = []

    pre = _conf_phrase(confidence)
    if a.get("is_anomaly"):
        feats = "、".join((a.get("features") or [])[:2]) or "特征异常"
        if float(confidence or 0) < 0.45:
            cl.append("疑似未知异常：" + feats)
        else:
            cl.append("疑似异常：" + feats + "，最接近" + (label_cn or label))
    elif pre == "疑似":
        cl.append("疑似" + (label_cn or label) + "，与已知类别匹配度低")
    else:
        cl.append((pre + (label_cn or label)) if pre else (label_cn or label))

    desc = DESCR.get(label)
    if desc and not a.get("is_anomaly"):
        cl.append(desc)

    # 关键量测：频率 + 峰峰（非周期性类别不要硬报频率）
    if f.get("freq_hz") and label not in ("noise", "signal_loss", "pulse", "step"):
        cl.append(fmt_hz(f["freq_hz"]))
    if f.get("vpp_v") is not None:
        cl.append("峰峰" + fmt_v(f["vpp_v"]))
    if label in ("square", "duty_abnormal", "pulse") and f.get("duty_pct") is not None:
        cl.append("占空比" + fmt_pct(f["duty_pct"]))

    # 建议放在质量前面：内容是"可执行动作"，比评分更不该被裁掉
    if a.get("is_anomaly") and a.get("suggestion"):
        cl.append(a["suggestion"])
    elif label in ADVICE:
        cl.append(ADVICE[label])

    # 质量
    if want_quality and q.get("applicable") and q.get("score") is not None:
        cl.append(_qual_phrase(q["score"]))
        if q.get("rise_us") is not None and q["rise_us"] < 1000:
            cl.append("上升" + fmt_us(q["rise_us"]))
        elif q.get("snr_db") is not None:
            cl.append("信噪比" + fmt_db(q["snr_db"]))
        if label in ("sine", "triangle", "sawtooth") and q.get("thd_pct") is not None:
            cl.append("谐波失真" + fmt_pct(q["thd_pct"]))
        if q.get("jitter_ns") is not None and q["jitter_ns"] < 500:
            cl.append("抖动" + fmt_ns(q["jitter_ns"]))

    # 异常建议 / 类别建议（已在上面按优先级插入，这里只处理"注意"类弱提示）
    if a.get("features") and not a.get("is_anomaly") and label not in ADVICE and \
            label not in ("clipping", "glitch", "am", "hum", "ringing",
                          "signal_loss", "noise"):
        cl.append("注意" + "、".join(a["features"][:1]))

    # 备注（低优先级）
    notes = [n for n in (q.get("notes") or []) if n]
    if notes and not a.get("is_anomaly"):
        cl.append(notes[0])
    return [c for c in cl if c]


def render(clauses, max_chars=MAX_DEFAULT):
    """贪心拼接：超长就从末尾丢子句，保证是完整的一句话"""
    if not clauses:
        return "无有效波形数据。"
    out = []
    for c in clauses:
        cand = "，".join(out + [c]) + "。"
        if len(cand) <= max_chars:
            out.append(c)
        elif not out:
            out.append(c[:max_chars - 1])
    if not out:
        out = [clauses[0][:max_chars - 1]]
    text = "，".join(out) + "。"
    return text


_ILLEGAL = re.compile(r"[*#`_\[\]{}<>|~^\\]|\r|\n|\t")
_EMOJI = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF]")


def clean_text(s):
    """去掉 Markdown/emoji/控制符，压掉多余标点（TTS 会把它们念出来）"""
    s = _ILLEGAL.sub("", str(s))
    s = _EMOJI.sub("", s)
    s = re.sub(r"[。．.!！?？]{2,}", "。", s)
    s = re.sub(r"[，,、]{2,}", "，", s)
    s = re.sub(r"\s+", "", s)
    return s.strip()


# ---------------------------------------------------------------------------
# 可选 LLM 润色（OpenAI 兼容；失败自动回退）
# ---------------------------------------------------------------------------
def _llm_config():
    url = os.environ.get("WAVE_LLM_URL", "").strip()
    if not url:
        return None
    return {
        "url": url,
        "model": os.environ.get("WAVE_LLM_MODEL", "deepseek-chat"),
        "key": os.environ.get("WAVE_LLM_KEY", ""),
        "timeout": float(os.environ.get("WAVE_LLM_TIMEOUT", "2.0")),
    }


def llm_polish(text, max_chars, cfg=None):
    cfg = cfg or _llm_config()
    if not cfg:
        return None
    prompt = ("把下面这句示波器测量结论改写成一句更自然的中文口语，"
              "不超过%d字，保留所有数字和结论，不要 Markdown、不要列表、不要表情：\n%s"
              % (max_chars, text))
    body = json.dumps({
        "model": cfg["model"],
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "max_tokens": 160,
    }).encode("utf-8")
    req = urllib.request.Request(cfg["url"], data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    if cfg["key"]:
        req.add_header("Authorization", "Bearer " + cfg["key"])
    try:
        with urllib.request.urlopen(req, timeout=cfg["timeout"]) as r:
            data = json.loads(r.read().decode("utf-8"))
        out = data["choices"][0]["message"]["content"]
        out = clean_text(out)
        if not out or len(out) > max_chars:
            return None
        if not out.endswith("。"):
            out += "。"
        return out
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 对外入口
# ---------------------------------------------------------------------------
def make_text(label, label_cn, confidence, info, quality=None, anomaly=None,
              max_chars=MAX_DEFAULT, for_voice=True, want_quality=True,
              use_llm=True):
    clauses = build_clauses(label, label_cn, confidence, info, quality, anomaly,
                            for_voice=for_voice, want_quality=want_quality)
    text = render(clauses, max_chars)
    source = "template"
    if use_llm:
        polished = llm_polish(text, max_chars)
        if polished:
            text, source = polished, "llm"
    text = clean_text(text)
    if len(text) > max_chars:
        text = text[:max_chars - 1] + "。"
    return {
        "text": text,
        "chars": len(text),
        "tts_ready": True,
        "source": source,
        "max_chars": int(max_chars),
    }


def explain_result(result, style=None):
    """契约 §3.2：输入融合结果 R，输出一句话分析（不再跑视觉模型）"""
    style = style or {}
    r = (result or {}).get("result", result or {})
    label = r.get("label", "unknown")
    from .config import CN
    label_cn = r.get("label_cn") or CN.get(label, label)
    meas = r.get("measurements") or {}
    qual = r.get("quality") or {}
    # 把 R 里的量测映射成 info 结构
    info = {
        "freq_hz": meas.get("freq_hz"),
        "vpp_v": meas.get("vpp_v"),
        "duty_pct": meas.get("duty_pct"),
        "vmax_v": meas.get("vmax_v"),
        "vmin_v": meas.get("vmin_v"),
    }
    q = {
        "applicable": bool(qual.get("score") is not None or qual.get("snr_db") is not None),
        "score": qual.get("score"),
        "rise_us": qual.get("rise_us") or meas.get("rise_us"),
        "fall_us": qual.get("fall_us") or meas.get("fall_us"),
        "snr_db": qual.get("snr_db"),
        "thd_pct": qual.get("thd_pct"),
        "jitter_ns": qual.get("jitter_ns"),
        "notes": [],
    }
    anom = r.get("anomaly") or {}
    t = make_text(label, label_cn, r.get("confidence", 0.0), info, q, anom,
                  max_chars=int(style.get("max_chars", MAX_DEFAULT)),
                  for_voice=bool(style.get("for_voice", True)),
                  want_quality=True)
    t["confidence"] = float(r.get("confidence", 0.0) or 0.0)
    return t


if __name__ == "__main__":
    print(make_text("square", "方波", 0.97,
                    {"freq_hz": 998.5, "vpp_v": 1.008, "duty_pct": 49.9},
                    {"applicable": True, "score": 87, "rise_us": 1.2, "snr_db": 42.0},
                    {"is_anomaly": False, "features": []}))
    print(make_text("noise", "噪声", 0.93, {"vpp_v": 0.31, "freq_hz": None},
                    {"applicable": False}, {"is_anomaly": False, "features": []}))
    print(make_text("double_freq", "双频叠加", 0.42,
                    {"freq_hz": 2000, "vpp_v": 0.8},
                    {"applicable": True, "score": 66, "snr_db": 28},
                    {"is_anomaly": True, "features": ["双频叠加", "轻度削顶"],
                     "suggestion": "可能为两个信号源叠加或通道串扰"}))
