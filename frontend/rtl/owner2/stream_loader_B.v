`default_nettype none
`include "accel.vh"

// Convert the B input stream into sequential writes to the local buffer.
module stream_loader_B (
    input  wire                   clk,
    input  wire                   rst_n,

    input  wire                   b_valid,
    output wire                   b_ready,
    input  wire [`ACCEL_B_W-1:0]   b_data,

    output wire                   b_wr_en,
    output wire [`ACCEL_B_ADDR_W-1:0] b_wr_addr,
    output wire [`ACCEL_B_W-1:0]   b_wr_data,

    output reg                    b_loaded,
    input  wire                   clear_load
  );

  localparam integer B_DEPTH = `ACCEL_B_DEPTH;
  localparam [`ACCEL_B_ADDR_W-1:0] B_LAST = B_DEPTH-1;

  // cnt advances on handshakes, so gaps in valid do not skip addresses.
  reg [`ACCEL_B_ADDR_W-1:0] cnt;

  // Backpressure begins immediately after the last buffer entry is written.
  assign b_ready   = ~b_loaded;

  assign b_wr_en   = b_valid & b_ready;

  assign b_wr_addr = cnt;
  assign b_wr_data = b_data;

  always @(posedge clk or negedge rst_n)
  begin
    if (!rst_n)
    begin
      cnt      <= {`ACCEL_B_ADDR_W{1'b0}};
      b_loaded <= 1'b0;
    end
    else if (clear_load)
    begin
      // RAM contents may remain; the next load overwrites all entries in order.
      cnt      <= {`ACCEL_B_ADDR_W{1'b0}};
      b_loaded <= 1'b0;
    end
    else if (b_wr_en)
    begin
      if (cnt == B_LAST)
      begin

        // Keep loaded high until the top-level clears the input phase.
        b_loaded <= 1'b1;
      end
      else
      begin

        cnt <= cnt + {{(`ACCEL_B_ADDR_W-1){1'b0}},1'b1};
      end
    end
  end

endmodule

`default_nettype wire
