`timescale 1ns / 1ps

// Dual-channel acquisition engine for the 3PA1030 module.
// Samples are packed as {CH2[9:0], CH1[9:0]} in a dual-clock BRAM.
module scope_dual_core #(
    parameter integer ADDR_WIDTH = 12,
    parameter integer DEPTH      = 4096
)(
    input  wire                  sample_clk,
    input  wire                  rst_n,
    input  wire                  start_pulse,
    input  wire                  stop_pulse,
    input  wire [15:0]           cfg_decimation,
    input  wire [9:0]            cfg_trigger_level,
    input  wire                  cfg_trigger_edge,
    input  wire [1:0]            cfg_trigger_mode,
    input  wire                  cfg_trigger_channel,
    // 触发源：0=CH1  1=CH2  2=任意通道（谁先过阈算谁）
    input  wire [1:0]            cfg_trigger_source,
    // 迟滞宽度（LSB）：hys = max(噪声x3, Vpp/32, 2)
    input  wire [9:0]            cfg_trigger_hys,
    // Roll 是【采集模式】，不再塞进触发源
    input  wire                  cfg_acq_roll,
    // 自由运行：采完一帧【立刻自动重新武装】，采样几乎不停，
    // 这样滚动模式下相邻帧的采样是连续的（原来每帧要等 PS 重新 start，
    // 往返是毫秒级，期间一个点都不采，拼起来就是断的/块状的）。
    input  wire                  cfg_free_run,
    input  wire [ADDR_WIDTH-1:0] cfg_pretrigger,
    input  wire [9:0]            adc1_data,
    input  wire [9:0]            adc2_data,

    output reg                   busy,
    output reg                   done,
    output reg                   triggered,
    output reg                   completed_bank,
    output reg  [ADDR_WIDTH-1:0] start_addr,
    output reg  [ADDR_WIDTH:0]   write_total,
    output reg  [31:0]           frame_sequence,

    input  wire                  rd_clk,
    input  wire [ADDR_WIDTH:0]   rd_addr,
    output reg  [19:0]           rd_data,

    // ================= Bank 锁定 / 应答（杜绝拼接帧）=================
    // 每个完成帧生成不可变描述符。PS 开始读帧时锁定 bank，读完发 ACK。
    // 核在 ACK 之前【绝不覆盖】已发布的 bank：宁可丢掉下一帧并累加
    // lost_frames，也不产生由两个 bank 拼成的帧。
    input  wire                  bank_lock_req,     // PS 请求锁定
    input  wire                  bank_lock_bank,    // 要锁哪个 bank
    input  wire                  bank_ack,          // PS 读完 -> 释放
    output reg                   bank_locked,
    output reg                   bank_locked_bank,
    output reg  [15:0]           lost_frames,       // 因未 ACK 而丢掉的帧数
    output reg  [ADDR_WIDTH-1:0] trigger_index,     // 触发点在帧内的位置
    output reg                   frame_triggered,   // 本帧是否真的触发了
    output reg  [15:0]           frame_decimation,  // 本帧实际用的抽取倍率
    // ---- SCP4：PL 侧流式统计，ARM 不必逐点扫描极值/频率 ----
    output reg  [9:0]            frame_min1,
    output reg  [9:0]            frame_max1,
    output reg  [9:0]            frame_min2,
    output reg  [9:0]            frame_max2,
    output reg  [1:0]            frame_clip1,
    output reg  [1:0]            frame_clip2,
    output reg  [7:0]            frame_edges1,
    output reg  [7:0]            frame_edges2,
    output reg  [23:0]           frame_edge_span1,
    output reg  [23:0]           frame_edge_span2,
    // ---- Roll 连续采集：把写指针和已填数量报给 PS ----
    output wire [12:0]           roll_ptr_out,      // 最新点位置（0..DEPTH-1）
    output wire [12:0]           roll_fill_out,     // 已连续采到的点数
    // ================= 阶段4：PL 列包络 =================
    // 采集过程中流式生成，每条目 = {max[9:0], min[9:0]}（20 位）。
    // PS 只需读 2*COLS 个 32 位字就能画整屏波形，
    // 事务数从 8192（逐点 ptr+data）降到 2016，帧率与 CPU 都受益。
    // 阶段4：可配置显示窗口（列包络只在这些点上算）
    //   win_start = 相对触发对齐起点的偏移（采样点）
    //   win_len   = 窗口长度（采样点），即 Timebase.span
    input  wire [ADDR_WIDTH-1:0] cfg_win_start,
    input  wire [ADDR_WIDTH:0]   cfg_win_len,
    // 列号步进（DDA 用）：PS 预先算好 round(COLS * 65536 / win_len) 下发给 PL。
    // ★ 这样 PL 里没有除法器。之前写成 (idx<<12)/win_len，综合出一个巨大
    //   除法器，直接把设计撑到 place 失败。
    input  wire [23:0]           cfg_col_step,
    input  wire [10:0]           env_rd_col,        // 0..COLS-1
    output reg  [19:0]           env_rd_data,
    // ---- 阶段4：帧统计（采集时流式算出，PS 只读寄存器）----
    output reg  [9:0]            st_min1,            // 帧内最小/最大
    output reg  [9:0]            st_max1,
    output reg  [9:0]            st_min2,
    output reg  [9:0]            st_max2,
    output reg  [31:0]           st_sum1,            // 累加和（PS 自己除出均值）
    output reg  [31:0]           st_sum2,
    output reg  [15:0]           st_clip_lo1,        // 贴 0 的点数
    output reg  [15:0]           st_clip_hi1,        // 贴 1023 的点数
    output reg  [15:0]           st_clip_lo2,
    output reg  [15:0]           st_clip_hi2,
    output reg  [15:0]           st_edges1,          // 迟滞边沿数
    output reg  [15:0]           st_edges2,
    output reg  [15:0]           st_span1,           // 首末边沿间隔（PS 除以边沿数得周期）
    output reg  [15:0]           st_span2,
    output reg  [15:0]           st_n,               // 本帧统计了多少点
    output reg                   st_valid            // 统计已就绪
);

    localparam [ADDR_WIDTH:0] DEPTH_COUNT = DEPTH;

    (* ram_style = "block" *) reg [19:0] sample_mem [0:(2*DEPTH)-1];

    reg                    write_bank;
    reg [ADDR_WIDTH-1:0]   write_ptr;
    reg [ADDR_WIDTH:0]     fill_count;
    reg [ADDR_WIDTH:0]     post_remaining;
    reg [15:0]             dec_count;
    reg [11:0]             trig_idx_r;
    reg                    frame_trig_r;
    reg [9:0]              prev_s1;
    reg [9:0]              prev_s2;
    reg                    previous_valid;

    wire [15:0] decimation_value = (cfg_decimation == 16'd0)
                                     ? 16'd1 : cfg_decimation;
    wire [9:0] selected_sample = cfg_trigger_channel ? adc2_data : adc1_data;

    // ================= 真正的迟滞（施密特）触发状态机 =================
    // 上升沿：必须先低于 level-hys，再高于 level+hys
    // 下降沿：必须先高于 level+hys，再低于 level-hys
    // 这一层跑在【原始 20MHz 数据】上，不跟随抽取倍率，慢时基也不会漏窄脉冲。
    wire [9:0] hys = (cfg_trigger_hys < 10'd2) ? 10'd2 : cfg_trigger_hys;
    wire [10:0] lv_hi_w = {1'b0, cfg_trigger_level} + {1'b0, hys};
    wire [10:0] lv_lo_w = {1'b0, cfg_trigger_level} - {1'b0, hys};
    wire [9:0]  lv_hi = (lv_hi_w > 11'd1023) ? 10'd1023 : lv_hi_w[9:0];
    wire [9:0]  lv_lo = (lv_lo_w[10]) ? 10'd0 : lv_lo_w[9:0];

    reg armed1, armed2;         // 1 = 已经回到门限外侧，等下一次穿越
    wire arm1_lo = (adc1_data <= lv_lo);
    wire arm1_hi = (adc1_data >= lv_hi);
    wire arm2_lo = (adc2_data <= lv_lo);
    wire arm2_hi = (adc2_data >= lv_hi);

    // 撞发极性（修正后）：
    //   上升沿 edge=0 -> 先 <=lo 武装，再 >=hi 触发   => 用 arm*_hi
    //   下降沿 edge=1 -> 先 >=hi 武装，再 <=lo 触发   => 用 arm*_lo
    // 原来写成 edge ? hi : lo，正好接反，导致"武装后仍在同侧触发"。
    wire hit1 = armed1 && (cfg_trigger_edge ? arm1_lo : arm1_hi);
    wire hit2 = armed2 && (cfg_trigger_edge ? arm2_lo : arm2_hi);

    // 3 种触发源
    wire edge_hit = (cfg_trigger_source == 2'd0) ? hit1 :
                    (cfg_trigger_source == 2'd1) ? hit2 :
                                                   (hit1 | hit2);
    wire no_trigger = cfg_acq_roll;   // Roll 模式不靠触发，靠缓冲填满收帧

    wire [ADDR_WIDTH-1:0] next_write_ptr = write_ptr + {{(ADDR_WIDTH-1){1'b0}}, 1'b1};
    wire [ADDR_WIDTH-1:0] pretrigger_clamped =
        (cfg_pretrigger >= DEPTH-1) ? DEPTH-1 : cfg_pretrigger;
    wire [ADDR_WIDTH:0] post_count = DEPTH_COUNT -
                                          {1'b0, pretrigger_clamped} - 1'b1;
    // ---- Roll（连续采集）：核永不停机 ------------------------------------
    // 普通模式：只有 busy 且抽取计数到位才采一个点。
    // Roll 模式：不看 busy，也不收帧，write_ptr 环形回绕，采样【连续】。
    //   这样 PS 每次取到的都是真正相邻的新点，滚动才不会跳变/缺段。
    wire roll_mode   = cfg_acq_roll;
    wire dec_ready   = (dec_count == decimation_value - 1'b1);
    wire take_sample = roll_mode ? dec_ready : (busy && dec_ready);
    // Roll 时不产生"帧完成"，避免自动重装带来的采样空洞
    wire frame_done_en = ~roll_mode;
    wire write_sample = take_sample && !start_pulse && !stop_pulse;
    wire enough_history = fill_count >= {1'b0, pretrigger_clamped};
    // Auto 模式靠"缓冲填满"收帧；自由运行(源=3)也靠它，这样完全不依赖触发
    wire auto_timeout = ((cfg_trigger_mode == 2'd0) || no_trigger) &&
                        (fill_count >= DEPTH_COUNT);
    // Single：触发一次就停，不再自动重装
    wire single_mode = (cfg_trigger_mode == 2'd2);
    // 自由运行（Roll）才自动重装；Normal/Single 不重装
    wire auto_rearm = cfg_free_run || cfg_acq_roll;

    // ================= 阶段4：帧统计引擎（流式，零额外扫描） =================
    // 说明：迟滞门限用【上一帧】的 min/max 推出来。因为帧内 min/max 要等帧
    // 结束才知道，而相邻两帧的幅度几乎不变，用上一帧的门限是完全够用的，
    // 而且第 2 帧起就收敛。这样避免了"先扫一遍求极值再扫一遍找边沿"。
    reg [9:0]  st_min1_r, st_max1_r, st_min2_r, st_max2_r;
    reg [31:0] st_sum1_r, st_sum2_r;
    reg [15:0] st_lo1_r, st_hi1_r, st_lo2_r, st_hi2_r;
    reg [15:0] st_ed1_r, st_ed2_r, st_fe1_r, st_le1_r, st_fe2_r, st_le2_r;
    reg [15:0] st_n_r;
    reg        st_arm1, st_arm2;
    reg [9:0]  st_pv1, st_pv2;
    reg        st_pv_v;

    // 上一帧的统计结果（用于算门限）
    reg [9:0]  pv_min1, pv_max1, pv_min2, pv_max2;

    wire [9:0] th_hi1 = (pv_min1 + ((pv_max1 - pv_min1) >> 1));
    wire [9:0] th_lo1 = th_hi1;
    wire [9:0] th_hi2 = (pv_min2 + ((pv_max2 - pv_min2) >> 1));
    wire [9:0] th_lo2 = th_hi2;
    wire [9:0] hys1 = ((pv_max1 - pv_min1) >> 5) < 10'd2 ? 10'd2 : ((pv_max1 - pv_min1) >> 5);
    wire [9:0] hys2 = ((pv_max2 - pv_min2) >> 5) < 10'd2 ? 10'd2 : ((pv_max2 - pv_min2) >> 5);

    // ★ 这里刻意用【同步复位】。曾经写成异步复位（or negedge rst_n）时，
    //   Vivado 会在这一行报 [Synth 8-91] ambiguous clock in event control，
    //   原因是本块给多个 output reg 赋值 + 位于一个含异步复位的敏感表里。
    //   同步复位对本块完全够用：真正需要清零的时机是 start_pulse（每帧开头）。
    always @(posedge sample_clk) begin
        if (!rst_n) begin
            st_min1_r <= 10'h3FF; st_max1_r <= 10'd0;
            st_min2_r <= 10'h3FF; st_max2_r <= 10'd0;
            st_sum1_r <= 32'd0;   st_sum2_r <= 32'd0;
            st_lo1_r <= 16'd0; st_hi1_r <= 16'd0;
            st_lo2_r <= 16'd0; st_hi2_r <= 16'd0;
            st_ed1_r <= 16'd0; st_ed2_r <= 16'd0;
            st_fe1_r <= 16'd0; st_le1_r <= 16'd0;
            st_fe2_r <= 16'd0; st_le2_r <= 16'd0;
            st_n_r <= 16'd0; st_arm1 <= 1'b0; st_arm2 <= 1'b0;
            st_pv_v <= 1'b0; st_valid <= 1'b0;
            pv_min1 <= 10'd0; pv_max1 <= 10'h3FF;
            pv_min2 <= 10'd0; pv_max2 <= 10'h3FF;
        end else if (start_pulse) begin
            st_min1_r <= 10'h3FF; st_max1_r <= 10'd0;
            st_min2_r <= 10'h3FF; st_max2_r <= 10'd0;
            st_sum1_r <= 32'd0;   st_sum2_r <= 32'd0;
            st_lo1_r <= 16'd0; st_hi1_r <= 16'd0;
            st_lo2_r <= 16'd0; st_hi2_r <= 16'd0;
            st_ed1_r <= 16'd0; st_ed2_r <= 16'd0;
            st_fe1_r <= 16'd0; st_le1_r <= 16'd0;
            st_fe2_r <= 16'd0; st_le2_r <= 16'd0;
            st_n_r <= 16'd0; st_arm1 <= 1'b0; st_arm2 <= 1'b0;
            st_pv_v <= 1'b0; st_valid <= 1'b0;
        end else if (write_sample) begin
            st_n_r <= st_n_r + 16'd1;
            st_sum1_r <= st_sum1_r + {22'd0, adc1_data};
            st_sum2_r <= st_sum2_r + {22'd0, adc2_data};
            if (adc1_data < st_min1_r) st_min1_r <= adc1_data;
            if (adc1_data > st_max1_r) st_max1_r <= adc1_data;
            if (adc2_data < st_min2_r) st_min2_r <= adc2_data;
            if (adc2_data > st_max2_r) st_max2_r <= adc2_data;
            if (adc1_data <= 10'd4)    st_lo1_r <= st_lo1_r + 16'd1;
            if (adc1_data >= 10'd1019) st_hi1_r <= st_hi1_r + 16'd1;
            if (adc2_data <= 10'd4)    st_lo2_r <= st_lo2_r + 16'd1;
            if (adc2_data >= 10'd1019) st_hi2_r <= st_hi2_r + 16'd1;
            // 迟滞边沿（门限来自上一帧）
            if (adc1_data <= (th_lo1 - hys1)) st_arm1 <= 1'b1;
            if (st_arm1 && (adc1_data >= (th_hi1 + hys1))) begin
                st_arm1 <= 1'b0;
                if (st_ed1_r == 16'd0) st_fe1_r <= st_n_r;
                st_le1_r <= st_n_r;
                st_ed1_r <= st_ed1_r + 16'd1;
            end
            if (adc2_data <= (th_lo2 - hys2)) st_arm2 <= 1'b1;
            if (st_arm2 && (adc2_data >= (th_hi2 + hys2))) begin
                st_arm2 <= 1'b0;
                if (st_ed2_r == 16'd0) st_fe2_r <= st_n_r;
                st_le2_r <= st_n_r;
                st_ed2_r <= st_ed2_r + 16'd1;
            end
            st_pv1 <= adc1_data; st_pv2 <= adc2_data; st_pv_v <= 1'b1;
        end
        // 帧结束：发布统计，并把本帧结果留作下一帧的门限
        if (done) begin
            st_min1 <= st_min1_r; st_max1 <= st_max1_r;
            st_min2 <= st_min2_r; st_max2 <= st_max2_r;
            st_sum1 <= st_sum1_r; st_sum2 <= st_sum2_r;
            st_clip_lo1 <= st_lo1_r; st_clip_hi1 <= st_hi1_r;
            st_clip_lo2 <= st_lo2_r; st_clip_hi2 <= st_hi2_r;
            st_edges1 <= st_ed1_r; st_edges2 <= st_ed2_r;
            st_span1 <= (st_ed1_r >= 16'd2) ? (st_le1_r - st_fe1_r) : 16'd0;
            st_span2 <= (st_ed2_r >= 16'd2) ? (st_le2_r - st_fe2_r) : 16'd0;
            st_n <= st_n_r;
            st_valid <= 1'b1;
            pv_min1 <= st_min1_r; pv_max1 <= st_max1_r;
            pv_min2 <= st_min2_r; pv_max2 <= st_max2_r;
        end
    end

    // ================= 阶段4：列包络引擎（纯增量，不动原数据通路） =================
    localparam integer COLS = 1008;      // 屏幕可用列数

    (* ram_style = "block" *) reg [19:0] env1_mem [0:COLS-1];
    (* ram_style = "block" *) reg [19:0] env2_mem [0:COLS-1];

    // 读口（独立时钟，给 AXI 侧用）
    //   env_rd_col[10] = 0 -> CH1, 1 -> CH2；[9:0] = 列号
    //   列号 1008 只用 10 位，第 11 位空出来正好当通道选择
    always @(posedge rd_clk) begin
        env_rd_data <= env_rd_col[10] ? env2_mem[env_rd_col[9:0]]
                                      : env1_mem[env_rd_col[9:0]];
    end

    // 列号 = (相对触发对齐起点的下标) * COLS / DEPTH
    //   ★ 必须相对 start_addr，否则每帧 start_addr 不同，
    //     包络第 0 列会对应不同采样点，波形会左右跳。
    //   核里 start_addr = write_ptr - pretrigger（帧结束时），
    //   所以采集过程中等价于：
    //       idx = (write_ptr + DEPTH - pretrigger) & (DEPTH-1)
    //   DEPTH 是 2 的幂，取模用位与。
    //   列号 = idx * COLS / DEPTH，用乘法+移位，不占 DSP。
    wire [ADDR_WIDTH:0] idx_rel =
        (write_ptr + DEPTH_COUNT - {1'b0, pretrigger_clamped}) & (DEPTH_COUNT - 1'b1);
    // ★ 只在 [win_start, win_start+win_len) 这段里算包络。
    //   否则时基窗口会被忽略，标签说 500us 实际画的是整帧。
    wire [ADDR_WIDTH:0] win_end = cfg_win_start + cfg_win_len;
    wire in_win = (idx_rel >= {1'b0, cfg_win_start}) && (idx_rel < win_end);

    // ---- 列号用 DDA（增量累加）算，PL 里没有除法器 ----
    //   累加器每采到一个"窗口内"的点就加 cfg_col_step（= COLS*65536/win_len），
    //   高 11 位就是列号。cfg_col_step 由 PS 用 Python 算好，PS 算除法不要钱。
    reg [31:0] col_acc;
    always @(posedge sample_clk) begin
        if (start_pulse) col_acc <= 32'd0;
        else if (write_sample && in_win) col_acc <= col_acc + {8'd0, cfg_col_step};
    end
    wire [10:0] col_now1 = col_acc[26:16];   // 恒 < 1008

    // 流式 min/max —— ★ 拆成"读一拍 + 写一拍"的两拍流水。
    //   原来写成同一拍内读-改-写同一地址（env_mem[col] <= f(env_mem[col])），
    //   Vivado 无法推断成 BRAM，把整块 1008x20 的存储器变成了触发器：
    //   实测多出 40,320 个 FF、26,000 个 LUT，LUT 被干到 82%，
    //   place_design 直接失败，并且突破 CNN 预留预算。
    //   拆开后是标准的"读口 + 写口"，能正确推断为双口 BRAM。
    reg [10:0] last_col1, last_col2;
    reg        env_started1, env_started2;
    reg        env_we_d;
    reg [10:0] env_col_d;
    reg [9:0]  env_a1_d, env_a2_d;
    reg [19:0] env_rd1, env_rd2;
    reg        env_started1_d, env_started2_d;
    reg [10:0] last_col1_d, last_col2_d;

    always @(posedge sample_clk) begin
        if (start_pulse) begin
            env_started1 <= 1'b0;          // 新帧：第一列走"置值"分支
            env_started2 <= 1'b0;
            last_col1    <= 11'd0;
            last_col2    <= 11'd0;
        end else if (write_sample && in_win) begin
            last_col1    <= col_now1;
            last_col2    <= col_now1;
            env_started1 <= 1'b1;
            env_started2 <= 1'b1;
        end
    end

    always @(posedge sample_clk) begin
        env_rd1        <= env1_mem[col_now1];    // 第 1 拍：读旧值
        env_rd2        <= env2_mem[col_now1];
        env_we_d       <= write_sample && in_win;
        env_col_d      <= col_now1;
        env_a1_d       <= adc1_data;
        env_a2_d       <= adc2_data;
        env_started1_d <= env_started1;
        env_started2_d <= env_started2;
        last_col1_d    <= last_col1;
        last_col2_d    <= last_col2;
    end

    always @(posedge sample_clk) begin
        if (env_we_d) begin                      // 第 2 拍：比较并写回
            if (env_started1_d && (env_col_d == last_col1_d))
                env1_mem[env_col_d] <= {
                    (env_a1_d > env_rd1[9:0])   ? env_a1_d : env_rd1[9:0],
                    (env_a1_d < env_rd1[19:10]) ? env_a1_d : env_rd1[19:10] };
            else
                env1_mem[env_col_d] <= {env_a1_d, env_a1_d};
            if (env_started2_d && (env_col_d == last_col2_d))
                env2_mem[env_col_d] <= {
                    (env_a2_d > env_rd2[9:0])   ? env_a2_d : env_rd2[9:0],
                    (env_a2_d < env_rd2[19:10]) ? env_a2_d : env_rd2[19:10] };
            else
                env2_mem[env_col_d] <= {env_a2_d, env_a2_d};
        end
    end

    // ---- 迟滞武装状态机（每个 20MHz 采样时钟都更新，不受抽取影响）----
    always @(posedge sample_clk or negedge rst_n) begin
        if (!rst_n) begin
            armed1 <= 1'b1;
            armed2 <= 1'b1;
        end else if (start_pulse) begin
            armed1 <= 1'b1;
            armed2 <= 1'b1;
        end else begin
            if (cfg_trigger_edge) begin
                if (arm1_hi) armed1 <= 1'b1;   // 下降沿触发：先回到高侧才武装
                if (hit1)    armed1 <= 1'b0;
                if (arm2_hi) armed2 <= 1'b1;
                if (hit2)    armed2 <= 1'b0;
            end else begin
                if (arm1_lo) armed1 <= 1'b1;   // 上升沿触发：先回到低侧才武装
                if (hit1)    armed1 <= 1'b0;
                if (arm2_lo) armed2 <= 1'b1;
                if (hit2)    armed2 <= 1'b0;
            end
        end
    end

    // ---- 发布许可：目标 bank 没被 PS 锁住，才可以发布并翻转 ----
    wire target_bank   = ~write_bank;
    wire bank_busy     = bank_locked && (bank_locked_bank == target_bank);
    wire can_publish   = ~bank_busy;
    wire [ADDR_WIDTH-1:0] trig_idx_now =
         (fill_count >= {1'b0, pretrigger_clamped})
             ? (write_ptr - {1'b0, pretrigger_clamped})
             : write_ptr;

    // Read side is intentionally independent of the acquisition clock.
    always @(posedge rd_clk) begin
        rd_data <= sample_mem[rd_addr];
    end

    // Keep the BRAM write port in a reset-free clocked process. 7-series
    // block RAM has no asynchronous reset on its memory array; placing this
    // write in the state-machine process below prevents Vivado from inferring
    // a true dual-port BRAM and would otherwise expand the array into flops.
    always @(posedge sample_clk) begin
        if (write_sample)
            sample_mem[{write_bank, write_ptr}] <= {adc2_data, adc1_data};
    end

    always @(posedge sample_clk or negedge rst_n) begin
        if (!rst_n) begin
            busy                    <= 1'b0;
            done                    <= 1'b0;
            triggered               <= 1'b0;
            completed_bank          <= 1'b0;
            write_bank              <= 1'b0;
            write_ptr               <= {ADDR_WIDTH{1'b0}};
            start_addr              <= {ADDR_WIDTH{1'b0}};
            fill_count              <= {(ADDR_WIDTH+1){1'b0}};
            write_total             <= {(ADDR_WIDTH+1){1'b0}};
            post_remaining          <= {(ADDR_WIDTH+1){1'b0}};
            dec_count               <= 16'd0;
            prev_s1        <= 10'd0;
            prev_s2        <= 10'd0;
            previous_valid          <= 1'b0;
            frame_sequence          <= 32'd0;
            bank_locked             <= 1'b0;
            bank_locked_bank        <= 1'b0;
            lost_frames             <= 16'd0;
            trigger_index           <= {ADDR_WIDTH{1'b0}};
            frame_triggered         <= 1'b0;
            frame_decimation        <= 16'd1;
        end else if (start_pulse) begin
            busy                    <= 1'b1;
            done                    <= 1'b0;
            triggered               <= 1'b0;
            write_ptr               <= {ADDR_WIDTH{1'b0}};
            fill_count              <= {(ADDR_WIDTH+1){1'b0}};
            write_total             <= {(ADDR_WIDTH+1){1'b0}};
            post_remaining          <= {(ADDR_WIDTH+1){1'b0}};
            dec_count               <= 16'd0;
            prev_s1        <= 10'd0;
            prev_s2        <= 10'd0;
            previous_valid          <= 1'b0;
        end else if (stop_pulse && busy) begin
            busy           <= 1'b0;
            done           <= 1'b1;
            completed_bank <= write_bank;
            start_addr     <= (fill_count >= DEPTH_COUNT)
                              ? write_ptr : {ADDR_WIDTH{1'b0}};
            write_total    <= fill_count;
            write_bank     <= ~write_bank;
            frame_sequence <= frame_sequence + 1'b1;
        end else if (!busy) begin
            // 空闲时处理锁 / 应答
            if (bank_ack) begin
                bank_locked <= 1'b0;
            end else if (bank_lock_req) begin
                bank_locked      <= 1'b1;
                bank_locked_bank <= bank_lock_bank;
            end
        end else if (busy) begin
            // 采样
            if (take_sample) begin
                dec_count <= 16'd0;
                // Roll 时 write_ptr 环形回绕；普通模式到 DEPTH 就停住
                write_ptr <= (roll_mode && write_ptr == DEPTH-1)
                             ? {ADDR_WIDTH{1'b0}} : next_write_ptr;

                if (fill_count < DEPTH_COUNT)
                    fill_count <= fill_count + 1'b1;

                prev_s1 <= adc1_data;
                prev_s2 <= adc2_data;
                previous_valid <= 1'b1;

                if (!triggered) begin
                    if (frame_done_en && ((edge_hit && enough_history) || auto_timeout)) begin
                        triggered <= 1'b1;
                        if (post_count == 0) begin
                            done           <= 1'b1;
                            completed_bank <= write_bank;
                            start_addr     <= next_write_ptr;
                            write_total    <= DEPTH_COUNT;
                            if (can_publish) begin
                                write_bank <= ~write_bank;
                            end else begin
                                lost_frames <= lost_frames + 1'b1;
                            end
                            trigger_index   <= trig_idx_now;
                            frame_triggered <= 1'b1;
                            frame_decimation<= decimation_value;
                            frame_sequence <= frame_sequence + 1'b1;
                            post_remaining <= 0;
                            if (auto_rearm || roll_mode) begin
                                // ★ 立刻重新武装：采样几乎不停（只差切换 bank 的一拍）
                                busy           <= 1'b1;
                                triggered      <= 1'b0;
                                write_ptr      <= {ADDR_WIDTH{1'b0}};
                                fill_count     <= {(ADDR_WIDTH+1){1'b0}};
                                dec_count      <= 16'd0;
                                prev_s1        <= 10'd0;
                                prev_s2        <= 10'd0;
                                previous_valid <= 1'b0;
                            end else begin
                                busy           <= 1'b0;
                            end
                        end else begin
                            post_remaining <= post_count;
                        end
                    end
                end else if (post_remaining <= 1) begin
                    done           <= 1'b1;
                    completed_bank <= write_bank;
                    start_addr     <= next_write_ptr;
                    write_total    <= DEPTH_COUNT;
                    post_remaining <= 0;
                    if (can_publish) begin
                        write_bank <= ~write_bank;
                    end else begin
                        lost_frames <= lost_frames + 1'b1;
                    end
                    trigger_index    <= trig_idx_now;
                    frame_triggered  <= 1'b1;
                    frame_decimation <= decimation_value;
                    frame_sequence <= frame_sequence + 1'b1;
                    if (auto_rearm || roll_mode) begin
                        busy           <= 1'b1;
                        triggered      <= 1'b0;
                        write_ptr      <= {ADDR_WIDTH{1'b0}};
                        fill_count     <= {(ADDR_WIDTH+1){1'b0}};
                        dec_count      <= 16'd0;
                        prev_s1        <= 10'd0;
                        prev_s2        <= 10'd0;
                        previous_valid <= 1'b0;
                    end else begin
                        busy           <= 1'b0;
                    end
                end else begin
                    post_remaining <= post_remaining - 1'b1;
                end
            end else begin
                dec_count <= dec_count + 1'b1;
            end
        end
    end

    // 旧的 SCP4 端口：改为由新的流式统计引擎驱动（原来那段残缺代码已删除）
    always @(posedge sample_clk or negedge rst_n) begin
        if (!rst_n) begin
            frame_min1 <= 10'd0; frame_max1 <= 10'd0;
            frame_min2 <= 10'd0; frame_max2 <= 10'd0;
            frame_clip1 <= 2'b00; frame_clip2 <= 2'b00;
            frame_edges1 <= 8'd0; frame_edges2 <= 8'd0;
            frame_edge_span1 <= 24'd0; frame_edge_span2 <= 24'd0;
        end else if (done) begin
            frame_min1 <= st_min1_r; frame_max1 <= st_max1_r;
            frame_min2 <= st_min2_r; frame_max2 <= st_max2_r;
            frame_clip1 <= {st_hi1_r != 16'd0, st_lo1_r != 16'd0};
            frame_clip2 <= {st_hi2_r != 16'd0, st_lo2_r != 16'd0};
            frame_edges1 <= st_ed1_r[7:0]; frame_edges2 <= st_ed2_r[7:0];
            frame_edge_span1 <= (st_ed1_r >= 16'd2) ? (st_le1_r - st_fe1_r) : 24'd0;
            frame_edge_span2 <= (st_ed2_r >= 16'd2) ? (st_le2_r - st_fe2_r) : 24'd0;
        end
    end

    // Roll 写指针 / 填充量（组合输出，AXI 侧自己同步）
    assign roll_ptr_out  = {1'b0, write_ptr};
    assign roll_fill_out = fill_count;

endmodule
