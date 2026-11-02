// ============================================================================
// conv2d.cpp —— 3x3 卷积核实现（Vitis HLS）
// ============================================================================
#include "conv2d.h"

void conv2d(const float img[CONV_IH * CONV_IW],
            const float wgt[CONV_KH * CONV_KW],
            float       out[CONV_OH * CONV_OW]) {

    // 接口：输入/权重/输出用内存接口（后续可改 AXI-Stream / m_axi）
    #pragma HLS INTERFACE ap_memory port=img
    #pragma HLS INTERFACE ap_memory port=wgt
    #pragma HLS INTERFACE ap_memory port=out
    // 默认控制接口：ap_ctrl_hs（带 start/done 握手，便于封装为 AXI-Stream IP）

    conv_loop:
    for (int oy = 0; oy < CONV_OH; oy++) {
        for (int ox = 0; ox < CONV_OW; ox++) {
            float acc = 0.0f;
            #pragma HLS PIPELINE II=1
            k_loop:
            for (int ky = 0; ky < CONV_KH; ky++) {
                for (int kx = 0; kx < CONV_KW; kx++) {
                    acc += img[(oy + ky) * CONV_IW + (ox + kx)] * wgt[ky * CONV_KW + kx];
                }
            }
            out[oy * CONV_OW + ox] = acc;
        }
    }
}
