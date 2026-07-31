`default_nettype none
`include "accel.vh"

// Flow v2 PE mesh; lane alignment is handled by the core's read schedule.
module mac_array_pxp (
    input  wire                               clk,
    input  wire                               rst_n,
    input  wire                               clear,
    input  wire                               step,
    input  wire                               shift,

    input  wire [`ACCEL_A_VEC_W-1:0]          a_vec_flat,
    input  wire [`ACCEL_B_VEC_W-1:0]          b_vec_flat,

    output wire [`ACCEL_PSUM_ROW_FLAT_W-1:0]  psum_bottom_row_flat
`ifdef ACCEL_EXPORT_PSUM_FLAT
    ,
    output wire [`ACCEL_PSUM_FLAT_W-1:0]      psum_flat
`endif
);

    localparam integer P      = `ACCEL_P;
    localparam integer A_W    = `ACCEL_A_W;
    localparam integer B_W    = `ACCEL_B_W;
    localparam integer PSUM_W = `ACCEL_PSUM_W;

    wire shift_eff;
    wire step_eff;
    // These guards mirror the PE priority and keep controls unambiguous.
    assign shift_eff = shift & ~clear;
    assign step_eff  = step  & ~clear & ~shift;

    // These packed vectors are point-to-point links, not shared buses.
    wire signed [(P*P*A_W)-1:0]    a_out_flat;
    wire signed [(P*P*B_W)-1:0]    b_out_flat;
    wire signed [(P*P*PSUM_W)-1:0] psum_out_flat;

`ifdef ACCEL_EXPORT_PSUM_FLAT
    assign psum_flat = psum_out_flat;
`endif
    // Each accepted unload beat exposes the current bottom row.
    genvar gj;
    generate
        for (gj = 0; gj < P; gj = gj + 1) begin : gen_bottom_row
            assign psum_bottom_row_flat[(gj*PSUM_W) +: PSUM_W] =
                psum_out_flat[(((P-1)*P + gj)*PSUM_W) +: PSUM_W];
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

                // A moves right, B moves down, and psums move down on shift.
                if (j == 0) begin : gen_a_left

                    assign a_in_w = $signed(a_vec_flat[(i*A_W) +: A_W]);
                end else begin : gen_a_from_left

                    assign a_in_w = $signed(a_out_flat[(((i*P) + (j-1))*A_W) +: A_W]);
                end

                if (i == 0) begin : gen_b_top

                    assign b_in_w = $signed(b_vec_flat[(j*B_W) +: B_W]);
                end else begin : gen_b_from_top

                    assign b_in_w = $signed(b_out_flat[(((i-1)*P + j)*B_W) +: B_W]);
                end

                if (i == 0) begin : gen_psum_top

                    // Every column begins with a zero psum at the top edge.
                    assign psum_in_w = {PSUM_W{1'b0}};
                end else begin : gen_psum_from_above

                    assign psum_in_w = $signed(psum_out_flat[(((i-1)*P + j)*PSUM_W) +: PSUM_W]);
                end

                pe_mac u_pe (
                    .clk      (clk),
                    .rst_n    (rst_n),
                    .clear    (clear),
                    .step     (step_eff),
                    .shift    (shift_eff),
                    .a_in     (a_in_w),
                    .b_in     (b_in_w),
                    .psum_in  (psum_in_w),
                    .a_out    (a_out_flat[(IDX*A_W) +: A_W]),
                    .b_out    (b_out_flat[(IDX*B_W) +: B_W]),
                    .psum_out (psum_out_flat[(IDX*PSUM_W) +: PSUM_W])
                );
            end
        end
    endgenerate

endmodule

`default_nettype wire
