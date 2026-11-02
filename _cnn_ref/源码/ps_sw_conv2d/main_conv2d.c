// ============================================================================
// main_conv2d.c —— M4a：PS 经 AXI 驱动 conv2d_accel（4x4 图 x 3x3 核 -> 2x2 输出）
// 寄存器（基址 0x43C00000, AXI4-Lite, ADDR_WIDTH=8）：
//   base + i*4        img[i]   (W)  i=0..15
//   base + 0x40+i*4   kern[i]  (W)  i=0..8
//   base + 0x80+i*4   out[i]   (R)  i=0..3
//   base + 0x100      ctrl     (W bit0=start; R bit0=busy bit1=done)
// ============================================================================
#include "xil_io.h"
#include "xil_printf.h"

#define ACC_BASE   0x43C00000UL
#define IMG(i)     (ACC_BASE + (i)*4)
#define KERN(i)    (ACC_BASE + 0x40 + (i)*4)
#define OUT(i)     (ACC_BASE + 0x80 + (i)*4)
#define CTRL       (ACC_BASE + 0x90)

static void delay(unsigned n){ volatile unsigned i; for(i=0;i<n;i++); }

int main(void){
    int i, oy, ox, ky, kx;
    unsigned img[16], k[9], out[4], ref[4];
    int err = 0;

    xil_printf("\r\n--- Zynq PS -> PL CONV2D Accelerator Demo ---\r\n");

    // 1) 4x4 渐变图（0..15），全 1 核（盒式滤波）
    for (i=0;i<16;i++) img[i] = i;
    for (i=0;i<9;i++)  k[i]  = 1;

    // 2) CPU 参考：3x3 卷积 -> 2x2
    for (oy=0;oy<2;oy++) for (ox=0;ox<2;ox++){
        unsigned acc=0;
        for (ky=0;ky<3;ky++) for (kx=0;kx<3;kx++)
            acc += img[(oy+ky)*4+(ox+kx)] * k[ky*3+kx];
        ref[oy*2+ox] = acc;
    }
    xil_printf("   [debug] ref computed\r\n");

    // 3) 写入加速器
    for (i=0;i<16;i++) Xil_Out32(IMG(i), img[i]);
    xil_printf("   [debug] image written (16)\r\n");
    for (i=0;i<9;i++)  Xil_Out32(KERN(i), k[i]);
    xil_printf("   [debug] kernel written (9)\r\n");

    // 4) 触发
    Xil_Out32(CTRL, 1);
    xil_printf("   [debug] triggered, waiting done...\r\n");

    // 5) 等 done
    unsigned st=0;
    for (i=0;i<1000000;i++){
        st = Xil_In32(CTRL);
        if (st & 2) break;
        delay(100);
    }
    xil_printf("   [debug] poll exit: status=0x%08X (done=%d)\r\n", st, (st>>1)&1);

    // 6) 读回并比对
    for (i=0;i<4;i++) out[i] = Xil_In32(OUT(i));
    for (i=0;i<4;i++) if (out[i] != ref[i]) err++;
    xil_printf("   conv2d output (2x2):\r\n");
    for (oy=0;oy<2;oy++){
        xil_printf("   ");
        for (ox=0;ox<2;ox++) xil_printf("%5u ", out[oy*2+ox]);
        xil_printf("\r\n");
    }
    if (err==0) xil_printf("\r\n   [CONV2D OK]  CPU reference matched (%d checks)\r\n", 4);
    else        xil_printf("\r\n   [CONV2D FAIL] errors=%d\r\n", err);

    xil_printf("--- demo done ---\r\n");
    return 0;
}
