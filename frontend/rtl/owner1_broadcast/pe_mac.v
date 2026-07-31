`default_nettype none

`include "accel.vh"

// Combinational MAC used by one cell of the broadcast array.
module pe_mac (
    input wire signed [`ACCEL_A_W-1:0] a,
    input wire signed [`ACCEL_B_W-1:0] b,
    input wire signed [`ACCEL_PSUM_W-1:0] psum_in,
    output wire signed [`ACCEL_PSUM_W-1:0] psum_out
);

    // Keep the multiply signed before widening it into the accumulator.
    wire signed [`ACCEL_PROD_W-1:0] prod;
    assign prod = $signed(a) * $signed(b);

    wire signed [`ACCEL_PSUM_W-1:0] prod_extend;
    assign prod_extend = $signed({{(`ACCEL_PSUM_W - `ACCEL_PROD_W){prod[`ACCEL_PROD_W -1]}}, prod});

    // State lives in the array; this block only computes the next lane value.
    assign psum_out = $signed(psum_in) + $signed(prod_extend);
endmodule

`default_nettype wire
