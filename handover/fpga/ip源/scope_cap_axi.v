//=====================================================================
//  scope_cap_axi.v  ——  scope_cap 的 AXI4-Lite 封装
//---------------------------------------------------------------------
//  寄存器映射 (全部 32 位, 步进 4)
//    0x00 CTRL     W[0]=start(脉冲)  W[1]=stop(脉冲)
//                  R[0]=done R[1]=busy R[2]=triggered R[3]=rd_bank
//    0x04 SRC      [0]=src_sel(0 DDS / 1 外部ADC)   [2:1]=wave
//    0x08 DIV      [15:0] 基础分频 (默认 5 -> 20 MSPS)
//    0x0C DEC      [7:0]  抽取 (默认 1)
//    0x10 FREQ     [31:0] DDS 频率字 (默认 ~1kHz @20MSPS)
//    0x14 TRIGLEV  [7:0]  触发电平 (默认 128)
//    0x18 TRIGCFG  [0]=边沿(0升1降)  [2:1]=模式(0Auto 1Normal 2Single)
//    0x1C PRE      [11:0] 预触发点数 (默认 2048)
//    0x20 START    R 最老样本地址 (读起点)
//    0x24 RDPTR    W 设置读指针 / R 当前读指针
//    0x28 RDATA    R 一次返回 4 个样本 {s3,s2,s1,s0}, 读完自动 +4
//    0x2C WRTOTAL  R 本次采集写了多少样本
//    0x30 STATUS   R[0]=err    W[0]=写1清错误
//    0x34 VERSION  R = 0x53434F50 ("SCOP")
//
//  ---- 为什么 RDATA 一次给 4 个样本 ----
//  4096 个样本如果一个个读, 就是 4096 次 AXI-Lite 往返, 每帧要 1~2ms。
//  打包成 4 个只需要 1024 次。做法是【后台预取】: 平时就把
//  [rd_ptr, rd_ptr+3] 这 4 个样本读进 pf_word (4 拍), 上层来读时直接
//  返回寄存器, 无需等待 —— 因为 AXI 往返远长于 4 拍。
//=====================================================================
`timescale 1ns / 1ps

module scope_cap_axi #(
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

    // ---------------- 外部 8 位并行 ADC ----------------
    input  wire [7:0]  adc_data,
    output wire        adc_clk,
    output wire [7:0]  adc_dbg          // 调试: 当前采样值 (可悬空)
);

    //=========================================================
    //  寄存器
    //=========================================================
    reg        reg_start, reg_stop;
    reg        reg_src;
    reg [1:0]  reg_wave;
    reg [15:0] reg_div;
    reg [7:0]  reg_dec;
    reg [31:0] reg_freq;
    reg [7:0]  reg_triglev;
    reg        reg_edge;
    reg [1:0]  reg_mode;
    reg [11:0] reg_pre;

    reg        err_r;

    //=========================================================
    //  采集核心
    //=========================================================
    wire        c_busy, c_done, c_trig, c_rdbank;
    wire [11:0] c_start;
    wire [12:0] c_wrtotal;
    wire [7:0]  c_rddata;

    reg  [11:0] rd_ptr;
    reg         pf_start;
    reg         pf_busy;
    reg  [1:0]  pf_cnt;
    reg  [31:0] pf_word;

    wire [11:0] cap_rd_addr = pf_busy ? (rd_ptr + {10'd0, pf_cnt} + 12'd1)
                                      : rd_ptr;
    wire        pf_idle = ~pf_busy;

    scope_cap u_cap (
        .clk(aclk), .rst_n(aresetn),
        .start(reg_start), .stop(reg_stop),
        .src_sel(reg_src), .wave(reg_wave), .freq(reg_freq),
        .div(reg_div), .dec(reg_dec),
        .trig_level(reg_triglev), .trig_edge(reg_edge), .trig_mode(reg_mode),
        .pre(reg_pre),
        .adc_data(adc_data), .adc_clk(adc_clk),
        .busy(c_busy), .done(c_done), .triggered(c_trig),
        .start_addr(c_start), .wr_total(c_wrtotal), .rd_bank(c_rdbank),
        .rd_addr(cap_rd_addr), .rd_data(c_rddata)
    );

    assign adc_dbg = c_rddata;

    //=========================================================
    //  后台预取: 把 [rd_ptr, rd_ptr+3] 读进 pf_word
    //---------------------------------------------------------
    //  ★ 关键细节: 读端口是【寄存输出】, 也就是
    //        rd_data(t+1) = mem[cap_rd_addr(t)]
    //    所以预取第 n 拍要拿到的数据, 地址必须【提前一拍】给出去。
    //    这里用 cap_rd_addr = rd_ptr + pf_cnt + 1 来对齐:
    //        pf_cnt=0 -> rd_ptr+1  (拿到的却是 mem[rd_ptr+0])  因为寄存了一拍
    //      第一版这里写成了 rd_ptr + pf_cnt, 结果 4 次读回同一个样本,
    //    仿真里表现为"周期数多出两倍"(相邻样本相同 -> 到处是虚假跳变)。
    //=========================================================
    always @(posedge aclk or negedge aresetn) begin
        if (!aresetn) begin
            pf_busy <= 1'b0;
            pf_cnt  <= 2'd0;
            pf_word <= 32'd0;
        end else if (pf_start) begin
            pf_busy <= 1'b1;
            pf_cnt  <= 2'd0;
        end else if (pf_busy) begin
            case (pf_cnt)
                2'd0: pf_word[7:0]   <= c_rddata;
                2'd1: pf_word[15:8]  <= c_rddata;
                2'd2: pf_word[23:16] <= c_rddata;
                default: pf_word[31:24] <= c_rddata;
            endcase
            if (pf_cnt == 2'd3) pf_busy <= 1'b0;
            else                pf_cnt  <= pf_cnt + 2'd1;
        end
    end

    //=========================================================
    //  AXI4-Lite 从机
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

            reg_start <= 1'b0; reg_stop <= 1'b0; reg_src <= 1'b0;
            reg_wave  <= 2'd0;
            reg_div   <= 16'd5;                 // 100MHz/5 = 20 MSPS
            reg_dec   <= 8'd1;
            // 100 kHz @ 20 MSPS: freq = 2^32 * 1e5 / 20e6 = 2^32/200 = 21474836
            // 这样默认窗口 (4096 点 @ DEC=1) 里正好约 20.5 个周期, 一上电就有波形
            reg_freq  <= 32'd21474836;
            reg_triglev <= 8'd128;
            reg_edge  <= 1'b0;
            reg_mode  <= 2'd0;                  // Auto
            reg_pre   <= 12'd2048;

            err_r   <= 1'b0;
            rd_ptr  <= 12'd0;
            pf_start <= 1'b0;
        end else begin
            pf_start <= 1'b0;                   // 默认单拍脉冲

            // ---- 写地址/数据 接收 ----
            // ★ 写 RDPTR(0x24) 必须等预取空闲 —— 否则会在预取中途改 rd_ptr,
            //   第一拍拿到的地址和数据对不上 (会有一个错样本)
            if (!s_axi_awready && s_axi_awvalid && s_axi_wvalid &&
                ((s_axi_awaddr[5:2] != 4'h9) || pf_idle)) begin
                awaddr_l      <= s_axi_awaddr;
                wdata_l       <= s_axi_wdata;
                wstrb_l       <= s_axi_wstrb;
                s_axi_awready <= 1'b1;
                s_axi_wready  <= 1'b1;
            end else begin
                s_axi_awready <= 1'b0;
                s_axi_wready  <= 1'b0;
            end

            // ---- 写寄存器 ----
            if (s_axi_awready && s_axi_wready) begin
                s_axi_bvalid <= 1'b1;
                s_axi_bresp  <= 2'b00;
                case (awaddr_l[5:2])
                    4'h0: begin
                        if (wstrb_l[0]) begin
                            if (wdata_l[0]) reg_start <= 1'b1;
                            if (wdata_l[1]) reg_stop  <= 1'b1;
                        end
                    end
                    4'h1: begin reg_src <= wdata_l[0]; reg_wave <= wdata_l[2:1]; end
                    4'h2: reg_div     <= wdata_l[15:0];
                    4'h3: reg_dec     <= wdata_l[7:0];
                    4'h4: reg_freq    <= wdata_l;
                    4'h5: reg_triglev <= wdata_l[7:0];
                    4'h6: begin reg_edge <= wdata_l[0]; reg_mode <= wdata_l[2:1]; end
                    4'h7: reg_pre     <= wdata_l[11:0];
                    4'h9: begin                       // 0x24 RDPTR
                        rd_ptr   <= wdata_l[11:0];
                        pf_start <= 1'b1;
                    end
                    4'hC: if (wstrb_l[0] && wdata_l[0]) err_r <= 1'b0;   // 0x30 STATUS
                    default: ;
                endcase
            end
            if (s_axi_bvalid && s_axi_bready) s_axi_bvalid <= 1'b0;

            // start/stop 是脉冲, 自动清零
            if (reg_start) reg_start <= 1'b0;
            if (reg_stop)  reg_stop  <= 1'b0;

            // ---- 读 ----
            // ★ 读 RDATA(0x28) 必须等预取完成, 否则拿到的是上一批的样本
            if (!s_axi_arready && s_axi_arvalid &&
                ((s_axi_araddr[5:2] != 4'hA) || pf_idle))
                s_axi_arready <= 1'b1;
            else
                s_axi_arready <= 1'b0;

            if (s_axi_arready && s_axi_arvalid) begin
                s_axi_rvalid <= 1'b1;
                s_axi_rresp  <= 2'b00;
                case (s_axi_araddr[5:2])
                    4'h0: s_axi_rdata <= {28'd0, c_rdbank, c_trig, c_busy, c_done};
                    4'h1: s_axi_rdata <= {29'd0, reg_wave, reg_src};
                    4'h2: s_axi_rdata <= {16'd0, reg_div};
                    4'h3: s_axi_rdata <= {24'd0, reg_dec};
                    4'h4: s_axi_rdata <= reg_freq;
                    4'h5: s_axi_rdata <= {24'd0, reg_triglev};
                    4'h6: s_axi_rdata <= {29'd0, reg_mode, reg_edge};
                    4'h7: s_axi_rdata <= {20'd0, reg_pre};
                    4'h8: s_axi_rdata <= {20'd0, c_start};        // 0x20 START
                    4'h9: s_axi_rdata <= {20'd0, rd_ptr};         // 0x24 RDPTR
                    4'hA: begin                                   // 0x28 RDATA
                        s_axi_rdata <= pf_word;
                        rd_ptr   <= rd_ptr + 12'd4;
                        pf_start <= 1'b1;
                    end
                    4'hB: s_axi_rdata <= {19'd0, c_wrtotal};      // 0x2C WRTOTAL
                    4'hC: s_axi_rdata <= {31'd0, err_r};          // 0x30 STATUS
                    4'hD: s_axi_rdata <= 32'h53434F50;            // 0x34 "SCOP"
                    default: s_axi_rdata <= 32'hDEADBEEF;
                endcase
            end
            if (s_axi_rvalid && s_axi_rready) s_axi_rvalid <= 1'b0;
        end
    end

endmodule
