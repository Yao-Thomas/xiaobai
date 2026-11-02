// ============================================================================
// cnn_conv.cpp —— M4b-1：单通道 3x3 卷积层（数据全部走 DDR，m_axi）
//   img[IH*IW]  (int8, 28x28)      -> out[OH*OW] (int8, 26x26)
//   w[KH*KW]    (int8, 3x3)
//   int8 输入/权重，int32 累加。
// 接口：数据用 m_axi(offset=slave)直读/写 DDR；参数用 s_axilite 控制寄存器。
// ============================================================================
#include <hls_stream.h>
#include <ap_int.h>

typedef ap_int<8>  d8;
typedef ap_int<32> d32;

// 顶层接口
void cnn_conv1(d8* img, d8* w, d8* out,
               int IH, int IW, int KH, int KW) {
    #pragma HLS INTERFACE m_axi port=img  offset=slave bundle=gmem
    #pragma HLS INTERFACE m_axi port=w    offset=slave bundle=gmem
    #pragma HLS INTERFACE m_axi port=out  offset=slave bundle=gmem
    #pragma HLS INTERFACE s_axilite port=IH
    #pragma HLS INTERFACE s_axilite port=IW
    #pragma HLS INTERFACE s_axilite port=KH
    #pragma HLS INTERFACE s_axilite port=KW
    #pragma HLS INTERFACE s_axilite port=return

    int OH = IH - KH + 1;
    int OW = IW - KW + 1;

    for (int oy = 0; oy < OH; oy++) {
        for (int ox = 0; ox < OW; ox++) {
            d32 acc = 0;
            #pragma HLS PIPELINE II=1
            for (int ky = 0; ky < KH; ky++) {
                for (int kx = 0; kx < KW; kx++) {
                    acc += (d32)img[(oy + ky) * IW + (ox + kx)] * (d32)w[ky * KW + kx];
                }
            }
            out[oy * OW + ox] = (d8)(acc >> 8);   // 简单右移 8 位近似 scale
        }
    }
}
