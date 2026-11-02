//=====================================================================
//  gpu2d_axi.v  ——  gpu2d 的 AXI 封装
//---------------------------------------------------------------------
//  · S_AXI : AXI4-Lite 从机 (控制寄存器)
//      0x00 CTRL    W[0]=start        R[0]=done R[1]=busy
//      0x04 OP      [1:0]  0=FILL 1=LINE
//      0x08 BASE    [31:0] 显存基址
//      0x0C STRIDE  [15:0] 行跨距(字节, 24bpp -> 宽度*3)
//      0x10 XY0     [31:16]=x0 [15:0]=y0
//      0x14 XY1     [31:16]=x1 [15:0]=y1
//      0x18 COLOR   [23:0] 0xRRGGBB
//      0x1C PIXCNT  [31:0] 已写像素数 (只读)
//
//  · M_AXI : AXI4 主机 (只写, AWSIZE=1字节, INCR 突发)
//      把 gpu2d 产生的像素流按连续段突发写入 DDR
//      连续段长度由核心的 mem_run 给出, 每段最多 256 字节
//
//  仿真验证: tb_gpu2d_axi.v  全部通过
//=====================================================================
`timescale 1ns / 1ps

module gpu2d_axi #(
    parameter AW = 32,
    parameter C_S_AXI_ADDR_WIDTH = 6
)(
    input  wire        aclk,
    input  wire        aresetn,

    // ---------------- AXI4-Lite 从机 ----------------
    input  wire [C_S_AXI_ADDR_WIDTH-1:0] s_axi_awaddr,
    input  wire [2:0]  s_axi_awprot,
    input  wire        s_axi_awvalid,
    output reg         s_axi_awready,
    input  wire [31:0] s_axi_wdata,
    input  wire [3:0]  s_axi_wstrb,
    input  wire        s_axi_wvalid,
    output reg         s_axi_wready,
    output reg  [1:0]  s_axi_bresp,
    output reg         s_axi_bvalid,
    input  wire        s_axi_bready,
    input  wire [C_S_AXI_ADDR_WIDTH-1:0] s_axi_araddr,
    input  wire [2:0]  s_axi_arprot,
    input  wire        s_axi_arvalid,
    output reg         s_axi_arready,
    output reg  [31:0] s_axi_rdata,
    output reg  [1:0]  s_axi_rresp,
    output reg         s_axi_rvalid,
    input  wire        s_axi_rready,

    // ---------------- AXI4 主机 (只写) ----------------
    output reg  [AW-1:0]   m_axi_awaddr,
    output reg  [7:0]      m_axi_awlen,
    output wire [2:0]      m_axi_awsize,
    output wire [1:0]      m_axi_awburst,
    output reg             m_axi_awvalid,
    input  wire            m_axi_awready,
    output wire [31:0]     m_axi_wdata,
    output wire [3:0]      m_axi_wstrb,
    output wire            m_axi_wlast,
    output reg             m_axi_wvalid,
    input  wire            m_axi_wready,
    input  wire [1:0]      m_axi_bresp,
    input  wire            m_axi_bvalid,
    output reg             m_axi_bready
);

    assign m_axi_awsize  = 3'b000;   // 1 字节/拍
    assign m_axi_awburst = 2'b01;    // INCR

    //=========================================================
    //  寄存器
    //=========================================================
    reg [31:0] reg_base;
    reg [15:0] reg_stride;
    reg [15:0] reg_x0, reg_y0, reg_x1, reg_y1;
    reg [23:0] reg_color;
    reg [1:0]  reg_op;
    reg        reg_start;

    //=========================================================
    //  gpu2d 核心实例
    //=========================================================
    wire          g_busy, g_done, g_mem_we, g_mem_last;
    wire [AW-1:0] g_mem_addr;
    wire [23:0]   g_mem_wdata;
    wire [15:0]   g_mem_run;
    wire [31:0]   g_pixcnt;
    wire          g_err_flag;
    reg           g_mem_ready_r;
    reg           g_abort;
    wire          g_mem_ready = g_mem_ready_r;

    gpu2d #(.AW(AW)) u_gpu (
        .clk(aclk), .rst_n(aresetn),
        .start(reg_start), .op(reg_op),
        .base(reg_base), .stride(reg_stride),
        .x0(reg_x0), .y0(reg_y0), .x1(reg_x1), .y1(reg_y1),
        .color(reg_color),
        .busy(g_busy), .done(g_done), .pix_written(g_pixcnt),
        .mem_we(g_mem_we), .mem_addr(g_mem_addr), .mem_wdata(g_mem_wdata),
        .mem_last(g_mem_last), .mem_run(g_mem_run),
        .mem_ready(g_mem_ready),
        .mem_abort(g_abort), .err_flag(g_err_flag)
    );

    // 错误标志 (总线超时 / 核心报错), 写 STATUS 位0 清
    reg err_r;

    //=========================================================
    //  AXI4-Lite 从机 (寄存器读写)
    //=========================================================
    reg [C_S_AXI_ADDR_WIDTH-1:0] awaddr_l;
    reg [31:0] wdata_l;
    reg [3:0]  wstrb_l;

    always @(posedge aclk or negedge aresetn) begin
        if (!aresetn) begin
            s_axi_awready <= 1'b0; s_axi_wready <= 1'b0; s_axi_bvalid <= 1'b0;
            s_axi_bresp   <= 2'b00;
            s_axi_arready <= 1'b0; s_axi_rvalid <= 1'b0; s_axi_rdata <= 32'd0;
            s_axi_rresp   <= 2'b00;
            awaddr_l <= 0; wdata_l <= 0; wstrb_l <= 0;
            reg_base <= 32'd0; reg_stride <= 16'd3072;
            reg_x0 <= 0; reg_y0 <= 0; reg_x1 <= 0; reg_y1 <= 0;
            reg_color <= 24'd0; reg_op <= 2'd0; reg_start <= 1'b0;
        end else begin
            // ---- 写地址/数据 接收 ----
            if (!s_axi_awready && s_axi_awvalid && s_axi_wvalid) begin
                awaddr_l      <= s_axi_awaddr;
                wdata_l       <= s_axi_wdata;
                wstrb_l       <= s_axi_wstrb;
                s_axi_awready <= 1'b1;
                s_axi_wready  <= 1'b1;
            end else begin
                s_axi_awready <= 1'b0;
                s_axi_wready  <= 1'b0;
            end

            // ---- 写入寄存器 ----
            if (s_axi_awready && s_axi_wready) begin
                s_axi_bvalid <= 1'b1;
                s_axi_bresp  <= 2'b00;
                case (awaddr_l[5:2])
                    4'h0: if (wstrb_l[0]) reg_start <= wdata_l[0];
                    4'h1: reg_op     <= wdata_l[1:0];
                    4'h2: reg_base   <= wdata_l;
                    4'h3: reg_stride <= wdata_l[15:0];
                    4'h4: begin reg_x0 <= wdata_l[31:16]; reg_y0 <= wdata_l[15:0]; end
                    4'h5: begin reg_x1 <= wdata_l[31:16]; reg_y1 <= wdata_l[15:0]; end
                    4'h6: reg_color  <= wdata_l[23:0];
                    4'h8: if (wstrb_l[0] && wdata_l[0]) err_r <= 1'b0;  // STATUS: 写1清错误
                    default: ;
                endcase
            end
            if (s_axi_bvalid && s_axi_bready) s_axi_bvalid <= 1'b0;

            // start 是脉冲, 自动清零
            if (reg_start) reg_start <= 1'b0;

            // ---- 读 ----
            if (!s_axi_arready && s_axi_arvalid) s_axi_arready <= 1'b1;
            else                                   s_axi_arready <= 1'b0;

            if (s_axi_arready && s_axi_arvalid) begin
                s_axi_rvalid <= 1'b1;
                s_axi_rresp  <= 2'b00;
                case (s_axi_araddr[5:2])
                    4'h0: s_axi_rdata <= {30'd0, g_busy, g_done};
                    4'h1: s_axi_rdata <= {30'd0, reg_op};
                    4'h2: s_axi_rdata <= reg_base;
                    4'h3: s_axi_rdata <= {16'd0, reg_stride};
                    4'h4: s_axi_rdata <= {reg_x0, reg_y0};
                    4'h5: s_axi_rdata <= {reg_x1, reg_y1};
                    4'h6: s_axi_rdata <= {8'd0, reg_color};
                    4'h7: s_axi_rdata <= g_pixcnt;
                    4'h8: s_axi_rdata <= {31'd0, err_r};
                    default: s_axi_rdata <= 32'hDEADBEEF;
                endcase
            end
            if (s_axi_rvalid && s_axi_rready) s_axi_rvalid <= 1'b0;
        end
    end

    //=========================================================
    //  AXI4 主机 (只写)
    //  ★ 核心按【行】交给主控一个 run(起始地址+像素数+颜色),
    //    主控自己生成整行字节流(B,G,R 循环)并突发写入 DDR,
    //    整行写完才 ack 核心一次 —— 消除每像素握手开销。
    //=========================================================
    localparam M_IDLE = 3'd0, M_AW = 3'd1, M_W = 3'd2,
               M_B    = 3'd3, M_ACK = 3'd4, M_ERR = 3'd5;
    localparam TIMEOUT_MAX = 32'd200000;   // 2 ms @100MHz

    reg [2:0]  mst;
    reg [31:0] to_cnt;
    reg [23:0] pix_data;        // 本次 run 的颜色 {R,G,B}
    reg [1:0]  phase;           // 当前字节在像素内的位置: 0=B 1=G 2=R
    reg [15:0] run_total;       // 本次 run 总字节数 = 像素数 * 3
    reg [15:0] run_idx;         // 已发出的字节数
    reg [15:0] burst_len;       // 当前突发的字节数
    reg [15:0] burst_sent;      // 当前突发已发出的字节数
    reg [AW-1:0] run_addr;      // run 的起始地址

    wire [15:0] run_bytes   = g_mem_run * 16'd3;
    // 单次 AXI 突发最多 256 拍 -> 最多 255 字节
    wire [15:0] first_burst = (run_bytes > 16'd255) ? 16'd255 : run_bytes;
    wire [15:0] rest_bytes  = run_total - run_idx;
    wire [15:0] next_burst  = (rest_bytes > 16'd255) ? 16'd255 : rest_bytes;

    // W 通道组合输出: 数据和地址同拍对齐
    assign m_axi_wdata = {24'd0, (phase == 2'd0) ? pix_data[7:0] :
                                  (phase == 2'd1) ? pix_data[15:8] :
                                                    pix_data[23:16]};
    assign m_axi_wstrb = 4'b0001;
    assign m_axi_wlast = m_axi_wvalid && ((burst_sent + 16'd1) >= burst_len);

    always @(posedge aclk or negedge aresetn) begin
        if (!aresetn) begin
            mst <= M_IDLE;
            m_axi_awaddr <= 0; m_axi_awlen <= 0; m_axi_awvalid <= 0;
            m_axi_wvalid <= 0; m_axi_bready <= 0;
            g_mem_ready_r <= 1'b0;
            g_abort <= 1'b0;
            err_r <= 1'b0;
            to_cnt <= 32'd0;
            pix_data <= 0; phase <= 0; run_total <= 0; run_idx <= 0;
            burst_len <= 0; burst_sent <= 0; run_addr <= 0;
        end else begin
            // ---------- 总线超时保护 ----------
            // 2ms @100MHz; 任何握手成功都清零计数
            if (mst == M_IDLE) begin
                to_cnt <= 32'd0;
            end else if ((m_axi_awvalid && m_axi_awready) ||
                         (m_axi_wvalid  && m_axi_wready)  ||
                         (m_axi_bvalid  && m_axi_bready)) begin
                to_cnt <= 32'd0;
            end else if (to_cnt >= TIMEOUT_MAX) begin
                // 超时! 中止总线动作, 报错, 让核心停下
                m_axi_awvalid <= 1'b0;
                m_axi_wvalid  <= 1'b0;
                m_axi_bready  <= 1'b0;
                err_r         <= 1'b1;
                mst           <= M_ERR;
            end else begin
                to_cnt <= to_cnt + 32'd1;
            end

            case (mst)
            // ---------- 空闲: 等核心给一个 run ----------
            M_IDLE: begin
                g_mem_ready_r <= 1'b0;
                if (g_mem_we) begin
                    pix_data      <= g_mem_wdata;
                    run_total     <= run_bytes;
                    run_addr      <= g_mem_addr;
                    run_idx       <= 16'd0;
                    phase         <= 2'd0;
                    burst_len     <= first_burst;
                    burst_sent    <= 16'd0;
                    m_axi_awaddr  <= g_mem_addr;
                    m_axi_awlen   <= first_burst[7:0] - 8'd1;
                    m_axi_awvalid <= 1'b1;
                    mst           <= M_AW;
                end
            end
            // ---------- 写地址 ----------
            M_AW: begin
                if (m_axi_awready) begin
                    m_axi_awvalid <= 1'b0;
                    mst <= M_W;
                end
            end
            // ---------- 写数据: 主控自己按 B,G,R 循环生成 ----------
            M_W: begin
                m_axi_wvalid <= 1'b1;
                if (m_axi_wvalid && m_axi_wready) begin
                    run_idx    <= run_idx + 16'd1;
                    burst_sent <= burst_sent + 16'd1;
                    phase      <= (phase == 2'd2) ? 2'd0 : phase + 2'd1;
                    if ((burst_sent + 16'd1) >= burst_len) begin
                        m_axi_wvalid <= 1'b0;      // 本突发发完
                        mst          <= M_B;
                    end
                end
            end
            // ---------- 等写响应 ----------
            M_B: begin
                m_axi_bready <= 1'b1;
                if (m_axi_bvalid && m_axi_bready) begin
                    m_axi_bready <= 1'b0;
                    if (run_idx >= run_total) begin
                        g_mem_ready_r <= 1'b1;     // ★ 整个 run 写完, ack 核心
                        mst           <= M_ACK;
                    end else begin
                        // 还有数据 -> 接着开下一个突发
                        m_axi_awaddr  <= run_addr + run_idx;
                        m_axi_awlen   <= next_burst[7:0] - 8'd1;
                        m_axi_awvalid <= 1'b1;
                        burst_len     <= next_burst;
                        burst_sent    <= 16'd0;
                        mst           <= M_AW;
                    end
                end
            end
            // ---------- ack 核心一拍 ----------
            M_ACK: begin
                g_mem_ready_r <= 1'b0;
                mst <= M_IDLE;
            end
            // ---------- 出错/超时: 等核心停下 ----------
            M_ERR: begin
                g_abort <= 1'b1;
                g_mem_ready_r <= 1'b0;
                if (!g_busy) begin
                    g_abort <= 1'b0;
                    mst     <= M_IDLE;
                end
            end
            default: mst <= M_IDLE;
            endcase
        end
    end

endmodule
