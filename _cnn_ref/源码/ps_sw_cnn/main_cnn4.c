// ============================================================================
// main_cnn4.c —— M4b-4 板级验证：全连接层 FC(400->10)，m_axi 走 DDR。
//   CPU 先算 Conv1+Conv2(含 pool) 得 FC 输入 x(400)，再让加速器做 FC，比对。
//   cache-line 对齐缓冲（关键，见 M4b-3 踩坑）。
// ============================================================================
#include <stdio.h>
#include "xil_types.h"
#include "xil_io.h"
#include "xil_cache.h"
#include "xparameters.h"
#include "mnist_data.h"

#define CNN_BASE 0x43C00000u
#define R_AP_CTRL 0x00
#define R_X_V 0x10
#define R_W_V 0x18
#define R_OUT_V 0x20
#define R_IN  0x28
#define R_OUT 0x30

#define IH1 28
#define IW1 28
#define C1  8
#define P   2
#define KH  3
#define KW  3
#define C26 (IH1-KH+1)   /* 26 */
#define OH1 (C26/P)
#define OW1 (C26/P)
#define N1 (C1*OH1*OW1)  /* 1352 */
#define IH2 13
#define IW2 13
#define C2  16
#define C11 (IH2-KH+1)   /* 11 */
#define OH2 (C11/P)
#define OW2 (C11/P)
#define N2 (C2*OH2*OW2)  /* 400 */
#define FCI 400
#define FCO 10

// cache-line 对齐 + 补齐到 64 倍数
static signed char img1[28*28]  __attribute__((aligned(64)));
static signed char fb1[1408]    __attribute__((aligned(64)));
static signed char w1[72]       __attribute__((aligned(64)));
static signed char w2[1152]     __attribute__((aligned(64)));
static signed char x[448]       __attribute__((aligned(64))); // FC 输入(400)兜到448
static signed char wf[4032]     __attribute__((aligned(64))); // FC 权重4000->4032
static signed char outf[64]     __attribute__((aligned(64))); // FC 输出10->64
static signed char rout[FCO];

static void conv1_pool_ref(void){
    int oc,py,px,sy,sx,ky,kx;
    for(oc=0;oc<C1;oc++)for(py=0;py<OH1;py++)for(px=0;px<OW1;px++){
        signed char m=0;
        for(sy=0;sy<P;sy++)for(sx=0;sx<P;sx++){
            int oy=py*P+sy,ox=px*P+sx; s32 acc=0;
            for(ky=0;ky<KH;ky++)for(kx=0;kx<KW;kx++)
                acc+=(s32)img1[(oy+ky)*IW1+(ox+kx)]*(s32)w1[oc*9+ky*3+kx];
            signed char v=(signed char)(acc>>8); if(v>m)m=v;
        }
        fb1[oc*169+py*13+px]=m;
    }
}
static void conv2_pool_ref(void){
    int oc,py,px,sy,sx,ic,ky,kx,k=0;
    for(oc=0;oc<C2;oc++)for(py=0;py<OH2;py++)for(px=0;px<OW2;px++){
        signed char m=0;
        for(sy=0;sy<P;sy++)for(sx=0;sx<P;sx++){
            int oy=py*P+sy,ox=px*P+sx; s32 acc=0;
            for(ic=0;ic<8;ic++)for(ky=0;ky<KH;ky++)for(kx=0;kx<KW;kx++)
                acc+=(s32)fb1[ic*169+(oy+ky)*13+(ox+kx)]*(s32)w2[(oc*8+ic)*9+ky*3+kx];
            signed char v=(signed char)(acc>>8); if(v>m)m=v;
        }
        x[k++]=m;   // FC 输入 x(400) 通道主序
    }
}
int main(void){
    u32 base=CNN_BASE, ap; int i,oc,ok=1,mism=0;
    xil_printf("\r\n=== M4b-4 FC(400->10) via m_axi ===\r\n");
    for(i=0;i<28*28;i++) img1[i]=(signed char)TEST_IMG[i];
    for(i=0;i<72;i++) w1[i]=W1[i];
    for(i=0;i<1152;i++) w2[i]=W2[i];
    for(i=0;i<4000;i++) wf[i]=WF[i];
    conv1_pool_ref();
    conv2_pool_ref();   // x[0..399] = FC 输入
    // CPU FC 参考
    for(oc=0;oc<FCO;oc++){ s32 acc=0; for(i=0;i<FCI;i++) acc+=(s32)x[i]*(s32)wf[oc*FCI+i]; rout[oc]=(signed char)(acc>>8); }
    // flush
    Xil_DCacheFlushRange((u32)(uintptr_t)x,sizeof(x));
    Xil_DCacheFlushRange((u32)(uintptr_t)wf,sizeof(wf));
    // config
    Xil_Out32(base+R_X_V,(u32)(uintptr_t)x);
    Xil_Out32(base+R_W_V,(u32)(uintptr_t)wf);
    Xil_Out32(base+R_OUT_V,(u32)(uintptr_t)outf);
    Xil_Out32(base+R_IN,FCI); Xil_Out32(base+R_OUT,FCO);
    Xil_Out32(base+R_AP_CTRL,1);
    xil_printf("[started] x=0x%x wf=0x%x out=0x%x\r\n",
               (unsigned)(uintptr_t)x,(unsigned)(uintptr_t)wf,(unsigned)(uintptr_t)outf);
    int timeout=20000000;
    do{ ap=Xil_In32(base+R_AP_CTRL);}while(((ap&0x2)==0)&&(--timeout>0));
    if(timeout<=0){xil_printf("[TIMEOUT] ctrl=0x%08x\r\n",ap); return 1;}
    xil_printf("[done] ctrl=0x%08x\r\n",ap);
    { volatile unsigned int t; for(t=0;t<4000000;t++){__asm__ volatile("");} }
    Xil_DCacheInvalidateRange((u32)(uintptr_t)outf,sizeof(outf));
    for(i=0;i<FCO;i++){ if((s32)outf[i]!=(s32)rout[i]){ ok=0; if(mism<10){xil_printf("MISMATCH[%d]: hw=%d ref=%d\r\n",i,outf[i],rout[i]); mism++;} } }
    if(ok) xil_printf("[CNN OK] %d/%d 点一致\r\n",FCO,FCO); else xil_printf("[CNN FAIL] mismatch=%d/%d\r\n",mism,FCO);
    xil_printf("hw logits :"); for(i=0;i<FCO;i++) xil_printf(" %d",outf[i]);
    xil_printf("\r\nref logits:"); for(i=0;i<FCO;i++) xil_printf(" %d",rout[i]);
    xil_printf("\r\n=== DEMO DONE ===\r\n");
    return ok?0:1;
}
