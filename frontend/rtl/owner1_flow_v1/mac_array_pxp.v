`default_nettype none
`include "accel.vh"

// Flow v1 array; boundary delay registers create the diagonal input wavefront.
module mac_array_pxp (
    input  wire                         clk,
    input  wire                         rst_n,
    input  wire                         clear,
    input  wire                         step,
    input  wire                         shift,

    input  wire [`ACCEL_A_VEC_W-1:0]     a_vec_flat,
    input  wire [`ACCEL_B_VEC_W-1:0]     b_vec_flat,

    output wire [`ACCEL_PSUM_ROW_FLAT_W-1:0] psum_bottom_row_flat
`ifdef ACCEL_EXPORT_PSUM_FLAT
    ,
    output wire [`ACCEL_PSUM_FLAT_W-1:0] psum_flat
`endif
);

    localparam integer P      = `ACCEL_P;
    localparam integer A_W    = `ACCEL_A_W;
    localparam integer B_W    = `ACCEL_B_W;
    localparam integer PSUM_W = `ACCEL_PSUM_W;

    wire step_eff;
    wire shift_eff;
    // Clear, unload, and compute are mutually exclusive at every PE.
    assign shift_eff = shift & ~clear;
    assign step_eff  = step  & ~clear & ~shift;

    // Lane t is delayed by t cycles before entering the array boundary.
    reg signed [A_W-1:0] a_skew [0:(P*P)-1];
    reg signed [B_W-1:0] b_skew [0:(P*P)-1];

    // The flattened P x P delay banks use row-major indices.
    integer t;
    integer r;
    integer s;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            for (t = 0; t < (P*P); t = t + 1) begin
                a_skew[t] <= {A_W{1'b0}};
                b_skew[t] <= {B_W{1'b0}};
            end
        end else if (clear) begin
            for (t = 0; t < (P*P); t = t + 1) begin
                a_skew[t] <= {A_W{1'b0}};
                b_skew[t] <= {B_W{1'b0}};
            end
        end else if (step_eff) begin

            // Shift each boundary lane once per compute cycle.
            for (r = 0; r < P; r = r + 1) begin
                a_skew[r*P + 0] <= a_vec_flat[r*A_W +: A_W];
                for (s = 1; s < P; s = s + 1) begin
                    a_skew[r*P + s] <= a_skew[r*P + (s-1)];
                end
            end

            for (r = 0; r < P; r = r + 1) begin
                b_skew[r*P + 0] <= b_vec_flat[r*B_W +: B_W];
                for (s = 1; s < P; s = s + 1) begin
                    b_skew[r*P + s] <= b_skew[r*P + (s-1)];
                end
            end
        end

    end

    wire signed [(P*P*A_W)-1:0]    a_out_flat;
    wire signed [(P*P*B_W)-1:0]    b_out_flat;
    wire signed [(P*P*PSUM_W)-1:0] psum_out_flat;

`ifdef ACCEL_EXPORT_PSUM_FLAT
    assign psum_flat = psum_out_flat;
`endif

    // Completed rows leave through the bottom edge during unload.
    genvar jj;
    generate
        for (jj = 0; jj < P; jj = jj + 1) begin : gen_bottom_row
            assign psum_bottom_row_flat[(jj*PSUM_W) +: PSUM_W] =
                psum_out_flat[(((P-1)*P + jj)*PSUM_W) +: PSUM_W];
        end
    endgenerate

    genvar i, j;
    generate
        for (i = 0; i < P; i = i + 1) begin : gen_row
            for (j = 0; j < P; j = j + 1) begin : gen_col
                localparam integer IDX = (i*P + j);

                wire signed [A_W-1:0]    a_in_w;
                wire signed [B_W-1:0]    b_in_w;
                wire signed [PSUM_W-1:0] psum_in_w;

                // A travels right, B travels down, and psums drain downward.
                if (j == 0) begin : gen_a_left
                    assign a_in_w = a_skew[i*P + i];
                end else begin : gen_a_from_left
                    assign a_in_w = a_out_flat[(((i*P) + (j-1))*A_W) +: A_W];
                end

                if (i == 0) begin : gen_b_top
                    assign b_in_w = b_skew[j*P + j];
                end else begin : gen_b_from_top
                    assign b_in_w = b_out_flat[(((i-1)*P + j)*B_W) +: B_W];
                end

                if (i == 0) begin : gen_psum_top
                    // The top row starts a fresh vertical accumulation chain.
                    assign psum_in_w = {PSUM_W{1'b0}};
                end else begin : gen_psum_from_above
                    assign psum_in_w = psum_out_flat[(((i-1)*P + j)*PSUM_W) +: PSUM_W];
                end

                pe_mac u_pe (
                    .clk     (clk),
                    .rst_n    (rst_n),
                    .clear   (clear),
                    .step    (step_eff),
                    .shift   (shift_eff),
                    .a_in    (a_in_w),
                    .b_in    (b_in_w),
                    .psum_in (psum_in_w),
                    .a_out   (a_out_flat[IDX*A_W +: A_W]),
                    .b_out   (b_out_flat[IDX*B_W +: B_W]),
                    .psum_out(psum_out_flat[IDX*PSUM_W +: PSUM_W])
                );

            end
        end
    endgenerate

endmodule

`default_nettype wire
