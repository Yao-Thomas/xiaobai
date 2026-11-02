// ============================================================================
// adc_capture.v —— 并行 ADC(如 AD9280, 8bit) -> AXI4-Stream 采集模块
//   把 PACK 个采样点打包成一个 32bit 字，按 AXI4-Stream 送给 AXI VDMA 的 S2MM。
//   带简单背压处理：只有 (m_tready | !m_tvalid) 时才推进采样计数。
//   带宽：adc_clk 频率 f，每 PACK 个采样出 1 个字 -> 字速率 f/PACK。
//         确保下游(VDMA/DDR)能吃下，否则靠 m_tready 反压(此处会丢采样,见 NOTE)。
//   NOTE: 采样是连续流，AXI 有背压时严格不丢需要加 FIFO；本模块为起点骨架，
//         如需不丢采样，请在 shreg 前插入异步/同步 FIFO。
// ============================================================================
`timescale 1ns/1ps

module adc_capture #(
    parameter integer ADC_W     = 8,      // ADC 位宽
    parameter integer PACK      = 4,      // 每字打包采样数 (32/ADC_W)
    parameter integer LINE_WORDS= 1024    // 每 "行"(tlast) 的字数; 0=不产生 tlast
)(
    input  wire               adc_clk,    // ADC 采样时钟
    input  wire               rst_n,
    input  wire [ADC_W-1:0]   adc_data,   // ADC 并行数据

    // AXI4-Stream Master (32-bit)
    output reg                m_axis_tvalid,
    input  wire               m_axis_tready,
    output reg  [31:0]        m_axis_tdata,
    output reg                m_axis_tlast
);

    reg [31:0] shreg;      // 采样移位/打包
    reg [31:0] word;       // 打包好的字
    reg [7:0]  pcnt;       // 已收采样数
    reg [31:0] wcnt;       // 已发字数
    reg        have;       // 是否有待发的字

    wire ready = m_axis_tready | ~m_axis_tvalid;

    always @(posedge adc_clk) begin
        if (!rst_n) begin
            shreg <= 32'd0; word <= 32'd0; pcnt <= 8'd0; wcnt <= 32'd0; have <= 1'b0;
            m_axis_tvalid <= 1'b0; m_axis_tdata <= 32'd0; m_axis_tlast <= 1'b0;
        end else begin
            // 握手：下游取走则清 valid
            if (m_axis_tvalid && m_axis_tready)
                m_axis_tvalid <= 1'b0;

            // 攒够 PACK 个采样 -> 出一个字
            if (ready) begin
                if (pcnt == PACK-1) begin
                    pcnt <= 8'd0;
                    word <= {shreg[31-ADC_W:0], adc_data};  // 打包(低位在前)
                    have <= 1'b1;
                end else begin
                    shreg <= {shreg[31-ADC_W:0], adc_data};
                    pcnt  <= pcnt + 8'd1;
                end
            end

            // 推送打包好的字
            if (have && !m_axis_tvalid) begin
                m_axis_tdata  <= word;
                m_axis_tvalid <= 1'b1;
                if (LINE_WORDS != 0) begin
                    m_axis_tlast <= (wcnt == LINE_WORDS-1);
                    wcnt <= (wcnt == LINE_WORDS-1) ? 32'd0 : wcnt + 32'd1;
                end else begin
                    m_axis_tlast <= 1'b0;
                end
                have <= 1'b0;
            end
        end
    end

endmodule
