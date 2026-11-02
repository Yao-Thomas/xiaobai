// ============================================================================
// cnn_conv_pool_tb.cpp —— M4b-3 协同仿真：Conv2(8->16) 用板级同一测试向量。
//   调用 cnn_conv_pool，与 conv2_test.h 中的 EXP(400) 逐点比对。
//   注意：与设计函数签名一致（ap_int<8>*）。
// ============================================================================
#include <cstdio>
#include <ap_int.h>
#include "conv2_test.h"

typedef ap_int<8> d8;
void cnn_conv_pool(d8* img, d8* w, d8* out,
                   int IH, int IW, int IN_CH, int OUT_CH, int KH, int KW, int P);

int main(void){
    static signed char imgb[1352], wb[1152], ob[400];
    int i, err=0;

    for (i=0;i<1352;i++) imgb[i] = fb1[i];
    for (i=0;i<1152;i++) wb[i]   = W2[i];
    for (i=0;i<400; i++) ob[i]   = 0;

    cnn_conv_pool((d8*)imgb, (d8*)wb, (d8*)ob, 13, 13, 8, 16, 3, 3, 2);

    for (i=0;i<400;i++){
        if (ob[i] != EXP[i]){
            if (err < 12) printf("MISMATCH[%d]: hw=%d exp=%d\n", i, (int)ob[i], (int)EXP[i]);
            err++;
        }
    }
    printf("ch15 row2:");
    for (i=15*25+10;i<15*25+15;i++) printf(" %d",(int)ob[i]);
    printf("\n");
    if (err){ printf("TB FAIL err=%d\n", err); return 1; }
    printf("TB ALL PASS\n");
    return 0;
}
