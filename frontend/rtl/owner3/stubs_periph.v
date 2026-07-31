`default_nettype none
`include "accel.vh"

// Deterministic accelerator model for Wishbone register and result-window tests.
module gemm_accel_top_b (
    input  wire                         clk,
    input  wire                         rst_n,

    input  wire                         a_valid,
    input  wire                         b_valid,
    output wire                         c_valid,

    output wire                         a_ready,
    output wire                         b_ready,
    input  wire                         c_ready,

    input  wire [`ACCEL_A_W-1:0]        a_data,
    input  wire [`ACCEL_B_W-1:0]        b_data,
    output wire [`ACCEL_PSUM_W-1:0]     c_data,

    output wire [`ACCEL_C_ADDR_W-1:0]   c_addr,

    output reg                          a_loaded_out,
    output reg                          b_loaded_out,

    input  wire                         start,
    input  wire                         clear,
    output wire                         start_accept,
    output wire                         busy,
    output reg                          done
);
    // This test double adds a first-beat stall and emits recognizable result words.
    localparam integer A_DEPTH = `ACCEL_A_DEPTH;
    localparam integer B_DEPTH = `ACCEL_B_DEPTH;
    localparam integer C_DEPTH = `ACCEL_C_DEPTH;
    localparam [`ACCEL_PSUM_W-1:0] RAW_WORD_BASE = 32'h1234_0000;

    reg [`ACCEL_A_ADDR_W-1:0] a_count;
    reg [`ACCEL_B_ADDR_W-1:0] b_count;
    reg [1:0]                 a_first_wait;
    reg [1:0]                 b_first_wait;
    reg                       a_first_done;
    reg                       b_first_done;

    // run_active drives a fixed 64-word result stream after a valid start.
    reg                       run_active;
    reg [`ACCEL_C_ADDR_W-1:0] out_addr;

    wire a_need_first_stall;
    wire b_need_first_stall;

    assign a_need_first_stall = (a_count == {`ACCEL_A_ADDR_W{1'b0}}) && !a_first_done;
    assign b_need_first_stall = (b_count == {`ACCEL_B_ADDR_W{1'b0}}) && !b_first_done;

    assign a_ready = (!a_loaded_out) && (!a_need_first_stall || a_first_done);
    assign b_ready = (!b_loaded_out) && (!b_need_first_stall || b_first_done);

    assign c_valid = run_active;
    assign c_addr  = out_addr;
    assign c_data  = RAW_WORD_BASE + out_addr;
    assign start_accept = !run_active && !done && start && a_loaded_out && b_loaded_out;
    assign busy    = run_active;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            a_count      <= {`ACCEL_A_ADDR_W{1'b0}};
            b_count      <= {`ACCEL_B_ADDR_W{1'b0}};
            a_loaded_out <= 1'b0;
            b_loaded_out <= 1'b0;
            a_first_wait <= 2'd0;
            b_first_wait <= 2'd0;
            a_first_done <= 1'b0;
            b_first_done <= 1'b0;
            run_active   <= 1'b0;
            out_addr     <= {`ACCEL_C_ADDR_W{1'b0}};
            done         <= 1'b0;
        end else begin
            if (clear) begin
                // Clear returns the model to the state before either input was loaded.
                a_count      <= {`ACCEL_A_ADDR_W{1'b0}};
                b_count      <= {`ACCEL_B_ADDR_W{1'b0}};
                a_loaded_out <= 1'b0;
                b_loaded_out <= 1'b0;
                a_first_wait <= 2'd0;
                b_first_wait <= 2'd0;
                a_first_done <= 1'b0;
                b_first_done <= 1'b0;
                run_active   <= 1'b0;
                out_addr     <= {`ACCEL_C_ADDR_W{1'b0}};
                done         <= 1'b0;
            end else begin
                if (!a_loaded_out && a_need_first_stall && a_valid) begin
                    if (a_first_wait == 2'd1)
                        a_first_done <= 1'b1;
                    else
                        a_first_wait <= a_first_wait + 2'd1;
                end

                if (!b_loaded_out && b_need_first_stall && b_valid) begin
                    if (b_first_wait == 2'd1)
                        b_first_done <= 1'b1;
                    else
                        b_first_wait <= b_first_wait + 2'd1;
                end

                if (a_valid && a_ready) begin
                    if (a_count == (A_DEPTH-1))
                        a_loaded_out <= 1'b1;
                    else
                        a_count <= a_count + {{(`ACCEL_A_ADDR_W-1){1'b0}}, 1'b1};
                end

                if (b_valid && b_ready) begin
                    if (b_count == (B_DEPTH-1))
                        b_loaded_out <= 1'b1;
                    else
                        b_count <= b_count + {{(`ACCEL_B_ADDR_W-1){1'b0}}, 1'b1};
                end

                if (start_accept) begin
                    run_active <= 1'b1;
                    out_addr   <= {`ACCEL_C_ADDR_W{1'b0}};
                end

                // c_valid remains asserted while c_ready stalls the current address.
                if (run_active && c_valid && c_ready) begin
                    if (out_addr == (C_DEPTH-1)) begin
                        run_active <= 1'b0;
                        done       <= 1'b1;
                    end else begin
                        out_addr <= out_addr + {{(`ACCEL_C_ADDR_W-1){1'b0}}, 1'b1};
                    end
                end
            end
        end
    end
endmodule

// Arithmetic stub that preserves the real post-processing handshake timing.
module requant_relu_b (
    input  wire         clk,
    input  wire         rst_n,

    input  wire         in_valid,
    output wire         in_ready,
    input  wire [5:0]   in_addr,
    input  wire [31:0]  in_data,

    input  wire         pp_en,
    input  wire         relu_en,
    input  wire [31:0]  mult,
    input  wire [5:0]   shift,

    output wire         out_valid,
    input  wire         out_ready,
    output wire [5:0]   out_addr,
    output wire [7:0]   out_q
);
    reg       vld_r;
    reg [5:0] addr_r;
    reg [7:0] q_r;

    // The peripheral test only needs backpressure behavior, not arithmetic fidelity.
    assign in_ready  = (~vld_r) | out_ready;
    assign out_valid = vld_r;
    assign out_addr  = addr_r;
    assign out_q     = q_r;

    wire fire_in  = in_valid & in_ready;
    wire fire_out = out_valid & out_ready;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            vld_r  <= 1'b0;
            addr_r <= 6'd0;
            q_r    <= 8'd0;
        end else begin
            if (fire_out && !fire_in)
                vld_r <= 1'b0;

            if (fire_in) begin
                // XOR data makes packed-byte ordering visible in peripheral tests.
                vld_r  <= 1'b1;
                addr_r <= in_addr;

                q_r    <= in_addr ^ 8'hA5;
            end
        end
    end
endmodule

// Fixed-latency pool stub for completion selection and result-view tests.
module maxpool2x2_b (
    input  wire        clk,
    input  wire        rst_n,

    input  wire        pool_en,
    input  wire        start_pool,
    output reg         pool_done,

    output wire [5:0]  q_rd_addr,
    input  wire [7:0]  q_rd_data,

    output reg         p_wr_en,
    output reg  [3:0]  p_wr_addr,
    output reg  [7:0]  p_wr_data
);
    // idx produces sixteen recognizable bytes while active is high.
    reg       active;
    reg [4:0] idx;
    reg       start_d;

    // Finish after a fixed delay so tests can check stage-dependent done timing.
    assign q_rd_addr = 6'd0;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            active    <= 1'b0;
            idx       <= 5'd0;
            start_d   <= 1'b0;
            pool_done <= 1'b0;
            p_wr_en   <= 1'b0;
            p_wr_addr <= 4'd0;
            p_wr_data <= 8'd0;
        end else begin
            start_d   <= start_pool;
            pool_done <= 1'b0;
            p_wr_en   <= 1'b0;

            if (!active) begin
                if (start_pool && !start_d) begin
                    if (!pool_en) begin
                        pool_done <= 1'b1;
                    end else begin
                        active <= 1'b1;
                        idx    <= 5'd0;
                    end
                end
            end else begin
                p_wr_en   <= 1'b1;
                p_wr_addr <= idx[3:0];
                p_wr_data <= 8'hC0 + idx[3:0];

                if (idx == 5'd15) begin
                    active    <= 1'b0;
                    pool_done <= 1'b1;
                end else begin
                    idx <= idx + 5'd1;
                end
            end
        end
    end
endmodule

`default_nettype wire
