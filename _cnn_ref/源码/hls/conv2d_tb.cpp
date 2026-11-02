// ============================================================================
// conv2d_tb.cpp —— 测试基准（用于 C simulation / Co-simulation）
// 板子到货前，用它在主机验证卷积核逻辑正确性。
// 生成一个 8x8 递增图像，权重也为递增，与参考实现比对，全部一致则 PASS。
// ============================================================================
#include <iostream>
#include <cmath>
#include "conv2d.h"

static int errors = 0;

static void check_ref() {
    float img[CONV_IH * CONV_IW];
    float wgt[CONV_KH * CONV_KW];
    float out[CONV_OH * CONV_OW];

    for (int i = 0; i < CONV_IH * CONV_IW; i++) img[i] = (float)i;
    for (int i = 0; i < CONV_KH * CONV_KW; i++) wgt[i] = (float)(i + 1);

    // 参考（CPU 版）结果
    float ref[CONV_OH * CONV_OW];
    for (int oy = 0; oy < CONV_OH; oy++) {
        for (int ox = 0; ox < CONV_OW; ox++) {
            float acc = 0.0f;
            for (int ky = 0; ky < CONV_KH; ky++)
                for (int kx = 0; kx < CONV_KW; kx++)
                    acc += img[(oy + ky) * CONV_IW + (ox + kx)] * wgt[ky * CONV_KW + kx];
            ref[oy * CONV_OW + ox] = acc;
        }
    }

    // DUT：调用 HLS 顶层
    conv2d(img, wgt, out);

    // 比对
    for (int i = 0; i < CONV_OH * CONV_OW; i++) {
        if (std::fabs(out[i] - ref[i]) > 1e-3f) {
            std::cout << "MISMATCH at " << i << " got=" << out[i] << " expect=" << ref[i] << "\n";
            errors++;
        }
    }
}

int main() {
    check_ref();
    if (errors == 0) std::cout << "\n[CSIM] ALL PASS\n";
    else             std::cout << "\n[CSIM] FAILED, errors=" << errors << "\n";
    return errors == 0 ? 0 : 1;
}
