`default_nettype none
`include "accel.vh"

// Tile scheduler for the boundary-skewed Flow v1 systolic array.
module gemm_core (
    input  wire                               clk,
    input  wire                               rst_n,

    input  wire                               core_start,
    output wire                               core_busy,
    output wire                               core_done,

    output reg  [`ACCEL_A_RD_ADDR_FLAT_W-1:0]  a_rd_addr_flat,
    input  wire [`ACCEL_A_RD_DATA_FLAT_W-1:0]  a_rd_data_flat,

    output reg  [`ACCEL_B_RD_ADDR_FLAT_W-1:0]  b_rd_addr_flat,
    input  wire [`ACCEL_B_RD_DATA_FLAT_W-1:0]  b_rd_data_flat,

    output wire                               c_row_valid,
    input  wire                               c_row_ready,
    output wire [`ACCEL_C_ROW_FLAT_W-1:0]      c_row_data_flat,
    output wire [`ACCEL_M_W-1:0]               c_m_base,
    output wire [`ACCEL_N_W-1:0]               c_n_base,
    output wire [`ACCEL_ROW_OFF_W-1:0]         c_row_off,
    output wire                               c_row_last
);

    localparam integer TM            = `ACCEL_TM;
    localparam integer TN            = `ACCEL_TN;
    localparam integer K_MAX         = `ACCEL_K_MAX;
    localparam integer P             = `ACCEL_P;
    localparam integer MAC_CYCLES    = `ACCEL_MAC_CYCLES;
    localparam integer UNLOAD_CYCLES = `ACCEL_UNLOAD_CYCLES;

    localparam integer A_ADDR_W      = `ACCEL_A_ADDR_W;
    localparam integer B_ADDR_W      = `ACCEL_B_ADDR_W;

    localparam [2:0]
        ST_IDLE      = 3'd0,
        ST_BLK_CLEAR = 3'd1,
        ST_BLK_MAC   = 3'd2,
        ST_BLK_UNLOAD= 3'd3,
        ST_BLK_NEXT  = 3'd4,
        ST_DONE      = 3'd5;

    reg [2:0] state, state_n;

    reg [`ACCEL_M_W-1:0] m_base, m_base_n;
    reg [`ACCEL_N_W-1:0] n_base, n_base_n;

    // mac_t covers input injection plus wavefront fill and drain cycles.
    reg [`ACCEL_MAC_T_W-1:0] mac_t, mac_t_n;

    // unload_cnt advances only when the row handshake completes.
    reg [`ACCEL_UNLOAD_T_W-1:0] unload_cnt, unload_cnt_n;

    wire mac_clear = (state == ST_BLK_CLEAR);
    wire mac_step  = (state == ST_BLK_MAC);

    assign c_row_valid = (state == ST_BLK_UNLOAD);
    // A stalled consumer must also stop the psum chain.
    wire unload_fire   = c_row_valid & c_row_ready;

    wire mac_shift = unload_fire;

    // Extra MAC cycles flush the array, so only the first K cycles read operands.
    wire inject_valid = (state == ST_BLK_MAC) && (mac_t < K_MAX);

    wire [`ACCEL_A_VEC_W-1:0] a_in_flat = inject_valid ? a_rd_data_flat
                                                       : {`ACCEL_A_VEC_W{1'b0}};
    wire [`ACCEL_B_VEC_W-1:0] b_in_flat = inject_valid ? b_rd_data_flat
                                                       : {`ACCEL_B_VEC_W{1'b0}};

    wire [`ACCEL_PSUM_ROW_FLAT_W-1:0] psum_bottom_row_flat;

`ifdef ACCEL_EXPORT_PSUM_FLAT
    wire [`ACCEL_PSUM_FLAT_W-1:0] psum_flat;
`endif

    mac_array_pxp u_mac_array (
        .clk                  (clk),
        .rst_n                (rst_n),
        .clear                (mac_clear),
        .step                 (mac_step),
        .shift                (mac_shift),
        .a_vec_flat           (a_in_flat),
        .b_vec_flat           (b_in_flat),
        .psum_bottom_row_flat (psum_bottom_row_flat)
`ifdef ACCEL_EXPORT_PSUM_FLAT
        ,
        .psum_flat            (psum_flat)
`endif
    );

    assign c_row_data_flat = (state == ST_BLK_UNLOAD) ? psum_bottom_row_flat
                                                      : {`ACCEL_C_ROW_FLAT_W{1'b0}};

    assign c_m_base = (state == ST_BLK_UNLOAD) ? m_base : {`ACCEL_M_W{1'b0}};
    assign c_n_base = (state == ST_BLK_UNLOAD) ? n_base : {`ACCEL_N_W{1'b0}};

    wire [`ACCEL_ROW_OFF_W-1:0] row_off_calc;
    // The bottom row appears first, hence the descending row offset.
    assign row_off_calc = (P-1) - unload_cnt;

    assign c_row_off = (state == ST_BLK_UNLOAD) ? row_off_calc
                                                : {`ACCEL_ROW_OFF_W{1'b0}};

    wire last_block;
    assign last_block = (((n_base + P) >= TN) && ((m_base + P) >= TM));

    wire last_row_in_block;
    assign last_row_in_block = (unload_cnt == (P-1));

    assign c_row_last = (state == ST_BLK_UNLOAD) && last_block && last_row_in_block;

    assign core_busy = (state != ST_IDLE);
    assign core_done = (state == ST_DONE);

    always @(*) begin
        state_n      = state;
        m_base_n     = m_base;
        n_base_n     = n_base;
        mac_t_n      = mac_t;
        unload_cnt_n = unload_cnt;

        case (state)
            ST_IDLE: begin
                if (core_start) begin
                    m_base_n     = {`ACCEL_M_W{1'b0}};
                    n_base_n     = {`ACCEL_N_W{1'b0}};
                    mac_t_n      = {`ACCEL_MAC_T_W{1'b0}};
                    unload_cnt_n = {`ACCEL_UNLOAD_T_W{1'b0}};
                    state_n      = ST_BLK_CLEAR;
                end
            end

            ST_BLK_CLEAR: begin

                mac_t_n      = {`ACCEL_MAC_T_W{1'b0}};
                unload_cnt_n = {`ACCEL_UNLOAD_T_W{1'b0}};
                state_n      = ST_BLK_MAC;
            end

            ST_BLK_MAC: begin
                if (mac_t == (MAC_CYCLES-1)) begin
                    mac_t_n      = {`ACCEL_MAC_T_W{1'b0}};
                    unload_cnt_n = {`ACCEL_UNLOAD_T_W{1'b0}};
                    state_n      = ST_BLK_UNLOAD;
                end else begin
                    mac_t_n = mac_t + 1'b1;
                end
            end

            ST_BLK_UNLOAD: begin

                if (unload_fire) begin
                    if (unload_cnt == (UNLOAD_CYCLES-1)) begin
                        unload_cnt_n = {`ACCEL_UNLOAD_T_W{1'b0}};
                        state_n      = ST_BLK_NEXT;
                    end else begin
                        unload_cnt_n = unload_cnt + 1'b1;
                    end
                end
            end

            ST_BLK_NEXT: begin

                // Sweep N inside M so output blocks remain row-major.
                if ((n_base + P) < TN) begin
                    n_base_n = n_base + P;
                    state_n  = ST_BLK_CLEAR;
                end else begin
                    n_base_n = {`ACCEL_N_W{1'b0}};
                    if ((m_base + P) < TM) begin
                        m_base_n = m_base + P;
                        state_n  = ST_BLK_CLEAR;
                    end else begin
                        state_n  = ST_DONE;
                    end
                end
            end

            ST_DONE: begin

                // Present done for one cycle before accepting a new start.
                state_n = ST_IDLE;
            end

            default: begin
                state_n = ST_IDLE;
            end
        endcase
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state      <= ST_IDLE;
            m_base     <= {`ACCEL_M_W{1'b0}};
            n_base     <= {`ACCEL_N_W{1'b0}};
            mac_t      <= {`ACCEL_MAC_T_W{1'b0}};
            unload_cnt <= {`ACCEL_UNLOAD_T_W{1'b0}};
        end else begin
            state      <= state_n;
            m_base     <= m_base_n;
            n_base     <= n_base_n;
            mac_t      <= mac_t_n;
            unload_cnt <= unload_cnt_n;
        end
    end

    integer t;
    reg [A_ADDR_W-1:0] a_addr_tmp;
    reg [B_ADDR_W-1:0] b_addr_tmp;

    always @(*) begin
        a_rd_addr_flat = {`ACCEL_A_RD_ADDR_FLAT_W{1'b0}};
        b_rd_addr_flat = {`ACCEL_B_RD_ADDR_FLAT_W{1'b0}};
        a_addr_tmp     = {A_ADDR_W{1'b0}};
        b_addr_tmp     = {B_ADDR_W{1'b0}};

        if (state == ST_BLK_MAC && (mac_t < K_MAX)) begin
            // Boundary skew registers handle lane alignment after these reads.
            for (t = 0; t < P; t = t + 1) begin

                a_addr_tmp = `ACCEL_ADDR_A((m_base + t), mac_t);
                a_rd_addr_flat[(t*A_ADDR_W) +: A_ADDR_W] = a_addr_tmp;

                b_addr_tmp = `ACCEL_ADDR_B(mac_t, (n_base + t));
                b_rd_addr_flat[(t*B_ADDR_W) +: B_ADDR_W] = b_addr_tmp;
            end
        end
    end

endmodule

`default_nettype wire
