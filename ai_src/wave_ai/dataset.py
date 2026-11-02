"""
dataset.py —— 数据集生成 / 缓存 / 读取

产出一个 split 的四件套：
    raw_{split}.npy    (N,4096) uint16      原始采集（与板端 JSONL 的 samples 同格式）
    feat_{split}.npy   (N,FEAT_DIM) float32 手工特征（含模拟的端侧 8 类概率）
    label_{split}.npy  (N,) int16           类别下标（= config.CLASSES 下标）
    param_{split}.npz  dict[str,(N,)] float32 仿真真值（仅 val/test，用于质量算法校验）

★ 为什么要模拟"端侧 8 类概率"
   契约里 local_cnn 是可选但强烈建议的输入。板端的 PL CNN 只有 8 类、28×28，
   在真实数据上会犯错（而且他们正在用真实数据重训，错误模式会变）。
   如果把 local_cnn 当"真值"喂给融合层，模型会学成"抄端侧答案"。
   所以训练时按 72% 正确 / 20% 混淆 / 8% 不可用 来模拟，
   并且混淆只发生在**形状相近**的类别之间（见 CONFUSABLE），逼模型学会
   "端侧说的是参考，不是答案"。
"""
from __future__ import annotations

import json
import os
import time

import numpy as np

from .config import CAP_LEN, CLASSES, N_CLASSES, VERSION
from .features import FEAT_DIM, FEATURE_NAMES, extract_features
from .hw_sim import synth

DATASET_VERSION = "2.0"

# 端侧 8 类 + 新类之间"形状相近"的混淆关系（模拟真实 PL CNN 的错误分布）
CONFUSABLE = {
    "sine": ["triangle", "am", "hum"],
    "square": ["pulse", "duty_abnormal", "ringing"],
    "triangle": ["sine", "sawtooth"],
    "sawtooth": ["triangle", "square"],
    "noise": ["signal_loss", "hum", "glitch"],
    "clipping": ["square", "duty_abnormal"],
    "signal_loss": ["noise", "step"],
    "duty_abnormal": ["square", "pulse"],
    "pulse": ["square", "duty_abnormal", "step"],
    "step": ["pulse", "signal_loss"],
    "am": ["hum", "sine", "double_freq"],
    "fm": ["double_freq", "am"],
    "ringing": ["square", "glitch", "pulse"],
    "double_freq": ["am", "fm", "hum"],
    "hum": ["am", "double_freq", "noise"],
    "glitch": ["noise", "ringing", "pulse"],
}

PARAM_KEYS = ["k", "dec", "fs_eff", "vpp_lsb", "half_amp", "gain", "duty", "noise",
              "bw", "clip_level", "mod_index", "mod_freq", "n_pulse", "n_glitch",
              "step_pos", "loss_len", "flat", "ratio", "amp2", "hum_amp", "hum_freq"]


def simulate_local_probs(y, rng):
    """模拟板端 PL CNN 的 8 类输出（返回 (n, N_CLASSES)，前 8 维非零）"""
    y = np.asarray(y, dtype=np.int64)
    n = len(y)
    lp = np.zeros((n, N_CLASSES), dtype=np.float32)
    kind = rng.choice(3, size=n, p=[0.72, 0.20, 0.08])
    for i in range(n):
        if kind[i] == 2:
            continue                                    # 8% 端侧不可用
        true = CLASSES[int(y[i])]
        if kind[i] == 0:                                # 正确
            p = rng.uniform(0.35, 0.97)
            main = true
        else:                                           # 混淆
            p = rng.uniform(0.30, 0.80)
            main = str(rng.choice(CONFUSABLE.get(true, CLASSES[:8])))
            if main not in CLASSES[:8]:
                main = str(rng.choice(CONFUSABLE.get(true, CLASSES[:8])))
        # 端侧只有 8 类：新类只能被映射到某个 8 类原型
        if main not in CLASSES[:8]:
            main = str(rng.choice(CLASSES[:8]))
        lp[i, CLASSES.index(main)] = p
        rest = 1.0 - p
        cand = [c for c in CONFUSABLE.get(true, []) if c in CLASSES[:8] and c != main]
        if not cand:
            cand = [c for c in CLASSES[:8] if c != main]
        k = int(rng.integers(1, min(3, len(cand)) + 1))
        picks = rng.choice(cand, size=k, replace=False)
        w = rng.dirichlet(np.ones(k))
        for c, ww in zip(picks, w):
            lp[i, CLASSES.index(str(c))] = rest * ww
    return lp


def _param_matrix(par_list):
    out = {}
    for k in PARAM_KEYS:
        if k in par_list:
            out[k] = np.asarray(par_list[k], dtype=np.float32)
    return out


def build_split(out_dir, split, n_total, seed, domain="train"):
    """生成一个 split 并落盘，返回 meta dict"""
    rng = np.random.default_rng([seed, {"train": 11, "val": 12, "test": 13}[split]])
    n_cls = len(CLASSES)
    per = n_total // n_cls
    counts = [per] * n_cls
    for i in rng.permutation(n_cls)[:n_total - per * n_cls]:
        counts[int(i)] += 1

    raw = np.empty((n_total, CAP_LEN), dtype=np.uint16)
    feat = np.empty((n_total, FEAT_DIM), dtype=np.float32)
    label = np.empty(n_total, dtype=np.int16)
    params = {k: np.empty(n_total, dtype=np.float32) for k in PARAM_KEYS}
    filled = np.zeros(n_total, dtype=bool)

    t0 = time.time()
    done = 0
    for ci, cls in enumerate(CLASSES):
        m = counts[ci]
        r, par = synth(cls, m, rng, domain=domain)
        lp = simulate_local_probs(np.full(m, ci), rng)
        fs = par["fs_eff"]
        for i in range(m):
            f, _info = extract_features(r[i], float(fs[i]), lp[i])
            feat[done + i] = f
        raw[done:done + m] = r
        label[done:done + m] = ci
        for k in PARAM_KEYS:
            params[k][done:done + m] = (
                np.asarray(par[k], dtype=np.float64) if k in par
                else np.full(m, np.nan))
        filled[done:done + m] = True
        done += m
        print("    [%s] %-14s %5d  %.1fs" % (split, cls, m, time.time() - t0), flush=True)

    assert filled.all()
    idx = rng.permutation(n_total)
    os.makedirs(out_dir, exist_ok=True)
    np.save(os.path.join(out_dir, "raw_%s.npy" % split), raw[idx])
    np.save(os.path.join(out_dir, "feat_%s.npy" % split), feat[idx])
    np.save(os.path.join(out_dir, "label_%s.npy" % split), label[idx])
    if split != "train":
        np.savez(os.path.join(out_dir, "param_%s.npz" % split),
                 **{k: v[idx] for k, v in params.items()})
    return {"n": n_total, "class_counts": {CLASSES[i]: int(c) for i, c in enumerate(counts)},
            "seconds": round(time.time() - t0, 1)}


def build(out_dir, n_train=24000, n_val=3000, n_test=3000, seed=20261021):
    print("=== 生成数据集 -> %s ===" % out_dir)
    stats = {}
    for split, n in (("train", n_train), ("val", n_val), ("test", n_test)):
        stats[split] = build_split(out_dir, split, n, seed)
    meta = {
        "dataset_version": DATASET_VERSION,
        "generator": "wave_ai/dataset.py (hw_sim 真实链路仿真)",
        "source": "sim_hw_10bit",
        "source_note": "按 3PA1030 + 真实信号源建模：10 bit、20MSPS/dec、模拟带宽、"
                       "13 LSB 噪声、ADC 失调、增益误差、触发相位抖动。"
                       "★ 不是真板采集；真板 JSONL 到了用 finetune.py 直接微调",
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "version": VERSION,
        "seed": seed,
        "classes": CLASSES,
        "n_classes": N_CLASSES,
        "input_shape": [CAP_LEN],
        "input_dtype": "uint16 (0~1023)",
        "feature_dim": FEAT_DIM,
        "feature_names": FEATURE_NAMES,
        "splits": {k: v["n"] for k, v in stats.items()},
        "class_counts": {k: v["class_counts"] for k, v in stats.items()},
        "param_keys": PARAM_KEYS,
    }
    with open(os.path.join(out_dir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print("=== 完成 ===", meta["splits"])
    return meta


def load_split(data_dir, split):
    d = {
        "raw": np.load(os.path.join(data_dir, "raw_%s.npy" % split)),
        "feat": np.load(os.path.join(data_dir, "feat_%s.npy" % split)),
        "label": np.load(os.path.join(data_dir, "label_%s.npy" % split)).astype(np.int64),
    }
    p = os.path.join(data_dir, "param_%s.npz" % split)
    if os.path.exists(p):
        with np.load(p) as z:
            d["param"] = {k: z[k] for k in z.files}
    return d


# ---------------------------------------------------------------------------
# 未知异常（OOD）混合集：不在训练类别里的人工合成形态
# ---------------------------------------------------------------------------
OOD_PAIRS = [
    ("square", "hum"), ("sine", "glitch"), ("am", "clipping"),
    ("double_freq", "ringing"), ("pulse", "hum"), ("triangle", "glitch"),
    ("fm", "clipping"), ("sawtooth", "hum"), ("step", "hum"),
    ("ringing", "glitch"), ("am", "glitch"), ("fm", "hum"),
]


def make_ood(n, seed=777, domain="train"):
    """两路真实波形按随机权重叠加 —— 训练集里没有这种形态，用来看"识未知"能力"""
    rng = np.random.default_rng(seed)
    out = np.empty((n, CAP_LEN), dtype=np.uint16)
    info = []
    per = int(np.ceil(n / float(len(OOD_PAIRS))))
    i = 0
    for a, b in OOD_PAIRS:
        m = min(per, n - i)
        if m <= 0:
            break
        ra, _ = synth(a, m, rng, domain=domain, chunk=m)
        rb, _ = synth(b, m, rng, domain=domain, chunk=m)
        wa = rng.uniform(0.45, 1.0, m)[:, None]
        wb = rng.uniform(0.45, 1.0, m)[:, None]
        mix = 511.5 + wa * (ra.astype(np.float64) - 511.5) + wb * (rb.astype(np.float64) - 511.5)
        # 按 99.5 分位缩放回 10 bit 安全区，避免整片削顶掩盖形态
        span = np.percentile(mix, 99.5, axis=1) - np.percentile(mix, 0.5, axis=1)
        sc = np.minimum(1.0, 980.0 / np.maximum(span, 1.0))
        mix = 511.5 + (mix - 511.5) * sc[:, None]
        out[i:i + m] = np.clip(np.rint(mix), 0, 1023).astype(np.uint16)
        info += ["%s+%s" % (a, b)] * m
        i += m
    return out[:n], info[:n]


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/ds_v2")
    ap.add_argument("--train", type=int, default=24000)
    ap.add_argument("--val", type=int, default=3000)
    ap.add_argument("--test", type=int, default=3000)
    ap.add_argument("--seed", type=int, default=20261021)
    args = ap.parse_args()
    build(args.out, args.train, args.val, args.test, args.seed)
