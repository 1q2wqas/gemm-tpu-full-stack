`default_nettype none
`include "accel.vh"

// Registered systolic PE: operands move across the grid while the psum stays local.
module pe_mac (
    input  wire                           clk,
    input  wire                           rst_n,

    input  wire                           clear,
    input  wire                           step,
    input  wire                           shift,

    input  wire signed [`ACCEL_A_W-1:0]    a_in,
    input  wire signed [`ACCEL_B_W-1:0]    b_in,
    input  wire signed [`ACCEL_PSUM_W-1:0] psum_in,

    output reg  signed [`ACCEL_A_W-1:0]    a_out,
    output reg  signed [`ACCEL_B_W-1:0]    b_out,
    output reg  signed [`ACCEL_PSUM_W-1:0] psum_out
);

    // The product width is exactly A_W+B_W before promotion to PSUM_W.
    wire signed [`ACCEL_PROD_W-1:0] prod;
    assign prod = a_in * b_in;

    wire signed [`ACCEL_PSUM_W-1:0] prod_psum;
    assign prod_psum = prod;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            a_out    <= {`ACCEL_A_W{1'b0}};
            b_out    <= {`ACCEL_B_W{1'b0}};
            psum_out <= {`ACCEL_PSUM_W{1'b0}};
        end else if (clear) begin
            a_out    <= {`ACCEL_A_W{1'b0}};
            b_out    <= {`ACCEL_B_W{1'b0}};
            psum_out <= {`ACCEL_PSUM_W{1'b0}};
        // Shift wins over step so unload and accumulation cannot overlap.
        end else if (shift) begin

            psum_out <= psum_in;

        end else if (step) begin

            // A and B move to their neighbors while this PE keeps its own sum.
            a_out    <= a_in;
            b_out    <= b_in;
            psum_out <= psum_out + prod_psum;
        end

    end

endmodule

`default_nettype wire
