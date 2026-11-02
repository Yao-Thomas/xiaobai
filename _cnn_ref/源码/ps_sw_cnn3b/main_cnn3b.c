// ============================================================================
// main_cnn3b.c —— M4b-3 修复版：编译期常量维度 Conv2(8->16)+ReLU+MaxPool。
//   仅设置 img/w/out 基址（维度已 #define 在核内）。验证 5x5x16 输出与 CPU 参考一致。
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

#define IH1 28
#define IW1 28
#define C1  8
#define P   2
#define KH  3
#define KW  3
#define C26 (IH1-KH+1)
#define OH1 (C26/P)
#define OW1 (C26/P)
#define N1 (C1*OH1*OW1)
#define IH2 13
#define IW2 13
#define C2  16
#define C11 (IH2-KH+1)
#define OH2 (C11/P)
#define OW2 (C11/P)
#define N2 (C2*OH2*OW2)

// DMA 缓冲补齐到 64B(一条 cache line) 的倍数，并 64B 对齐：
// 否则 CPU 的 Flush/Invalidate 对"最后一条不完整 line"不处理，读到旧缓存值(0)。
static signed char img1[28*28]         __attribute__((aligned(64)));
static signed char fb1[1408]           __attribute__((aligned(64))); // >=1352, 22 lines
static signed char w1[72]              __attribute__((aligned(64)));
static signed char w2[1152]            __attribute__((aligned(64))); // 18 lines exact
static signed char fb2[448]            __attribute__((aligned(64))); // >=400, 7 lines
static signed char r2[N2];

static void conv1_pool_ref(void){
    int oc,py,px,sy,sx,ky,kx;
    for(oc=0;oc<C1;oc++) for(py=0;py<OH1;py++) for(px=0;px<OW1;px++){
        signed char m=0;
        for(sy=0;sy<P;sy++) for(sx=0;sx<P;sx++){
            int oy=py*P+sy, ox=px*P+sx; s32 acc=0;
            for(ky=0;ky<KH;ky++) for(kx=0;kx<KW;kx++)
                acc += (s32)img1[(oy+ky)*IW1+(ox+kx)] * (s32)w1[oc*9+ky*3+kx];
            signed char v=(signed char)(acc>>8); if(v>m)m=v;
        }
        fb1[oc*169+py*13+px]=m;
    }
}
static void conv2_pool_ref(void){
    int oc,py,px,sy,sx,ic,ky,kx;
    for(oc=0;oc<C2;oc++) for(py=0;py<OH2;py++) for(px=0;px<OW2;px++){
        signed char m=0;
        for(sy=0;sy<P;sy++) for(sx=0;sx<P;sx++){
            int oy=py*P+sy, ox=px*P+sx; s32 acc=0;
            for(ic=0;ic<8;ic++) for(ky=0;ky<KH;ky++) for(kx=0;kx<KW;kx++)
                acc += (s32)fb1[ic*169+(oy+ky)*13+(ox+kx)] * (s32)w2[(oc*8+ic)*9+ky*3+kx];
            signed char v=(signed char)(acc>>8); if(v>m)m=v;
        }
        r2[oc*25+py*5+px]=m;
    }
}

int main(void){
    u32 base=CNN_BASE, ap; int i,ok=1,mism=0;
    xil_printf("\r\n=== M4b-3b const-dim Conv2(8->16)+ReLU+Pool ===\r\n");
    for(i=0;i<28*28;i++) img1[i]=(signed char)TEST_IMG[i];
    for(i=0;i<72;i++)    w1[i]=W1[i];
    for(i=0;i<1152;i++)  w2[i]=W2[i];
    conv1_pool_ref();
    conv2_pool_ref();
    Xil_DCacheFlushRange((u32)(uintptr_t)fb1,sizeof(fb1));  // 1408
    Xil_DCacheFlushRange((u32)(uintptr_t)w2,sizeof(w2));
    Xil_DCacheFlushRange((u32)(uintptr_t)img1,sizeof(img1));
    Xil_DCacheFlushRange((u32)(uintptr_t)w1,sizeof(w1));
    Xil_Out32(base+R_IMG_V,(u32)(uintptr_t)fb1);
    Xil_Out32(base+R_W_V,  (u32)(uintptr_t)w2);
    Xil_Out32(base+R_OUT_V,(u32)(uintptr_t)fb2);
    Xil_Out32(base+R_AP_CTRL,1);
    xil_printf("[started] fb1=0x%x w2=0x%x fb2=0x%x\r\n",
               (unsigned)(uintptr_t)fb1,(unsigned)(uintptr_t)w2,(unsigned)(uintptr_t)fb2);
    int timeout=20000000;
    do{ ap=Xil_In32(base+R_AP_CTRL); }while(((ap&0x2)==0)&&(--timeout>0));
    if(timeout<=0){xil_printf("[TIMEOUT] ctrl=0x%08x\r\n",ap); return 1;}
    xil_printf("[done] ctrl=0x%08x\r\n",ap);
    { volatile unsigned int t; for(t=0;t<4000000;t++){ __asm__ volatile(""); } }
    Xil_DCacheInvalidateRange((u32)(uintptr_t)fb2,sizeof(fb2));  // 448 -> 覆盖最后一条 line
    for(i=0;i<N2;i++){ if((s32)fb2[i]!=(s32)r2[i]){ ok=0; if(mism<10){xil_printf("MISMATCH[%d]: hw=%d ref=%d\r\n",i,fb2[i],r2[i]); mism++;} } }
    if(ok) xil_printf("[CNN OK] %d/%d 点一致\r\n",N2,N2); else xil_printf("[CNN FAIL] mismatch=%d/%d\r\n",mism,N2);
    xil_printf("ch0 row2 :"); for(i=0;i<5;i++) xil_printf(" %d",fb2[0*25+2*5+i]);
    xil_printf("\r\nch8 row2 :"); for(i=0;i<5;i++) xil_printf(" %d",fb2[8*25+2*5+i]);
    xil_printf("\r\nch15 row2:"); for(i=0;i<5;i++) xil_printf(" %d",fb2[15*25+2*5+i]);
    xil_printf("\r\n=== DEMO DONE ===\r\n");
    return ok?0:1;
}
