# -*- coding: utf-8 -*-
"""wave_templates.py —— 波形模板学习与形态匹配（V3：谐波特征）

★ 核心思路（最终版）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
用【谐波结构】而不是波形相似度。原因：
  · 波形相似度需要"整数个周期"，实际采样 4096 点几乎不可能是整数周期
    ⇒ 首尾不连续 ⇒ 相关系数只有 0.02~0.4，完全不可用。
  · 谐波结构天然与相位、幅度、周期数无关，只要知道【基频】即可。

各类波形的谐波签名（幅度归一化到基频=1）：
    正弦: H1=1.00  H2≈0     H3≈0     H4≈0     H5≈0
    方波: H1=1.00  H2≈0     H3=0.33  H4≈0     H5=0.20
    三角: H1=1.00  H2≈0     H3=0.11  H4≈0     H5=0.04
    锯齿: H1=1.00  H2=0.50  H3=0.33  H4=0.25  H5=0.20

判定：
    ① 找基频（重采样到 512 点后对前 128 bin 做 DFT，取最大峰）
    ② 算前 6 次谐波幅度
    ③ 归一化（除以 H1）
    ④ 与模板签名比欧氏距离（或者加权余弦）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import json
import math
import os

TPL_FILE = "/home/zynq/.scope_templates.json"
N = 512              # 重采样长度（DFT 用）
NH = 6               # 取前 6 次谐波
MATCH_THRESHOLD = 0.80

LABELS_CN = {
    "sine": "正弦波", "square": "方波", "triangle": "三角波",
    "sawtooth": "锯齿波", "pulse": "脉冲", "noise": "噪声",
    "clipping": "削顶", "custom": "自定义",
}


# ============================================================
# 基础
# ============================================================
def _resample(d, n=N):
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


def _mean(d):
    s = 0.0
    for v in d:
        s += v
    return s / len(d) if d else 0.0


def _dft_mag(x, k):
    """算第 k 个频点的幅度（Goertzel 简化版，O(N)）"""
    n = len(x)
    if n == 0 or k <= 0 or k >= n // 2:
        return 0.0
    w = 2.0 * math.pi * k / n
    cw = math.cos(w)
    sw = math.sin(w)
    re = 0.0
    im = 0.0
    # 递推（比直接算 cos(k*i*w) 快很多）
    cr = 1.0
    ci = 0.0
    for v in x:
        re += v * cr
        im += v * ci
        # (cr,ci) *= (cw,sw) 的复数旋转
        nr = cr * cw - ci * sw
        ni = cr * sw + ci * cw
        cr, ci = nr, ni
    return math.sqrt(re * re + im * im) * 2.0 / n


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


def harmonics(data, n=N, nh=NH):
    """返回前 nh 次谐波幅度（归一化到 H1=1）；失败返回 None

    步骤：
      ① 去均值 + 重采样到 n 点
      ② 对 bin 2..n/4 做 DFT，找最大峰 = 基频 bin k0
      ③ 取 k0, 2k0, 3k0... 的幅度
      ④ 除以 H1
    """
    d = [float(v) for v in data]
    if len(d) < 16:
        return None
    m = _mean(d)
    d = [v - m for v in d]
    mx = 0.0
    for v in d:
        a = v if v >= 0 else -v
        if a > mx:
            mx = a
    if mx < 1e-9:
        return None
    d = [v / mx for v in d]
    x = _resample(d, n)

    # 找基频峰
    kmax = n // 4
    best_k, best_m = 0, 0.0
    for k in range(2, kmax):
        mg = _dft_mag(x, k)
        if mg > best_m:
            best_m, best_k = mg, k
    if best_k <= 0 or best_m < 1e-6:
        return None

    hs = []
    for j in range(1, nh + 1):
        k = best_k * j
        if k >= n // 2:
            hs.append(0.0)
        else:
            hs.append(_dft_mag(x, k))
    if hs[0] < 1e-9:
        return None
    return [round(h / hs[0], 4) for h in hs]


# ============================================================
# 模板库
# ============================================================
def _math_harmonics():
    """数学波形的谐波签名（理论值）"""
    t = {}
    t["sine"] = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0]
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
    """读模板库（这里只存 label，签名从实测谐波算）"""
    try:
        with open(TPL_FILE, encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict) and d:
            out = {}
            for k, v in d.items():
                if isinstance(v, dict) and isinstance(v.get("harm"), list) and len(v["harm"]) >= 3:
                    out[k] = v
            if out:
                return out
    except Exception:
        pass
    base = _math_harmonics()
    out = {}
    for k, v in base.items():
        out[k] = {"label_cn": LABELS_CN.get(k, k), "harm": v,
                  "crest": round(_crest_of_harm(v), 3), "source": "math"}
    save(out)
    return out


def _crest_of_harm(h):
    """从谐波签名估算峰值因数（大致）"""
    return 0.0


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
    """用实测波形学一个模板（存谐波签名）"""
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
    """加权欧氏距离。前几次谐波权重更大。"""
    n = min(len(a), len(b))
    s = 0.0
    ws = 0.0
    for i in range(n):
        w = 1.0 / (1.0 + i)          # H1 权重 1.0, H2 0.5, H3 0.33 ...
        d = a[i] - b[i]
        s += w * d * d
        ws += w
    return math.sqrt(s / ws) if ws > 0 else 1.0


def _sim(a, b):
    """把距离转成 0~1 的相似度"""
    d = _dist(a, b)
    return max(0.0, 1.0 - d * 1.6)


def best_match(data, tpls=None):
    """返回 (category, label_cn, score, scores)"""
    if tpls is None:
        tpls = load()

    # 平线检测
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
    print("=== 谐波签名自测 ===")
    for cat in ["sine", "square", "triangle", "sawtooth"]:
        base = _math_harmonics()[cat]
        vals = []
        for i in range(4096):
            p = (i / 1100.0) % 1.0      # 3.7 个周期
            if cat == "sine":
                v = math.sin(2 * math.pi * p)
            elif cat == "square":
                v = 1.0 if p < 0.5 else -1.0
            elif cat == "triangle":
                v = 1.0 - 4.0 * abs(p - 0.5)
            else:
                v = -1.0 + 2.0 * p
            vals.append(v * 300 + 500)
        h = harmonics(vals)
        t0 = time.time()
        c, cn, s, allsc = best_match(vals, tpls)
        dt = (time.time() - t0) * 1000
        ok = (c == cat)
        print("  %-9s -> %-10s score=%.3f %s  (%0.0f ms)" % (
            cat, c, s, "OK" if ok else "X", dt))
        print("     实测谐波:", h)
        print("     理论谐波:", base)

    print()
    print("=== 幅度变化测试（识别应不变）===")
    for amp in [10, 50, 200, 400]:
        vals = []
        for i in range(4096):
            p = (i / 1100.0) % 1.0
            vals.append(math.sin(2 * math.pi * p) * amp + 500)
        c, cn, s, _ = best_match(vals, tpls)
        print("  amp=%3d -> %-10s score=%.3f" % (amp, c, s))
