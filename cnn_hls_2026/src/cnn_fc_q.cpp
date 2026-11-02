// ============================================================================
// cnn_fc_q.cpp —— M4b-5：全连接层，带真实 requantization。
//   logits[oc] = sat((acc * MFQ) >> 16)，acc=Σ x[i]*w[oc*IN+i]。
//   FC 无 ReLU，输出饱和到 int8（不透传 wrap）。
// ============================================================================
#include <ap_int.h>
typedef ap_int<8>  d8;
typedef ap_int<32> d32;
typedef ap_int<32> s32;

void cnn_fc_q(d8* x, d8* w, d8* out, int IN, int OUT, int MFQ){
    #pragma HLS INTERFACE m_axi port=x   offset=slave bundle=gmem_x
    #pragma HLS INTERFACE m_axi port=w   offset=slave bundle=gmem_w
    #pragma HLS INTERFACE m_axi port=out offset=slave bundle=gmem_out
    #pragma HLS INTERFACE s_axilite port=IN
    #pragma HLS INTERFACE s_axilite port=OUT
    #pragma HLS INTERFACE s_axilite port=MFQ
    #pragma HLS INTERFACE s_axilite port=return

    for (int oc = 0; oc < OUT; oc++){
        d32 acc = 0;
        for (int i = 0; i < IN; i++){
            acc += (d32)x[i] * (d32)w[oc * IN + i];
        }
        s32 q = (s32)((acc * MFQ) >> 16);
        if (q > 127)  q = 127;   // saturate (no wrap)
        if (q < -128) q = -128;
        out[oc] = (d8)q;
    }
}
