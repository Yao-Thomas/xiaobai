//=====================================================================
//  gpu2d_axi.v  ——  gpu2d 的 AXI 封装
//---------------------------------------------------------------------
//  · S_AXI : AXI4-Lite 从机 (控制寄存器)   —— 寄存器映射保持不变
//      0x00 CTRL    W[0]=start        R[0]=done R[1]=busy
//      0x04 OP      [1:0]  0=FILL 1=LINE
//      0x08 BASE    [31:0] 显存基址
//      0x0C STRIDE  [15:0] 行跨距(字节, 24bpp -> 宽度*3)
//      0x10 XY0     [31:16]=x0 [15:0]=y0
//      0x14 XY1     [31:16]=x1 [15:0]=y1
//      0x18 COLOR   [23:0] 0xRRGGBB
//      0x1C PIXCNT  [31:0] 已写像素数 (只读)
//      0x20 STATUS  R[0]=err        W[0]=1 清错误
//
//  · M_AXI : AXI4 主机 (只写, 64 位数据, AWSIZE=3'b011 => 8 字节/拍)
//
//  =================== 2026-09 关键性能修复 ===================
//  原来:  assign m_axi_awsize = 3'b000;   // 1 字节/拍
//         assign m_axi_wdata  = 32 位;   assign m_axi_wstrb = 4 位;
//
//  AXI 总线明明是 64 位宽, 却一次只搬 1 个字节, 一次突发最多 255 字节。
//  实测整屏 1024x600 填充:
//        FPGA GPU 20.19 ms (91.3 MB/s)
//        CPU C 填充 3.58 ms (514.4 MB/s)   <- CPU 比它快 5.6 倍
//  理论值 = 1843200 字节 x 10ns(100MHz) = 18.43 ms, 实测 20.19ms => 91% 效率,
//  说明 100% 卡在"拍数"上, 根本不是我原来以为的 DDR 带宽问题。
//
//  现在:  64 位数据 + awsize=3'b011 (8 字节/拍)  => 理论上限 800 MB/s,
//         整屏填充理论值 2.30 ms, 真正快于 CPU。
//
//  =================== 突发拆分规则 (AXI4 强制) ===================
//    · 单个 INCR 突发最多 256 拍          (awlen 8 位)
//    · 单个突发不得跨越 4KB 地址边界      (这条不满足会写坏 DDR)
//  因此一个 run 会被拆成多个突发, 见 M_SETUP 状态。
//
//  =================== 字节流模型 (核心思路) ===================
//  核心按【行】交给主控一个 run: 起始字节地址 A + 像素数 N + 颜色。
//  内存里一个像素是 3 字节 B,G,R。
//
//  取  base = A & ~7      off = A & 7
//  构造"扩展流" E, 长度 = off + 3N:
//        E[p] = (p < off) ? 无关 : BGR[(p - off) % 3]
//  第 k 拍写地址 base + 8k, WDATA 是 E[8k .. 8k+7],
//  WSTRB 屏蔽掉 [0,off) 前缀 和 [off+3N, 末尾) 尾巴。
//
//  这样做的好处: 所有突发地址都是 8 字节对齐的, 彻底避开
//  "非对齐 INCR 突发首拍字节道摆放" 这个极易写错的地方;
//  前缀/尾巴用 WSTRB 屏蔽即可, 不会越界写坏别的内存。
//
//  相位(phase) 表示当前拍 lane0 对应的 BGR 相位:
//        0 -> B   1 -> G   2 -> R
//  因为 lane j 的相位 = (phase + j) % 3, 所以 8 个 lane 的相位
//  必然是 phase,phase+1,phase+2 的循环 -> 只有 3 种可能的 64 位字,
//  组合逻辑直接选出来, 不需要移位器。
//
//  仿真验证: tb_gpu2d_axi.v
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

    // ---------------- AXI4 主机 (只写, 64 位) ----------------
    output reg  [AW-1:0]   m_axi_awaddr,
    output reg  [7:0]      m_axi_awlen,
    output wire [2:0]      m_axi_awsize,
    output wire [1:0]      m_axi_awburst,
    output reg             m_axi_awvalid,
    input  wire            m_axi_awready,
    output wire [63:0]     m_axi_wdata,
    output wire [7:0]      m_axi_wstrb,
    output wire            m_axi_wlast,
    output reg             m_axi_wvalid,
    input  wire            m_axi_wready,
    input  wire [1:0]      m_axi_bresp,
    input  wire            m_axi_bvalid,
    output reg             m_axi_bready
);

    // ★★★ 关键修复: 8 字节/拍 (原来 3'b000 = 1 字节/拍, 慢 8 倍) ★★★
    assign m_axi_awsize  = 3'b011;   // 2^3 = 8 字节/拍
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
    // ★ 注意: err_r 只能在【AXI-Lite 寄存器块】里赋值!
    //   主控 FSM 用 mst_err_pulse 单拍脉冲通知, 否则会造成多驱动(DRC MDRV-1)
    reg err_r;
    reg mst_err_pulse;

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

            // ★ 主控超时脉冲 -> 置起错误状态 (只在这里赋值 err_r)
            if (mst_err_pulse) err_r <= 1'b1;

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
                    // 只报 err_r: 核心的出错只会由主控超时(发 abort)引起, 已被 err_r 覆盖
                    4'h8: s_axi_rdata <= {31'd0, err_r};
                    default: s_axi_rdata <= 32'hDEADBEEF;
                endcase
            end
            if (s_axi_rvalid && s_axi_rready) s_axi_rvalid <= 1'b0;
        end
    end

    //=========================================================
    //  AXI4 主机 (只写, 64 位)
    //=========================================================
    localparam M_IDLE  = 3'd0,   // 等核心给一个 run
               M_SETUP = 3'd1,   // 算好本次突发的 awaddr / awlen
               M_AW    = 3'd2,   // 写地址握手
               M_W     = 3'd3,   // 写数据握手
               M_B     = 3'd4,   // 等写响应
               M_ACK   = 3'd5,   // ack 核心一拍
               M_ERR   = 3'd6;   // 超时/出错
    localparam TIMEOUT_MAX = 32'd200000;   // 2 ms @100MHz

    reg [2:0]  mst;
    reg [31:0] to_cnt;

    reg [23:0]   pix_data;     // 本次 run 的颜色 {R,G,B}
    reg [2:0]    off_r;        // run 起始地址 & 7
    reg [17:0]   ext_total;    // 扩展流总字节数 = off + 3N
    reg [17:0]   beat_idx;     // run 内已发出的拍数 (0 起)
    reg [17:0]   beats_left;   // run 内还没发的拍数
    reg [17:0]   burst_beats;  // 本次突发的拍数
    reg [17:0]   burst_sent;   // 本次突发已发出的拍数
    reg [1:0]    phase;        // 当前拍 lane0 的 BGR 相位 (0/1/2)
    reg [AW-1:0] cur_addr;     // 本次突发的起始地址 (8 字节对齐)

    //---------- 组合: run -> 扩展流 / 拍数 ----------
    wire [17:0] run_bytes  = g_mem_run * 18'd3;      // 3N
    wire [17:0] ext_len    = {15'd0, g_mem_addr[2:0]} + run_bytes;
    wire [17:0] nbeats_all = (ext_len + 18'd7) >> 3; // ceil((off+3N)/8)

    //---------- 组合: 本次突发能发多少拍 ----------
    // 4KB 边界: 从 cur_addr 到下一个 4KB 边界还有多少字节 / 8
    wire [17:0] room4k = (18'd4096 - {6'd0, cur_addr[11:0]}) >> 3;
    wire [17:0] cap    = (room4k > 18'd256) ? 18'd256 : room4k;
    wire [17:0] this_burst = (beats_left > cap) ? cap : beats_left;

    //---------- 组合: 本拍的数据 / 掩码 ----------
    wire [17:0] pos0   = {beat_idx[14:0], 3'b000};      // beat_idx * 8
    wire [17:0] remain = ext_total - pos0;              // 本拍还能写几个字节
    wire [3:0]  nb     = (remain >= 18'd8) ? 4'd8 : remain[3:0];
    wire [7:0]  full_msk = (nb >= 4'd8) ? 8'hFF
                                        : ((8'h01 << nb) - 8'h01);

    // 相位推进 k 步 (mod 3)
    function [1:0] ph_inc;
        input [1:0] p;
        input [1:0] k;
        reg   [2:0] s;
        begin
            s = {1'b0, p} + {1'b0, k};
            ph_inc = (s >= 3'd3) ? (s - 3'd3) : s[1:0];
        end
    endfunction

    function [7:0] ch;
        input [1:0]  p;
        input [23:0] c;
        begin
            ch = (p == 2'd0) ? c[7:0] :          // B
                 (p == 2'd1) ? c[15:8] :         // G
                               c[23:16];         // R
        end
    endfunction

    // 当前地址 off 对应的初始相位 (第一个有效字节在 lane off 处, 相位 0)
    function [1:0] ph_of_off;
        input [2:0] o;
        case (o)
            3'd0: ph_of_off = 2'd0;   // off%3=0 -> 0
            3'd1: ph_of_off = 2'd2;   // off%3=1 -> (3-1)%3=2
            3'd2: ph_of_off = 2'd1;   // off%3=2 -> (3-2)%3=1
            3'd3: ph_of_off = 2'd0;
            3'd4: ph_of_off = 2'd2;
            3'd5: ph_of_off = 2'd1;
            3'd6: ph_of_off = 2'd0;
            default: ph_of_off = 2'd2; // 3'd7
        endcase
    endfunction

    wire [1:0] pA = phase;
    wire [1:0] pB = ph_inc(phase, 2'd1);
    wire [1:0] pC = ph_inc(phase, 2'd2);
    wire [7:0] lB0 = ch(pA, pix_data);   // lane0 / lane3 / lane6
    wire [7:0] lB1 = ch(pB, pix_data);   // lane1 / lane4 / lane7
    wire [7:0] lB2 = ch(pC, pix_data);   // lane2 / lane5

    // lane7..lane0 = pB,pA,pC,pB,pA,pC,pB,pA
    assign m_axi_wdata = { lB1, lB0, lB2, lB1, lB0, lB2, lB1, lB0 };

    // WSTRB: 第一拍要屏蔽 [0,off) 前缀, 每拍末尾都要屏蔽超出 ext_total 的尾巴
    assign m_axi_wstrb = (beat_idx == 18'd0)
                       ? (full_msk & (8'hFF << off_r))
                       : full_msk;

    assign m_axi_wlast = m_axi_wvalid && ((burst_sent + 18'd1) >= burst_beats);

    // 相位推进: 一拍发 nb 个字节, 相位 +nb (mod 3)
    // ★ ph_sum 的范围是 0..10 (phase<=2, nb<=8), 所以减法要分四档,
    //   只减一次 6 是不够的 (10-6=4 仍然是错的) —— 这里踩过一次坑。
    wire [3:0] ph_sum = {2'b00, phase} + {1'b0, nb};
    wire [1:0] ph_nxt = (ph_sum >= 4'd9) ? (ph_sum - 4'd9) :
                        (ph_sum >= 4'd6) ? (ph_sum - 4'd6) :
                        (ph_sum >= 4'd3) ? (ph_sum - 4'd3) : ph_sum[1:0];

    always @(posedge aclk or negedge aresetn) begin
        if (!aresetn) begin
            mst <= M_IDLE;
            m_axi_awaddr <= 0; m_axi_awlen <= 0; m_axi_awvalid <= 0;
            m_axi_wvalid <= 0; m_axi_bready <= 0;
            g_mem_ready_r <= 1'b0;
            g_abort <= 1'b0;
            mst_err_pulse <= 1'b0;          // err_r 归 AXI-Lite 块管, 这里只发脉冲
            to_cnt <= 32'd0;
            pix_data <= 0; off_r <= 0; ext_total <= 0;
            beat_idx <= 0; beats_left <= 0;
            burst_beats <= 0; burst_sent <= 0;
            phase <= 2'd0; cur_addr <= 0;
        end else begin
            mst_err_pulse <= 1'b0;          // 默认拉低, 只在超时那一拍拉高
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
                mst_err_pulse <= 1'b1;      // ★ 单拍脉冲通知 AXI-Lite 块置 err_r
                mst           <= M_ERR;
            end else begin
                to_cnt <= to_cnt + 32'd1;
            end

            case (mst)
            // ---------- 空闲: 等核心给一个 run ----------
            M_IDLE: begin
                g_mem_ready_r <= 1'b0;
                if (g_mem_we) begin
                    pix_data   <= g_mem_wdata;
                    off_r      <= g_mem_addr[2:0];
                    ext_total  <= ext_len;
                    beat_idx   <= 18'd0;
                    beats_left <= nbeats_all;
                    burst_sent <= 18'd0;
                    phase      <= ph_of_off(g_mem_addr[2:0]);
                    cur_addr   <= {g_mem_addr[AW-1:3], 3'b000};   // 8 字节对齐
                    mst        <= M_SETUP;
                end
            end
            // ---------- 算好本次突发的地址/长度 ----------
            M_SETUP: begin
                m_axi_awaddr  <= cur_addr;
                m_axi_awlen   <= this_burst[7:0] - 8'd1;
                m_axi_awvalid <= 1'b1;
                burst_beats   <= this_burst;
                burst_sent    <= 18'd0;
                mst           <= M_AW;
            end
            // ---------- 写地址 ----------
            M_AW: begin
                if (m_axi_awready) begin
                    m_axi_awvalid <= 1'b0;
                    mst <= M_W;
                end
            end
            // ---------- 写数据 ----------
            M_W: begin
                m_axi_wvalid <= 1'b1;
                if (m_axi_wvalid && m_axi_wready) begin
                    beat_idx   <= beat_idx   + 18'd1;
                    burst_sent <= burst_sent + 18'd1;
                    beats_left <= beats_left - 18'd1;
                    phase      <= ph_nxt;
                    if ((burst_sent + 18'd1) >= burst_beats) begin
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
                    if (beats_left == 18'd0) begin
                        g_mem_ready_r <= 1'b1;     // ★ 整个 run 写完, ack 核心
                        mst           <= M_ACK;
                    end else begin
                        // 还有数据 -> 接着开下一个突发
                        cur_addr <= cur_addr + {burst_beats, 3'b000};
                        mst      <= M_SETUP;
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
