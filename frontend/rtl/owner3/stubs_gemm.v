`default_nettype none
`include "accel.vh"

// Minimal A loader used when verifying owner3 integration without owner2 RTL.
module stream_loader_A (
    input  wire                       clk,
    input  wire                       rst_n,
    input  wire                       a_valid,
    output wire                       a_ready,
    input  wire [`ACCEL_A_W-1:0]      a_data,
    output wire                       a_wr_en,
    output wire [`ACCEL_A_ADDR_W-1:0] a_wr_addr,
    output wire [`ACCEL_A_W-1:0]      a_wr_data,
    output reg                        a_loaded,
    input  wire                       clear_load
);
    localparam integer A_DEPTH = `ACCEL_A_DEPTH;
    localparam [`ACCEL_A_ADDR_W-1:0] A_LAST = A_DEPTH - 1;

    reg [`ACCEL_A_ADDR_W-1:0] cnt;

    assign a_ready   = ~a_loaded;
    assign a_wr_en   = a_valid & a_ready;
    assign a_wr_addr = cnt;
    assign a_wr_data = a_data;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cnt      <= {`ACCEL_A_ADDR_W{1'b0}};
            a_loaded <= 1'b0;
        end else if (clear_load) begin
            cnt      <= {`ACCEL_A_ADDR_W{1'b0}};
            a_loaded <= 1'b0;
        end else if (a_wr_en) begin
            if (cnt == A_LAST)
                a_loaded <= 1'b1;
            else
                cnt <= cnt + {{(`ACCEL_A_ADDR_W-1){1'b0}}, 1'b1};
        end
    end
endmodule

// B-side companion to the integration-test A loader above.
module stream_loader_B (
    input  wire                       clk,
    input  wire                       rst_n,
    input  wire                       b_valid,
    output wire                       b_ready,
    input  wire [`ACCEL_B_W-1:0]      b_data,
    output wire                       b_wr_en,
    output wire [`ACCEL_B_ADDR_W-1:0] b_wr_addr,
    output wire [`ACCEL_B_W-1:0]      b_wr_data,
    output reg                        b_loaded,
    input  wire                       clear_load
);
    localparam integer B_DEPTH = `ACCEL_B_DEPTH;
    localparam [`ACCEL_B_ADDR_W-1:0] B_LAST = B_DEPTH - 1;

    reg [`ACCEL_B_ADDR_W-1:0] cnt;

    assign b_ready   = ~b_loaded;
    assign b_wr_en   = b_valid & b_ready;
    assign b_wr_addr = cnt;
    assign b_wr_data = b_data;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cnt      <= {`ACCEL_B_ADDR_W{1'b0}};
            b_loaded <= 1'b0;
        end else if (clear_load) begin
            cnt      <= {`ACCEL_B_ADDR_W{1'b0}};
            b_loaded <= 1'b0;
        end else if (b_wr_en) begin
            if (cnt == B_LAST)
                b_loaded <= 1'b1;
            else
                cnt <= cnt + {{(`ACCEL_B_ADDR_W-1){1'b0}}, 1'b1};
        end
    end
endmodule

// Behavioral A memory with the same flattened P-lane interface as the real RAM.
module a_buf (
    input  wire                            clk,
    input  wire                            wr_en,
    input  wire [`ACCEL_A_ADDR_W-1:0]      wr_addr,
    input  wire [`ACCEL_A_W-1:0]           wr_data,
    input  wire [`ACCEL_A_RD_ADDR_FLAT_W-1:0] rd_addr_flat,
    output wire [`ACCEL_A_RD_DATA_FLAT_W-1:0] rd_data_flat
);
    localparam integer DEPTH = `ACCEL_A_DEPTH;
    reg [`ACCEL_A_W-1:0] mem [0:DEPTH-1];

    always @(posedge clk) begin
        if (wr_en)
            mem[wr_addr] <= wr_data;
    end

    genvar i;
    generate

        for (i = 0; i < `ACCEL_P; i = i + 1) begin : GEN_A_RD
            wire [`ACCEL_A_ADDR_W-1:0] addr_i;
            assign addr_i = `ACCEL_A_ADDR_LANE(rd_addr_flat, i);
            assign rd_data_flat[i*`ACCEL_A_W +: `ACCEL_A_W] = mem[addr_i];
        end
    endgenerate
endmodule

// Behavioral B memory used to keep top-level tests self-contained.
module b_buf (
    input  wire                            clk,
    input  wire                            wr_en,
    input  wire [`ACCEL_B_ADDR_W-1:0]      wr_addr,
    input  wire [`ACCEL_B_W-1:0]           wr_data,
    input  wire [`ACCEL_B_RD_ADDR_FLAT_W-1:0] rd_addr_flat,
    output wire [`ACCEL_B_RD_DATA_FLAT_W-1:0] rd_data_flat
);
    localparam integer DEPTH = `ACCEL_B_DEPTH;
    reg [`ACCEL_B_W-1:0] mem [0:DEPTH-1];

    always @(posedge clk) begin
        if (wr_en)
            mem[wr_addr] <= wr_data;
    end

    genvar i;
    generate

        for (i = 0; i < `ACCEL_P; i = i + 1) begin : GEN_B_RD
            wire [`ACCEL_B_ADDR_W-1:0] addr_i;
            assign addr_i = `ACCEL_B_ADDR_LANE(rd_addr_flat, i);
            assign rd_data_flat[i*`ACCEL_B_W +: `ACCEL_B_W] = mem[addr_i];
        end
    endgenerate
endmodule

module gemm_core (
    input  wire                                clk,
    input  wire                                rst_n,
    input  wire                                core_start,
    output reg                                 core_busy,
    output reg                                 core_done,
    output wire [`ACCEL_A_RD_ADDR_FLAT_W-1:0]  a_rd_addr_flat,
    input  wire [`ACCEL_A_RD_DATA_FLAT_W-1:0]  a_rd_data_flat,
    output wire [`ACCEL_B_RD_ADDR_FLAT_W-1:0]  b_rd_addr_flat,
    input  wire [`ACCEL_B_RD_DATA_FLAT_W-1:0]  b_rd_data_flat,
    output reg                                 c_row_valid,
    input  wire                                c_row_ready,
    output reg  [`ACCEL_C_ROW_FLAT_W-1:0]      c_row_data_flat,
    output reg  [`ACCEL_M_W-1:0]               c_m_base,
    output reg  [`ACCEL_N_W-1:0]               c_n_base,
    output reg  [`ACCEL_ROW_OFF_W-1:0]         c_row_off,
    output reg                                 c_row_last
);
    // This deterministic core isolates top-level sequencing from GEMM arithmetic.
    localparam integer P = `ACCEL_P;
    // PREP inserts launch latency; ROW emits deterministic rows for the unloader.
    localparam [1:0] ST_IDLE = 2'd0, ST_PREP = 2'd1, ST_ROW = 2'd2, ST_DONE = 2'd3;

    reg [1:0] state;
    reg [3:0] prep_cnt;
    reg [3:0] row_idx;
    integer lane;
    reg [`ACCEL_PSUM_W-1:0] lane_word;

    assign a_rd_addr_flat = {`ACCEL_A_RD_ADDR_FLAT_W{1'b0}};
    assign b_rd_addr_flat = {`ACCEL_B_RD_ADDR_FLAT_W{1'b0}};

    // Encode the row and lane in each word so ordering errors are easy to spot.
    always @(*) begin
        c_row_data_flat = {`ACCEL_C_ROW_FLAT_W{1'b0}};
        for (lane = 0; lane < P; lane = lane + 1) begin
            lane_word = {24'h0, row_idx[3:0], lane[3:0]};
            c_row_data_flat[(lane*`ACCEL_PSUM_W) +: `ACCEL_PSUM_W] = lane_word;
        end
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state      <= ST_IDLE;
            prep_cnt   <= 4'd0;
            row_idx    <= 4'd0;
            core_busy  <= 1'b0;
            core_done  <= 1'b0;
            c_row_valid <= 1'b0;
            c_m_base   <= {`ACCEL_M_W{1'b0}};
            c_n_base   <= {`ACCEL_N_W{1'b0}};
            c_row_off  <= {`ACCEL_ROW_OFF_W{1'b0}};
            c_row_last <= 1'b0;
        end else begin
            core_done <= 1'b0;

            case (state)
                ST_IDLE: begin
                    core_busy   <= 1'b0;
                    c_row_valid <= 1'b0;
                    if (core_start) begin
                        core_busy <= 1'b1;
                        prep_cnt  <= 4'd2;
                        row_idx   <= 4'd0;
                        state     <= ST_PREP;
                    end
                end

                ST_PREP: begin
                    if (prep_cnt != 0)
                        prep_cnt <= prep_cnt - 1'b1;
                    else begin
                        c_row_valid <= 1'b1;
                        c_m_base    <= {`ACCEL_M_W{1'b0}};
                        c_n_base    <= {`ACCEL_N_W{1'b0}};
                        c_row_off   <= {`ACCEL_ROW_OFF_W{1'b0}};
                        c_row_last  <= (P == 1);
                        state       <= ST_ROW;
                    end
                end

                ST_ROW: begin
                    c_row_off  <= row_idx[`ACCEL_ROW_OFF_W-1:0];
                    c_row_last <= (row_idx == (P-1));

                    // Keep row data and sideband stable until the transfer completes.
                    if (c_row_valid && c_row_ready) begin
                        if (row_idx == (P-1)) begin
                            c_row_valid <= 1'b0;
                            state       <= ST_DONE;
                        end else begin
                            row_idx <= row_idx + 1'b1;
                        end
                    end
                end

                ST_DONE: begin
                    core_busy <= 1'b0;
                    core_done <= 1'b1;
                    state     <= ST_IDLE;
                end

                default: begin
                    state <= ST_IDLE;
                end
            endcase
        end
    end
endmodule

// Lightweight scalar serializer for top-level sequencing tests.
module stream_unloader_C_b (
    input  wire                          clk,
    input  wire                          rst_n,
    input  wire                          c_row_valid,
    output wire                          c_row_ready,
    input  wire [`ACCEL_P*`ACCEL_PSUM_W-1:0] c_row_data_flat,
    input  wire [2:0]                    c_m_base,
    input  wire [2:0]                    c_n_base,
    input  wire [`ACCEL_ROW_OFF_W-1:0]   c_row_off,
    input  wire                          c_row_last,
    output wire                          c_valid,
    input  wire                          c_ready,
    output wire [5:0]                    c_addr,
    output wire [`ACCEL_PSUM_W-1:0]      c_data,
    output reg                           output_done
);
    localparam integer P = `ACCEL_P;

    // One accepted row is retained until all P scalar lanes leave.
    reg                                 ser_active;
    reg [`ACCEL_P*`ACCEL_PSUM_W-1:0]    hold_data;
    reg [2:0]                           hold_m_base;
    reg [2:0]                           hold_n_base;
    reg [`ACCEL_ROW_OFF_W-1:0]          hold_row_off;
    reg                                 hold_last;
    reg [3:0]                           lane_idx;

    // Accept one row at a time, then serialize it with normal ready-valid stalls.
    assign c_row_ready = ~ser_active;
    assign c_valid     = ser_active;
    assign c_data      = hold_data[(lane_idx*`ACCEL_PSUM_W) +: `ACCEL_PSUM_W];

    assign c_addr      = (({3'b000, hold_m_base} + {3'b000, hold_row_off}) << 3) +
                         {3'b000, hold_n_base} + {3'b000, lane_idx[2:0]};

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            ser_active   <= 1'b0;
            hold_data    <= {(`ACCEL_P*`ACCEL_PSUM_W){1'b0}};
            hold_m_base  <= 3'd0;
            hold_n_base  <= 3'd0;
            hold_row_off <= {`ACCEL_ROW_OFF_W{1'b0}};
            hold_last    <= 1'b0;
            lane_idx     <= 4'd0;
            output_done  <= 1'b0;
        end else begin
            output_done <= 1'b0;

            if (!ser_active && c_row_valid) begin
                // Capture the address sideband with the row so it survives stalls.
                hold_data    <= c_row_data_flat;
                hold_m_base  <= c_m_base;
                hold_n_base  <= c_n_base;
                hold_row_off <= c_row_off;
                hold_last    <= c_row_last;
                ser_active   <= 1'b1;
                lane_idx     <= 4'd0;
            end else if (ser_active && c_valid && c_ready) begin
                if (lane_idx == (P-1)) begin
                    ser_active  <= 1'b0;
                    lane_idx    <= 4'd0;
                    if (hold_last)
                        output_done <= 1'b1;
                end else begin
                    lane_idx <= lane_idx + 1'b1;
                end
            end
        end
    end
endmodule

`default_nettype wire
