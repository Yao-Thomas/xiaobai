// ============================================================================
// conv2d.h —— 3x3 卷积核（加速器核心原语）
// 输入：单通道 HxW 图像，3x3 卷积核
// 输出：(H-2)x(W-2)
// 后续可扩展为多通道、加 ReLU/Pooling 的完整卷积层（见 ROADMAP §3 M6）
// ============================================================================
#ifndef CONV2D_H
#define CONV2D_H

#include <hls_stream.h>
#include <ap_int.h>

// 卷积参数（先固定做小尺寸，便于上板资源评估；后续参数化）
#define CONV_IH 8
#define CONV_IW 8
#define CONV_KH 3
#define CONV_KW 3
#define CONV_OH (CONV_IH - CONV_KH + 1)
#define CONV_OW (CONV_IW - CONV_KW + 1)

// 顶层接口：
//   img : 输入特征图（按行主序）
//   wgt : 卷积核权重
//   out : 输出特征图
//   (h/w/ic/oc 等参数后面再加 AXILite 寄存器控制，先定长做通)
void conv2d(const float img[CONV_IH * CONV_IW],
            const float wgt[CONV_KH * CONV_KW],
            float       out[CONV_OH * CONV_OW]);

#endif
