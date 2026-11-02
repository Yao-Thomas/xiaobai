// ============================================================================
// main_cnn3.c —— M4b-3 板级验证：通用 Conv+ReLU+MaxPool，用 Conv2(8->16) 验证多输入通道。
//   CPU 先算 Conv1(->8)+pool 得 fb1(13x13x8)，作为 Conv2 输入。
//   加速器读 fb1 + W2，做 Conv2(8->16)+ReLU+pool -> fb2(5x5x16)，与 CPU 参考比对。
//   xil_printf 仅 ASCII。
// ============================================================================
#include <stdio.h>
#include "xil_types.h"
#include "xil_io.h"
#include "xil_cache.h"
#include "xparameters.h"
#include "mnist_data.h"

#define CNN_BASE   0x43C00000u
#define R_AP_CTRL  0x00
#define R_IMG_V    0x10
#define R_W_V      0x18
#define R_OUT_V    0x20
#define R_IH       0x28
#define R_IW       0x30
#define R_IN_CH    0x38
#define R_OUT_CH   0x40
#define R_KH       0x48
#define R_KW       0x50
#define R_P        0x58

// --- Conv1: 28x28 -> pool 13x13x8 ---
#define IH1 28
#define IW1 28
#define C1  8
#define P   2
#define KH  3
#define KW  3
#define C26 (IH1-KH+1)     /* 26 */
#define OH1 (C26/P)         /* 13 */
#define OW1 (C26/P)         /* 13 */
#define N1 (C1*OH1*OW1)     /* 1352 */
// --- Conv2: 13x13x8 -> pool 5x5x16 ---
#define IH2 13
#define IW2 13
#define C2  16
#define C11 (IH2-KH+1)      /* 11 */
#define OH2 (C11/P)         /* 5 */
#define OW2 (C11/P)         /* 5 */
#define N2 (C2*OH2*OW2)     /* 400 */

static signed char img1[28*28]         __attribute__((aligned(64)));
static signed char fb1[N1]             __attribute__((aligned(64))); // conv1 pooled -> conv2 input
static signed char w1[72]              __attribute__((aligned(64)));
static signed char w2[1152]            __attribute__((aligned(64)));
static signed char fb2[N2]             __attribute__((aligned(64))); // conv2 pooled output
static signed char r2[N2];

// Conv1(1->8)+ReLU+pool(2x2): img1(28x28) -> fb1 channel-major
static void conv1_pool_ref(void){
    int oc,py,px,sy,sx,ky,kx;
    for(oc=0;oc<8;oc++) for(py=0;py<13;py++) for(px=0;px<13;px++){
        signed char m=0;
        for(sy=0;sy<2;sy++) for(sx=0;sx<2;sx++){
            int oy=py*2+sy, ox=px*2+sx; s32 acc=0;
            for(ky=0;ky<3;ky++) for(kx=0;kx<3;kx++)
                acc += (s32)img1[(oy+ky)*28+(ox+kx)] * (s32)w1[oc*9+ky*3+kx];
            signed char v=(signed char)(acc>>8); if(v>m)m=v;
        }
        fb1[oc*169+py*13+px]=m;
    }
}
// Conv2(8->16)+ReLU+pool(2x2): fb1(13x13x8) -> r2(5x5x16)
static void conv2_pool_ref(void){
    int oc,py,px,sy,sx,ic,ky,kx;
    for(oc=0;oc<16;oc++) for(py=0;py<5;py++) for(px=0;px<5;px++){
        signed char m=0;
        for(sy=0;sy<2;sy++) for(sx=0;sx<2;sx++){
            int oy=py*2+sy, ox=px*2+sx; s32 acc=0;
            for(ic=0;ic<8;ic++) for(ky=0;ky<3;ky++) for(kx=0;kx<3;kx++)
                acc += (s32)fb1[ic*169+(oy+ky)*13+(ox+kx)] * (s32)w2[(oc*8+ic)*9+ky*3+kx];
            signed char v=(signed char)(acc>>8); if(v>m)m=v;
        }
        r2[oc*25+py*5+px]=m;
    }
}

int main(void){
    u32 base=CNN_BASE, ap; int i,ok=1,mism=0;
    xil_printf("\r\n=== M4b-3 Conv2(8->16)+ReLU+Pool via m_axi ===\r\n");

    for(i=0;i<28*28;i++) img1[i]=(signed char)TEST_IMG[i];
    for(i=0;i<72;i++)    w1[i]=W1[i];
    for(i=0;i<1152;i++)  w2[i]=W2[i];

    conv1_pool_ref();   // build fb1 (CPU conv1 reference)
    conv2_pool_ref();   // build r2 (CPU conv2 reference)

    Xil_DCacheFlushRange((u32)(uintptr_t)fb1,sizeof(fb1));
    Xil_DCacheFlushRange((u32)(uintptr_t)w2,sizeof(w2));
    Xil_DCacheFlushRange((u32)(uintptr_t)img1,sizeof(img1));
    Xil_DCacheFlushRange((u32)(uintptr_t)w1,sizeof(w1));

    Xil_Out32(base+R_IMG_V,(u32)(uintptr_t)fb1);
    Xil_Out32(base+R_W_V,  (u32)(uintptr_t)w2);
    Xil_Out32(base+R_OUT_V,(u32)(uintptr_t)fb2);
    Xil_Out32(base+R_IH,13); Xil_Out32(base+R_IW,13);
    Xil_Out32(base+R_IN_CH,8); Xil_Out32(base+R_OUT_CH,16);
    Xil_Out32(base+R_KH,3); Xil_Out32(base+R_KW,3); Xil_Out32(base+R_P,2);

    Xil_Out32(base+R_AP_CTRL,1);
    xil_printf("[started] fb1=0x%x w2=0x%x fb2=0x%x\r\n",
               (unsigned)(uintptr_t)fb1,(unsigned)(uintptr_t)w2,(unsigned)(uintptr_t)fb2);
    int timeout=20000000;
    do{ ap=Xil_In32(base+R_AP_CTRL); }while(((ap&0x2)==0)&&(--timeout>0));
    if(timeout<=0){xil_printf("[TIMEOUT] ctrl=0x%08x\r\n",ap); return 1;}
    xil_printf("[done] ctrl=0x%08x\r\n",ap);

    // --- 关键：等 m_axi 最后一批写数据排空到 DDR（否则最后通道读到脏 0）---
    { volatile unsigned int t; for(t=0; t<4000000; t++){ __asm__ volatile(""); } }

    Xil_DCacheInvalidateRange((u32)(uintptr_t)fb2,sizeof(fb2));

    for(i=0;i<N2;i++){ if((s32)fb2[i]!=(s32)r2[i]){ ok=0; if(mism<10){xil_printf("MISMATCH[%d]: hw=%d ref=%d\r\n",i,fb2[i],r2[i]); mism++;} } }
    if(ok) xil_printf("[CNN OK] %d/%d 点一致\r\n",N2,N2); else xil_printf("[CNN FAIL] mismatch=%d/%d\r\n",mism,N2);

    // show ch0/8/15, pooled row 2 (5 wide)
    xil_printf("ch0 row2 :"); for(i=0;i<5;i++) xil_printf(" %d",fb2[0*25+2*5+i]);
    xil_printf("\r\nch8 row2 :"); for(i=0;i<5;i++) xil_printf(" %d",fb2[8*25+2*5+i]);
    xil_printf("\r\nch15 row2:"); for(i=0;i<5;i++) xil_printf(" %d",fb2[15*25+2*5+i]);
    xil_printf("\r\n=== DEMO DONE ===\r\n");
    return ok?0:1;
}
