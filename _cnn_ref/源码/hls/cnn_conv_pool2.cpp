// ============================================================================
// cnn_conv_pool2.cpp —— M4b-3 修复：改用编译期常量维度（规避变量循环边界导致
//   最后一个输出通道被算错的 HLS 综合 bug）。
//   维度以 #define 固定（Conv2: 13x13x8 -> 5x5x16）。仅 img/w/out 基址走 s_axilite。
// ============================================================================
#include <ap_int.h>
typedef ap_int<8>  d8;
typedef ap_int<32> d32;

#define IH 13
#define IW 13
#define IN_CH 8
#define OUT_CH 16
#define KH 3
#define KW 3
#define P 2

void cnn_conv_pool2(d8* img, d8* w, d8* out){
    #pragma HLS INTERFACE m_axi port=img  offset=slave bundle=gmem_img
    #pragma HLS INTERFACE m_axi port=w    offset=slave bundle=gmem_w
    #pragma HLS INTERFACE m_axi port=out  offset=slave bundle=gmem_out
    #pragma HLS INTERFACE s_axilite port=return

    const int HW  = IH * IW;
    const int KW9 = KH * KW;
    const int OH  = (IH - KH + 1) / P;
    const int OW  = (IW - KW + 1) / P;

    for (int oc = 0; oc < OUT_CH; oc++) {
        for (int py = 0; py < OH; py++) {
            for (int px = 0; px < OW; px++) {
                d8 m = 0;
                for (int sy = 0; sy < P; sy++) {
                    for (int sx = 0; sx < P; sx++) {
                        int oy = py * P + sy;
                        int ox = px * P + sx;
                        d32 acc = 0;
                        for (int ic = 0; ic < IN_CH; ic++)
                            for (int ky = 0; ky < KH; ky++)
                                for (int kx = 0; kx < KW; kx++)
                                    acc += (d32)img[ic * HW + (oy + ky) * IW + (ox + kx)] *
                                           (d32)w[(oc * IN_CH + ic) * KW9 + ky * KW + kx];
                        d8 v = (d8)(acc >> 8);
                        if (v > m) m = v;
                    }
                }
                out[oc * (OH * OW) + py * OW + px] = m;
            }
        }
    }
}
