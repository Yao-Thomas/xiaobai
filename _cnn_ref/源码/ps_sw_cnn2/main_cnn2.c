// ============================================================================
// main_cnn2.c —— M4b-2 板级验证：Conv1(1->8,3x3) + ReLU + MaxPool(2x2)，m_axi 走 DDR。
//   1) CPU 放 TEST_IMG(784) + W1(72) 到 DDR（flush 缓存）。
//   2) 配置 cnn_conv1_pool 控制寄存器（基址/IH/IW/IN_CH/OUT_CH/KH/KW/P），ap_start=1。
//   3) 硬件经 m_axi->HP0 读 DDR、卷积+ReLU+池化、写回 13x13x8 特征图。
//   4) CPU invalidate 后读出，与 C 软件参考逐点比对（8*13*13=1352 点）。
//   注意：xil_printf 仅 ASCII，字串用英文，避免乱码。
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

#define IH 28
#define IW 28
#define IN_CH 1
#define OUT_CH 8
#define KH 3
#define KW 3
#define P  2
#define C26 (IH-KH+1)     // 26 conv-space
#define OH (C26/P)        // 13 pooled
#define OW (C26/P)        // 13 pooled
#define N (OUT_CH*OH*OW)  // 1352

static signed char img[IN_CH*IH*IW] __attribute__((aligned(64)));
static signed char w  [OUT_CH*KH*KW] __attribute__((aligned(64)));
static signed char out[N]            __attribute__((aligned(64)));
static signed char ref[N];

int main(void)
{
    u32 base = CNN_BASE;
    u32 ap;
    int i, oc, py, px, sy, sx, ky, kx;
    int ok = 1, mism = 0;

    xil_printf("\r\n=== M4b-2 Conv1+ReLU+MaxPool (m_axi DDR) ===\r\n");

    // --- prepare data ---
    for (i = 0; i < IH*IW; i++) img[i] = (signed char)TEST_IMG[i];
    for (i = 0; i < OUT_CH*KH*KW; i++) w[i] = W1[i];

    // --- CPU software reference (int8 wrap + ReLU via m=0 start + 2x2 max) ---
    for (oc = 0; oc < OUT_CH; oc++)
        for (py = 0; py < OH; py++)
            for (px = 0; px < OW; px++){
                signed char m = 0;
                for (sy = 0; sy < P; sy++)
                    for (sx = 0; sx < P; sx++){
                        int oy = py*P + sy, ox = px*P + sx;
                        s32 acc = 0;
                        for (ky = 0; ky < KH; ky++)
                            for (kx = 0; kx < KW; kx++)
                                acc += (s32)img[(oy+ky)*IW + (ox+kx)] *
                                       (s32)w[oc*(IN_CH*KH*KW) + ky*KW + kx];
                        signed char v = (signed char)(acc >> 8);  // int8 wrap
                        if (v > m) m = v;
                    }
                ref[oc*(OH*OW) + py*OW + px] = m;
            }

    // --- flush CPU writes to DDR ---
    Xil_DCacheFlushRange((u32)(uintptr_t)img, sizeof(img));
    Xil_DCacheFlushRange((u32)(uintptr_t)w,   sizeof(w));

    // --- config control regs ---
    Xil_Out32(base + R_IMG_V,  (u32)(uintptr_t)img);
    Xil_Out32(base + R_W_V,    (u32)(uintptr_t)w);
    Xil_Out32(base + R_OUT_V,  (u32)(uintptr_t)out);
    Xil_Out32(base + R_IH,     IH);
    Xil_Out32(base + R_IW,     IW);
    Xil_Out32(base + R_IN_CH,  IN_CH);
    Xil_Out32(base + R_OUT_CH, OUT_CH);
    Xil_Out32(base + R_KH,     KH);
    Xil_Out32(base + R_KW,     KW);
    Xil_Out32(base + R_P,      P);

    // --- start ---
    out[0] = 0;
    Xil_Out32(base + R_AP_CTRL, 1);
    xil_printf("[started] img=0x%x w=0x%x out=0x%x\r\n",
               (unsigned)(uintptr_t)img, (unsigned)(uintptr_t)w, (unsigned)(uintptr_t)out);

    // --- poll ap_done ---
    int timeout = 20000000;
    do { ap = Xil_In32(base + R_AP_CTRL); } while (((ap & 0x2) == 0) && (--timeout > 0));
    if (timeout <= 0) { xil_printf("[TIMEOUT] ctrl=0x%08x\r\n", ap); return 1; }
    xil_printf("[done] ctrl=0x%08x (idle=%u)\r\n", ap, (unsigned)((ap>>2)&1));

    // --- 关键：等 m_axi 最后一批写数据排空到 DDR（避免最后通道读到脏 0）---
    { volatile unsigned int t; for(t=0; t<4000000; t++){ __asm__ volatile(""); } }

    // --- invalidate out cache ---
    Xil_DCacheInvalidateRange((u32)(uintptr_t)out, sizeof(out));

    // --- compare ---
    for (i = 0; i < N; i++){
        if ((s32)out[i] != (s32)ref[i]){
            ok = 0;
            if (mism < 10) { xil_printf("MISMATCH[%d]: hw=%d ref=%d\r\n", i, out[i], ref[i]); mism++; }
        }
    }
    if (ok) xil_printf("[CNN OK] %d/%d 点一致\r\n", N, N);
    else    xil_printf("[CNN FAIL] mismatch=%d / %d\r\n", mism, N);

    // --- show a few pooled rows (ch0/1/7, pooled row 6) for eyeball check ---
    xil_printf("ch0 row6 :");
    for (i = 0; i < 13; i++) xil_printf(" %d", out[0*169 + 6*13 + i]);
    xil_printf("\r\nch1 row6 :");
    for (i = 0; i < 13; i++) xil_printf(" %d", out[1*169 + 6*13 + i]);
    xil_printf("\r\nch7 row6 :");
    for (i = 0; i < 13; i++) xil_printf(" %d", out[7*169 + 6*13 + i]);
    xil_printf("\r\n=== DEMO DONE ===\r\n");

    return ok ? 0 : 1;
}
