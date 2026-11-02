// tb_conv2d_accel.v —— 验证 4x4 x 3x3 -> 2x2 卷积
// image[i]=i (0..15), kernel 全1 -> out = 每个 3x3 窗口求和
`timescale 1ns / 1ps
module tb_conv2d_accel;
    reg ACLK=0, ARESETN=0;
    reg  [7:0]  S_AXI_AWADDR=0; reg S_AXI_AWVALID=0; wire S_AXI_AWREADY;
    reg  [31:0] S_AXI_WDATA=0;  reg [3:0] S_AXI_WSTRB=4'hF; reg S_AXI_WVALID=0; wire S_AXI_WREADY;
    wire S_AXI_BVALID; reg S_AXI_BREADY=1; wire [1:0] S_AXI_BRESP;
    reg  [7:0]  S_AXI_ARADDR=0; reg S_AXI_ARVALID=0; wire S_AXI_ARREADY;
    wire S_AXI_RVALID; reg S_AXI_RREADY=1; wire [31:0] S_AXI_RDATA; wire [1:0] S_AXI_RRESP;

    integer errors=0, i;
    reg [31:0] val, st;
    // 期望值：out[0..3] = 3x3 窗口和
    reg [31:0] exp[0:3];

    conv2d_accel dut (
        .S_AXI_ACLK(ACLK), .S_AXI_ARESETN(ARESETN),
        .S_AXI_AWADDR(S_AXI_AWADDR), .S_AXI_AWVALID(S_AXI_AWVALID), .S_AXI_AWREADY(S_AXI_AWREADY),
        .S_AXI_WDATA(S_AXI_WDATA), .S_AXI_WSTRB(S_AXI_WSTRB), .S_AXI_WVALID(S_AXI_WVALID), .S_AXI_WREADY(S_AXI_WREADY),
        .S_AXI_BVALID(S_AXI_BVALID), .S_AXI_BREADY(S_AXI_BREADY), .S_AXI_BRESP(S_AXI_BRESP),
        .S_AXI_ARADDR(S_AXI_ARADDR), .S_AXI_ARVALID(S_AXI_ARVALID), .S_AXI_ARREADY(S_AXI_ARREADY),
        .S_AXI_RVALID(S_AXI_RVALID), .S_AXI_RREADY(S_AXI_RREADY), .S_AXI_RDATA(S_AXI_RDATA), .S_AXI_RRESP(S_AXI_RRESP)
    );
    always #5 ACLK = ~ACLK;

    task write_reg(input [7:0] addr, input [31:0] data);
        begin
            @(posedge ACLK); #1;
            S_AXI_AWADDR=addr; S_AXI_AWVALID=1; S_AXI_WDATA=data; S_AXI_WVALID=1;
            while (!(S_AXI_AWREADY && S_AXI_WREADY)) @(posedge ACLK);
            @(posedge ACLK); #1; S_AXI_AWVALID=0; S_AXI_WVALID=0;
            while (!S_AXI_BVALID) @(posedge ACLK);
            @(posedge ACLK); #1;
        end
    endtask
    task read_reg(input [7:0] addr, output [31:0] data);
        begin
            @(posedge ACLK); #1;
            S_AXI_ARADDR=addr; S_AXI_ARVALID=1;
            while (!S_AXI_RVALID) @(posedge ACLK);
            data = S_AXI_RDATA;
            @(posedge ACLK); #1; S_AXI_ARVALID=0;
            @(posedge ACLK); #1;
        end
    endtask

    initial begin
        // 期望值
        exp[0]=45; exp[1]=54; exp[2]=81; exp[3]=90;
        #20 ARESETN=1;
        for (i=0;i<16;i=i+1) write_reg(i*4, i);            // img[0..15] = 0..15
        for (i=0;i<9;i=i+1)  write_reg(8'h40 + i*4, 1);    // kern 全1
        write_reg(8'h90, 1);                                // start
        begin
            st=0;
            for (i=0;i<100;i=i+1) begin read_reg(8'h90, st); if (st[1]) i=100; #20; end
        end
        for (i=0;i<4;i=i+1) begin
            read_reg(8'h80 + i*4, val);
            $display("out[%0d]=%0d expect %0d", i, val, exp[i]);
            if (val !== exp[i]) errors = errors + 1;
        end
        $display("errors=%0d", errors);
        if (errors==0) $display("==> [TB] ALL PASS (4x4 conv)");
        else           $display("==> [TB] FAILED");
        #30 $finish;
    end
endmodule
