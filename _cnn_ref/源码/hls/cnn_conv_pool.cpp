// ============================================================================
// cnn_conv_pool.cpp —— M4b-3：通用 卷积+ReLU+MaxPool，支持任意输入/输出通道，走 DDR(m_axi)
//   支持 Conv1(IN_CH=1->8) 和 Conv2(IN_CH=8->16)。
//   img[(IN_CH*IH*IW) int8] * w[(OUT_CH*IN_CH*KH*KW) int8] -> out[(OUT_CH*OH*OW) int8]
//   Conv -> (>>8) -> ReLU(max0) -> 2x2 MaxPool
//   输入图/权重/输出都在 DDR，经 m_axi(S_AXI_HP0) 直读/写。
// ============================================================================
#include <hls_stream.h>
#include <ap_int.h>

typedef ap_int<8>  d8;
typedef ap_int<32> d32;

void cnn_conv_pool(d8* img, d8* w, d8* out,
                   int IH, int IW, int IN_CH, int OUT_CH, int KH, int KW, int P) {
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
    #pragma HLS INTERFACE s_axilite port=return

    int OH = (IH - KH + 1) / P;   // pooled output height
    int OW = (IW - KW + 1) / P;   // pooled output width
    int HW = IH * IW;             // per-channel input plane
    int KW9 = KH * KW;

    for (int oc = 0; oc < OUT_CH; oc++) {
        for (int py = 0; py < OH; py++) {
            for (int px = 0; px < OW; px++) {
                d8 m = 0;
                for (int sy = 0; sy < P; sy++) {
                    for (int sx = 0; sx < P; sx++) {
                        int oy = py * P + sy;   // conv-space row
                        int ox = px * P + sx;   // conv-space col
                        d32 acc = 0;
                        for (int ic = 0; ic < IN_CH; ic++) {
                            for (int ky = 0; ky < KH; ky++) {
                                for (int kx = 0; kx < KW; kx++) {
                                    acc += (d32)img[ic * HW + (oy + ky) * IW + (ox + kx)] *
                                           (d32)w[(oc * IN_CH + ic) * KW9 + ky * KW + kx];
                                }
                            }
                        }
                        d8 v = (d8)(acc >> 8);   // quantized conv out (int8 wrap)
                        if (v > m) m = v;         // ReLU via m>=0 start + max-pool
                    }
                }
                out[oc * (OH * OW) + py * OW + px] = m;
            }
        }
    }
}
