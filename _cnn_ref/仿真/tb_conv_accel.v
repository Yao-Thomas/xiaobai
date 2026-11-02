// ============================================================================
// tb_conv_accel.v —— conv_accel_axi_lite 的 AXI4-Lite 仿真验证（M5）
// 验证：写入 A/B/C/D 后读回 result = A*B + C*D，以及 status。
// 运行：xvlog ; xelab tb_conv_accel -s tb_sim ; xsim tb_sim -R
// ============================================================================
`timescale 1ns / 1ps

module tb_conv_accel;

    reg ACLK = 0, ARESETN = 0;
    reg  [5:0]  S_AXI_AWADDR = 0;  reg S_AXI_AWVALID = 0;  wire S_AXI_AWREADY;
    reg  [31:0] S_AXI_WDATA = 0;   reg [3:0] S_AXI_WSTRB = 4'b1111; reg S_AXI_WVALID = 0; wire S_AXI_WREADY;
    wire S_AXI_BVALID;  reg S_AXI_BREADY = 1;  wire [1:0] S_AXI_BRESP;
    reg  [5:0]  S_AXI_ARADDR = 0;  reg S_AXI_ARVALID = 0;  wire S_AXI_ARREADY;
    wire S_AXI_RVALID;  reg S_AXI_RREADY = 1;  wire [31:0] S_AXI_RDATA;  wire [1:0] S_AXI_RRESP;

    integer errors = 0;
    reg [31:0] res, st, a, b, c, d;

    conv_accel_axi_lite dut (
        .S_AXI_ACLK(ACLK), .S_AXI_ARESETN(ARESETN),
        .S_AXI_AWADDR(S_AXI_AWADDR), .S_AXI_AWVALID(S_AXI_AWVALID), .S_AXI_AWREADY(S_AXI_AWREADY),
        .S_AXI_WDATA(S_AXI_WDATA), .S_AXI_WSTRB(S_AXI_WSTRB), .S_AXI_WVALID(S_AXI_WVALID), .S_AXI_WREADY(S_AXI_WREADY),
        .S_AXI_BVALID(S_AXI_BVALID), .S_AXI_BREADY(S_AXI_BREADY), .S_AXI_BRESP(S_AXI_BRESP),
        .S_AXI_ARADDR(S_AXI_ARADDR), .S_AXI_ARVALID(S_AXI_ARVALID), .S_AXI_ARREADY(S_AXI_ARREADY),
        .S_AXI_RVALID(S_AXI_RVALID), .S_AXI_RREADY(S_AXI_RREADY), .S_AXI_RDATA(S_AXI_RDATA), .S_AXI_RRESP(S_AXI_RRESP)
    );

    always #5 ACLK = ~ACLK;   // 100 MHz

    // 一次写：地址+数据并行发，等双 READY，发 BVALID，接受后结束
    task write_reg(input [5:0] addr, input [31:0] data);
        begin
            @(posedge ACLK); #1;
            S_AXI_AWADDR = addr; S_AXI_AWVALID = 1;
            S_AXI_WDATA  = data; S_AXI_WVALID  = 1;
            while (!(S_AXI_AWREADY && S_AXI_WREADY)) @(posedge ACLK);
            @(posedge ACLK); #1;
            S_AXI_AWVALID = 0; S_AXI_WVALID = 0;
            while (!S_AXI_BVALID) @(posedge ACLK);
            @(posedge ACLK); #1;
        end
    endtask

    // 一次读：发 ARVALID，等 RVALID，取数据，释放
    task read_reg(input [5:0] addr, output [31:0] data);
        begin
            @(posedge ACLK); #1;
            S_AXI_ARADDR = addr; S_AXI_ARVALID = 1;
            while (!S_AXI_RVALID) @(posedge ACLK);
            data = S_AXI_RDATA;
            @(posedge ACLK); #1;
            S_AXI_ARVALID = 0;
            @(posedge ACLK); #1;
        end
    endtask

    initial begin
        #20 ARESETN = 1;
        // A=6,B=7,C=5,D=9 => result = 42 + 45 = 87
        write_reg(6'h00, 32'd6);
        write_reg(6'h04, 32'd7);
        write_reg(6'h08, 32'd5);
        write_reg(6'h0C, 32'd9);

        read_reg(6'h10, res);
        read_reg(6'h14, st);
        $display("RESULT = %0d (expect 87)", res);
        $display("STATUS = 0x%08X", st);

        if (res !== 87) begin errors = errors + 1; $display("[FAIL] mismatch"); end
        else              $display("[PASS] AXI MAC chain works");

        read_reg(6'h00,a); read_reg(6'h04,b); read_reg(6'h08,c); read_reg(6'h0C,d);
        $display("A=%0d B=%0d C=%0d D=%0d", a,b,c,d);

        if (errors == 0) $display("\n[TB] ALL PASS");
        else             $display("\n[TB] FAILED errors=%0d", errors);
        #30 $finish;
    end

endmodule
