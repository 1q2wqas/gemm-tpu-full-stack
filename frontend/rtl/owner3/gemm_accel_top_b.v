`default_nettype none
`include "accel.vh"

// Assemble loaders, operand RAMs, systolic core, and row serializer.
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

    output wire                         a_loaded_out,
    output wire                         b_loaded_out,

    input  wire                         start,
    input  wire                         clear,
    output wire                         start_accept,
    output wire                         busy,
    output wire                         done
);

// WAIT means both input buffers are full and the core may be started.
localparam [1:0]
    S_IDLE = 2'd0,
    S_WAIT = 2'd1,
    S_RUN  = 2'd2,
    S_DONE = 2'd3;

wire                                 core_start;
wire                                 core_busy;
wire                                 core_done;

wire [`ACCEL_A_RD_ADDR_FLAT_W-1:0]   a_rd_addr_flat;
wire [`ACCEL_B_RD_ADDR_FLAT_W-1:0]   b_rd_addr_flat;
wire [`ACCEL_A_RD_DATA_FLAT_W-1:0]   a_rd_data_flat;
wire [`ACCEL_B_RD_DATA_FLAT_W-1:0]   b_rd_data_flat;

wire                                 c_row_valid;
wire                                 c_row_ready;
wire [`ACCEL_C_ROW_FLAT_W-1:0]       c_row_data_flat;
wire [`ACCEL_M_W-1:0]                c_m_base;
wire [`ACCEL_N_W-1:0]                c_n_base;
wire [`ACCEL_ROW_OFF_W-1:0]          c_row_off;
wire                                 c_row_last;

wire [2:0]                           c_m_base_u;
wire [2:0]                           c_n_base_u;
wire [`ACCEL_ROW_OFF_W-1:0]          c_row_off_u;

wire                                 a_wr_en;
wire [`ACCEL_A_ADDR_W-1:0]           a_wr_addr;
wire [`ACCEL_A_W-1:0]                a_wr_data;

wire                                 b_wr_en;
wire [`ACCEL_B_ADDR_W-1:0]           b_wr_addr;
wire [`ACCEL_B_W-1:0]                b_wr_data;

wire                                 a_loaded;
wire                                 b_loaded;
wire                                 a_clear_load;
wire                                 b_clear_load;

// output_done arrives after the final C word has been accepted downstream.
wire                                 output_done;

reg [1:0]                            state;

gemm_core u_core (
    .clk                (clk),
    .rst_n              (rst_n),

    .core_start         (core_start),
    .core_busy          (core_busy),
    .core_done          (core_done),

    .a_rd_addr_flat     (a_rd_addr_flat),
    .a_rd_data_flat     (a_rd_data_flat),
    .b_rd_addr_flat     (b_rd_addr_flat),
    .b_rd_data_flat     (b_rd_data_flat),

    .c_row_valid        (c_row_valid),
    .c_row_ready        (c_row_ready),
    .c_row_data_flat    (c_row_data_flat),
    .c_m_base           (c_m_base),
    .c_n_base           (c_n_base),
    .c_row_off          (c_row_off),
    .c_row_last         (c_row_last)
);

a_buf u_a_buf (
    .clk                (clk),

    .wr_en              (a_wr_en),
    .wr_addr            (a_wr_addr),
    .wr_data            (a_wr_data),

    .rd_addr_flat       (a_rd_addr_flat),
    .rd_data_flat       (a_rd_data_flat)
);

b_buf u_b_buf (
    .clk                (clk),

    .wr_en              (b_wr_en),
    .wr_addr            (b_wr_addr),
    .wr_data            (b_wr_data),

    .rd_addr_flat       (b_rd_addr_flat),
    .rd_data_flat       (b_rd_data_flat)
);

stream_loader_A u_loader_a (
    .clk                (clk),
    .rst_n              (rst_n),

    .a_valid            (a_valid),
    .a_ready            (a_ready),
    .a_data             (a_data),

    .a_wr_en            (a_wr_en),
    .a_wr_addr          (a_wr_addr),
    .a_wr_data          (a_wr_data),

    .a_loaded           (a_loaded),
    .clear_load         (a_clear_load)
);

stream_loader_B u_loader_b (
    .clk                (clk),
    .rst_n              (rst_n),

    .b_valid            (b_valid),
    .b_ready            (b_ready),
    .b_data             (b_data),

    .b_wr_en            (b_wr_en),
    .b_wr_addr          (b_wr_addr),
    .b_wr_data          (b_wr_data),

    .b_loaded           (b_loaded),
    .clear_load         (b_clear_load)
);

stream_unloader_C_b u_unloader_c (
    .clk                (clk),
    .rst_n              (rst_n),

    .c_row_valid        (c_row_valid),
    .c_row_ready        (c_row_ready),
    .c_row_data_flat    (c_row_data_flat),
    .c_m_base           (c_m_base_u),
    .c_n_base           (c_n_base_u),
    .c_row_off          (c_row_off_u),
    .c_row_last         (c_row_last),

    .c_valid            (c_valid),
    .c_ready            (c_ready),
    .c_data             (c_data),
    .c_addr             (c_addr),
    .output_done        (output_done)
);

// The top-level FSM separates input loading, launch, execution, and retirement.
always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
        state <= S_IDLE;
    end else begin
        case (state)
            S_IDLE:
                if (a_loaded && b_loaded)
                    state <= S_WAIT;

            S_WAIT:
                if (start)
                    state <= S_RUN;

            S_RUN:
                // The last serialized C word, not core_done, ends the transaction.
                if (output_done)
                    state <= S_DONE;

            S_DONE:
                if (clear)
                    state <= S_IDLE;

            default:
                state <= S_IDLE;
        endcase
    end
end

// start_accept is a one-cycle launch handshake into gemm_core.
assign start_accept = (state == S_WAIT) && start;
assign core_start   = start_accept;

assign busy         = (state == S_WAIT) || (state == S_RUN);
assign done         = (state == S_DONE);

// Reuse the input buffers only after software acknowledges completion.
assign a_clear_load = (state == S_DONE) && clear;
assign b_clear_load = (state == S_DONE) && clear;

assign a_loaded_out = a_loaded;
assign b_loaded_out = b_loaded;

assign c_m_base_u  = c_m_base;
assign c_n_base_u  = c_n_base;
assign c_row_off_u = c_row_off;

endmodule

`default_nettype wire
