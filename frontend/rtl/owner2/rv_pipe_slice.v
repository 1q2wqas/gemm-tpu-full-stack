`default_nettype none

// One-entry skid-free ready/valid stage carrying an address with its data.
module rv_pipe_slice #(
  parameter integer DW = 32,
  parameter integer AW = 6
)(
  input  wire          clk,
  input  wire          rst_n,

  input  wire          s_valid,
  output wire          s_ready,
  input  wire [AW-1:0] s_addr,
  input  wire [DW-1:0] s_data,

  output wire          m_valid,
  input  wire          m_ready,
  output wire [AW-1:0] m_addr,
  output wire [DW-1:0] m_data
);

  // vld owns the output contract while addr_r/data_r are held during stalls.
  reg          vld;
  reg [AW-1:0] addr_r;
  reg [DW-1:0] data_r;

  assign m_valid = vld;
  assign m_addr  = addr_r;
  assign m_data  = data_r;

  // A consumed entry may be replaced in the same cycle without a bubble.
  assign s_ready = (~vld) | m_ready;

  wire fire_in  = s_valid & s_ready;
  wire fire_out = m_valid & m_ready;

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      vld    <= 1'b0;
      addr_r <= {AW{1'b0}};
      data_r <= {DW{1'b0}};
    end else begin

      if (fire_out && !fire_in)
        vld <= 1'b0;

      // Data and address must remain paired while the downstream stalls.
      if (fire_in) begin
        vld    <= 1'b1;
        addr_r <= s_addr;
        data_r <= s_data;
      end
    end
  end

endmodule
`default_nettype wire
