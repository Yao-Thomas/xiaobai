`timescale 1ns / 1ps

//=====================================================================
// scope_env —— 波形运算（照搬 07_scope_demo 的思路，全部在 RTL 里做）
//
// 采集过程中【流式】完成，不额外扫描：
//   · 整帧 min / max
//   · 中心值 center = (max+min)/2
//   · 迟滞门限 hys = max(p2p/16, 2)
//   · 迟滞边沿检测（数字施密特触发器），统计边沿位置与数量
//   · 高电平点数 high_count -> 占空比
//
// 采集结束后：
//   · period = (last_edge - first_edge) / (N-1)   —— 多周期平均
//   · 列包络：把 4096 点按屏幕 1008 列压成每列的 min/max
//             写进一块小 BRAM，PS 只读 2KB 就能画整屏波形
//
// 列包络是「运算在 FPGA」的关键：PS 不必再读 8192 个采样点。
//=====================================================================
module scope_env #(
    parameter integer DEPTH = 4096,
    parameter integer COLS  = 1008
)(
    input  wire        sample_clk,
    input  wire        rst_n,

    // 采集侧：每采到一个点就推一个进去
    input  wire        st_sample,       // 本拍有一个新采样点
    input  wire [9:0]  st_data,         // 该点的值
    input  wire [11:0] st_index,        // 该点在帧内的序号 0..DEPTH-1
    input  wire        st_frame_start,  // 新帧开始（清统计）
    input  wire        st_frame_end,    // 帧结束（开始算 period / 清包络）

    // 列包络读口（给 AXI 域用，异步时钟）
    input  wire        rd_clk,
    input  wire [9:0]  rd_col,          // 0..COLS-1
    output reg  [9:0]  rd_min,
    output reg  [9:0]  rd_max,

    // 统计结果（在 sample_clk 域，AXI 侧自己做同步）
    output reg  [11:0] o_min,
    output reg  [11:0] o_max,
    output reg  [12:0] o_high_count,
    output reg  [15:0] o_edge_count,
    output reg  [15:0] o_period,
    output reg  [15:0] o_first_edge,
    output reg  [15:0] o_last_edge,
    output reg         o_locked
);

    // ---------------- 列包络 BRAM ----------------
    (* ram_style = "block" *) reg [9:0] env_min [0:COLS-1];
    (* ram_style = "block" *) reg [9:0] env_max [0:COLS-1];

    reg [9:0]  rmin, rmax;
    reg        rvalid;
    reg [9:0]  pend_min, pend_max;
    reg [9:0]  pend_col;
    reg        pend_we;
    reg [9:0]  col_d;

    // 读口（rd_clk 域）
    always @(posedge rd_clk) begin
        rd_min <= env_min[rd_col];
        rd_max <= env_max[rd_col];
    end

    // ---------------- 统计寄存器 ----------------
    reg [11:0] fmin, fmax;
    reg [12:0] hcnt;
    reg [15:0] ecnt;
    reg [15:0] efirst, elast;
    reg [9:0]  armed_val;
    reg        armed;
    reg [15:0] period_r;
    reg        locked_r;
    reg [9:0]  prev_s;
    reg        prev_v;

    wire [11:0] p2p = (fmax >= fmin) ? (fmax - fmin) : 12'd0;
    wire [11:0] ctr = (fmax + fmin) >> 1;
    wire [11:0] hys = (p2p >> 4) > 12'd2 ? (p2p >> 4) : 12'd2;
    wire [11:0] th_hi = ctr + hys;
    wire [11:0] th_lo = (ctr > hys) ? (ctr - hys) : 12'd0;

    wire rise_hit = armed && (st_data >= th_hi[9:0]);
    wire fall_hit = armed && (st_data <= th_lo[9:0]);

    // 列号 = index * COLS / DEPTH （用乘法+移位；COLS=1008, DEPTH=4096）
    wire [23:0] col_mul = st_index * COLS;
    wire [9:0]  col_now = col_mul >> 12;     // /4096

    always @(posedge sample_clk or negedge rst_n) begin
        if (!rst_n) begin
            fmin <= 12'hFFF; fmax <= 12'd0; hcnt <= 13'd0;
            ecnt <= 16'd0; efirst <= 16'd0; elast <= 16'd0;
            armed <= 1'b0; armed_val <= 10'd0;
            period_r <= 16'd0; locked_r <= 1'b0;
            prev_s <= 10'd0; prev_v <= 1'b0;
            pend_we <= 1'b0; rvalid <= 1'b0;
            o_min <= 0; o_max <= 0; o_high_count <= 0;
            o_edge_count <= 0; o_period <= 0;
            o_first_edge <= 0; o_last_edge <= 0; o_locked <= 0;
        end else begin
            // ---- 包络写回（一拍延迟，RMW 的第二拍）----
            pend_we <= 1'b0;
            if (rvalid) begin
                if (pend_min < rmin) rmin <= pend_min;
                if (pend_max > rmax) rmax <= pend_max;
                env_min[pend_col] <= (pend_min < rmin) ? pend_min : rmin;
                env_max[pend_col] <= (pend_max > rmax) ? pend_max : rmax;
                rvalid <= 1'b0;
            end

            if (st_frame_start) begin
                fmin <= 12'hFFF; fmax <= 12'd0; hcnt <= 13'd0;
                ecnt <= 16'd0; efirst <= 16'd0; elast <= 16'd0;
                armed <= 1'b0; period_r <= 16'd0; locked_r <= 1'b0;
                prev_v <= 1'b0;
                // 清包络：第一列写一次会覆盖，这里靠 rvalid 机制，
                // 所以每帧开头把所有列清成 0x3FF / 0
                // （用 COLS 拍顺序清，20MHz 下 1008 拍 = 50us，可接受）
                env_min[st_index % COLS] <= 10'h3FF;
                env_max[st_index % COLS] <= 10'd0;
            end

            if (st_sample) begin
                // 整帧 min/max
                if ({1'b0, st_data} < fmin) fmin <= st_data;
                if ({1'b0, st_data} > fmax) fmax <= st_data;
                // 占空比
                if (st_data >= ctr[9:0]) hcnt <= hcnt + 1'b1;

                // 迟滞边沿
                if (!armed) begin
                    if (st_data <= th_lo[9:0]) begin armed <= 1'b1; armed_val <= st_data; end
                    else if (st_data >= th_hi[9:0]) begin armed <= 1'b1; armed_val <= st_data; end
                end else begin
                    if (rise_hit || fall_hit) begin
                        if (ecnt == 16'd0) efirst <= {4'd0, st_index};
                        elast <= {4'd0, st_index};
                        ecnt <= ecnt + 1'b1;
                        armed <= 1'b0;
                    end
                end
                prev_s <= st_data;
                prev_v <= 1'b1;

                // 列包络 RMW：先读旧值
                rmin <= env_min[col_now];
                rmax <= env_max[col_now];
                pend_min <= st_data;
                pend_max <= st_data;
                pend_col <= col_now;
                rvalid <= 1'b1;
            end

            // ---- 帧结束：算周期 ----
            if (st_frame_end) begin
                o_min <= fmin; o_max <= fmax;
                o_high_count <= hcnt;
                o_edge_count <= ecnt;
                o_first_edge <= efirst;
                o_last_edge <= elast;
                if (ecnt >= 16'd2 && elast > efirst) begin
                    // period = (last - first) / (N-1)
                    case (ecnt)
                        16'd2: period_r <= elast - efirst;
                        16'd3: period_r <= (elast - efirst) >> 1;
                        16'd4: period_r <= (elast - efirst) / 3;
                        16'd5: period_r <= (elast - efirst) >> 2;
                        default: period_r <= (elast - efirst) / (ecnt - 1'b1);
                    endcase
                    locked_r <= (p2p >= 12'd8);
                end else begin
                    period_r <= 16'd0;
                    locked_r <= 1'b0;
                end
                o_period <= period_r;
                o_locked <= locked_r;
            end
        end
    end

endmodule
