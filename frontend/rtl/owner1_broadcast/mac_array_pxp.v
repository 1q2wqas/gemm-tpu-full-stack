`default_nettype none
`include "accel.vh"

// P x P output-stationary array with broadcast A rows and B columns.
module mac_array_pxp (
    input wire clk,
    input wire rst_n,
    input wire clear,
    input wire step,

    input wire [(`ACCEL_P * `ACCEL_A_W)-1:0] a_vec_flat,
    input wire [(`ACCEL_P * `ACCEL_B_W)-1:0] b_vec_flat,

    output wire [(`ACCEL_P * `ACCEL_P * `ACCEL_PSUM_W)-1:0] psum_flat
);

    localparam integer P = `ACCEL_P;
    localparam integer A_W = `ACCEL_A_W;
    localparam integer B_W = `ACCEL_B_W;
    localparam integer PSUM_W = `ACCEL_PSUM_W;
    localparam integer PSUM_FLAT_W = P * P * PSUM_W;

    // Each lane owns its partial sum; A and B are broadcast across the tile.
    reg [PSUM_FLAT_W-1:0] psum_flat_r;
    assign psum_flat = psum_flat_r;

    // next contains the full outer-product update for the current k index.
    wire [PSUM_FLAT_W-1:0] psum_flat_next;

    // One combinational MAC feeds each registered accumulator lane.
    genvar i, j;
    generate
        for (i = 0; i < P; i = i + 1) begin : gen_I
            for (j = 0; j < P; j = j + 1) begin : gen_J
                pe_mac u_pe_mac (
                    .a( $signed(a_vec_flat[i * A_W +: A_W])),
                    .b( $signed(b_vec_flat[j * B_W +: B_W])),
                    .psum_in( $signed(psum_flat_r[(i*P + j)*PSUM_W +: PSUM_W]) ),
                    .psum_out( psum_flat_next[(i*P + j)*PSUM_W +: PSUM_W] )
                );
            end
        end
    endgenerate

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            psum_flat_r <= {PSUM_FLAT_W{1'b0}};
        end else if (clear) begin
            psum_flat_r <= {PSUM_FLAT_W{1'b0}};
        end else if (step) begin
            // A step commits all P x P products together.
            psum_flat_r <= psum_flat_next;
        end else begin
            psum_flat_r <= psum_flat_r;
        end
    end
endmodule

`default_nettype wire
