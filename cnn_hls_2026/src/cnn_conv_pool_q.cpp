// ============================================================================
// cnn_conv_pool_q.cpp —— M4b-5：通用 Conv+ReLU+MaxPool，带真实 requantization。
//   out[oc] = relu( sat((acc * MFQ) >> 16) )，再 2x2 MaxPool。
//   输入/输出通道、核尺寸、stride(池化) 由寄存器配置；MFQ 为定点乘子(统一~119, R=16)。
//   支持 Conv1(IN_CH=1->8, 28x28) 和 Conv2(IN_CH=8->16, 13x13)。
// ============================================================================
#include <ap_int.h>
typedef ap_int<8>  d8;
typedef ap_int<32> d32;
typedef ap_int<32> s32;

void cnn_conv_pool_q(d8* img, d8* w, d8* out,
                     int IH, int IW, int IN_CH, int OUT_CH, int KH, int KW, int P, int MFQ){
    #pragma HLS INTERFACE m_axi port=img  offset=slave bundle=gmem_img
    #pragma HLS INTERFACE m_axi port=w    offset=slave bundle=gmem_w
    #pragma HLS INTERFACE m_axi port=out  offset=slave bundle=gmem_out
    #pragma HLS INTERFACE s_axilite port=IH
    #pragma HLS INTERFACE s_axilite port=IW
    #pragma HLS INTERFACE s_axilite port=IN_CH
    #pragma HLS INTERFACE s_axilite port=OUT_CH
    #pragma HLS INTERFACE s_axilite port=KH
    #pragma HLS INTERFACE s_axilite port=KW
    #pragma HLS INTERFACE s_axilite port=P
    #pragma HLS INTERFACE s_axilite port=MFQ
    #pragma HLS INTERFACE s_axilite port=return

    int OH = (IH - KH + 1) / P;
    int OW = (IW - KW + 1) / P;
    int HW = IH * IW;
    int KW9 = KH * KW;

    for (int oc = 0; oc < OUT_CH; oc++){
        for (int py = 0; py < OH; py++){
            for (int px = 0; px < OW; px++){
                d8 m = 0;
                for (int sy = 0; sy < P; sy++){
                    for (int sx = 0; sx < P; sx++){
                        int oy = py * P + sy;
                        int ox = px * P + sx;
                        d32 acc = 0;
                        for (int ic = 0; ic < IN_CH; ic++)
                            for (int ky = 0; ky < KH; ky++)
                                for (int kx = 0; kx < KW; kx++)
                                    acc += (d32)img[ic * HW + (oy + ky) * IW + (ox + kx)] *
                                           (d32)w[(oc * IN_CH + ic) * KW9 + ky * KW + kx];
                        s32 q = (s32)((acc * MFQ) >> 16);   // requant
                        if (q < 0)  q = 0;                   // ReLU
                        if (q > 127) q = 127;                // saturate int8
                        d8 v = (d8)q;
                        if (v > m) m = v;                    // max-pool
                    }
                }
                out[oc * (OH * OW) + py * OW + px] = m;
            }
        }
    }
}
