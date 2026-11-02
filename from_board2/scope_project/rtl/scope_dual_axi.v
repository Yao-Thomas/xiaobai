`timescale 1ns / 1ps

// AXI4-Lite wrapper for the dual 3PA1030 capture engine.
module scope_dual_axi #(
    parameter integer C_S_AXI_ADDR_WIDTH = 12,   // BD 已给 64K 范围，扩到 12 位以便放统计寄存器
    parameter integer C_S_AXI_DATA_WIDTH = 32
)(
    (* X_INTERFACE_PARAMETER = "ASSOCIATED_BUSIF S_AXI, ASSOCIATED_RESET aresetn, FREQ_HZ 100000000" *)
    (* X_INTERFACE_INFO = "xilinx.com:signal:clock:1.0 aclk CLK" *)
    input  wire                              aclk,
    (* X_INTERFACE_PARAMETER = "POLARITY ACTIVE_LOW" *)
    (* X_INTERFACE_INFO = "xilinx.com:signal:reset:1.0 aresetn RST" *)
    input  wire                              aresetn,

    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI AWADDR" *)
    input  wire [C_S_AXI_ADDR_WIDTH-1:0]     s_axi_awaddr,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI AWPROT" *)
    input  wire [2:0]                        s_axi_awprot,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI AWVALID" *)
    input  wire                              s_axi_awvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI AWREADY" *)
    output reg                               s_axi_awready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI WDATA" *)
    input  wire [C_S_AXI_DATA_WIDTH-1:0]     s_axi_wdata,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI WSTRB" *)
    input  wire [(C_S_AXI_DATA_WIDTH/8)-1:0] s_axi_wstrb,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI WVALID" *)
    input  wire                              s_axi_wvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI WREADY" *)
    output reg                               s_axi_wready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI BRESP" *)
    output reg [1:0]                         s_axi_bresp,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI BVALID" *)
    output reg                               s_axi_bvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI BREADY" *)
    input  wire                              s_axi_bready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI ARADDR" *)
    input  wire [C_S_AXI_ADDR_WIDTH-1:0]     s_axi_araddr,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI ARPROT" *)
    input  wire [2:0]                        s_axi_arprot,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI ARVALID" *)
    input  wire                              s_axi_arvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI ARREADY" *)
    output reg                               s_axi_arready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI RDATA" *)
    output reg [C_S_AXI_DATA_WIDTH-1:0]      s_axi_rdata,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI RRESP" *)
    output reg [1:0]                         s_axi_rresp,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI RVALID" *)
    output reg                               s_axi_rvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI RREADY" *)
    input  wire                              s_axi_rready,

    // 0-degree clock forwarded to the ADCs. The separate 270-degree
    // sample_clk captures their outputs midway through the valid window.
    (* X_INTERFACE_PARAMETER = "FREQ_HZ 20000000" *)
    (* X_INTERFACE_INFO = "xilinx.com:signal:clock:1.0 adc_ref_clk CLK" *)
    input  wire                              adc_ref_clk,
    (* X_INTERFACE_PARAMETER = "FREQ_HZ 20000000, PHASE 270.0" *)
    (* X_INTERFACE_INFO = "xilinx.com:signal:clock:1.0 sample_clk CLK" *)
    input  wire                              sample_clk,
    input  wire [9:0]                        adc1_data,
    input  wire [9:0]                        adc2_data,
    output wire                              adc1_clk,
    output wire                              adc2_clk
);

    localparam [9:0] REG_CTRL = 10'h00;
    localparam [9:0] REG_SOURCE = 10'h01;
    localparam [9:0] REG_DIV = 10'h02;
    localparam [9:0] REG_DEC = 10'h03;
    localparam [9:0] REG_RESERVED = 10'h04;   // 已改作 ENV_PTR
    // ---- 阶段4：列包络读取口 ----
    //   ENV_PTR (0x04)  写：起始列；bit10=通道(0:CH1 1:CH2)，bit9:0=列号
    //   ENV_DATA(0x01)  读：返回该列 {max[9:0],min[9:0]}，并自动 +1
    //   ★ 一次读顶一次事务（旧路径是"写RDPTR+读RDATA"两次），
    //     1008 列 x 2 通道 = 2016 次，比原来的 8192 次少 4 倍。
    localparam [9:0] REG_ENV_PTR = 10'h04;
    localparam [9:0] REG_ENV_DATA = 10'h01;
    localparam [9:0] REG_TRIGLEV = 10'h05;
    localparam [9:0] REG_TRIGCFG = 10'h06;
    localparam [9:0] REG_PRE = 10'h07;
    localparam [9:0] REG_START = 10'h08;
    localparam [9:0] REG_RDPTR = 10'h09;
    localparam [9:0] REG_RDATA = 10'h0A;
    localparam [9:0] REG_WRTOTAL = 10'h0B;
    localparam [9:0] REG_STATUS = 10'h0C;
    localparam [9:0] REG_VERSION = 10'h0D;
    localparam [9:0] REG_CAPS = 10'h0E;
    localparam [9:0] REG_RATE = 10'h0F;
    localparam [9:0] REG_FRAMESEQ = 10'h10;
    // ---- 帧描述符 + Bank 锁定（步骤1：杜绝拼接帧）----
    localparam [9:0] REG_DESC0 = 10'h11; // {bank(1), start_addr[11:0]}
    localparam [9:0] REG_DESC1 = 10'h12; // sample_count
    localparam [9:0] REG_TRIGIDX = 10'h13; // 触发点在帧内位置
    localparam [9:0] REG_LOST = 10'h14; // 丢帧计数
    localparam [9:0] REG_LOCK = 10'h15; // 写: bit0=lock  bit1=bank  bit2=ack
    localparam [9:0] REG_FLAGS = 10'h16; // bit0=triggered bit1=locked bit2=busy
    localparam [9:0] REG_FRAMEDEC = 10'h17; // 本帧实际抽取倍率
    // ---- 步骤2：迟滞宽度 + Roll 采集模式 ----
    localparam [9:0] REG_HYS = 10'h18; // 迟滞宽度（LSB）
    localparam [9:0] REG_ACQMODE = 10'h19; // 0=Auto 1=Normal 2=Single 3=Roll
    localparam [9:0] REG_ROLLPTR = 10'h1A; // Roll 写指针（最新点在哪儿）+ 填充数

    // ---- 诊断寄存器（接线排查用，不影响正常采集）----
    // 读 REG_LIVE 会把调试计数器清零后重新开始统计
    localparam [9:0] REG_LIVE = 10'h1B; // {6'd0,live2,6'd0,live1} 实时引脚
    localparam [9:0] REG_ACT = 10'h1C; // {8'd0,chg2[11:0],chg1[11:0]} 翻转次数
    localparam [9:0] REG_EVER = 10'h1D; // {lo1,hi1,lo2,hi2} 各位是否出现过高/低
    localparam [9:0] REG_CLKCNT = 10'h1E; // sample_clk 计数（证明时钟树在跑）
    localparam [9:0] REG_TESTPAT = 10'h1F; // !=0 时用内部测试波形代替 ADC
    // ---- 阶段4：帧统计结果（PL 采集时流式算出，PS 只读寄存器）----
    localparam [9:0] REG_ST_MM1   = 10'h20; // {max1[9:0], min1[9:0]}
    localparam [9:0] REG_ST_MM2   = 10'h21; // {max2[9:0], min2[9:0]}
    localparam [9:0] REG_ST_SUM1  = 10'h22; // 累加和（PS 除以 n 得均值）
    localparam [9:0] REG_ST_SUM2  = 10'h23;
    localparam [9:0] REG_ST_CLIP1 = 10'h24; // {贴1023数, 贴0数}
    localparam [9:0] REG_ST_CLIP2 = 10'h25;
    localparam [9:0] REG_ST_EDG1  = 10'h26; // {首末边沿间隔, 边沿数}
    localparam [9:0] REG_ST_EDG2  = 10'h27;
    localparam [9:0] REG_ST_N     = 10'h28; // {valid, 统计点数}
    localparam [9:0] REG_WIN_START= 10'h29; // 显示窗口起点（相对触发点，采样点）
    localparam [9:0] REG_WIN_LEN  = 10'h2A; // 显示窗口长度（采样点）= Timebase.span
    localparam [9:0] REG_COL_STEP = 10'h2B; // 列号步进 = round(COLS*65536/win_len)，DDA 用


    // Forward a clean 50% duty-cycle sampling clock to both ADC channels.
    ODDR #(
        .DDR_CLK_EDGE("SAME_EDGE"),
        .INIT(1'b0),
        .SRTYPE("SYNC")
    ) adc1_clock_oddr (
        .Q(adc1_clk), .C(adc_ref_clk), .CE(1'b1),
        .D1(1'b1), .D2(1'b0), .R(1'b0), .S(1'b0)
    );

    ODDR #(
        .DDR_CLK_EDGE("SAME_EDGE"),
        .INIT(1'b0),
        .SRTYPE("SYNC")
    ) adc2_clock_oddr (
        .Q(adc2_clk), .C(adc_ref_clk), .CE(1'b1),
        .D1(1'b1), .D2(1'b0), .R(1'b0), .S(1'b0)
    );

    (* IOB = "TRUE" *) reg [9:0] adc1_iob;
    (* IOB = "TRUE" *) reg [9:0] adc2_iob;
    always @(posedge sample_clk) begin
        adc1_iob <= adc1_data;
        adc2_iob <= adc2_data;
    end

    // =====================================================================
    // 诊断：实时监视 ADC 引脚，判断"信号到底有没有到 FPGA 引脚上"
    //
    //   CLKCNT  一直在涨     -> PL 的 20MHz 采样时钟树正常
    //   ACT 一直是 0         -> 引脚死住，外部没有数据进来（接线/供电/OE/时钟）
    //   EVER1/2 的 hi|lo     -> 每一位是否出现过高和低（该位有没有动过）
    //   TESTPAT != 0         -> 用内部产生的三角波/方波代替 ADC，
    //                           用来单独验证"采集 -> 存储 -> 读出 -> 显示"整条链路
    // =====================================================================
    reg [23:0] dbg_clkcnt;
    reg [11:0] dbg_chg1, dbg_chg2;
    reg [9:0]  dbg_hi1, dbg_hi2, dbg_lo1, dbg_lo2;
    reg [9:0]  dbg_live1, dbg_live2;
    reg [15:0] pat_cnt;
    reg [15:0] reg_testpat;
    reg        dbg_clr_s1, dbg_clr_s2;
    reg        dbg_clear_hold;      // aclk 域产生，sample_clk 域使用

    always @(posedge sample_clk or negedge sample_resetn) begin
        if (!sample_resetn) begin
            dbg_clkcnt <= 24'd0;
            dbg_chg1 <= 12'd0;  dbg_chg2 <= 12'd0;
            dbg_hi1  <= 10'd0;  dbg_hi2  <= 10'd0;
            dbg_lo1  <= 10'd0;  dbg_lo2  <= 10'd0;
            dbg_live1 <= 10'd0; dbg_live2 <= 10'd0;
            pat_cnt  <= 16'd0;
            dbg_clr_s1 <= 1'b0; dbg_clr_s2 <= 1'b0;
        end else begin
            dbg_clr_s1 <= dbg_clear_hold;
            dbg_clr_s2 <= dbg_clr_s1;
            dbg_clkcnt <= dbg_clkcnt + 24'd1;
            dbg_live1  <= adc1_data;
            dbg_live2  <= adc2_data;
            pat_cnt    <= pat_cnt + 16'd1;
            if (dbg_clr_s2) begin
                dbg_chg1 <= 12'd0;  dbg_chg2 <= 12'd0;
                dbg_hi1  <= 10'd0;  dbg_hi2  <= 10'd0;
                dbg_lo1  <= 10'd0;  dbg_lo2  <= 10'd0;
            end else begin
                if (adc1_data != dbg_live1) dbg_chg1 <= dbg_chg1 + 12'd1;
                if (adc2_data != dbg_live2) dbg_chg2 <= dbg_chg2 + 12'd1;
                dbg_hi1 <= dbg_hi1 | adc1_data;
                dbg_hi2 <= dbg_hi2 | adc2_data;
                dbg_lo1 <= dbg_lo1 | (~adc1_data);
                dbg_lo2 <= dbg_lo2 | (~adc2_data);
            end
        end
    end

    // 内部测试波形：三角波 / 方波，周期 2048 个采样点（20MHz/2048 ≈ 9.77kHz）
    wire [9:0] pat_tri = pat_cnt[9:0] ^ {10{pat_cnt[10]}};
    wire [9:0] pat_sqr = {10{pat_cnt[10]}};

    wire [9:0] core_adc1 = reg_testpat[0] ? pat_tri : adc1_iob;
    wire [9:0] core_adc2 = reg_testpat[0] ? pat_sqr : adc2_iob;

    reg [15:0] reg_decimation;
    reg [9:0]  reg_trigger_level;
    reg        reg_trigger_edge;
    reg [1:0]  reg_trigger_mode;
    reg        reg_trigger_channel;
    // 触发源：0=CH1  1=CH2  2=CH1&CH2 同时  3=不触发（自由运行，用于滚动模式）
    reg [1:0]  reg_trigger_source;
    reg [11:0] reg_pretrigger;
    reg [11:0] reg_win_start;
    reg [12:0] reg_win_len;
    reg [23:0] reg_col_step;
    reg [23:0] cs_s1, cs_s2;
    reg [11:0] win_st_s1, win_st_s2;
    reg [12:0] win_ln_s1, win_ln_s2;
    reg [10:0] env_ptr;              // {ch, col}
    reg [10:0] env_ptr_next;
    reg [9:0]  reg_trigger_hys;
    reg [1:0]  reg_acq_mode;
    reg        bank_lock_req_r;
    reg        bank_lock_bank_r;
    reg        bank_ack_r;
    reg        start_toggle;
    reg        stop_toggle;

    // Configuration and command synchronization into the 20 MHz domain.
    reg [15:0] dec_sync1, dec_sync2;
    reg [9:0]  level_sync1, level_sync2;
    reg        edge_sync1, edge_sync2;
    reg [1:0]  mode_sync1, mode_sync2;
    reg        channel_sync1, channel_sync2;
    reg [1:0]  src_sync1, src_sync2;
    reg [9:0]  hys_sync1, hys_sync2;
    reg [1:0]  acq_sync1, acq_sync2;
    reg [11:0] pre_sync1, pre_sync2;
    reg [2:0]  start_sync, stop_sync;
    reg        start_seen, stop_seen;
    reg [1:0]  sample_reset_sync;

    wire sample_resetn = sample_reset_sync[1];
    wire start_pulse_sample = start_sync[2] ^ start_seen;
    wire stop_pulse_sample  = stop_sync[2] ^ stop_seen;

    always @(posedge sample_clk or negedge aresetn) begin
        if (!aresetn) begin
            sample_reset_sync <= 2'b00;
            dec_sync1 <= 16'd1; dec_sync2 <= 16'd1;
            level_sync1 <= 10'd512; level_sync2 <= 10'd512;
            edge_sync1 <= 1'b0; edge_sync2 <= 1'b0;
            mode_sync1 <= 2'd0; mode_sync2 <= 2'd0;
            channel_sync1 <= 1'b0; channel_sync2 <= 1'b0;
            src_sync1 <= 2'd0; src_sync2 <= 2'd0;
            hys_sync1 <= 10'd2; hys_sync2 <= 10'd2;
            acq_sync1 <= 2'd0; acq_sync2 <= 2'd0;
            pre_sync1 <= 12'd2048; pre_sync2 <= 12'd2048;
            start_sync <= 3'b000; stop_sync <= 3'b000;
            start_seen <= 1'b0; stop_seen <= 1'b0;
        end else begin
            sample_reset_sync <= {sample_reset_sync[0], 1'b1};
            dec_sync1 <= reg_decimation; dec_sync2 <= dec_sync1;
            level_sync1 <= reg_trigger_level; level_sync2 <= level_sync1;
            edge_sync1 <= reg_trigger_edge; edge_sync2 <= edge_sync1;
            mode_sync1 <= reg_trigger_mode; mode_sync2 <= mode_sync1;
            channel_sync1 <= reg_trigger_channel; channel_sync2 <= channel_sync1;
            src_sync1 <= reg_trigger_source; src_sync2 <= src_sync1;
            hys_sync1 <= reg_trigger_hys;     hys_sync2 <= hys_sync1;
            acq_sync1 <= reg_acq_mode;        acq_sync2 <= acq_sync1;
            win_st_s1 <= reg_win_start;       win_st_s2 <= win_st_s1;
            win_ln_s1 <= reg_win_len;         win_ln_s2 <= win_ln_s1;
            cs_s1 <= reg_col_step;            cs_s2 <= cs_s1;
            pre_sync1 <= reg_pretrigger; pre_sync2 <= pre_sync1;
            start_sync <= {start_sync[1:0], start_toggle};
            stop_sync  <= {stop_sync[1:0], stop_toggle};
            if (start_pulse_sample) start_seen <= start_sync[2];
            if (stop_pulse_sample)  stop_seen  <= stop_sync[2];
        end
    end

    wire        core_busy;
    wire        core_done;
    wire        core_triggered;
    wire        core_completed_bank;
    wire [11:0] core_start_addr;
    wire [12:0] core_write_total;
    wire [31:0] core_frame_sequence;
    reg  [11:0] rd_ptr;
    wire [19:0] core_rd_data;
    wire        core_bank_locked;
    wire        core_bank_locked_bank;
    wire [15:0] core_lost_frames;
    wire [11:0] core_trigger_index;
    wire [12:0] core_roll_ptr;
    wire [19:0] core_env_data;
    wire [9:0]  core_st_min1, core_st_max1, core_st_min2, core_st_max2;
    wire [31:0] core_st_sum1, core_st_sum2;
    wire [15:0] core_st_lo1, core_st_hi1, core_st_lo2, core_st_hi2;
    wire [15:0] core_st_ed1, core_st_ed2, core_st_sp1, core_st_sp2;
    wire [15:0] core_st_n;
    wire        core_st_valid;
    wire [12:0] core_roll_fill;
    wire        core_frame_triggered;
    wire [15:0] core_frame_decimation;

    // Status synchronization back into the AXI domain.
    reg busy_sync1, busy_sync2, done_sync1, done_sync2;
    reg trig_sync1, trig_sync2, bank_sync1, bank_sync2;
    reg [11:0] start_addr_sync1, start_addr_sync2;
    reg [12:0] write_total_sync1, write_total_sync2;
    reg [31:0] frame_sync1, frame_sync2;

    // ---- 诊断值同步回 AXI 域 ----
    reg [23:0] clkcnt_s1, clkcnt_s2;
    reg [11:0] chg1_s1, chg1_s2, chg2_s1, chg2_s2;
    reg [9:0]  live1_s1, live1_s2, live2_s1, live2_s2;
    reg [9:0]  hi1_s1, hi1_s2, hi2_s1, hi2_s2;
    reg [9:0]  lo1_s1, lo1_s2, lo2_s1, lo2_s2;
    reg        dbg_clear_req;
    reg [4:0]  dbg_clear_timer;

    always @(posedge aclk or negedge aresetn) begin
        if (!aresetn) begin
            clkcnt_s1 <= 24'd0; clkcnt_s2 <= 24'd0;
            chg1_s1 <= 12'd0; chg1_s2 <= 12'd0;
            chg2_s1 <= 12'd0; chg2_s2 <= 12'd0;
            live1_s1 <= 10'd0; live1_s2 <= 10'd0;
            live2_s1 <= 10'd0; live2_s2 <= 10'd0;
            hi1_s1 <= 10'd0; hi1_s2 <= 10'd0; hi2_s1 <= 10'd0; hi2_s2 <= 10'd0;
            lo1_s1 <= 10'd0; lo1_s2 <= 10'd0; lo2_s1 <= 10'd0; lo2_s2 <= 10'd0;
            dbg_clear_hold <= 1'b0;
            dbg_clear_timer <= 5'd0;
        end else begin
            clkcnt_s1 <= dbg_clkcnt;   clkcnt_s2 <= clkcnt_s1;
            chg1_s1 <= dbg_chg1;       chg1_s2 <= chg1_s1;
            chg2_s1 <= dbg_chg2;       chg2_s2 <= chg2_s1;
            live1_s1 <= dbg_live1;     live1_s2 <= live1_s1;
            live2_s1 <= dbg_live2;     live2_s2 <= live2_s1;
            hi1_s1 <= dbg_hi1; hi1_s2 <= hi1_s1;
            hi2_s1 <= dbg_hi2; hi2_s2 <= hi2_s1;
            lo1_s1 <= dbg_lo1; lo1_s2 <= lo1_s1;
            lo2_s1 <= dbg_lo2; lo2_s2 <= lo2_s1;
            if (dbg_clear_req) begin
                dbg_clear_hold  <= 1'b1;
                dbg_clear_timer <= 5'd20;
            end else if (dbg_clear_timer != 5'd0) begin
                dbg_clear_timer <= dbg_clear_timer - 5'd1;
                if (dbg_clear_timer == 5'd1) dbg_clear_hold <= 1'b0;
            end
        end
    end

    always @(posedge aclk or negedge aresetn) begin
        if (!aresetn) begin
            busy_sync1 <= 0; busy_sync2 <= 0;
            done_sync1 <= 0; done_sync2 <= 0;
            trig_sync1 <= 0; trig_sync2 <= 0;
            bank_sync1 <= 0; bank_sync2 <= 0;
            start_addr_sync1 <= 0; start_addr_sync2 <= 0;
            write_total_sync1 <= 0; write_total_sync2 <= 0;
            frame_sync1 <= 0; frame_sync2 <= 0;
        end else begin
            busy_sync1 <= core_busy; busy_sync2 <= busy_sync1;
            done_sync1 <= core_done; done_sync2 <= done_sync1;
            trig_sync1 <= core_triggered; trig_sync2 <= trig_sync1;
            bank_sync1 <= core_completed_bank; bank_sync2 <= bank_sync1;
            start_addr_sync1 <= core_start_addr; start_addr_sync2 <= start_addr_sync1;
            write_total_sync1 <= core_write_total; write_total_sync2 <= write_total_sync1;
            frame_sync1 <= core_frame_sequence; frame_sync2 <= frame_sync1;
        end
    end

    scope_dual_core capture_core (
        .sample_clk(sample_clk),
        .rst_n(sample_resetn),
        .start_pulse(start_pulse_sample),
        .stop_pulse(stop_pulse_sample),
        .cfg_decimation(dec_sync2),
        .cfg_trigger_level(level_sync2),
        .cfg_trigger_edge(edge_sync2),
        .cfg_trigger_mode(mode_sync2),
        .cfg_trigger_channel(channel_sync2),
        .cfg_trigger_source(src_sync2),
        .cfg_trigger_hys(hys_sync2),
        .cfg_acq_roll(acq_sync2 == 2'd3),
        .cfg_free_run(src_sync2 == 2'd3),
        .cfg_pretrigger(pre_sync2),
        .adc1_data(core_adc1),
        .adc2_data(core_adc2),
        .busy(core_busy),
        .done(core_done),
        .triggered(core_triggered),
        .completed_bank(core_completed_bank),
        .start_addr(core_start_addr),
        .write_total(core_write_total),
        .frame_sequence(core_frame_sequence),
        .bank_lock_req(bank_lock_req_r),
        .bank_lock_bank(bank_lock_bank_r),
        .bank_ack(bank_ack_r),
        .bank_locked(core_bank_locked),
        .bank_locked_bank(core_bank_locked_bank),
        .lost_frames(core_lost_frames),
        .trigger_index(core_trigger_index),
        .cfg_win_start(win_st_s2),
        .cfg_col_step(cs_s2),
        .cfg_win_len(win_ln_s2),
        .st_min1(core_st_min1), .st_max1(core_st_max1),
        .st_min2(core_st_min2), .st_max2(core_st_max2),
        .st_sum1(core_st_sum1), .st_sum2(core_st_sum2),
        .st_clip_lo1(core_st_lo1), .st_clip_hi1(core_st_hi1),
        .st_clip_lo2(core_st_lo2), .st_clip_hi2(core_st_hi2),
        .st_edges1(core_st_ed1), .st_edges2(core_st_ed2),
        .st_span1(core_st_sp1), .st_span2(core_st_sp2),
        .st_n(core_st_n), .st_valid(core_st_valid),
        .env_rd_col(env_ptr),
        .env_rd_data(core_env_data),
        .roll_ptr_out(core_roll_ptr),
        .roll_fill_out(core_roll_fill),
        .frame_triggered(core_frame_triggered),
        .frame_decimation(core_frame_decimation),
        .rd_clk(aclk),
        .rd_addr({bank_sync2, rd_ptr}),
        .rd_data(core_rd_data)
    );

    reg [C_S_AXI_ADDR_WIDTH-1:0] awaddr_hold;
    reg [31:0] wdata_hold;
    reg [3:0]  wstrb_hold;
    reg        aw_hold_valid;
    reg        w_hold_valid;
    reg [2:0]  rd_wait;

    wire [9:0] write_word = awaddr_hold[11:2];
    wire [9:0] read_word  = s_axi_araddr[11:2];

    always @(posedge aclk or negedge aresetn) begin
        if (!aresetn) begin
            s_axi_awready <= 1'b0;
            s_axi_wready  <= 1'b0;
            s_axi_bresp   <= 2'b00;
            s_axi_bvalid  <= 1'b0;
            s_axi_arready <= 1'b0;
            s_axi_rdata   <= 32'd0;
            s_axi_rresp   <= 2'b00;
            s_axi_rvalid  <= 1'b0;
            awaddr_hold   <= 0;
            wdata_hold    <= 0;
            wstrb_hold    <= 0;
            aw_hold_valid <= 1'b0;
            w_hold_valid  <= 1'b0;
            reg_decimation <= 16'd1;
            reg_trigger_level <= 10'd512;
            reg_trigger_edge <= 1'b0;
            reg_trigger_mode <= 2'd0;
            reg_trigger_channel <= 1'b0;
            reg_trigger_source  <= 2'd0;
            env_ptr             <= 11'd0;
            reg_win_start       <= 12'd0;
            reg_win_len         <= 13'd4096;
            reg_col_step        <= 24'd1008;      // COLS*65536/4096 = 1008
            cs_s1 <= 24'd1008; cs_s2 <= 24'd1008;
            win_st_s1 <= 12'd0; win_st_s2 <= 12'd0;
            win_ln_s1 <= 13'd4096; win_ln_s2 <= 13'd4096;
            reg_trigger_hys     <= 10'd2;
            reg_acq_mode        <= 2'd0;
            bank_lock_req_r     <= 1'b0;
            bank_lock_bank_r    <= 1'b0;
            bank_ack_r          <= 1'b0;
            reg_pretrigger <= 12'd2048;
            start_toggle <= 1'b0;
            stop_toggle <= 1'b0;
            rd_ptr <= 12'd0;
            rd_wait <= 3'd3;
            reg_testpat <= 16'd0;
            dbg_clear_req <= 1'b0;
        end else begin
            s_axi_awready <= 1'b0;
            s_axi_wready  <= 1'b0;
            s_axi_arready <= 1'b0;
            dbg_clear_req <= 1'b0;   // 单周期脉冲
            bank_ack_r    <= 1'b0;   // 应答也是一拍脉冲

            if (rd_wait != 0)
                rd_wait <= rd_wait - 1'b1;

            if (!aw_hold_valid && !s_axi_bvalid && s_axi_awvalid) begin
                awaddr_hold   <= s_axi_awaddr;
                aw_hold_valid <= 1'b1;
                s_axi_awready <= 1'b1;
            end
            if (!w_hold_valid && !s_axi_bvalid && s_axi_wvalid) begin
                wdata_hold   <= s_axi_wdata;
                wstrb_hold   <= s_axi_wstrb;
                w_hold_valid <= 1'b1;
                s_axi_wready <= 1'b1;
            end

            if (aw_hold_valid && w_hold_valid && !s_axi_bvalid) begin
                aw_hold_valid <= 1'b0;
                w_hold_valid  <= 1'b0;
                s_axi_bvalid  <= 1'b1;
                s_axi_bresp   <= 2'b00;
                case (write_word)
                    REG_CTRL: if (wstrb_hold[0]) begin
                        if (wdata_hold[0]) start_toggle <= ~start_toggle;
                        if (wdata_hold[1]) stop_toggle  <= ~stop_toggle;
                    end
                    REG_SOURCE: if (wstrb_hold[0])
                        reg_trigger_channel <= wdata_hold[0];
                    REG_DEC: begin
                        if (wstrb_hold[0]) reg_decimation[7:0]  <= wdata_hold[7:0];
                        if (wstrb_hold[1]) reg_decimation[15:8] <= wdata_hold[15:8];
                    end
                    REG_TRIGLEV: begin
                        if (wstrb_hold[0]) reg_trigger_level[7:0] <= wdata_hold[7:0];
                        if (wstrb_hold[1]) reg_trigger_level[9:8] <= wdata_hold[9:8];
                    end
                    REG_TRIGCFG: if (wstrb_hold[0]) begin
                        reg_trigger_edge    <= wdata_hold[0];
                        reg_trigger_mode    <= wdata_hold[2:1];
                        reg_trigger_source  <= wdata_hold[4:3];
                        reg_trigger_channel <= wdata_hold[3];
                    end
                    REG_PRE: begin
                        if (wstrb_hold[0]) reg_pretrigger[7:0] <= wdata_hold[7:0];
                        if (wstrb_hold[1]) reg_pretrigger[11:8] <= wdata_hold[11:8];
                    end
                    REG_RDPTR: begin
                        rd_ptr  <= wdata_hold[11:0];
                        rd_wait <= 3'd3;
                    end
                    REG_TESTPAT: if (wstrb_hold[0]) begin
                        reg_testpat <= wdata_hold[15:0];
                    end
                    REG_LIVE: begin        // 写这个寄存器 = 清零诊断计数
                        dbg_clear_req <= 1'b1;
                    end
                    REG_HYS: if (wstrb_hold[0]) begin
                        reg_trigger_hys <= wdata_hold[9:0];
                    end
                    REG_ACQMODE: if (wstrb_hold[0]) begin
                        reg_acq_mode <= wdata_hold[1:0];
                    end
                    REG_WIN_START: if (wstrb_hold[0]) begin
                        reg_win_start <= wdata_hold[11:0];
                    end
                    REG_WIN_LEN: if (wstrb_hold[0]) begin
                        reg_win_len <= wdata_hold[12:0];
                    end
                    REG_COL_STEP: if (wstrb_hold[0]) begin
                        reg_col_step <= wdata_hold[23:0];
                    end
                    REG_ENV_PTR: begin     // 写：设置包络起始列
                        env_ptr <= wdata_hold[10:0];
                    end
                    REG_LOCK: begin        // bit0=锁定请求 bit1=bank bit2=应答
                        bank_lock_req_r  <= wdata_hold[0];
                        bank_lock_bank_r <= wdata_hold[1];
                        bank_ack_r       <= wdata_hold[2];
                    end
                    default: ;
                endcase
            end
            if (s_axi_bvalid && s_axi_bready)
                s_axi_bvalid <= 1'b0;

            if (!s_axi_rvalid && s_axi_arvalid &&
                ((read_word != REG_RDATA) || (rd_wait == 0))) begin
                s_axi_arready <= 1'b1;
                s_axi_rvalid  <= 1'b1;
                s_axi_rresp   <= 2'b00;
                case (read_word)
                    REG_CTRL:     s_axi_rdata <= {28'd0, bank_sync2, trig_sync2,
                                                   busy_sync2, done_sync2};
                    REG_DIV:      s_axi_rdata <= 32'd5;
                    REG_DEC:      s_axi_rdata <= {16'd0, reg_decimation};
                    REG_TRIGLEV:  s_axi_rdata <= {22'd0, reg_trigger_level};
                    REG_TRIGCFG:  s_axi_rdata <= {26'd0, reg_trigger_source,
                                                   reg_trigger_mode, reg_trigger_edge};
                    REG_PRE:      s_axi_rdata <= {20'd0, reg_pretrigger};
                    REG_START:    s_axi_rdata <= {20'd0, start_addr_sync2};
                    REG_RDPTR:    s_axi_rdata <= {20'd0, rd_ptr};
                    REG_RDATA: begin
                        s_axi_rdata <= {6'd0, core_rd_data[19:10],
                                       6'd0, core_rd_data[9:0]};
                        rd_ptr  <= rd_ptr + 1'b1;
                        rd_wait <= 3'd3;
                    end
                    REG_WRTOTAL:  s_axi_rdata <= {19'd0, write_total_sync2};
                    REG_STATUS:   s_axi_rdata <= 32'd0;
                    REG_ST_MM1:   s_axi_rdata <= {12'd0, core_st_max1, core_st_min1};
                    REG_ST_MM2:   s_axi_rdata <= {12'd0, core_st_max2, core_st_min2};
                    REG_ST_SUM1:  s_axi_rdata <= core_st_sum1;
                    REG_ST_SUM2:  s_axi_rdata <= core_st_sum2;
                    REG_ST_CLIP1: s_axi_rdata <= {core_st_hi1, core_st_lo1};
                    REG_ST_CLIP2: s_axi_rdata <= {core_st_hi2, core_st_lo2};
                    REG_ST_EDG1:  s_axi_rdata <= {core_st_sp1, core_st_ed1};
                    REG_ST_EDG2:  s_axi_rdata <= {core_st_sp2, core_st_ed2};
                    REG_ST_N:     s_axi_rdata <= {15'd0, core_st_valid, core_st_n};
                    REG_WIN_START:s_axi_rdata <= {20'd0, reg_win_start};
                    REG_WIN_LEN:  s_axi_rdata <= {19'd0, reg_win_len};
                    REG_COL_STEP: s_axi_rdata <= reg_col_step;
                    REG_ENV_PTR:  s_axi_rdata <= {21'd0, env_ptr};
                    REG_ENV_DATA: s_axi_rdata <= {12'd0, core_env_data};
                    REG_VERSION:  s_axi_rdata <= 32'h53435033; // "SCP3"
                    REG_CAPS:     s_axi_rdata <= 32'h020A1000; // 2ch, 10bit, 4096
                    REG_RATE:     s_axi_rdata <= 32'd20000000;
                    REG_FRAMESEQ: s_axi_rdata <= frame_sync2;
                    REG_DESC0:    s_axi_rdata <= {19'd0, core_completed_bank,
                                                   core_start_addr};
                    REG_DESC1:    s_axi_rdata <= {19'd0, write_total_sync2};
                    REG_TRIGIDX:  s_axi_rdata <= {20'd0, core_trigger_index};
                    REG_LOST:     s_axi_rdata <= {16'd0, core_lost_frames};
                    REG_LOCK:     s_axi_rdata <= {28'd0, bank_ack_r,
                                                  bank_lock_bank_r,
                                                  bank_lock_req_r};
                    REG_FLAGS:    s_axi_rdata <= {29'd0, busy_sync2,
                                                  core_bank_locked,
                                                  core_frame_triggered};
                    REG_FRAMEDEC: s_axi_rdata <= {16'd0, core_frame_decimation};
                    REG_HYS:      s_axi_rdata <= {22'd0, reg_trigger_hys};
                    REG_ACQMODE:  s_axi_rdata <= {30'd0, reg_acq_mode};
                    REG_ROLLPTR:  s_axi_rdata <= {6'd0, core_roll_fill,
                                                  core_roll_ptr[11:0]};
                    // ---- 诊断 ----
                    REG_LIVE:     s_axi_rdata <= {6'd0, live2_s2, 6'd0, live1_s2};
                    REG_ACT:      s_axi_rdata <= {8'd0, chg2_s2, chg1_s2};
                    REG_EVER:     s_axi_rdata <= {lo1_s2, hi1_s2, lo2_s2, hi2_s2};
                    REG_CLKCNT:   s_axi_rdata <= {8'd0, clkcnt_s2};
                    REG_TESTPAT:  s_axi_rdata <= {16'd0, reg_testpat};
                    default:      s_axi_rdata <= 32'hDEADBEEF;
                endcase
                // ★ 读 ENV_DATA 后自动 +1：PS 只写一次起始列，
                //   然后连读 1008 次就能拿到整条包络（每次读只占一次事务）
                if (read_word == REG_ENV_DATA)
                    env_ptr <= (env_ptr[9:0] == 10'd1007)
                               ? {~env_ptr[10], 10'd0}      // 到列尾 -> 翻到另一通道
                               : (env_ptr + 11'd1);
            end
            if (s_axi_rvalid && s_axi_rready)
                s_axi_rvalid <= 1'b0;
        end
    end

endmodule
