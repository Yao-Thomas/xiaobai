# -*- coding: utf-8 -*-
"""wave_templates.py —— 波形模板学习与形态匹配（V4：整数周期 + 谐波）

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
为什么用谐波结构
  波形相似度需要"整数个周期"，实际 4096 点采样几乎不是整数周期
  ⇒ 首尾不连续 ⇒ 相关系数只有 0.02~0.4，不可用。
  谐波结构与相位、幅度、周期数都无关，只要把基频对齐到整数 bin 即可。

关键实现
  ① 零交叉找基频周期（小数点数）
  ② 截取【整数个周期】，重采样到 512 点
     ⇒ 4 个周期时基频正好是 bin 4，谐波在 bin 4/8/12/16/20/24
  ③ Goertzel 算这几个 bin 的幅度
  ④ 除以 H1 归一化 ⇒ 谐波签名

各类波形的签名（H1=1）：
    正弦: [1, ~0,    ~0,   ~0,   ~0,   ~0  ]
    方波: [1, ~0,    1/3,  ~0,   1/5,  ~0  ]
    三角: [1, ~0,    1/9,  ~0,   1/25, ~0  ]
    锯齿: [1, 1/2,   1/3,  1/4,  1/5,  1/6 ]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import json
import math
import os

TPL_FILE = "/home/zynq/.scope_templates.json"
NC = 16             # 截取多少个整数周期（多取一些，让谐波落在 Nyquist 以内）
N = 512             # 重采样后的点数（每周期 N/NC 点）
NH = 6              # 谐波次数
MATCH_THRESHOLD = 0.78

LABELS_CN = {
    "sine": "正弦波", "square": "方波", "triangle": "三角波",
    "sawtooth": "锯齿波", "pulse": "脉冲", "noise": "噪声",
    "clipping": "削顶", "custom": "自定义",
}


# ============================================================
# 基础工具
# ============================================================
def _mean(d):
    s = 0.0
    for v in d:
        s += v
    return s / len(d) if d else 0.0


def _resample(d, n):
    m = len(d)
    if m == 0:
        return [0.0] * n
    if m == n:
        return [float(v) for v in d]
    out = []
    step = (m - 1) / float(n - 1) if n > 1 else 0.0
    last = m - 1
    for i in range(n):
        p = i * step
        i0 = int(p)
        if i0 >= last:
            out.append(float(d[last]))
            continue
        t = p - i0
        out.append(float(d[i0]) * (1.0 - t) + float(d[i0 + 1]) * t)
    return out


def find_period(data):
    """零交叉找基频周期（小数点数）。失败返回 None"""
    d = [float(v) for v in data]
    if len(d) < 16:
        return None
    m = _mean(d)
    x = [v - m for v in d]

    ups = []
    for i in range(1, len(x)):
        if x[i - 1] <= 0.0 < x[i]:
            den = x[i] - x[i - 1]
            if abs(den) > 1e-12:
                ups.append((i - 1) + (-x[i - 1]) / den)
    if len(ups) < 3:
        return None
    # 第 1 个到最后一个上升过零点的平均间隔（最稳）
    per = (ups[-1] - ups[0]) / float(len(ups) - 1)
    if per < 8.0:
        return None
    # 至少要能放 2 个周期
    if per * 2 > len(x):
        return None
    return per


def integer_cycles(data, nc=NC):
    """截取 nc 个整数周期，返回 (截取后的数据, 周期长度)。失败返回 (data, None)"""
    per = find_period(data)
    if per is None:
        return list(data), None
    need = int(round(per * nc))
    n = len(data)
    if need > n:
        # 降级：能用几个周期用几个
        k = int(n / per)
        if k < 2:
            return list(data), None
        per = per
        need = int(round(per * k))
        if need > n:
            need = n
    if need < 16:
        return list(data), None
    return list(data[:need]), per


def _goertzel(x, k):
    """算第 k 个 bin 的幅度（O(N)）"""
    n = len(x)
    if n == 0 or k <= 0 or k >= n // 2:
        return 0.0
    w = 2.0 * math.pi * k / n
    cw = math.cos(w)
    sw = math.sin(w)
    re = 0.0
    im = 0.0
    cr = 1.0
    ci = 0.0
    for v in x:
        re += v * cr
        im += v * ci
        nr = cr * cw - ci * sw
        ni = cr * sw + ci * cw
        cr, ci = nr, ni
    return math.sqrt(re * re + im * im) * 2.0 / n


def harmonics(data, nc=NC, n=N, nh=NH):
    """返回前 nh 次谐波（归一化 H1=1）。整数周期对齐后基频在 bin n/nc"""
    d = [float(v) for v in data]
    if len(d) < 32:
        return None

    # ★ 截取整数周期
    seg, per = integer_cycles(d, nc)
    if per is None:
        return None

    # 去均值 + 归一化
    m = _mean(seg)
    seg = [v - m for v in seg]
    mx = 0.0
    for v in seg:
        a = v if v >= 0 else -v
        if a > mx:
            mx = a
    if mx < 1e-9:
        return None
    seg = [v / mx for v in seg]

    # 重采样到 n 点 ⇒ 每周期 n/nc 点 ⇒ 基频 bin = n/nc
    x = _resample(seg, n)
    k0 = n // nc           # 基频 bin

    hs = []
    for j in range(1, nh + 1):
        k = k0 * j
        if k >= n // 2:
            hs.append(0.0)
        else:
            hs.append(_goertzel(x, k))
    if hs[0] < 1e-9:
        return None
    return [round(h / hs[0], 4) for h in hs]


def crest_factor(data):
    d = [float(v) for v in data]
    if not d:
        return 0.0
    m = _mean(d)
    d = [v - m for v in d]
    sq = 0.0
    pk = 0.0
    for v in d:
        sq += v * v
        a = v if v >= 0 else -v
        if a > pk:
            pk = a
    rms = math.sqrt(sq / len(d))
    if rms < 1e-9:
        return 0.0
    return pk / rms


# ============================================================
# 模板库
# ============================================================
def _math_harmonics():
    t = {}
    t["sine"] = [1.0] + [0.0] * (NH - 1)
    sq = [1.0]
    for j in range(2, NH + 1):
        sq.append(round(1.0 / j, 4) if j % 2 == 1 else 0.0)
    t["square"] = sq
    tri = [1.0]
    for j in range(2, NH + 1):
        tri.append(round(1.0 / (j * j), 4) if j % 2 == 1 else 0.0)
    t["triangle"] = tri
    saw = [1.0]
    for j in range(2, NH + 1):
        saw.append(round(1.0 / j, 4))
    t["sawtooth"] = saw
    return t


def load():
    try:
        with open(TPL_FILE, encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict) and d:
            out = {}
            for k, v in d.items():
                if isinstance(v, dict) and isinstance(v.get("harm"), list) and len(v["harm"]) >= 3:
                    out[k] = v
            if out:
                for k, v in _math_harmonics().items():
                    if k not in out:
                        out[k] = {"label_cn": LABELS_CN.get(k, k), "harm": v, "source": "math"}
                return out
    except Exception:
        pass
    base = _math_harmonics()
    out = {}
    for k, v in base.items():
        out[k] = {"label_cn": LABELS_CN.get(k, k), "harm": v, "source": "math"}
    save(out)
    return out


def save(tpls):
    try:
        tmp = TPL_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(tpls, f, ensure_ascii=False)
        os.replace(tmp, TPL_FILE)
        try:
            os.chmod(TPL_FILE, 0o644)
        except Exception:
            pass
        return True
    except Exception as e:
        print("[TPL] save failed:", e)
        return False


def learn(category, data, label_cn=None):
    h = harmonics(data)
    if h is None:
        return False, None
    tpls = load()
    tpls[category] = {
        "label_cn": label_cn or LABELS_CN.get(category, category),
        "harm": h,
        "crest": round(crest_factor(data), 3),
        "source": "measured",
    }
    ok = save(tpls)
    return ok, tpls[category]


# ============================================================
# 匹配
# ============================================================
def _dist(a, b):
    n = min(len(a), len(b))
    s = 0.0
    ws = 0.0
    for i in range(n):
        w = 1.0 / (1.0 + i)
        d = a[i] - b[i]
        s += w * d * d
        ws += w
    return math.sqrt(s / ws) if ws > 0 else 1.0


def _sim(a, b):
    return max(0.0, 1.0 - _dist(a, b) * 1.8)


def best_match(data, tpls=None):
    if tpls is None:
        tpls = load()

    d = [float(v) for v in data]
    if d:
        m = _mean(d)
        dd = [v - m for v in d]
        sq = 0.0
        pk = 0.0
        for v in dd:
            sq += v * v
            a = v if v >= 0 else -v
            if a > pk:
                pk = a
        rms = math.sqrt(sq / len(dd))
        if rms < 0.5 or pk < 1.5:
            return ("signal_loss", "信号丢失/平线", 1.0, {"signal_loss": 1.0})

    h = harmonics(data)
    if h is None:
        return (None, None, -1.0, {})

    scores = {}
    for cat, t in tpls.items():
        th = t.get("harm")
        if not isinstance(th, list) or len(th) < 3:
            continue
        scores[cat] = round(_sim(h, th), 4)

    if not scores:
        return (None, None, -1.0, {})

    cat = max(scores, key=scores.get)
    return (cat,
            (tpls.get(cat) or {}).get("label_cn") or LABELS_CN.get(cat, cat),
            scores[cat], scores)


def forced(data, threshold=MATCH_THRESHOLD):
    cat, cn, score, scores = best_match(data)
    if cat is not None and score >= threshold:
        return {"category": cat, "label_cn": cn, "score": score,
                "scores": scores, "crest": round(crest_factor(data), 3)}
    return None


# ============================================================
# 自测
# ============================================================
if __name__ == "__main__":
    import time

    tpls = load()
    print("模板库:", list(tpls.keys()))
    print()

    def gen(cat, amp, per, npts=4096, off=500):
        out = []
        for i in range(npts):
            p = (i / per) % 1.0
            if cat == "sine":
                v = math.sin(2 * math.pi * p)
            elif cat == "square":
                v = 1.0 if p < 0.5 else -1.0
            elif cat == "triangle":
                v = 1.0 - 4.0 * abs(p - 0.5)
            elif cat == "sawtooth":
                v = -1.0 + 2.0 * p
            elif cat == "pulse":
                v = 1.0 if p < 0.15 else -1.0
            else:
                v = 0.0
            out.append(v * amp + off)
        return out

    print("=== 谐波签名 ===")
    for cat in ["sine", "square", "triangle", "sawtooth"]:
        d = gen(cat, 300, 1100)
        h = harmonics(d)
        print("  %-9s 实测 %s" % (cat, h))
        print("  %-9s 理论 %s" % ("", tpls[cat]["harm"]))

    print()
    print("=== 识别（不同幅度/周期）===")
    fail = 0
    total = 0
    for cat in ["sine", "square", "triangle", "sawtooth"]:
        for amp, per in [(40, 1100), (150, 733), (400, 2200), (300, 512)]:
            d = gen(cat, amp, per)
            t0 = time.time()
            c, cn, s, allsc = best_match(d, tpls)
            dt = (time.time() - t0) * 1000
            ok = (c == cat)
            total += 1
            if not ok:
                fail += 1
            print("  %-9s amp=%3d per=%4d -> %-10s score=%.3f %s (%.0fms)" % (
                cat, amp, per, c, s, "OK" if ok else "X", dt))
    print()
    print("失败 %d / %d" % (fail, total))
