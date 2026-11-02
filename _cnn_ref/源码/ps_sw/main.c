// ============================================================================
// main.c —— Zynq PS 侧裸机 APP（CPU 端驱动 PL 侧加速器，跑通 CPU-FPGA-NPU 链路）
//
// 说明：与 M3 Block Design 的寄存器映射一致（见 conv_accel_axi_lite.v）：
//   0x00 = 操作数 A (W)
//   0x04 = 操作数 B (W)
//   0x08 = 操作数 C (W)
//   0x0C = 操作数 D (W)
//   0x10 = result A*B + C*D (R)
//   0x14 = status (R, bit0=valid, bit1=busy)
//   AXI GPIO 基址 0x41200000（写 GPIO 输出点亮 LED）。
// 交叉编译：SDK 2018.3 内嵌 arm-none-eabi-gcc，用 xsct 建 BSP 后编译。
// ============================================================================
#include "xil_io.h"
#include "xil_printf.h"

#define ACCEL_BASE   0x43C00000UL          // 加速器 AXI4-Lite 基址（0x43C00000）
#define ACCEL_A      (ACCEL_BASE + 0x00)
#define ACCEL_B      (ACCEL_BASE + 0x04)
#define ACCEL_C      (ACCEL_BASE + 0x08)
#define ACCEL_D      (ACCEL_BASE + 0x0C)
#define ACCEL_RESULT (ACCEL_BASE + 0x10)
#define ACCEL_STATUS (ACCEL_BASE + 0x14)
#define GPIO_BASE    0x41200000UL          // AXI GPIO 基址（8 位 LED）
#define GPIO_DATA    (GPIO_BASE + 0x00)

static void delay_loop(unsigned n) { volatile unsigned i; for (i = 0; i < n; i++) ; }

int main(void) {
    xil_printf("\r\n--- Zynq PS -> PL Accelerator Chain Demo ---\r\n");

    unsigned a = 6, b = 7, c = 5, d = 9;   // 6*7 + 5*9 = 42 + 45 = 87

    // 1) 经 AXI 写入 4 个操作数
    Xil_Out32(ACCEL_A, a);
    Xil_Out32(ACCEL_B, b);
    Xil_Out32(ACCEL_C, c);
    Xil_Out32(ACCEL_D, d);
    delay_loop(1000);

    // 2) 读回结果与状态
    unsigned res = Xil_In32(ACCEL_RESULT);
    unsigned st  = Xil_In32(ACCEL_STATUS);

    xil_printf("   A=%u B=%u C=%u D=%u\r\n", a, b, c, d);
    xil_printf("   STATUS=0x%08X (valid=%d)\r\n", st, st & 1);
    xil_printf("   RESULT=%u (expect %u)\r\n", res, a * b + c * d);
    xil_printf("   %s\r\n", (res == a * b + c * d) ? "[CHAIN OK]" : "[CHAIN FAIL]");

    // 3) 点亮 LED，给出板级联通反馈
    Xil_Out32(GPIO_DATA, 0x5A);
    xil_printf("--- demo done ---\r\n");
    return 0;
}
