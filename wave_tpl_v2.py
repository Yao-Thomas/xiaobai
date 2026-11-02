# -*- coding: utf-8 -*-
"""wave_templates.py —— 波形模板学习与形态匹配

★ TEMPLATE_MATCH_V2

设计目标：解决「不同幅度识别不一样」的问题。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
算法（两级）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
第一级：峰值因数（crest factor = peak / rms），与幅度无关
    square   ≈ 1.00
    sine     ≈ 1.41
    triangle ≈ 1.73
    sawtooth ≈ 1.73
  ⇒ 先把方波单独分出来（它和正弦的相关系数高达 0.90，单靠相关无法区分）

第二级：归一化波形 + 皮尔逊相关系数（允许相位平移）
  ⇒ 在 crest 相近的候选里用形状相似度细分

★ 踩过的坑
  ① 最早直接用「点积均值」当相似度 ⇒ sin 自相关只有 0.5
     因为 sin² 的均值是 0.5，必须除以 sqrt(Σa²·Σb²) 才是真正的相关系数。
  ② 「粗略重采样到 64 点找峰」会因 256→64 的插值步长 4.0476（非整数）
     导致相位漂移 ⇒ 改成整数步长抽样。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import json
import math
import os

TPL_FILE = "/home/zynq/.scope_templates.json"
N = 256
MATCH_THRESHOLD = 0.80

LABELS_CN = {
    "sine": "正弦波",
    "square": "方波",
    "triangle": "三角波",
    "sawtooth": "锯齿波",
    "pulse": "脉冲",
    "noise": "噪声",
    "clipping": "削顶",
    "custom": "自定义",
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


def normalize(data, n=N):
    d = [float(v) for v in data]
    if not d:
        return [0.0] * n
    mean = sum(d) / len(d)
    d = [v - mean for v in d]
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
    d = [float(v) for v in data]
    if not d:
        return 0.0
    mean = sum(d) / len(d)
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


def match(query, tpl, max_shift=None, stride=2):
    n = len(query)
    if max_shift is None:
        max_shift = n // 2   # ★ 半周期即可覆盖所有相位（循环平移超过 n/2 等价于反向）
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
    print("=== 自测：4 种波形 x 3 种幅度/相位 ===")
    fail = 0
    total = 0
    for cat in ["sine", "square", "triangle", "sawtooth"]:
        base = _math_templates()[cat]
        for amp, off, ph in [(3.7, 500, 40), (0.5, 480, 0), (10.0, 520, 77)]:
            d = [base[(i + ph) % N] * amp + off for i in range(N)]
            c, cn, s, allsc = best_match(d, tpls)
            ok = (c == cat)
            total += 1
            if not ok:
                fail += 1
            print("  %-10s amp=%4.1f ph=%3d -> %-10s score=%.3f %s  crest=%.2f" % (
                cat, amp, ph, c, s, "OK" if ok else "X", crest_factor(d)))
    print()
    print("  失败 %d / %d" % (fail, total))
