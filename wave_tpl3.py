# -*- coding: utf-8 -*-
"""wave_templates_v2.py —— 带周期检测的波形模板匹配

★ 修复：原算法假设信号是整数个周期（用循环平移匹配），
  但实际 4096 点采样不是整数周期 ⇒ 首尾不连续 ⇒ 相关只有 0.02。
  
  ⇒ 新增「周期检测 + 整数周期截取」：
     ① 用过零检测找主周期
     ② 截取整数个周期
     ③ 重采样到固定长度后匹配
"""

import json
import math
import os

TPL_FILE = "/home/zynq/.scope_templates.json"
N = 256
MATCH_THRESHOLD = 0.80

LABELS_CN = {
    "sine": "正弦波", "square": "方波", "triangle": "三角波",
    "sawtooth": "锯齿波", "pulse": "脉冲", "noise": "噪声",
    "clipping": "削顶", "custom": "自定义",
}


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


def _detrend(d):
    """去直流 + 去线性趋势（消除低频漂移和倾斜）"""
    n = len(d)
    if n < 2:
        return [float(v) for v in d]
    s = 0.0
    for v in d:
        s += v
    mean = s / n
    # 线性拟合
    sx = sy = sxx = sxy = 0.0
    for i, v in enumerate(d):
        x = float(i)
        sx += x
        sy += v
        sxx += x * x
        sxy += x * v
    den = n * sxx - sx * sx
    if abs(den) < 1e-9:
        return [float(v) - mean for v in d]
    a = (n * sxy - sx * sy) / den
    b = (sy - a * sx) / n
    return [float(d[i]) - (a * i + b) for i in range(n)]


def find_period(d):
    """用过零检测找主周期（返回小数周期的样本数），失败返回 None"""
    x = _detrend(d)
    n = len(x)
    # 找上升过零点（- → +）
    ups = []
    for i in range(1, n):
        if x[i - 1] <= 0 < x[i]:
            # 线性插值
            t = -x[i - 1] / (x[i] - x[i - 1])
            ups.append(i - 1 + t)
    if len(ups) < 2:
        return None
    # 用相邻上升过零间距的中位数当周期
    gaps = [ups[i + 1] - ups[i] for i in range(len(ups) - 1)]
    gaps.sort()
    med = gaps[len(gaps) // 2]
    if med < 4:
        return None
    # 用最小二乘拟合更好地估计（用第 1 和第 k 个过零点的平均间隔）
    k = len(ups) - 1
    per = (ups[-1] - ups[0]) / k
    if per < 4:
        return None
    return per


def integer_cycles(d, max_cycles=8):
    """截取整数个周期，返回 (截取后的数据, 周期长度, 周期数)"""
    per = find_period(d)
    if per is None:
        return d, None, 0
    n = len(d)
    cycles = int(n / per)
    if cycles < 1:
        return d, per, 0
    cycles = min(cycles, max_cycles)
    # 用浮点周期乘以整数周期数
    length = int(round(per * cycles))
    if length > n:
        length = n
        cycles = int(length / per)
        length = int(round(per * cycles))
    if length < 8:
        return d, per, 0
    return d[:length], per, cycles


def normalize(data, n=N, use_cycles=True):
    """去趋势 + 归一化到 ±1 + (可选)截取整数周期 + 重采样"""
    d = [float(v) for v in data]
    if not d:
        return [0.0] * n

    if use_cycles:
        seg, per, cyc = integer_cycles(d)
        if cyc >= 1:
            d = seg

    d = _detrend(d)
    mx = 0.0
    for v in d:
        a = v if v >= 0 else -v
        if a > mx:
            mx = a
    if mx < 1e-9:
        return [0.0] * n
    d = [v / mx for v in d]
    return _resample(d, n)


def crest_factor(data):
    """峰值因数。★ 只减均值，不做线性去趋势

    ★ 踩坑：原来这里用了 _detrend（减均值+去线性趋势），
      但当信号不是整数个周期时，线性拟合会把"首尾不连续"当成趋势减掉，
      导致 crest 系统性偏高（sine 1.41 -> 1.60，square 1.00 -> 1.23），
      于是 crest 分档全错，匹配也跟着错。
      ⇒ crest 是形状的粗糙特征，只减均值就够。
    """
    d = [float(v) for v in data]
    if not d:
        return 0.0
    s = 0.0
    for v in d:
        s += v
    mean = s / len(d)
    d = [v - mean for v in d]
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


def _pearson_at(a, b, shift):
    n = len(a)
    sab = saa = sbb = 0.0
    for i in range(n):
        av = a[i]
        bv = b[(i + shift) % n]
        sab += av * bv
        saa += av * av
        sbb += bv * bv
    den = math.sqrt(saa * sbb)
    if den < 1e-12:
        return 0.0
    return sab / den


def match(query, tpl, max_shift=None, stride=4):
    n = len(query)
    if max_shift is None:
        max_shift = n // 2
    if n <= 2 * stride:
        best, best_i = -2.0, 0
        for sh in range(-max_shift, max_shift + 1):
            s = _pearson_at(query, tpl, sh)
            if s > best:
                best, best_i = s, sh
        return best, best_i

    qs = query[::stride]
    ts = tpl[::stride]
    best_s, best_ks = -2.0, 0
    for ks in range(0, len(qs)):
        s = _pearson_at(qs, ts, ks)
        if s > best_s:
            best_s, best_ks = s, ks
    center = best_ks * stride
    if center > n // 2:
        center -= n

    best, best_i = -2.0, center
    for sh in range(center - stride, center + stride + 1):
        sh2 = sh
        if sh2 > n // 2:
            sh2 -= n
        if sh2 < -n // 2:
            sh2 += n
        if abs(sh2) > max_shift:
            continue
        s = _pearson_at(query, tpl, sh2)
        if s > best:
            best, best_i = s, sh2
    return best, best_i


def _math_templates():
    t = {}
    t["sine"] = [math.sin(2.0 * math.pi * i / N) for i in range(N)]
    t["square"] = [1.0 if i < N // 2 else -1.0 for i in range(N)]
    t["triangle"] = [1.0 - 4.0 * abs((i / float(N)) - 0.5) for i in range(N)]
    t["sawtooth"] = [-1.0 + 2.0 * i / float(N) for i in range(N)]
    return t


def load():
    try:
        with open(TPL_FILE, encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict) and d:
            out = {}
            for k, v in d.items():
                if isinstance(v, dict) and isinstance(v.get("sig"), list) and len(v["sig"]) == N:
                    out[k] = v
            if out:
                for k, v in _math_templates().items():
                    if k not in out:
                        out[k] = {"label_cn": LABELS_CN.get(k, k), "sig": v, "source": "math"}
                return out
    except Exception:
        pass
    base = _math_templates()
    out = {}
    for k, v in base.items():
        out[k] = {"label_cn": LABELS_CN.get(k, k), "sig": v, "source": "math"}
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
    tpls = load()
    sig = normalize(data)
    tpls[category] = {
        "label_cn": label_cn or LABELS_CN.get(category, category),
        "sig": sig,
        "crest": round(crest_factor(data), 3),
        "source": "measured",
    }
    ok = save(tpls)
    return ok, tpls[category]


def _crest_bucket(c):
    if c <= 0:
        return "?"
    if c < 1.20:
        return "sq"
    if c < 1.58:
        return "sine"
    if c < 1.95:
        return "tri"
    return "?"


_MT_CREST = {}


def best_match(data, tpls=None, use_crest=True):
    if tpls is None:
        tpls = load()

    d = [float(v) for v in data]
    if d:
        dd = _detrend(d)
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

    q = normalize(data)
    qc = crest_factor(data)
    qb = _crest_bucket(qc) if use_crest else "?"

    if not _MT_CREST:
        for k, v in _math_templates().items():
            _MT_CREST[k] = crest_factor(v)

    scores = {}
    for cat, t in tpls.items():
        try:
            s, _ = match(q, t["sig"])
        except Exception:
            continue
        tc = t.get("crest")
        if not tc:
            tc = _MT_CREST.get(cat)
        if use_crest and tc:
            tb = _crest_bucket(float(tc))
            if qb != "?" and tb != "?" and qb != tb:
                s *= 0.55
        scores[cat] = round(s, 4)

    if not scores:
        return None, None, -1.0, {}

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


if __name__ == "__main__":
    tpls = load()
    print("模板库:", list(tpls.keys()))
    print()
    fail = 0
    total = 0
    for cat in ["sine", "square", "triangle", "sawtooth"]:
        base = tpls[cat]["sig"]
        for amp, off in [(40, 500), (150, 510), (400, 490)]:
            # 模拟 3.7 个周期（非整数周期，这是真实情况）
            npts = 4096
            per = 1100.0   # 每个周期 1100 点 -> 3.7 个周期
            ss = []
            for i in range(npts):
                p = (i / per) % 1.0          # 周期内相位
                x = p * (N - 1)
                i0 = int(x)
                i1 = min(i0 + 1, N - 1)
                t = x - i0
                v = base[i0] * (1 - t) + base[i1] * t
                ss.append(v * amp + off)
            t0 = __import__("time").time()
            c, cn, s, allsc = best_match(ss, tpls)
            dt = (__import__("time").time() - t0) * 1000
            ok = (c == cat)
            total += 1
            if not ok:
                fail += 1
            print("  %-9s amp=%3d 4096点/3.7周期 -> %-10s score=%.3f %s crest=%.2f %.0fms" % (
                cat, amp, c, s, "OK" if ok else "X", crest_factor(ss), dt))
    print()
    print("失败 %d / %d" % (fail, total))
