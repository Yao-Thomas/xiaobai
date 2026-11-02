`timescale 1ns / 1ps

module tb_scope_dual_core;
    reg sample_clk = 1'b0;
    reg rd_clk = 1'b0;
    reg rst_n = 1'b0;
    always #25 sample_clk = ~sample_clk; // 20 MHz
    always #5  rd_clk = ~rd_clk;         // 100 MHz

    reg start_pulse = 0;
    reg stop_pulse = 0;
    reg [15:0] cfg_decimation = 1;
    reg [9:0] cfg_trigger_level = 10'd512;
    reg cfg_trigger_edge = 0;
    reg [1:0] cfg_trigger_mode = 0;
    reg cfg_trigger_channel = 0;
    reg [11:0] cfg_pretrigger = 12'd64;
    reg [9:0] adc1_data = 0;
    reg [9:0] adc2_data = 10'd100;

    wire busy, done, triggered, completed_bank;
    wire [11:0] start_addr;
    wire [12:0] write_total;
    wire [31:0] frame_sequence;
    reg [12:0] rd_addr = 0;
    wire [19:0] rd_data;

    scope_dual_core dut (
        .sample_clk(sample_clk), .rst_n(rst_n),
        .start_pulse(start_pulse), .stop_pulse(stop_pulse),
        .cfg_decimation(cfg_decimation),
        .cfg_trigger_level(cfg_trigger_level),
        .cfg_trigger_edge(cfg_trigger_edge),
        .cfg_trigger_mode(cfg_trigger_mode),
        .cfg_trigger_channel(cfg_trigger_channel),
        .cfg_pretrigger(cfg_pretrigger),
        .adc1_data(adc1_data), .adc2_data(adc2_data),
        .busy(busy), .done(done), .triggered(triggered),
        .completed_bank(completed_bank), .start_addr(start_addr),
        .write_total(write_total), .frame_sequence(frame_sequence),
        .rd_clk(rd_clk), .rd_addr(rd_addr), .rd_data(rd_data)
    );

    always @(posedge sample_clk) begin
        if (rst_n) begin
            adc1_data <= adc1_data + 10'd1;
            adc2_data <= adc2_data + 10'd3;
        end
    end

    task pulse_start;
    begin
        @(negedge sample_clk);
        start_pulse = 1'b1;
        @(negedge sample_clk);
        start_pulse = 1'b0;
    end
    endtask

    task wait_done_with_timeout;
        integer cycles;
    begin
        cycles = 0;
        while (!done && cycles < 20000) begin
            @(posedge sample_clk);
            cycles = cycles + 1;
        end
        if (!done) begin
            $display("FAIL: capture timed out");
            $fatal(1);
        end
    end
    endtask

    task check_frame;
        input [31:0] expected_sequence;
    begin
        if (write_total !== 13'd4096) begin
            $display("FAIL: write_total=%0d", write_total);
            $fatal(1);
        end
        if (!triggered) begin
            $display("FAIL: triggered flag not set");
            $fatal(1);
        end
        if (frame_sequence !== expected_sequence) begin
            $display("FAIL: frame_sequence=%0d expected=%0d",
                     frame_sequence, expected_sequence);
            $fatal(1);
        end
        rd_addr = {completed_bank, start_addr};
        repeat (3) @(posedge rd_clk);
        if (^rd_data === 1'bx) begin
            $display("FAIL: BRAM read returned X");
            $fatal(1);
        end
    end
    endtask

    initial begin
        repeat (5) @(posedge sample_clk);
        rst_n = 1'b1;
        repeat (3) @(posedge sample_clk);

        // Auto mode: proves timeout trigger and a complete circular frame.
        cfg_trigger_mode = 2'd0;
        cfg_pretrigger = 12'd2048;
        cfg_trigger_level = 10'd1023; // no rising crossing in the sawtooth
        pulse_start();
        wait_done_with_timeout();
        check_frame(32'd1);

        // Normal mode: rising edge on channel 1 with 64 pre-trigger samples.
        cfg_trigger_mode = 2'd1;
        cfg_pretrigger = 12'd64;
        cfg_trigger_level = 10'd512;
        cfg_trigger_edge = 1'b0;
        cfg_trigger_channel = 1'b0;
        pulse_start();
        wait_done_with_timeout();
        check_frame(32'd2);

        if (completed_bank !== 1'b1) begin
            $display("FAIL: double buffer did not alternate banks");
            $fatal(1);
        end

        $display("PASS: dual-channel auto/normal trigger, BRAM and bank swap");
        $finish;
    end
endmodule
