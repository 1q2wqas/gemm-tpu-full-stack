`default_nettype none

// Convert signed INT32 accumulators to signed INT8 with optional scale and ReLU.
module requant_relu_b (
    input  wire         clk,
    input  wire         rst_n,

    input  wire         in_valid,
    output wire         in_ready,
    input  wire [5:0]   in_addr,
    input  wire [31:0]  in_data,

    input  wire         pp_en,
    input  wire         relu_en,
    input  wire [31:0]  mult,
    input  wire [5:0]   shift,

    output wire         out_valid,
    input  wire         out_ready,
    output wire [5:0]   out_addr,
    output wire [7:0]   out_q
);

  wire        s0_valid;
  wire        s0_ready;
  wire [5:0]  s0_addr;
  wire [31:0] s0_data;

  // The input slice breaks the combinational ready path through the arithmetic.
  rv_pipe_slice #(.DW(32), .AW(6)) u_in_pipe (
    .clk    (clk),
    .rst_n  (rst_n),
    .s_valid(in_valid),
    .s_ready(in_ready),
    .s_addr (in_addr),
    .s_data (in_data),
    .m_valid(s0_valid),
    .m_ready(s0_ready),
    .m_addr (s0_addr),
    .m_data (s0_data)
  );

  reg        vld;
  reg [5:0]  addr_r;
  reg [7:0]  q_r;

  assign out_valid = vld;
  assign out_addr  = addr_r;
  assign out_q     = q_r;

  assign s0_ready = (~vld) | out_ready;

  wire fire_in  = s0_valid & s0_ready;
  wire fire_out = out_valid & out_ready;

  // Saturate after ReLU so the output always fits signed INT8.
  function [7:0] sat_int8_64;
    input signed [63:0] x;
    begin
      if (x > 64'sd127)        sat_int8_64 = 8'h7F;
      else if (x < -64'sd128)  sat_int8_64 = 8'h80;
      else                     sat_int8_64 = x[7:0];
    end
  endfunction

  // Halfway cases round away from zero to match the software model.
  function signed [63:0] round_arshift_away0;
    input signed [63:0] x;
    input [5:0]         sh;
    reg [63:0]          bias;
    reg [63:0]          mag;
    reg [63:0]          rounded_mag;
    begin
      if (sh == 0) begin
        round_arshift_away0 = x;
      end else begin
        if (sh == 1) bias = 64'd1;
        else         bias = 64'd1 << (sh - 1);

        if (x >= 0) begin
          round_arshift_away0 = (x + $signed(bias)) >>> sh;
        end else begin

          // Round the magnitude first; arithmetic shifts bias negatives downward.
          mag = (~x) + 64'd1;
          rounded_mag = (mag + bias) >> sh;
          round_arshift_away0 = -$signed(rounded_mag);
        end
      end
    end
  endfunction

  wire signed [31:0] in_s  = s0_data;
  wire signed [31:0] mul_s = mult;

  // Use 64 bits so the signed 32 x 32 multiply cannot overflow before shifting.
  wire signed [63:0] prod64 = in_s * mul_s;
  wire signed [63:0] rq64   = round_arshift_away0(prod64, shift);

  // Bypass keeps the raw accumulator value but still applies ReLU and saturation.
  wire signed [63:0] pre64  = (pp_en) ? rq64 : {{32{in_s[31]}}, in_s};

  wire signed [63:0] relu64 = (relu_en && (pre64 < 0)) ? 64'sd0 : pre64;

  // q_next is evaluated only when the input slice transfers into this stage.
  wire [7:0] q_next = sat_int8_64(relu64);

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      vld    <= 1'b0;
      addr_r <= 6'd0;
      q_r    <= 8'd0;
    end else begin

      if (fire_out && !fire_in)
        vld <= 1'b0;

      // The output register is also the final ready-valid pipeline stage.
      if (fire_in) begin
        vld    <= 1'b1;
        addr_r <= s0_addr;
        q_r    <= q_next;
      end
    end
  end

endmodule

`default_nettype wire
