`default_nettype none
`include "accel.vh"

// Registered PE shared by compute and bottom-row unload phases.
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

    wire signed [`ACCEL_PROD_W-1:0] prod;
    wire signed [`ACCEL_PSUM_W-1:0] prod_psum;

    // Widen the signed product explicitly before adding it to the psum.
    assign prod = $signed(a_in) * $signed(b_in);
    assign prod_psum =
        {{(`ACCEL_PSUM_W-`ACCEL_PROD_W){prod[`ACCEL_PROD_W-1]}}, prod};

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            a_out    <= {`ACCEL_A_W{1'b0}};
            b_out    <= {`ACCEL_B_W{1'b0}};
            psum_out <= {`ACCEL_PSUM_W{1'b0}};
        end else if (clear) begin
            a_out    <= {`ACCEL_A_W{1'b0}};
            b_out    <= {`ACCEL_B_W{1'b0}};
            psum_out <= {`ACCEL_PSUM_W{1'b0}};
        // Unload has priority so a held row is never accumulated twice.
        end else if (shift) begin
            psum_out <= psum_in;

        end else if (step) begin
            // Forward the current operands and retain the updated local psum.
            a_out    <= a_in;
            b_out    <= b_in;
            psum_out <= psum_out + prod_psum;
        end
    end

endmodule

`default_nettype wire
