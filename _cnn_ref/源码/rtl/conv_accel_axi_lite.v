// ============================================================================
// conv_accel_axi_lite.v —— Zynq PL 侧 AXI4-Lite 从机加速器（链路验证用）
//
// 计算： y = A*B + C*D
// 寄存器映射（基址 0x43C00000，与 Block Design 一致）：
//   0x00 = A (R/W)
//   0x04 = B (R/W)
//   0x08 = C (R/W)
//   0x0C = D (R/W)
//   0x10 = result = A*B + C*D (R)
//   0x14 = status (R, bit0=valid, bit1=busy)
//
// 采用标准 AXI4-Lite 从机握手（地址与数据分离，逐拍就绪）。
// 后续可用 M2 生成的 conv2d HLS IP 替换本 MAC 核（见 ROADMAP M3b）。
// ============================================================================
`timescale 1ns / 1ps

module conv_accel_axi_lite #(
    parameter integer C_AXI_ADDR_WIDTH = 6,
    parameter integer C_AXI_DATA_WIDTH = 32
)(
    input  wire                            S_AXI_ACLK,
    input  wire                            S_AXI_ARESETN,
    // 写地址通道
    input  wire                            S_AXI_AWVALID,
    output wire                            S_AXI_AWREADY,
    input  wire [C_AXI_ADDR_WIDTH-1:0]     S_AXI_AWADDR,
    // 写数据通道
    input  wire                            S_AXI_WVALID,
    output wire                            S_AXI_WREADY,
    input  wire [C_AXI_DATA_WIDTH-1:0]     S_AXI_WDATA,
    input  wire [C_AXI_DATA_WIDTH/8-1:0]   S_AXI_WSTRB,
    // 写响应
    output wire                            S_AXI_BVALID,
    input  wire                            S_AXI_BREADY,
    output wire [1:0]                      S_AXI_BRESP,
    // 读地址通道
    input  wire                            S_AXI_ARVALID,
    output wire                            S_AXI_ARREADY,
    input  wire [C_AXI_ADDR_WIDTH-1:0]     S_AXI_ARADDR,
    // 读数据通道
    output wire                            S_AXI_RVALID,
    input  wire                            S_AXI_RREADY,
    output wire [C_AXI_DATA_WIDTH-1:0]     S_AXI_RDATA,
    output wire [1:0]                      S_AXI_RRESP
);

    // ---- 寄存器 ----
    reg [C_AXI_DATA_WIDTH-1:0] r_a = 0, r_b = 0, r_c = 0, r_d = 0;
    reg                        r_valid = 0;   // busy/valid 标志

    // ---- 写通道 ----
    reg awready = 0, wready = 0, bvalid = 0;
    reg [C_AXI_ADDR_WIDTH-1:0] awaddr_l = 0;
    assign S_AXI_AWREADY = awready;
    assign S_AXI_WREADY  = wready;
    assign S_AXI_BRESP   = 2'b00;
    assign S_AXI_BVALID  = bvalid;

    always @(posedge S_AXI_ACLK) begin
        if (!S_AXI_ARESETN) begin
            awready <= 0; wready <= 0; bvalid <= 0; awaddr_l <= 0;
            r_a <= 0; r_b <= 0; r_c <= 0; r_d <= 0; r_valid <= 0;
        end else begin
            // 写地址握手
            if (S_AXI_AWVALID && !awready) begin
                awaddr_l <= S_AXI_AWADDR[5:0];
                awready  <= 1;
            end else if (!S_AXI_AWVALID && awready) begin
                awready <= 0;
            end
            // 写数据握手
            if (S_AXI_WVALID && !wready) begin
                wready <= 1;
            end else if (!S_AXI_WVALID && wready) begin
                wready <= 0;
            end
            // 当地址与数据都准备好，按字偏移写寄存器，并给出写响应
            if (awready && wready) begin
                case (awaddr_l[5:2])
                    4'h0: r_a <= S_AXI_WDATA;
                    4'h1: r_b <= S_AXI_WDATA;
                    4'h2: r_c <= S_AXI_WDATA;
                    4'h3: r_d <= S_AXI_WDATA;
                    default: ;
                endcase
                r_valid <= 1'b1;
                bvalid  <= 1'b1;
            end else if (bvalid && S_AXI_BREADY) begin
                bvalid  <= 1'b0;
            end
        end
    end

    // ---- 读通道 ----
    reg arready = 0, rvalid = 0;
    reg [C_AXI_DATA_WIDTH-1:0] rdata = 0;
    assign S_AXI_ARREADY = arready;
    assign S_AXI_RRESP   = 2'b00;
    assign S_AXI_RVALID  = rvalid;
    assign S_AXI_RDATA   = rdata;

    always @(posedge S_AXI_ACLK) begin
        if (!S_AXI_ARESETN) begin
            arready <= 0; rvalid <= 0; rdata <= 0;
        end else begin
            if (S_AXI_ARVALID && !arready) begin
                arready <= 1;
                case (S_AXI_ARADDR[5:2])
                    4'h0:  rdata <= r_a;
                    4'h1:  rdata <= r_b;
                    4'h2:  rdata <= r_c;
                    4'h3:  rdata <= r_d;
                    4'h4:  rdata <= r_a * r_b + r_c * r_d;   // result
                    4'h5:  rdata <= {31'b0, r_valid};        // status
                    default: rdata <= 32'h0;
                endcase
                rvalid <= 1;
            end else begin
                if (arready && !S_AXI_ARVALID) arready <= 0;
                if (rvalid && S_AXI_RREADY)    rvalid  <= 0;
            end
        end
    end

endmodule
