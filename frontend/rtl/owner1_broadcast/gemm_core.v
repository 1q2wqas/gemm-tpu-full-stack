`default_nettype none
`include "accel.vh"

// Blocked GEMM controller for the simple broadcast-array implementation.
module gemm_core (
    input  wire clk,
    input  wire rst_n,

    input  wire core_start,
    output wire core_busy,
    output wire core_done,

    output reg  [`ACCEL_A_RD_ADDR_FLAT_W-1:0] a_rd_addr_flat,
    input  wire [`ACCEL_A_RD_DATA_FLAT_W-1:0] a_rd_data_flat,

    output reg  [`ACCEL_B_RD_ADDR_FLAT_W-1:0] b_rd_addr_flat,
    input  wire [`ACCEL_B_RD_DATA_FLAT_W-1:0] b_rd_data_flat,

    output reg                                c_wr_en,
    output reg  [`ACCEL_C_ADDR_W-1:0]          c_wr_addr,
    output reg  signed [`ACCEL_PSUM_W-1:0]    c_wr_data
);

    localparam integer TM    = `ACCEL_TM;
    localparam integer TN    = `ACCEL_TN;
    localparam integer K_MAX = `ACCEL_K_MAX;
    localparam integer P     = `ACCEL_P;

    localparam integer A_ADDR_W = `ACCEL_A_ADDR_W;
    localparam integer B_ADDR_W = `ACCEL_B_ADDR_W;

    // A tile is cleared, accumulated over K, then written back one lane at a time.
    localparam [2:0]
        ST_IDLE      = 3'd0,
        ST_BLK_CLEAR = 3'd1,
        ST_BLK_MAC   = 3'd2,
        ST_BLK_WB    = 3'd3,
        ST_BLK_NEXT  = 3'd4,
        ST_DONE      = 3'd5;

    reg [2:0] state, state_n;

    // m_base/n_base select the tile; k walks the shared reduction dimension.
    reg [3:0] m_base, m_base_n;
    reg [3:0] n_base, n_base_n;
    reg [3:0] k, k_n;
    reg [3:0] wb_i, wb_i_n;
    reg [3:0] wb_j, wb_j_n;

    // The array receives a one-cycle clear before each output tile.
    wire mac_clear = (state == ST_BLK_CLEAR);
    wire mac_step  = (state == ST_BLK_MAC);

    wire [`ACCEL_PSUM_FLAT_W-1:0] psum_flat;

    mac_array_pxp u_mac_array (
        .clk        (clk),
        .rst_n      (rst_n),
        .clear      (mac_clear),
        .step       (mac_step),
        .a_vec_flat (a_rd_data_flat),
        .b_vec_flat (b_rd_data_flat),
        .psum_flat  (psum_flat)
    );

    assign core_busy = (state != ST_IDLE) && (state != ST_DONE);
    assign core_done = (state == ST_DONE);

    always @(*) begin
        state_n  = state;
        m_base_n = m_base;
        n_base_n = n_base;
        k_n      = k;
        wb_i_n   = wb_i;
        wb_j_n   = wb_j;

        case (state)
            ST_IDLE: begin
                if (core_start) begin

                    m_base_n = 0;
                    n_base_n = 0;
                    k_n      = 0;
                    wb_i_n   = 0;
                    wb_j_n   = 0;
                    state_n  = ST_BLK_CLEAR;
                end
            end

            ST_BLK_CLEAR: begin

                k_n    = 0;
                wb_i_n = 0;
                wb_j_n = 0;
                state_n = ST_BLK_MAC;
            end

            ST_BLK_MAC: begin

                if (k == (K_MAX-1)) begin
                    k_n    = 0;
                    wb_i_n = 0;
                    wb_j_n = 0;
                    state_n = ST_BLK_WB;
                end else begin
                    k_n = k + 1'b1;
                end
            end

            ST_BLK_WB: begin

                // Walk the tile in row-major order to match the C memory layout.
                if (wb_j == (P-1)) begin
                    wb_j_n = 0;
                    if (wb_i == (P-1)) begin
                        wb_i_n  = 0;
                        state_n = ST_BLK_NEXT;
                    end else begin
                        wb_i_n = wb_i + 1'b1;
                    end
                end else begin
                    wb_j_n = wb_j + 1'b1;
                end
            end

            ST_BLK_NEXT: begin

                // N is the inner block loop; M advances after the row is complete.
                if ((n_base + P) < TN) begin
                    n_base_n = n_base + P;
                    state_n  = ST_BLK_CLEAR;
                end else begin
                    n_base_n = 0;
                    if ((m_base + P) < TM) begin
                        m_base_n = m_base + P;
                        state_n  = ST_BLK_CLEAR;
                    end else begin
                        state_n  = ST_DONE;
                    end
                end
            end

            ST_DONE: begin

                // done is a pulse because the next cycle returns to IDLE.
                state_n = ST_IDLE;
            end

            default: begin
                state_n = ST_IDLE;
            end
        endcase
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state  <= ST_IDLE;
            m_base <= 0;
            n_base <= 0;
            k      <= 0;
            wb_i   <= 0;
            wb_j   <= 0;
        end else begin
            state  <= state_n;
            m_base <= m_base_n;
            n_base <= n_base_n;
            k      <= k_n;
            wb_i   <= wb_i_n;
            wb_j   <= wb_j_n;
        end
    end

    integer t;
    reg [A_ADDR_W-1:0] a_addr_tmp;
    reg [B_ADDR_W-1:0] b_addr_tmp;

    always @(*) begin

        a_rd_addr_flat = {`ACCEL_A_RD_ADDR_FLAT_W{1'b0}};
        b_rd_addr_flat = {`ACCEL_B_RD_ADDR_FLAT_W{1'b0}};

        c_wr_en   = 1'b0;
        c_wr_addr = {`ACCEL_C_ADDR_W{1'b0}};
        c_wr_data = {`ACCEL_PSUM_W{1'b0}};

        if (state == ST_BLK_MAC) begin
            // Lane t reads A[m_base+t, k] and B[k, n_base+t].
            for (t = 0; t < P; t = t + 1) begin

                a_addr_tmp = (m_base + t) * K_MAX + k;
                a_rd_addr_flat[t*A_ADDR_W +: A_ADDR_W] = a_addr_tmp;

                b_addr_tmp = k * TN + (n_base + t);
                b_rd_addr_flat[t*B_ADDR_W +: B_ADDR_W] = b_addr_tmp;
            end
        end

        if (state == ST_BLK_WB) begin
            // The array exposes all lanes, so writeback is serialized here.
            c_wr_en   = 1'b1;
            c_wr_addr = (m_base + wb_i) * TN + (n_base + wb_j);
            c_wr_data = $signed(`ACCEL_PSUM_LANE(psum_flat, wb_i, wb_j));
        end
    end

endmodule

`default_nettype wire
