// ============================================================================
// main_cnn5.c —— M4b-5 端到端 MNIST：Conv1->ReLU->Pool -> Conv2->ReLU->Pool -> FC -> argmax
//   真实 requantization：out = sat/(relu)((acc*MFQ)>>16)，MFQ 统一=119（主机校准一致）。
//   两个 IP：cpq(0x43C00000)=卷积+池化(可配 Conv1/Conv2)；fcq(0x43C10000)=全连接。
//   打印识别数字，并与 CPU 参考比对（应为 7）。
// ============================================================================
#include <stdio.h>
#include "xil_types.h"
#include "xil_io.h"
#include "xil_cache.h"
#include "xparameters.h"
#include "mnist_data.h"

#define CPQB 0x43C00000u
#define FCQB 0x43C10000u
// cpq registers
#define R_AP 0x00
#define R_IMG 0x10
#define R_W  0x18
#define R_OUT 0x20
#define R_IH 0x28
#define R_IW 0x30
#define R_INC 0x38
#define R_OUTC 0x40
#define R_KH 0x48
#define R_KW 0x50
#define R_P  0x58
#define R_MFQ 0x60
// fcq registers
#define F_AP 0x00
#define F_X  0x10
#define F_W  0x18
#define F_OUT 0x20
#define F_IN  0x28
#define F_OUTN 0x30
#define F_MFQ 0x38

#define MFQ 119
#define CB1 8
#define CB2 16
#define P 2
#define KH 3
#define KW 3
// conv1: 28->13x13x8
#define OH1 13
#define OW1 13
#define N1 (CB1*OH1*OW1)  // 1352
// conv2: 13->5x5x16
#define OH2 5
#define OW2 5
#define N2 (CB2*OH2*OW2)  // 400
#define FCI 400
#define FCO 10

// cache-line aligned + padded
static signed char img[832]   __attribute__((aligned(64)));
static signed char W1b[128]   __attribute__((aligned(64)));
static signed char fb1[1408]  __attribute__((aligned(64)));
static signed char W2b[1152]  __attribute__((aligned(64)));
static signed char fb2[448]   __attribute__((aligned(64)));
static signed char WFb[4032]  __attribute__((aligned(64)));
static signed char lg[64]     __attribute__((aligned(64)));
static signed char lg_ref[FCO];
// CPU reference intermediates (stack/heap)
static int ref1[N1];
static int ref2[N2];

static int run_cpq(int IH,int IW,int inC,int outC,int KH_,int KW_,int P_,
                   void* imgin, void* wptr, void* outptr){
    // 不在这里 flush：imgin 对 Conv2 是加速器输出 fb1，CPU 缓存是旧 0，flush 会把它冲坏。
    Xil_Out32(CPQB+R_IMG,(u32)(uintptr_t)imgin);
    Xil_Out32(CPQB+R_W,(u32)(uintptr_t)wptr);
    Xil_Out32(CPQB+R_OUT,(u32)(uintptr_t)outptr);
    Xil_Out32(CPQB+R_IH,IH); Xil_Out32(CPQB+R_IW,IW);
    Xil_Out32(CPQB+R_INC,inC); Xil_Out32(CPQB+R_OUTC,outC);
    Xil_Out32(CPQB+R_KH,KH_); Xil_Out32(CPQB+R_KW,KW_); Xil_Out32(CPQB+R_P,P_);
    Xil_Out32(CPQB+R_MFQ,MFQ);
    Xil_Out32(CPQB+R_AP,1);
    u32 ap; int t=20000000; do{ap=Xil_In32(CPQB+R_AP);}while(((ap&2)==0)&&(--t>0));
    if(t<=0){xil_printf("[TIMEOUT cpq]\r\n"); return 1;}
    { volatile unsigned int tt; for(tt=0;tt<4000000;tt++){__asm__ volatile("");} }
    return 0;
}

int main(void){
    int i,oc,py,px,sy,sx,ic,ky,kx;
    int expected=0, got=0, mism=0;
    xil_printf("\r\n=== M4b-5 End-to-End MNIST (requant MFQ) ===\r\n");

    // prepare input int8 = u8-128
    for(i=0;i<784;i++) img[i]=(signed char)(TEST_IMG[i]-128);
    for(i=0;i<72;i++)  W1b[i]=W1[i];
    for(i=0;i<1152;i++)W2b[i]=W2[i];
    for(i=0;i<4000;i++)WFb[i]=WF[i];
    // 关键：只 flush CPU 写的数据（输入图 + 权重），放入 DDR 供加速器读。
    Xil_DCacheFlushRange((u32)(uintptr_t)img,sizeof(img));
    Xil_DCacheFlushRange((u32)(uintptr_t)W1b,sizeof(W1b));
    Xil_DCacheFlushRange((u32)(uintptr_t)W2b,sizeof(W2b));
    Xil_DCacheFlushRange((u32)(uintptr_t)WFb,sizeof(WFb));

    // ---- CPU reference (int8 requant) ----
    for(oc=0;oc<CB1;oc++)for(py=0;py<OH1;py++)for(px=0;px<OW1;px++){
        int m=0;
        for(sy=0;sy<P;sy++)for(sx=0;sx<P;sx++){
            int oy=py*P+sy,ox=px*P+sx; s32 acc=0;
            for(ky=0;ky<KH;ky++)for(kx=0;kx<KW;kx++)
                acc+=(s32)img[(oy+ky)*28+(ox+kx)]*(s32)W1[oc*9+ky*3+kx];
            int q=(acc*MFQ)>>16; if(q<0)q=0; if(q>127)q=127; if(q>m)m=q;
        }
        ref1[oc*169+py*13+px]=m;
    }
    for(oc=0;oc<CB2;oc++)for(py=0;py<OH2;py++)for(px=0;px<OW2;px++){
        int m=0;
        for(sy=0;sy<P;sy++)for(sx=0;sx<P;sx++){
            int oy=py*P+sy,ox=px*P+sx; s32 acc=0;
            for(ic=0;ic<8;ic++)for(ky=0;ky<KH;ky++)for(kx=0;kx<KW;kx++)
                acc+=(s32)ref1[ic*169+(oy+ky)*13+(ox+kx)]*(s32)W2[(oc*8+ic)*9+ky*3+kx];
            int q=(acc*MFQ)>>16; if(q<0)q=0; if(q>127)q=127; if(q>m)m=q;
        }
        ref2[oc*25+py*5+px]=m;
    }
    for(oc=0;oc<FCO;oc++){
        s32 acc=0; for(i=0;i<FCI;i++) acc+=(s32)ref2[i]*(s32)WF[oc*FCI+i];
        int q=(acc*MFQ)>>16; if(q>127)q=127; if(q<-128)q=-128; lg_ref[oc]=(signed char)q;
    }
    for(i=0;i<FCO;i++) if(lg_ref[i]>lg_ref[expected]) expected=i;

    xil_printf("[ref] argmax=%d  logits:", expected);
    for(i=0;i<FCO;i++) xil_printf(" %d",lg_ref[i]);
    xil_printf("\r\n");

    // ---- conv1 ----
    if(run_cpq(28,28,1,8,KH,KW,P,img,W1b,fb1)) return 1;
    // ---- conv2 ----  (input = fb1, 加速器输出，不 flush)
    if(run_cpq(13,13,8,16,KH,KW,P,fb1,W2b,fb2)) return 1;
    // ---- fc ----   (input = fb2, 加速器输出，不 flush)
    Xil_Out32(FCQB+F_X,(u32)(uintptr_t)fb2);
    Xil_Out32(FCQB+F_W,(u32)(uintptr_t)WFb);
    Xil_Out32(FCQB+F_OUT,(u32)(uintptr_t)lg);
    Xil_Out32(FCQB+F_IN,FCI); Xil_Out32(FCQB+F_OUTN,FCO); Xil_Out32(FCQB+F_MFQ,MFQ);
    Xil_Out32(FCQB+F_AP,1);
    u32 ap; int t=20000000; do{ap=Xil_In32(FCQB+F_AP);}while(((ap&2)==0)&&(--t>0));
    if(t<=0){xil_printf("[TIMEOUT fcq]\r\n"); return 1;}
    { volatile unsigned int tt; for(tt=0;tt<4000000;tt++){__asm__ volatile("");} }
    Xil_DCacheInvalidateRange((u32)(uintptr_t)lg,sizeof(lg));

    // ---- argmax + compare ----
    for(i=0;i<FCO;i++){ if((s32)lg[i]!=(s32)lg_ref[i]){ mism++; } }
    for(i=0;i<FCO;i++) if(lg[i]>lg[got]) got=i;

    xil_printf("[hw ] argmax=%d  logits:", got);
    for(i=0;i<FCO;i++) xil_printf(" %d",lg[i]);
    xil_printf("\r\n");

    if(mism==0 && got==expected && got==7)
        xil_printf(">>> [M4B-5 OK] 识别数字 = %d（与参考一致, label=7）<<<\r\n", got);
    else
        xil_printf("[M4B-5 FAIL] mism=%d got=%d expect=%d (应识别7)\r\n", mism, got, expected);

    xil_printf("=== DEMO DONE ===\r\n");
    return (mism==0 && got==7)?0:1;
}
