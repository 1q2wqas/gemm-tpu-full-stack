`default_nettype none
`include "accel.vh"

// Convert the A input stream into sequential writes to the local buffer.
module stream_loader_A (
    input  wire                   clk,
    input  wire                   rst_n,

    input  wire                   a_valid,
    output wire                   a_ready,
    input  wire [`ACCEL_A_W-1:0]   a_data,

    output wire                   a_wr_en,
    output wire [`ACCEL_A_ADDR_W-1:0] a_wr_addr,
    output wire [`ACCEL_A_W-1:0]   a_wr_data,

    output reg                    a_loaded,
    input  wire                   clear_load
  );

  localparam integer A_DEPTH = `ACCEL_A_DEPTH;
  localparam [`ACCEL_A_ADDR_W-1:0] A_LAST = A_DEPTH-1;

  // cnt always points at the address for the next accepted beat.
  reg [`ACCEL_A_ADDR_W-1:0] cnt;

  // Stop accepting data once the fixed-size image is complete.
  assign a_ready   = ~a_loaded;

  assign a_wr_en   = a_valid & a_ready;

  assign a_wr_addr = cnt;
  assign a_wr_data = a_data;

  always @(posedge clk or negedge rst_n)
  begin
    if (!rst_n)
    begin
      cnt      <= {`ACCEL_A_ADDR_W{1'b0}};
      a_loaded <= 1'b0;
    end
    else if (clear_load)
    begin
      // Clearing starts a new matrix load without resetting the buffer RAM.
      cnt      <= {`ACCEL_A_ADDR_W{1'b0}};
      a_loaded <= 1'b0;
    end
    else if (a_wr_en)
    begin
      if (cnt == A_LAST)
      begin

        // The final accepted beat remains stored at A_LAST.
        a_loaded <= 1'b1;
      end
      else
      begin

        cnt <= cnt + {{(`ACCEL_A_ADDR_W-1){1'b0}},1'b1};
      end
    end
  end

endmodule

`default_nettype wire
