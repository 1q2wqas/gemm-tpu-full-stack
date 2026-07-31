`default_nettype none
`include "accel.vh"

// Single-write, P-read storage for row-major matrix B.
module b_buf (
    input  wire                          clk,

    input  wire                          wr_en,
    input  wire [`ACCEL_B_ADDR_W-1:0]     wr_addr,
    input  wire [`ACCEL_B_W-1:0]          wr_data,

    input  wire [`ACCEL_B_RD_ADDR_FLAT_W-1:0] rd_addr_flat,
    output wire [`ACCEL_B_RD_DATA_FLAT_W-1:0] rd_data_flat
  );

  localparam integer DEPTH = `ACCEL_B_DEPTH;

  // Each combinational read lane serves one array column.
  reg [`ACCEL_B_W-1:0] mem [0:DEPTH-1];

  always @(posedge clk) begin
    if (wr_en)
      mem[wr_addr] <= wr_data;
  end

  // The core reads P columns in parallel from the shared buffer.
  genvar i;
  generate
    for (i=0; i<`ACCEL_P; i=i+1) begin : GEN_B_RD
      wire [`ACCEL_B_ADDR_W-1:0] addr_i;
      assign addr_i = `ACCEL_B_ADDR_LANE(rd_addr_flat, i);
      assign rd_data_flat[i*`ACCEL_B_W +: `ACCEL_B_W] = mem[addr_i];
    end
  endgenerate

endmodule

`default_nettype wire
