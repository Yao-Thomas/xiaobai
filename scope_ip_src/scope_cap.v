//=====================================================================
//  scope_cap.v  ——  数字示波器 采集核心
//---------------------------------------------------------------------
//  · 4096 点 x 8 bit,【双 bank】环形缓冲 (共 8 KB BRAM)
//
//  · 信号源二选一 (src_sel):
//        0 = 内部 DDS (正弦/方波/三角/锯齿, 32 位频率字)   ← 自检/演示用
//        1 = 外部 8 位并行 ADC (adc_data[7:0], 时钟由本模块产生)
//
//  · 基础采样时钟 = clk / DIV      (DIV=5 -> 100MHz/5 = 20 MSPS)
//  · 抽取 DEC: 每 DEC 个基础采样存 1 点
//        时基 = DIV * DEC / 100MHz  每点
//
//  · 触发: 电平 + 边沿(升/降) + 模式(Auto/Normal/Single) + 预触发 PRE
//
//  ---- 为什么用环形缓冲 ----
//  预触发需要"触发点【之前】"的样本。做法是让写指针一直转圈,
//  触发时不做任何搬运, 只是继续写 POST 个点然后停。
//  这样"最后 4096 个样本"天然就是 [触发点-PRE, 触发点+POST] 这个窗,
//  读起点 = 收工时写指针的值 (它正好指向窗里最老的那个样本)。
//  读地址 12 位自动回绕, 所以上层直接从 start_addr 顺序读 4096 个就是
//  正确的时间顺序 —— 不需要任何线性化/搬运逻辑。
//
//  作者: DSH  为 Zynq-7020 领航者板配套
//=====================================================================
`timescale 1ns / 1ps

module scope_cap (
    input  wire        clk,
    input  wire        rst_n,

    // ---------------- 控制 ----------------
    input  wire        start,        // 脉冲: 重新布防
    input  wire        stop,         // 脉冲: 中止本次采集
    input  wire        src_sel,      // 0=DDS  1=外部 ADC
    input  wire [1:0]  wave,         // DDS 波形 0正弦 1方波 2三角 3锯齿
    input  wire [31:0] freq,         // DDS 频率字 (f = freq*fs/2^32)
    input  wire [15:0] div,          // 基础分频, 最小 4
    input  wire [7:0]  dec,          // 抽取, 0 当 1
    input  wire [7:0]  trig_level,   // 触发电平
    input  wire        trig_edge,    // 0=上升沿 1=下降沿
    input  wire [1:0]  trig_mode,    // 0=Auto 1=Normal 2=Single
    input  wire [11:0] pre,          // 预触发点数 (0..4095)

    // ---------------- 外部 ADC ----------------
    input  wire [7:0]  adc_data,
    output reg         adc_clk,

    // ---------------- 状态 ----------------
    output reg         busy,
    output reg         done,         // 高电平保持到下次 start
    output reg         triggered,    // 本次是否真的触发了
    output reg  [11:0] start_addr,   // 最老样本地址 = 读起点
    output reg  [12:0] wr_total,     // 本次写了多少样本 (调试)
    output reg         rd_bank,      // 当前可读 bank

    // ---------------- 读端口 (AXI 侧) ----------------
    input  wire [11:0] rd_addr,
    output reg  [7:0]  rd_data
);

    //=========================================================
    //  采样时钟分频
    //=========================================================
    reg  [15:0] divcnt;
    wire        tick = (divcnt == 16'd0);
    wire [15:0] div_ok = (div < 16'd4) ? 16'd4 : div;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)      divcnt <= 16'd0;
        else if (tick)   divcnt <= div_ok - 16'd1;
        else             divcnt <= divcnt - 16'd1;
    end

    // ADC 时钟: 前半周期高, 后半周期低。
    // 在 tick (周期的最后一拍, 即低电平末尾) 采样 —— 尽量远离 ADC 的
    // 数据翻转沿, 也就是在数据眼中间取。
    wire [15:0] half = {1'b0, div_ok[15:1]};
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) adc_clk <= 1'b0;
        else        adc_clk <= (divcnt > half);
    end

    //=========================================================
    //  DDS 信号源 (在基础采样率上推进相位)
    //=========================================================
    reg [31:0] phase;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)     phase <= 32'd0;
        else if (tick)  phase <= phase + freq;
    end

    // 1/4 波表 (q=0..63 对应 0..90 度), 值 = round(127.5 + 127.5*sin(q*pi/128))
    function [7:0] sine8;
        input [7:0] ph;
        reg   [5:0] q;
        reg   [7:0] b;
        begin
            q = ph[6] ? (~ph[5:0]) : ph[5:0];
            case (q)
                6'd0 : b = 8'd128; 6'd1 : b = 8'd131; 6'd2 : b = 8'd134; 6'd3 : b = 8'd137;
                6'd4 : b = 8'd140; 6'd5 : b = 8'd143; 6'd6 : b = 8'd146; 6'd7 : b = 8'd149;
                6'd8 : b = 8'd152; 6'd9 : b = 8'd155; 6'd10: b = 8'd158; 6'd11: b = 8'd162;
                6'd12: b = 8'd165; 6'd13: b = 8'd167; 6'd14: b = 8'd170; 6'd15: b = 8'd173;
                6'd16: b = 8'd176; 6'd17: b = 8'd179; 6'd18: b = 8'd182; 6'd19: b = 8'd185;
                6'd20: b = 8'd188; 6'd21: b = 8'd190; 6'd22: b = 8'd193; 6'd23: b = 8'd196;
                6'd24: b = 8'd198; 6'd25: b = 8'd201; 6'd26: b = 8'd203; 6'd27: b = 8'd206;
                6'd28: b = 8'd208; 6'd29: b = 8'd211; 6'd30: b = 8'd213; 6'd31: b = 8'd215;
                6'd32: b = 8'd218; 6'd33: b = 8'd220; 6'd34: b = 8'd222; 6'd35: b = 8'd224;
                6'd36: b = 8'd226; 6'd37: b = 8'd228; 6'd38: b = 8'd230; 6'd39: b = 8'd232;
                6'd40: b = 8'd234; 6'd41: b = 8'd235; 6'd42: b = 8'd237; 6'd43: b = 8'd238;
                6'd44: b = 8'd240; 6'd45: b = 8'd241; 6'd46: b = 8'd243; 6'd47: b = 8'd244;
                6'd48: b = 8'd245; 6'd49: b = 8'd246; 6'd50: b = 8'd248; 6'd51: b = 8'd249;
                6'd52: b = 8'd250; 6'd53: b = 8'd250; 6'd54: b = 8'd251; 6'd55: b = 8'd252;
                6'd56: b = 8'd253; 6'd57: b = 8'd253; 6'd58: b = 8'd254; 6'd59: b = 8'd254;
                6'd60: b = 8'd254; 6'd61: b = 8'd255; 6'd62: b = 8'd255; default: b = 8'd255;
            endcase
            sine8 = ph[7] ? (~b) : b;
        end
    endfunction

    reg [7:0] dds_val;
    always @(*) begin
        case (wave)
            2'd0:    dds_val = sine8(phase[31:24]);
            2'd1:    dds_val = phase[31] ? 8'hFF : 8'h00;                  // 方波
            2'd2:    dds_val = phase[31] ? (8'hFF - phase[30:23])          // 三角
                                         : phase[30:23];
            default: dds_val = phase[31:24];                               // 锯齿
        endcase
    end

    wire [7:0] smp = src_sel ? adc_data : dds_val;

    //=========================================================
    //  抽取: 每 DEC 个基础采样存 1 点
    //=========================================================
    reg [7:0] deccnt;
    // ★ 这里必须写 [7:0]! 写成 `wire dec1 = ...` 就是 1 位线,
    //   DEC=16 会被截断成 0, 于是 "deccnt+1 >= 0" 恒真 -> deccnt 永远是 0
    //   -> 抽取完全失效 (仿真里表现成 cap_en 每个采样时钟都触发)。
    wire [7:0] dec1  = (dec == 8'd0) ? 8'd1 : dec;
    wire       cap_en = tick && (deccnt == 8'd0);

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)         deccnt <= 8'd0;
        else if (tick)      deccnt <= (deccnt + 8'd1 >= dec1) ? 8'd0 : (deccnt + 8'd1);
    end

    //=========================================================
    //  采集缓冲: 2 bank x 4096 x 8bit
    //=========================================================
    reg [7:0]  mem [0:8191];
    reg        wb;                 // 写 bank
    reg [11:0] wp;                 // 写指针 (环形)
    reg [11:0] post_target;
    reg [11:0] post_cnt;
    reg [7:0]  prev_smp;

    localparam S_IDLE = 2'd0, S_ARM = 2'd1, S_POST = 2'd2;

    reg [1:0] state;

    wire [11:0] wp_nxt   = wp + 12'd1;
    wire        writing  = cap_en && (state == S_ARM || state == S_POST);
    wire        finishing = cap_en && (state == S_POST) && (post_cnt >= post_target);

    // 边沿检测
    wire rising  = (prev_smp <  trig_level) && (smp >= trig_level);
    wire falling = (prev_smp >= trig_level) && (smp <  trig_level);
    wire trig_hit = trig_edge ? falling : rising;
    wire auto_mode = (trig_mode == 2'd0);

    // ★ 必须【攒够 pre 个样本才允许触发】。
    //   否则信号一来就触发, 预触发区里根本没有 pre 个点,
    //   读出来的窗口一半是没写过的旧数据 —— 仿真里表现为
    //   "幅度对了但周期数多出一半"(那些多出来的沿是 0 和真实数据的跳变)。
    wire arm_ready = (wr_total >= {1'b0, pre});

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state      <= S_IDLE;
            busy       <= 1'b0;
            done       <= 1'b0;
            triggered  <= 1'b0;
            start_addr <= 12'd0;
            wr_total   <= 13'd0;
            wb         <= 1'b0;
            wp         <= 12'd0;
            post_cnt   <= 12'd0;
            post_target<= 12'd0;
            prev_smp   <= 8'd0;
            rd_bank    <= 1'b0;
        end else begin
            // ---- 写 ----
            // ★ 注意: 存储器写入【不在这里】! 见下面单独的 always 块。
            //   如果把 mem 的写在带异步复位的块里, Vivado 推断不出 Block RAM,
            //   会把 8192x8 全铺成触发器 (65536 个 FF, 占掉器件 61%)。
            //   实测综合日志: "Trying to implement RAM 'mem_reg' in registers"。
            if (writing) begin
                wp            <= wp_nxt;
                wr_total      <= wr_total + 13'd1;
                prev_smp      <= smp;
            end

            if (finishing) begin
                // 收工: 发布这一帧, 换到另一个 bank 准备下一帧
                start_addr <= wp_nxt;    // 最后一个样本的下一格 = 最老样本
                rd_bank    <= wb;        // 发布刚写完的 bank
                wb         <= ~wb;
                busy       <= 1'b0;
                done       <= 1'b1;
                state      <= S_IDLE;
            end else begin
                case (state)
                S_IDLE: begin
                    // ★ 这里【不能】每拍都清 done!
                    //   done 必须保持到下一次 start —— 软件轮询一次要微秒级,
                    //   而 1 个时钟周期只有 10ns, 单拍脉冲软件永远抓不到。
                    //   (GPU 那边已经踩过一模一样的坑)
                    if (start) begin
                        wp          <= 12'd0;
                        wr_total    <= 13'd0;
                        post_cnt    <= 12'd0;
                        triggered   <= 1'b0;
                        busy        <= 1'b1;
                        done        <= 1'b0;
                        // 触发点要落在窗口的第 pre 个位置。
                        // 设 POST 写完 P 个样本后收工, 窗口 = 最后 4096 个,
                        // 触发点索引 = 4095 - P, 要它等于 pre => P = 4095 - pre。
                        // 而 finishing 那一拍本身也会写一个样本, 所以
                        // post_target = P - 1 = 4094 - pre。
                        post_target <= 12'd4094 - pre;
                        prev_smp    <= smp;
                        state       <= S_ARM;
                    end
                end
                S_ARM: begin
                    if (cap_en) begin
                        if (arm_ready && trig_hit) begin
                            triggered <= 1'b1;
                            post_cnt  <= 12'd0;
                            state     <= S_POST;
                        end else if (auto_mode && (wr_total >= 13'd4095)) begin
                            // Auto: 一直没触发也要出图 (自由扫描)
                            post_cnt <= 12'd0;
                            state    <= S_POST;
                        end
                    end
                    if (stop) begin
                        busy  <= 1'b0;
                        state <= S_IDLE;
                    end
                end
                S_POST: begin
                    if (cap_en && !finishing) begin
                        if (post_cnt >= post_target) post_cnt <= post_target;
                        else                         post_cnt <= post_cnt + 12'd1;
                    end
                    if (stop) begin
                        busy  <= 1'b0;
                        state <= S_IDLE;
                    end
                end
                default: state <= S_IDLE;
                endcase
            end
        end
    end

    //=========================================================
    //  读端口 (给 AXI 侧)
    //=========================================================
    always @(posedge clk) begin
        rd_data <= mem[{rd_bank, rd_addr}];
    end

    //=========================================================
    //  ★ 存储器的【写端口】: 单独一个 always 块, 而且【绝对不能带复位】。
    //    Vivado 只有看到"纯时钟沿触发的写"才会推断 Block RAM;
    //    一旦写语句出现在 `if (!rst_n) ... else ...` 里, 它就会放弃 BRAM,
    //    改用触发器实现整个 8KB —— 这在 Zynq7020 上是灾难性的。
    //=========================================================
    always @(posedge clk) begin
        if (writing) mem[{wb, wp}] <= smp;
    end

endmodule
