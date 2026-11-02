// ============================================================================
// cnn_conv1_pool.cpp —— M4b-2：Conv1(1->8, 3x3) + ReLU + MaxPool(2x2)，走 DDR(m_axi)
//   img[IN_CH*IH*IW]  int8 (28x28)      -> out[OUT_CH*OH*OW] int8 (13x13x8)
//   w[OUT_CH*IN_CH*KH*KW] int8 (W1, 72)
//   Conv -> shift(>>8) -> ReLU -> 2x2 MaxPool
//   输入图/权重/输出都在 DDR，经 m_axi(S_AXI_HP0) 直读/写。
// ============================================================================
#include <hls_stream.h>
#include <ap_int.h>

typedef ap_int<8>  d8;
typedef ap_int<32> d32;

void cnn_conv1_pool(d8* img, d8* w, d8* out,
                    int IH, int IW, int IN_CH, int OUT_CH, int KH, int KW, int P) {
    #pragma HLS INTERFACE m_axi port=img  offset=slave bundle=gmem
    #pragma HLS INTERFACE m_axi port=w    offset=slave bundle=gmem
    #pragma HLS INTERFACE m_axi port=out  offset=slave bundle=gmem
    #pragma HLS INTERFACE s_axilite port=IH
    #pragma HLS INTERFACE s_axilite port=IW
    #pragma HLS INTERFACE s_axilite port=IN_CH
    #pragma HLS INTERFACE s_axilite port=OUT_CH
    #pragma HLS INTERFACE s_axilite port=KH
    #pragma HLS INTERFACE s_axilite port=KW
    #pragma HLS INTERFACE s_axilite port=P
    #pragma HLS INTERFACE s_axilite port=return

    int OH = (IH - KH + 1) / P;      // pooled output height
    int OW = (IW - KW + 1) / P;      // pooled output width

    for (int oc = 0; oc < OUT_CH; oc++) {
        for (int py = 0; py < OH; py++) {
            for (int px = 0; px < OW; px++) {
                d8 m = 0;
                for (int sy = 0; sy < P; sy++) {
                    for (int sx = 0; sx < P; sx++) {
                        int oy = py * P + sy;   // conv-space row
                        int ox = px * P + sx;   // conv-space col
                        d32 acc = 0;
                        for (int ky = 0; ky < KH; ky++) {
                            for (int kx = 0; kx < KW; kx++) {
                                acc += (d32)img[(oy + ky) * IW + (ox + kx)] *
                                       (d32)w[oc * (IN_CH * KH * KW) + ky * KW + kx];
                            }
                        }
                        d8 v = (d8)(acc >> 8);        // quantized conv out
                        if (v > m) m = v;             // ReLU(>=0) + max-pool
                    }
                }
                out[oc * (OH * OW) + py * OW + px] = m;
            }
        }
    }
}
