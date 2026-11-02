// ============================================================================
// main_cnn.c —— M4b-1 板级验证：m_axi 数据通路。
//   1) CPU 把 28x28 图 + 3x3 核放到 DDR（缓存刷新）。
//   2) 配置 cnn_conv1 控制寄存器（基址、IH/IW/KH/KW），置 ap_start。
//   3) 硬件经 m_axi->S_AXI_HP0 直读 DDR、计算、写回 DDR。
//   4) CPU 无效化缓存后读出结果，与软件参考逐点比对。
// 波特率调试输出走 UART0 @115200。
// ============================================================================
#include <stdio.h>
#include "xil_types.h"
#include "xil_io.h"
#include "xil_cache.h"
#include "xparameters.h"
#include "mnist_data.h"

#define CNN_BASE   0x43C00000u      // cnn_conv1 s_axilite 基址（BD 分配）
#define AP_CTRL    0x00            // bit0 ap_start, bit1 ap_done, bit2 ap_idle
#define IMG_V      0x10            // img 基址(物理DDR地址)
#define W_V        0x18            // w   基址
#define OUT_V      0x20            // out 基址
#define IH_OFF     0x28            // IH
#define IW_OFF     0x30            // IW
#define KH_OFF     0x38            // KH
#define KW_OFF     0x40            // KW

#define IH 28
#define IW 28
#define KH 3
#define KW 3
#define OH (IH-KH+1)   // 26
#define OW (IW-KW+1)   // 26

// 放 DDR 的缓冲，64 字节对齐以保证 cache line 对齐
static signed char img[IH*IW] __attribute__((aligned(64)));
static signed char w  [KH*KW] __attribute__((aligned(64)));
static signed char out[OH*OW] __attribute__((aligned(64)));

static void put32(u32 addr, u32 val){ Xil_Out32(addr, val); }

int main(void)
{
    u32 base = CNN_BASE;
    s32 ref[OH*OW];
    u32 ap;
    int i, oy, ox, ky, kx;
    int ok = 1, mism = 0;

    xil_printf("\r\n=== M4b-1 CNN m_axi 数据通路 ===\r\n");

    // --- 准备数据：TEST_IMG -> img；W1 第 0 通道 -> w ---
    for (i = 0; i < IH*IW; i++) img[i] = (signed char)(TEST_IMG[i]); // 0..255 -> int8
    for (i = 0; i < KH*KW; i++) w[i] = W1[i];

    // --- 软件参考（int8 累加 -> >>8）---
    for (oy = 0; oy < OH; oy++)
        for (ox = 0; ox < OW; ox++){
            s32 acc = 0;
            for (ky = 0; ky < KH; ky++)
                for (kx = 0; kx < KW; kx++)
                    acc += (s32)img[(oy+ky)*IW + (ox+kx)] * (s32)w[ky*KW + kx];
            ref[oy*OW + ox] = acc >> 8;
        }

    // --- 缓存刷新：CPU 写的数据要能被 HP0 直读 ---
    Xil_DCacheFlushRange((u32)(uintptr_t)img, sizeof(img));
    Xil_DCacheFlushRange((u32)(uintptr_t)w,   sizeof(w));

    // --- 配置控制寄存器 ---
    put32(base + IMG_V, (u32)(uintptr_t)img);
    put32(base + W_V,   (u32)(uintptr_t)w);
    put32(base + OUT_V, (u32)(uintptr_t)out);
    put32(base + IH_OFF, IH);
    put32(base + IW_OFF, IW);
    put32(base + KH_OFF, KH);
    put32(base + KW_OFF, KW);

    // --- 启动 ---
    put32(base + AP_CTRL, 1);            // ap_start = 1
    xil_printf("[started] img=0x%x w=0x%x out=0x%x\r\n",
               (unsigned)(uintptr_t)img, (unsigned)(uintptr_t)w, (unsigned)(uintptr_t)out);

    // --- 轮询 ap_done (bit1)，带超时 ---
    int timeout = 2000000;
    do {
        ap = Xil_In32(base + AP_CTRL);
    } while (((ap & 0x2) == 0) && (--timeout > 0));
    if (timeout <= 0) {
        xil_printf("[TIMEOUT] ap_done never set, ctrl=0x%08x\r\n", ap);
        return 1;
    }
    xil_printf("[done] ctrl=0x%08x (idle=%u)\r\n", ap, (unsigned)((ap>>2)&1));

    // --- 无效化缓存：让 CPU 读到硬件新写的数据 ---
    Xil_DCacheInvalidateRange((u32)(uintptr_t)out, sizeof(out));

    // --- 比对参考 ---
    for (i = 0; i < OH*OW; i++){
        if ((s32)out[i] != ref[i]){
            ok = 0;
            if (mism < 10) {
                xil_printf("MISMATCH[%d]: hw=%d ref=%d\r\n", i, out[i], ref[i]);
                mism++;
            }
        }
    }

    xil_printf("\r\n");
    if (ok){
        xil_printf("[CNN OK] %d/%d 点一致\r\n", OH*OW, OH*OW);
    } else {
        xil_printf("[CNN FAIL] mismatch=%d / %d\r\n", mism, OH*OW);
    }

    // 打印第 0 行（首行/背景，应为全 0）便于肉眼核对
    xil_printf("out row0 :");
    for (i = 0; i < 26; i++) xil_printf(" %d", out[i]);
    xil_printf("\r\nref row0 :");
    for (i = 0; i < 26; i++) xil_printf(" %d", ref[i]);
    // 打印第 12 行（数字笔画位置，应出现非零值）
    xil_printf("\r\nout row12:");
    for (i = 12*26; i < 13*26; i++) xil_printf(" %d", out[i]);
    xil_printf("\r\nref row12:");
    for (i = 12*26; i < 13*26; i++) xil_printf(" %d", ref[i]);
    xil_printf("\r\n=== DEMO DONE ===\r\n");

    return ok ? 0 : 1;
}
