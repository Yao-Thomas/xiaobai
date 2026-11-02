//=====================================================================
//  gpu2d.v  ——  简易 2D 图形加速器 (FPGA "GPU") 核心
//---------------------------------------------------------------------
//  功能:
//    op=0  FILL  矩形填充   (x0,y0)-(x1,y1) 用 color 填充
//    op=1  LINE  Bresenham 直线  (x0,y0)->(x1,y1)
//  像素格式: 24bpp packed  (内存里 B,G,R 三字节, 与 /dev/fb0 一致)
//  显存地址: base + y*stride + x*3
//
//  内存接口: 单次写握手  mem_we / mem_addr / mem_wdata / mem_ready
//            (真实系统里会包一层 AXI4 master / 突发写)
//
//  作者: DSH 为 Zynq-7020 自研桌面配套
//=====================================================================
`timescale 1ns / 1ps

module gpu2d #(
    parameter AW = 32
)(
    input  wire            clk,
    input  wire            rst_n,

    // ---- 控制寄存器 ----
    input  wire            start,
    input  wire [1:0]      op,        // 0=FILL  1=LINE
    input  wire [AW-1:0]   base,      // 显存基址(字节)
    input  wire [15:0]     stride,    // 行跨距(字节)
    input  wire [15:0]     x0,
    input  wire [15:0]     y0,
    input  wire [15:0]     x1,
    input  wire [15:0]     y1,
    input  wire [23:0]     color,     // {R,G,B}

    // ---- 状态 ----
    output reg             busy,
    output reg             done,
    output reg  [31:0]     pix_written,

    // ---- 内存写端口 ----
    output reg             mem_we,
    output reg  [AW-1:0]   mem_addr,
    output reg  [23:0]     mem_wdata,
    output reg             mem_last,      // 本行/本段的最后一个像素(AXI 突发结尾)
    output reg  [15:0]     mem_run,       // 从当前像素起, 地址连续的像素个数
    input  wire            mem_ready,
    input  wire            mem_abort,     // 内存侧超时/出错 -> 中止本次操作
    output reg             err_flag       // 本次操作出错 (注意: 不要和 Bresenham 的 err 混用!)
);

    localparam S_IDLE = 3'd0,
               S_FILL = 3'd1,
               S_LINE = 3'd2,
               S_NEXT = 3'd3,
               S_DONE = 3'd4;

    reg [2:0]  state;
    reg [15:0] cx, cy;              // 当前坐标
    // Bresenham
    reg signed [16:0] dx, dy, err;
    reg signed [16:0] sx, sy;
    reg        steep;

    // 目标坐标(按像素存储的 BGR: 低字节=B, 中=G, 高=R)
    // 注意: Verilog {a,b,c} 中 a 在高位! 所以这里高字节放 R
    wire [23:0] wdata = {color[23:16], color[15:8], color[7:0]}; // -> R,G,B 拼接
    wire [15:0] row_len = (x1 - x0) + 16'd1;                     // 本行像素数

    function [AW-1:0] addr_of;
        input [15:0] px;
        input [15:0] py;
        begin
            addr_of = base + (py * stride) + (px * 3);
        end
    endfunction

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state       <= S_IDLE;
            busy        <= 1'b0;
            done        <= 1'b0;
            pix_written <= 32'd0;
            mem_we      <= 1'b0;
            mem_addr    <= {AW{1'b0}};
            mem_wdata   <= 24'd0;
            mem_last    <= 1'b0;
            mem_run     <= 16'd0;
            err_flag    <= 1'b0;
            cx <= 16'd0; cy <= 16'd0;
            dx <= 0; dy <= 0; err <= 0; sx <= 0; sy <= 0; steep <= 1'b0;
        end else begin
            // ★ 这里【不能】有 mem_we <= 1'b0 的默认赋值!
            //   否则在 "we=1 等 ready" 期间会被强制拉低, 下一拍的 ack 撞上 we=0 而丢失,
            //   主控就会反复重写同一个像素(实测每像素 500+ 周期)。
            //   mem_we 现在由各状态显式管理。
            case (state)
            // ---------------- IDLE ----------------
            S_IDLE: begin
                done <= 1'b0;
                if (start) begin
                    busy        <= 1'b1;
                    pix_written <= 32'd0;
                    err_flag    <= 1'b0;            // 每次操作清错误标志
                    cx <= x0;
                    cy <= y0;
                    if (op == 2'd0) begin
                        state <= S_FILL;
                    end else begin
                        // Bresenham 初始化
                        dx <= (x1 >= x0) ? (x1 - x0) : (x0 - x1);
                        dy <= (y1 >= y0) ? (y1 - y0) : (y0 - y1);
                        sx <= (x1 >= x0) ? 17'sd1 : -17'sd1;
                        sy <= (y1 >= y0) ? 17'sd1 : -17'sd1;
                        err <= ((x1 >= x0) ? (x1 - x0) : (x0 - x1))
                             - ((y1 >= y0) ? (y1 - y0) : (y0 - y1));
                        steep <= 1'b0;
                        state <= S_LINE;
                    end
                end
            end
            // ---------------- 矩形填充 (★ 每行握手一次) ----------------
            // 一行的像素颜色都相同, 所以核心只需给出【起始地址 + 行像素数】,
            // 由 AXI 主控自己生成整行字节流 —— 消除了每像素握手开销。
            S_FILL: begin
                if (mem_abort) begin
                    mem_we   <= 1'b0;
                    err_flag <= 1'b1;
                    state    <= S_DONE;
                end else if (mem_we && mem_ready) begin // 整行写完
                    mem_we      <= 1'b0;
                    pix_written <= pix_written + row_len;
                    if (cy >= y1) begin
                        state <= S_DONE;
                    end else begin
                        cy <= cy + 16'd1;
                    end
                end else if (!mem_we) begin
                    mem_we    <= 1'b1;
                    mem_addr  <= addr_of(x0, cy);
                    mem_wdata <= wdata;
                    mem_last  <= 1'b1;
                    mem_run   <= row_len;           // 整行像素数
                end
            end
            // ---------------- 直线 (Bresenham) ----------------
            S_LINE: begin
                if (mem_abort) begin                    // 内存侧出错 -> 中止
                    mem_we   <= 1'b0;
                    err_flag <= 1'b1;
                    state    <= S_DONE;
                end else if (mem_we && mem_ready) begin // ★ 先握手
                    mem_we      <= 1'b0;
                    pix_written <= pix_written + 32'd1;
                    if ((cx == x1) && (cy == y1)) begin
                        state <= S_DONE;
                    end else begin
                        state <= S_NEXT;
                    end
                end else if (!mem_we) begin
                    mem_we    <= 1'b1;
                    mem_addr  <= addr_of(cx, cy);
                    mem_wdata <= wdata;
                    mem_last  <= 1'b1;              // 直线每个像素单独一段
                    mem_run   <= 16'd1;
                end
            end
            S_NEXT: begin
                // e2 = 2*err  (一次算好, 避免 err 被赋值两次)
                // Bresenham: e2 > -dy 则 x 步进; e2 < dx 则 y 步进
                err <= err
                     + (((err * 2) > -dy) ? -dy : 17'sd0)
                     + (((err * 2) <  dx) ?  dx : 17'sd0);
                if ((err * 2) > -dy) begin
                    if (cx != x1) cx <= (sx > 0) ? (cx + 16'd1) : (cx - 16'd1);
                end
                if ((err * 2) <  dx) begin
                    if (cy != y1) cy <= (sy > 0) ? (cy + 16'd1) : (cy - 16'd1);
                end
                state <= S_LINE;
            end
            // ---------------- 完成 ----------------
            S_DONE: begin
                mem_we <= 1'b0;          // 保证操作之间 mem_we 一定是低的
                busy  <= 1'b0;
                done  <= 1'b1;
                state <= S_IDLE;
            end
            default: state <= S_IDLE;
            endcase
        end
    end

endmodule
