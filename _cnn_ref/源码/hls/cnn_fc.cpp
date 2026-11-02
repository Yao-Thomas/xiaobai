// ============================================================================
// cnn_fc.cpp —— M4b-4：全连接层 FC(Nin->Nout)，m_axi 走 DDR。
//   out[oc] = (sum_i x[i]*w[oc*Nin+i]) >> 8   (int8 wrap)
//   x=5x5x16 展平(400)  -> 10 logits，权重 WF[4000]。
// ============================================================================
#include <ap_int.h>
typedef ap_int<8>  d8;
typedef ap_int<32> d32;

void cnn_fc(d8* x, d8* w, d8* out, int IN, int OUT){
    #pragma HLS INTERFACE m_axi port=x   offset=slave bundle=gmem_x
    #pragma HLS INTERFACE m_axi port=w   offset=slave bundle=gmem_w
    #pragma HLS INTERFACE m_axi port=out offset=slave bundle=gmem_out
    #pragma HLS INTERFACE s_axilite port=IN
    #pragma HLS INTERFACE s_axilite port=OUT
    #pragma HLS INTERFACE s_axilite port=return

    for (int oc = 0; oc < OUT; oc++){
        d32 acc = 0;
        for (int i = 0; i < IN; i++){
            acc += (d32)x[i] * (d32)w[oc * IN + i];
        }
        out[oc] = (d8)(acc >> 8);
    }
}
