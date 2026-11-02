// ============================================================================
// led_blink.v —— M1 里程碑：纯 PL LED 闪烁（验证 FPGA 配置 + LED）
// 输入：sys_clk  (U18 板载 50MHz 时钟)，sys_rst_n (N16 低有效复位)
// 输出：led0/led1 (底板 LED，H15/L15)
// ============================================================================
`timescale 1ns / 1ps
module led_blink (
    input  sys_clk,     // U18, 50MHz
    input  sys_rst_n,   // N16
    output led0,        // H15
    output led1         // L15
);
    reg [25:0] cnt;
    always @(posedge sys_clk or negedge sys_rst_n) begin
        if (!sys_rst_n) cnt <= 26'd0;
        else            cnt <= cnt + 1'b1;
    end
    // 50MHz / 2^26 ~= 0.75Hz（led0 慢闪）；2^25 ~= 1.5Hz（led1 快闪）
    assign led0 = cnt[25];
    assign led1 = cnt[24];
endmodule
