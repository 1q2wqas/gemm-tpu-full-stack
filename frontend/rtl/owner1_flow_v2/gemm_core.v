`default_nettype none
`include "accel.vh"

// Flow v2 controller: pre-skew operands, compute one tile, then stream P rows.
module gemm_core (
    input  wire                                clk,
    input  wire                                rst_n,

    input  wire                                core_start,
    output wire                                core_busy,
    output wire                                core_done,

    output reg  [`ACCEL_A_RD_ADDR_FLAT_W-1:0]  a_rd_addr_flat,
    input  wire [`ACCEL_A_RD_DATA_FLAT_W-1:0]  a_rd_data_flat,

    output reg  [`ACCEL_B_RD_ADDR_FLAT_W-1:0]  b_rd_addr_flat,
    input  wire [`ACCEL_B_RD_DATA_FLAT_W-1:0]  b_rd_data_flat,

    output wire                                c_row_valid,
    input  wire                                c_row_ready,
    output wire [`ACCEL_C_ROW_FLAT_W-1:0]      c_row_data_flat,
    output wire [`ACCEL_M_W-1:0]               c_m_base,
    output wire [`ACCEL_N_W-1:0]               c_n_base,
    output wire [`ACCEL_ROW_OFF_W-1:0]         c_row_off,
    output wire                                c_row_last
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
        ST_IDLE       = 3'd0,
        ST_BLK_CLEAR  = 3'd1,
        ST_BLK_MAC    = 3'd2,
        ST_BLK_UNLOAD = 3'd3,
        ST_BLK_NEXT   = 3'd4,
        ST_DONE       = 3'd5;

    reg [2:0] state, state_n;

    // Tile coordinates remain stable through MAC and UNLOAD.
    reg [`ACCEL_M_W-1:0]        m_base, m_base_n;
    reg [`ACCEL_N_W-1:0]        n_base, n_base_n;
    reg [`ACCEL_MAC_T_W-1:0]    mac_t, mac_t_n;
    reg [`ACCEL_UNLOAD_T_W-1:0] unload_cnt, unload_cnt_n;

    wire mac_clear;
    wire mac_step;
    reg  mac_shift;
    wire unload_fire;

    assign mac_clear = (state == ST_BLK_CLEAR);
    assign mac_step  = (state == ST_BLK_MAC);

    assign c_row_valid = (state == ST_BLK_UNLOAD);

    // Do not advance the bottom row until the receiver accepts it.
    always @(*) begin
        mac_shift = 1'b0;
        if ((state == ST_BLK_UNLOAD) && c_row_ready)
            mac_shift = 1'b1;
    end

    assign unload_fire = mac_shift;

    // Valid masks suppress lanes outside the diagonal wavefront.
    reg [P-1:0] inject_a_valid;
    reg [P-1:0] inject_b_valid;

    reg [`ACCEL_A_VEC_W-1:0] a_in_flat;
    reg [`ACCEL_B_VEC_W-1:0] b_in_flat;

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

    // Rows emerge bottom-first from the vertical psum chain.
    assign row_off_calc = (P-1) - unload_cnt;
    assign c_row_off = (state == ST_BLK_UNLOAD) ? row_off_calc
                                                : {`ACCEL_ROW_OFF_W{1'b0}};

    wire last_block;
    wire last_row_in_block;

    assign last_block = (((n_base + P) >= TN) && ((m_base + P) >= TM));
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

                // Clear occupies a full cycle before the first scheduled operands.
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

                // Keep N as the inner block loop for row-major traversal.
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

                // done is intentionally a single-cycle state.
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
    integer k_eff_a;
    integer k_eff_b;
    reg [A_ADDR_W-1:0] a_addr_tmp;
    reg [B_ADDR_W-1:0] b_addr_tmp;

    always @(*) begin
        a_rd_addr_flat = {`ACCEL_A_RD_ADDR_FLAT_W{1'b0}};
        b_rd_addr_flat = {`ACCEL_B_RD_ADDR_FLAT_W{1'b0}};
        a_in_flat      = {`ACCEL_A_VEC_W{1'b0}};
        b_in_flat      = {`ACCEL_B_VEC_W{1'b0}};
        inject_a_valid = {P{1'b0}};
        inject_b_valid = {P{1'b0}};
        a_addr_tmp     = {A_ADDR_W{1'b0}};
        b_addr_tmp     = {B_ADDR_W{1'b0}};
        k_eff_a        = 0;
        k_eff_b        = 0;

        if (state == ST_BLK_MAC) begin

            for (t = 0; t < P; t = t + 1) begin

                // Pre-skew lane t in the address schedule instead of using delay registers.
                k_eff_a = mac_t - t;
                if ((mac_t >= t) && (k_eff_a < K_MAX)) begin
                    inject_a_valid[t] = 1'b1;
                    a_addr_tmp = `ACCEL_ADDR_A((m_base + t), k_eff_a);
                end else begin
                    inject_a_valid[t] = 1'b0;
                    a_addr_tmp = {A_ADDR_W{1'b0}};
                end
                a_rd_addr_flat[(t*A_ADDR_W) +: A_ADDR_W] = a_addr_tmp;

                k_eff_b = mac_t - t;
                if ((mac_t >= t) && (k_eff_b < K_MAX)) begin
                    inject_b_valid[t] = 1'b1;
                    b_addr_tmp = `ACCEL_ADDR_B(k_eff_b, (n_base + t));
                end else begin
                    inject_b_valid[t] = 1'b0;
                    b_addr_tmp = {B_ADDR_W{1'b0}};
                end
                b_rd_addr_flat[(t*B_ADDR_W) +: B_ADDR_W] = b_addr_tmp;

                // Invalid lanes stay zero while the wavefront fills and drains.
                if (inject_a_valid[t]) begin
                    a_in_flat[(t*`ACCEL_A_W) +: `ACCEL_A_W] =
                        a_rd_data_flat[(t*`ACCEL_A_W) +: `ACCEL_A_W];
                end
                if (inject_b_valid[t]) begin
                    b_in_flat[(t*`ACCEL_B_W) +: `ACCEL_B_W] =
                        b_rd_data_flat[(t*`ACCEL_B_W) +: `ACCEL_B_W];
                end
            end
        end
    end

endmodule

`default_nettype wire
