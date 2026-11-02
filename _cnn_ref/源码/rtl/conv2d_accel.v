// ============================================================================
// conv2d_accel.v —— 真正 3x3 卷积加速器（AXI4-Lite 从机），小尺寸组合式实现
//   M4a：验证"真卷积"在 PL 上计算（4x4 图 x 3x3 核 -> 2x2 输出）。
//   完全套用已验证可跑的 conv_accel_axi_lite 的 AXI 结构。
//
// 寄存器（基址 0x43C00000，AXI4-Lite，ADDR_WIDTH=8）：
//   word 0x000..0x00F  img[0..15]   (W, 字节地址 base + i*4)
//   word 0x010..0x018  kern[0..8]   (W, 字节地址 base + 0x40 + i*4)
//   word 0x020..0x023  out[0..3]    (R, 字节地址 base + 0x80 + i*4)
//   word 0x040         ctrl         (W bit0=start, R bit0=busy bit1=done, 字节 base+0x100)
// ============================================================================
`timescale 1ns / 1ps
module conv2d_accel #(
    parameter integer C_AXI_ADDR_WIDTH = 8,
    parameter integer C_AXI_DATA_WIDTH = 32
)(
    input  wire                            S_AXI_ACLK,
    input  wire                            S_AXI_ARESETN,
    input  wire                            S_AXI_AWVALID, output wire S_AXI_AWREADY,
    input  wire [C_AXI_ADDR_WIDTH-1:0]     S_AXI_AWADDR,
    input  wire                            S_AXI_WVALID,  output wire S_AXI_WREADY,
    input  wire [C_AXI_DATA_WIDTH-1:0]     S_AXI_WDATA,
    input  wire [C_AXI_DATA_WIDTH/8-1:0]   S_AXI_WSTRB,
    output wire                            S_AXI_BVALID, input wire S_AXI_BREADY, output wire [1:0] S_AXI_BRESP,
    input  wire                            S_AXI_ARVALID, output wire S_AXI_ARREADY,
    input  wire [C_AXI_ADDR_WIDTH-1:0]     S_AXI_ARADDR,
    output wire                            S_AXI_RVALID, input wire S_AXI_RREADY,
    output wire [C_AXI_DATA_WIDTH-1:0]     S_AXI_RDATA,  output wire [1:0] S_AXI_RRESP
);

    // ---- 寄存器区 ----
    reg [31:0] img  [0:15];
    reg [31:0] kern [0:8];
    reg [31:0] out  [0:3];
    reg        start_bit = 0;
    reg        busy = 0, done = 0, start_prev = 0;
    integer    i;

    // ---- 组合卷积：4x4 图 -> 2x2 输出（低 8 位像素/权重）----
    function [15:0] conv_pt;
        input [1:0] oy, ox;
        begin
            conv_pt = img[(oy+0)*4+(ox+0)][7:0]*kern[0][7:0] + img[(oy+0)*4+(ox+1)][7:0]*kern[1][7:0]
                    + img[(oy+0)*4+(ox+2)][7:0]*kern[2][7:0] + img[(oy+1)*4+(ox+0)][7:0]*kern[3][7:0]
                    + img[(oy+1)*4+(ox+1)][7:0]*kern[4][7:0] + img[(oy+1)*4+(ox+2)][7:0]*kern[5][7:0]
                    + img[(oy+2)*4+(ox+0)][7:0]*kern[6][7:0] + img[(oy+2)*4+(ox+1)][7:0]*kern[7][7:0]
                    + img[(oy+2)*4+(ox+2)][7:0]*kern[8][7:0];
        end
    endfunction

    // 触发计算（start_bit 上升沿 -> 组合算出 4 个输出并锁存，置 done）
    always @(posedge S_AXI_ACLK or negedge S_AXI_ARESETN) begin
        if (!S_AXI_ARESETN) begin
            busy <= 0; done <= 0; start_prev <= 0;
            for (i=0;i<4;i=i+1) out[i] <= 0;
        end else begin
            if (start_bit && !start_prev) begin
                out[0] <= conv_pt(2'd0,2'd0);
                out[1] <= conv_pt(2'd0,2'd1);
                out[2] <= conv_pt(2'd1,2'd0);
                out[3] <= conv_pt(2'd1,2'd1);
                busy <= 1; done <= 0;
            end
            start_prev <= start_bit;
            if (busy) begin busy <= 0; done <= 1; end   // 拍一拍后置 done
        end
    end

    // ===================== AXI4-Lite 写通道 =====================
    reg awready=0, wready=0, bvalid=0;
    reg [C_AXI_ADDR_WIDTH-1:0] awaddr_l=0;
    assign S_AXI_AWREADY=awready; assign S_AXI_WREADY=wready;
    assign S_AXI_BRESP=2'b00;     assign S_AXI_BVALID=bvalid;

    always @(posedge S_AXI_ACLK) begin
        if (!S_AXI_ARESETN) begin awready<=0; wready<=0; bvalid<=0; awaddr_l<=0; start_bit<=0; end
        else begin
            if (S_AXI_AWVALID && !awready) begin awaddr_l<=S_AXI_AWADDR; awready<=1; end
            else if (!S_AXI_AWVALID && awready) awready<=0;
            if (S_AXI_WVALID && !wready) wready<=1;
            else if (!S_AXI_WVALID && wready) wready<=0;
            if (awready && wready) begin
                case (awaddr_l[7:2])
                    6'h00: img[0]  <= S_AXI_WDATA;
                    6'h01: img[1]  <= S_AXI_WDATA;
                    6'h02: img[2]  <= S_AXI_WDATA;
                    6'h03: img[3]  <= S_AXI_WDATA;
                    6'h04: img[4]  <= S_AXI_WDATA;
                    6'h05: img[5]  <= S_AXI_WDATA;
                    6'h06: img[6]  <= S_AXI_WDATA;
                    6'h07: img[7]  <= S_AXI_WDATA;
                    6'h08: img[8]  <= S_AXI_WDATA;
                    6'h09: img[9]  <= S_AXI_WDATA;
                    6'h0A: img[10] <= S_AXI_WDATA;
                    6'h0B: img[11] <= S_AXI_WDATA;
                    6'h0C: img[12] <= S_AXI_WDATA;
                    6'h0D: img[13] <= S_AXI_WDATA;
                    6'h0E: img[14] <= S_AXI_WDATA;
                    6'h0F: img[15] <= S_AXI_WDATA;
                    6'h10: kern[0] <= S_AXI_WDATA;
                    6'h11: kern[1] <= S_AXI_WDATA;
                    6'h12: kern[2] <= S_AXI_WDATA;
                    6'h13: kern[3] <= S_AXI_WDATA;
                    6'h14: kern[4] <= S_AXI_WDATA;
                    6'h15: kern[5] <= S_AXI_WDATA;
                    6'h16: kern[6] <= S_AXI_WDATA;
                    6'h17: kern[7] <= S_AXI_WDATA;
                    6'h18: kern[8] <= S_AXI_WDATA;
                    6'h24: start_bit <= S_AXI_WDATA[0];
                    default: ;
                endcase
                bvalid <= 1;
            end else if (bvalid && S_AXI_BREADY) bvalid <= 0;
        end
    end

    // ===================== AXI4-Lite 读通道 =====================
    reg arready=0, rvalid=0;
    reg [31:0] rdata=0;
    assign S_AXI_ARREADY=arready; assign S_AXI_RRESP=2'b00;
    assign S_AXI_RVALID=rvalid;  assign S_AXI_RDATA=rdata;

    always @(posedge S_AXI_ACLK) begin
        if (!S_AXI_ARESETN) begin arready<=0; rvalid<=0; rdata<=0; end
        else begin
            if (S_AXI_ARVALID && !arready) begin
                arready<=1;
                case (S_AXI_ARADDR[7:2])
                    6'h00: rdata <= img[0];
                    6'h01: rdata <= img[1];
                    6'h02: rdata <= img[2];
                    6'h03: rdata <= img[3];
                    6'h04: rdata <= img[4];
                    6'h05: rdata <= img[5];
                    6'h06: rdata <= img[6];
                    6'h07: rdata <= img[7];
                    6'h08: rdata <= img[8];
                    6'h09: rdata <= img[9];
                    6'h0A: rdata <= img[10];
                    6'h0B: rdata <= img[11];
                    6'h0C: rdata <= img[12];
                    6'h0D: rdata <= img[13];
                    6'h0E: rdata <= img[14];
                    6'h0F: rdata <= img[15];
                    6'h10: rdata <= kern[0];
                    6'h11: rdata <= kern[1];
                    6'h12: rdata <= kern[2];
                    6'h13: rdata <= kern[3];
                    6'h14: rdata <= kern[4];
                    6'h15: rdata <= kern[5];
                    6'h16: rdata <= kern[6];
                    6'h17: rdata <= kern[7];
                    6'h18: rdata <= kern[8];
                    6'h20: rdata <= out[0];
                    6'h21: rdata <= out[1];
                    6'h22: rdata <= out[2];
                    6'h23: rdata <= out[3];
                    6'h24: rdata <= {30'b0, done, busy};
                    default: rdata <= 32'h0;
                endcase
                rvalid<=1;
            end else begin
                if (arready && !S_AXI_ARVALID) arready<=0;
                if (rvalid && S_AXI_RREADY)    rvalid<=0;
            end
        end
    end

endmodule
