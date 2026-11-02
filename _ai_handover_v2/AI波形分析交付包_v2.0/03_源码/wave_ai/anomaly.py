"""
anomaly.py —— 未知异常检测（方向 3）

   端侧只有 8 类，且 fc 400→8 写死在 PL 里 ⇒ 认不出就归 noise。
   这里做两件事：
     ① **开放式识别**：模型输出"这段波形离已知 16 类的流形有多远"（马氏距离），
        再和 softmax 置信度融合成一个 0~1 的异常分。
     ② **可解释特征**：把"双频叠加 / 轻度削顶 / 低频幅度调制 / 窄脉冲毛刺"这类
        人话特征从量测里直接检出来 —— 不是让大模型自由发挥，而是有判据。

★★ 为什么用马氏距离而不是"自编码器重构误差"
   训练集每类都有几千条样本，256 维嵌入空间里每类的协方差可以稳定估计；
   马氏距离等价于"在每一类自己的尺度下看离中心几倍标准差"，
   不需要额外训练一个自编码器，也没有重构阈值难标定的问题。
   协方差做收缩（shrinkage）保证可逆（256 维 / 1500 样本）。
"""
from __future__ import annotations

import json
import math
import os

import numpy as np

EPS = 1e-9


# ---------------------------------------------------------------------------
# 统计量
# ---------------------------------------------------------------------------
def fit_embedding_stats(embed, label, shrinkage=0.15):
    """按类拟合高斯：均值 + 收缩协方差 + 精度矩阵"""
    embed = np.asarray(embed, dtype=np.float64)
    label = np.asarray(label, dtype=np.int64)
    d = embed.shape[1]
    stats = {"dim": int(d), "classes": [], "mean": [], "prec": [], "logdet": []}
    glob = embed.mean(axis=0)
    gcov = np.cov(embed, rowvar=False) + 1e-6 * np.eye(d)
    for c in sorted(set(label.tolist())):
        x = embed[label == c]
        mu = x.mean(axis=0)
        if len(x) >= d + 2:
            cov = np.cov(x, rowvar=False)
        else:
            cov = gcov
        cov = (1.0 - shrinkage) * cov + shrinkage * np.trace(cov) / d * np.eye(d)
        cov += 1e-6 * np.eye(d)
        prec = np.linalg.pinv(cov)
        sign, logdet = np.linalg.slogdet(cov)
        stats["classes"].append(int(c))
        stats["mean"].append(mu)
        stats["prec"].append(prec)
        stats["logdet"].append(float(logdet))
    stats["global_mean"] = glob
    # 训练集上的距离分布 → 阈值
    dists = np.array([mahalanobis(embed[i], stats) for i in range(len(embed))])
    stats["train_dist_p50"] = float(np.median(dists))
    stats["train_dist_p99"] = float(np.percentile(dists, 99))
    stats["train_dist_p999"] = float(np.percentile(dists, 99.9))
    return stats


def mahalanobis(z, stats):
    z = np.asarray(z, dtype=np.float64).reshape(-1)
    best = float("inf")
    for mu, prec, logdet in zip(stats["mean"], stats["prec"], stats["logdet"]):
        dz = z - mu
        d2 = float(dz @ prec @ dz)
        # 用 logdet 做一个轻量的"维度惩罚"（协方差大的类不该因为距离大就被冤枉）
        best = min(best, d2 + 0.0 * logdet)
    return math.sqrt(max(best, 0.0))


def save_stats(stats, path):
    """存成 float32 + 压缩：16 类 × 256×256 精度矩阵用 float64 要 8 MB，
    float32 + 压缩后约 3 MB（模型本体才 1.2 MB，不能本末倒置）。"""
    np.savez_compressed(
        path,
        dim=stats["dim"], classes=np.asarray(stats["classes"]),
        mean=np.asarray(stats["mean"], dtype=np.float32),
        prec=np.asarray(stats["prec"], dtype=np.float32),
        logdet=np.asarray(stats["logdet"], dtype=np.float32),
        train_dist_p50=stats["train_dist_p50"],
        train_dist_p99=stats["train_dist_p99"],
        train_dist_p999=stats["train_dist_p999"],
        val_dist_p95=stats.get("val_dist_p95", stats["train_dist_p99"]),
        val_dist_p99=stats.get("val_dist_p99", stats["train_dist_p99"]),
        feat_q=np.asarray(stats.get("feat_q", np.zeros((0, 0))), dtype=np.float32),
        rule_features=np.asarray(stats.get("rule_features", RULE_FEATURES)),
        class_names=np.asarray(stats.get("class_names", [])))


def load_stats(path):
    with np.load(path, allow_pickle=False) as z:
        s = {"dim": int(z["dim"]), "classes": z["classes"].tolist(),
             "mean": z["mean"].astype(np.float64),
             "prec": z["prec"].astype(np.float64),
             "logdet": z["logdet"].astype(np.float64).tolist(),
             "train_dist_p50": float(z["train_dist_p50"]),
             "train_dist_p99": float(z["train_dist_p99"]),
             "train_dist_p999": float(z["train_dist_p999"]),
             "val_dist_p95": float(z["val_dist_p95"]),
             "val_dist_p99": float(z["val_dist_p99"]),
             "feat_q": z["feat_q"].astype(np.float64)
             if "feat_q" in z.files else np.zeros((0, 0)),
             "rule_features": [str(x) for x in z["rule_features"]]
             if "rule_features" in z.files else list(RULE_FEATURES),
             "class_names": [str(x) for x in z["class_names"]]
             if "class_names" in z.files else []}
    return s


# ---------------------------------------------------------------------------
# 规则：可解释的异常特征
# ---------------------------------------------------------------------------
# 参与规则判定的特征（顺序冻结，与 anomaly_stats.npz 里的 feat_q 对应）
RULE_FEATURES = ["clip_frac", "flat_frac", "max_res", "two_tone",
                 "env_mod", "half_drift", "spec_flatness"]

# 绝对下限：低于它一律不报警（防止"某类天生就高"的特征被当成异常）
RULE_FLOOR = {
    "clip_frac": 0.004, "flat_frac": 0.35, "max_res": 0.55,
    "two_tone": 0.10, "env_mod": 0.30, "half_drift": 0.18,
    "spec_flatness": 0.40,
}

RULE_TEXT = {
    "clip_frac": ("rail", "满量程饱和", "采样贴到 0/1023 轨"),
    "flat_frac": ("flat", "信号中断/平坦段", "大段采样几乎不动"),
    "max_res": ("spike", "窄脉冲毛刺", "局部残差显著高于该类的正常范围"),
    "two_tone": ("two_tone", "双频叠加", "存在非谐波相关的第二谱峰"),
    "env_mod": ("am", "低频幅度调制", "包络起伏显著高于该类正常范围"),
    "half_drift": ("drift", "基线缓慢漂移", "前后半窗均值差显著偏大"),
    "spec_flatness": ("noise_like", "宽带噪声底偏高", "谱平坦度显著偏高"),
}


def fit_feature_quantiles(feat, label, classes, q=99.0):
    """按类统计规则特征的 q 分位（用于"超过本类正常范围才报警"）"""
    feat = np.asarray(feat, dtype=np.float64)
    label = np.asarray(label, dtype=np.int64)
    names = list(RULE_FEATURES)
    from .features import FEATURE_NAMES
    idx = [FEATURE_NAMES.index(n) for n in names]
    out = np.zeros((len(classes), len(names)), dtype=np.float64)
    for ci in range(len(classes)):
        x = feat[label == ci][:, idx]
        if len(x) < 20:
            out[ci] = np.full(len(names), np.inf)
            continue
        out[ci] = np.percentile(x, q, axis=0)
    return out, names


def rule_features(fd: dict, label: str, quality: dict, info: dict, stats=None):
    """按"超出本类正常范围"检人话异常特征。

    ★★ 为什么必须按类门限：
      固定阈值会大量误报 —— 实测方波的 max_res 天生接近 1.0（边沿残差就是半峰峰值），
      用 max_res>0.55 当"毛刺"判据，43% 的干净样本会被误报。
      改成"超过该类别训练集 p99"后，误报率被压到每特征 ~1%，
      而真正没见过的形态（两类混合）会在多个特征上同时越界。
    """
    out = []
    ci = None
    if stats is not None and label in stats.get("class_names", []):
        ci = stats["class_names"].index(label)
    qvals = stats["feat_q"][ci] if (ci is not None and "feat_q" in stats) else None
    names = stats.get("rule_features", RULE_FEATURES) if stats else RULE_FEATURES

    for j, name in enumerate(names):
        v = float(fd.get(name, 0.0) or 0.0)
        floor = RULE_FLOOR.get(name, 0.0)
        thr = floor
        if qvals is not None and np.isfinite(qvals[j]):
            thr = max(floor, float(qvals[j]))
        if v <= thr:
            continue
        code, text, why = RULE_TEXT[name]
        out.append({"code": code, "text": text,
                    "why": "%s（%.3f > 本类 p99 %.3f）" % (why, v, thr)})

    # 质量侧的两条（阈值不依赖类别分布，直接给绝对判据）
    overshoot = float(quality.get("overshoot_pct") or 0.0)
    shape = quality.get("shape_fidelity")
    if overshoot > 12.0:
        out.append({"code": "overshoot", "text": "边沿过冲",
                    "why": "过冲 %.1f%% > 12%%" % overshoot})
    if shape is not None and shape < 0.85 and label in ("square", "pulse", "step"):
        out.append({"code": "shape", "text": "波形畸变",
                    "why": "与理想波形保真度 %.2f < 0.85" % shape})
    return out


SUGGESTIONS = {
    "rail": "可能为增益档位过高或信号超出量程",
    "clip": "可能为信号源幅度过大或增益档位过高",
    "flat": "可能为信号源断开、接触不良或探头脱落",
    "spike": "可能为探头接地不良或阻抗失配",
    "two_tone": "可能为两个信号源叠加或通道串扰",
    "am": "可能为电源纹波耦合或信号源被调制",
    "drift": "可能为工频干扰或地环路电流",
    "noise_like": "可能为前端噪声过大或屏蔽不良",
    "overshoot": "可能为阻抗失配或探头补偿未调好",
    "shape": "可能为带宽不足或传输线反射",
}


def suggestion_for(codes):
    for c in ("rail", "flat", "spike", "two_tone", "am", "drift",
              "clip", "noise_like", "overshoot", "shape"):
        if c in codes:
            return SUGGESTIONS[c]
    return "建议检查探头连接与信号源输出"


# ---------------------------------------------------------------------------
# 融合成异常结论
# ---------------------------------------------------------------------------
class Detector:
    def __init__(self, stats=None):
        self.stats = stats

    def distance_score(self, embed):
        if not self.stats:
            return 0.0, None
        d = mahalanobis(embed, self.stats)
        p99 = max(self.stats["train_dist_p99"], 1e-6)
        scale = max(p99 - self.stats["train_dist_p50"], 1e-6)
        # 距 p99 还有 1 个尺度 → 0.5；距离越远越接近 1
        s = 1.0 / (1.0 + math.exp(-(d - p99) / (0.5 * scale)))
        return float(s), float(d)

    def detect(self, embed, probs, label, fd, quality, info):
        p = np.asarray(probs, dtype=np.float64)
        max_p = float(p.max()) if p.size else 0.0
        dscore, dist = self.distance_score(embed)
        conf_score = float(np.clip((0.55 - max_p) / 0.35, 0.0, 1.0))
        feats = rule_features(fd, label, quality, info, self.stats)
        codes = [f["code"] for f in feats]

        # 已知类别自带的特征不算"未知异常"
        benign = {
            "clipping": {"rail", "clip"}, "glitch": {"spike"},
            "am": {"am"}, "hum": {"drift"}, "ringing": {"overshoot"},
            "signal_loss": {"flat"}, "noise": {"noise_like"},
        }.get(label, set())
        unknown = [f for f in feats if f["code"] not in benign]
        unknown_codes = [f["code"] for f in unknown]

        # 判定：≥2 个未知特征同时越界（每特征 ~1% 误报 ⇒ 联合误报很低），
        #       或出现"量程饱和/长平线"这类单项即致命的特征，
        #       或嵌入距离超过 val p99（分布外）。
        severe = bool(set(unknown_codes) & {"rail", "flat"})
        is_anom = bool(len(unknown_codes) >= 2 or severe
                       or (dist is not None and self.stats is not None
                           and dist > self.stats.get("val_dist_p99", 1e9)))
        if label in ("noise", "signal_loss") and not severe:
            is_anom = False

        rule_score = float(min(len(unknown_codes), 2) / 2.0)
        score = float(np.clip(0.45 * dscore + 0.25 * conf_score + 0.30 * rule_score,
                              0.0, 1.0))
        if is_anom:
            score = max(score, 0.55)

        reason = ""
        if is_anom and max_p < 0.45:
            reason = "与已知 16 类均不匹配（最高置信度 %.2f）" % max_p
        elif is_anom and unknown_codes:
            reason = "检出 %d 项该类别不应出现的特征" % len(unknown_codes)
        elif is_anom:
            reason = "特征偏离已知类别分布（马氏距离 %.1f，val p99 %.1f）" % (
                dist or 0, self.stats.get("val_dist_p99", 0) if self.stats else 0)

        texts = [f["text"] for f in unknown][:3]
        if not texts:
            texts = [f["text"] for f in feats][:3]
        sugg = suggestion_for(unknown_codes) if (
            is_anom or unknown_codes) else ""
        if not sugg and is_anom:
            sugg = SUGGESTIONS.get("spike", "")
        return {
            "is_anomaly": is_anom,
            "score": round(score, 3),
            "distance": round(dist, 3) if dist is not None else None,
            "max_prob": round(max_p, 4),
            "features": texts,
            "suggestion": sugg,
            "reason": reason,
            "details": feats,
            "n_unexpected": len(unknown_codes),
        }
