"""
model.py —— 视觉 + 特征 + 端侧先验 的融合分类网络

结构（约 0.35M 参数，CPU 单帧 < 15 ms）：

    图像 3×96×96 ── Conv3×3/s2 ×4（BN+ReLU）──┬─ GAP ─┐
                                              └─ GMP ─┴→ 256
    特征 59 维 ──── Linear→128（BN+ReLU）──────────────→ 128
    端侧 8 类概率（已含在 59 维里）──────────────────────┘
                                     concat 384 → FC256 → 16 类 logits

★ 为什么不是纯 CNN：
   绝对幅度、撞轨比例、自相关置信度这些量在 96×96 图上本来就画不出来；
   而端侧 8 类概率是**外部先验**，必须显式进融合层（并且训练时随机丢弃，
   防止模型退化成"抄端侧答案"）。
★ 为什么不是 VLM：
   单帧 ≤800 ms、可离线、无 GPU 的约束下，微调 Qwen2-VL 级别的模型不现实；
   本结构在 CPU 上 10 ms 级完成"图像 + 量测 + 端侧概率"三模态融合，
   语言理解由 explain.py 的受控生成层负责（可外挂 LLM 润色）。
   模型卡片里明确写清这条边界，不夸大。
"""
from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F

from .config import IMG, N_CHANNELS, N_CLASSES
from .features import FEAT_DIM


def _block(cin, cout):
    return nn.Sequential(
        nn.Conv2d(cin, cout, 3, stride=2, padding=1, bias=False),
        nn.BatchNorm2d(cout),
        nn.ReLU(inplace=True),
    )


class WaveFusionNet(nn.Module):
    def __init__(self, n_classes: int = N_CLASSES, n_feat: int = FEAT_DIM,
                 widths=(24, 48, 96, 128), feat_hidden: int = 128,
                 fusion_hidden: int = 256, p_drop: float = 0.10,
                 in_ch: int = N_CHANNELS):
        super().__init__()
        w1, w2, w3, w4 = widths
        self.cnn = nn.Sequential(
            _block(in_ch, w1), _block(w1, w2), _block(w2, w3), _block(w3, w4),
        )
        self.img_dim = 2 * w4
        self.feat = nn.Sequential(
            nn.Linear(n_feat, feat_hidden), nn.BatchNorm1d(feat_hidden),
            nn.ReLU(inplace=True), nn.Dropout(p_drop),
            nn.Linear(feat_hidden, feat_hidden), nn.ReLU(inplace=True),
        )
        self.fusion = nn.Sequential(
            nn.Linear(self.img_dim + feat_hidden, fusion_hidden),
            nn.BatchNorm1d(fusion_hidden), nn.ReLU(inplace=True),
            nn.Dropout(p_drop),
            nn.Linear(fusion_hidden, n_classes),
        )
        self.n_classes = n_classes

    def forward(self, img, feat):
        z = self.cnn(img)
        z = torch.cat([F.adaptive_avg_pool2d(z, 1).flatten(1),
                       F.adaptive_max_pool2d(z, 1).flatten(1)], dim=1)
        f = self.feat(feat)
        return self.fusion(torch.cat([z, f], dim=1))

    def embedding(self, img, feat):
        """倒数第二层 256 维嵌入（异常检测的马氏距离用）"""
        z = self.cnn(img)
        z = torch.cat([F.adaptive_avg_pool2d(z, 1).flatten(1),
                       F.adaptive_max_pool2d(z, 1).flatten(1)], dim=1)
        f = self.feat(feat)
        h = self.fusion[:-1](torch.cat([z, f], dim=1))
        return h


def count_params(model: nn.Module) -> int:
    return int(sum(p.numel() for p in model.parameters()))
