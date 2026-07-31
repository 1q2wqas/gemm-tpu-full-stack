`default_nettype none

// Scan an 8 x 8 INT8 image and write sixteen non-overlapping 2 x 2 maxima.
module maxpool2x2_b (
    input  wire        clk,
    input  wire        rst_n,

    input  wire        pool_en,
    input  wire        start_pool,
    output reg         pool_done,

    output wire [5:0]  q_rd_addr,
    input  wire [7:0]  q_rd_data,

    output reg         p_wr_en,
    output reg  [3:0]  p_wr_addr,
    output reg  [7:0]  p_wr_data
);

  // Treat start_pool as a command even if software leaves it high for a cycle.
  reg start_pool_d;
  wire start_pulse = start_pool & ~start_pool_d;

  reg [1:0] state;
  localparam [1:0] S_IDLE = 2'd0, S_ACC = 2'd1, S_WRITE = 2'd2;

  // pr/pc select the output cell; sub selects one of its four inputs.
  reg [1:0] pr;
  reg [1:0] pc;
  reg [1:0] sub;
  reg signed [7:0] cur_max;

  wire signed [7:0] q_s = q_rd_data;

  wire [2:0] base_r = {pr, 1'b0};
  wire [2:0] base_c = {pc, 1'b0};
  wire [2:0] dr = (sub[1]) ? 3'd1 : 3'd0;
  wire [2:0] dc = (sub[0]) ? 3'd1 : 3'd0;
  wire [2:0] r  = base_r + dr;
  wire [2:0] c  = base_c + dc;

  // The 8 x 8 source image is row-major; each output scans four neighbors.
  assign q_rd_addr = ({r, 3'b000} + {3'b000, c});

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      start_pool_d <= 1'b0;

      state     <= S_IDLE;
      pool_done <= 1'b0;

      p_wr_en   <= 1'b0;
      p_wr_addr <= 4'd0;
      p_wr_data <= 8'd0;

      pr        <= 2'd0;
      pc        <= 2'd0;
      sub       <= 2'd0;
      cur_max   <= -8'sd128;
    end else begin
      start_pool_d <= start_pool;

      pool_done <= 1'b0;
      p_wr_en   <= 1'b0;

      case (state)
        S_IDLE: begin
          if (start_pulse) begin
            if (!pool_en) begin

              // Disabled pooling acknowledges the command without touching memory.
              pool_done <= 1'b1;
              state     <= S_IDLE;
              sub       <= 2'd0;
              cur_max   <= -8'sd128;
            end else begin
              pr      <= 2'd0;
              pc      <= 2'd0;
              sub     <= 2'd0;
              cur_max <= -8'sd128;
              state   <= S_ACC;
            end
          end
        end

        S_ACC: begin

          // sub[1:0] visits (0,0), (0,1), (1,0), then (1,1).
          if (q_s > cur_max) cur_max <= q_s;

          if (sub == 2'd3) begin
            state <= S_WRITE;
          end else begin
            sub <= sub + 2'd1;
          end
        end

        S_WRITE: begin

          // Pool output is a compact 4 x 4 row-major image.
          p_wr_en   <= 1'b1;
          p_wr_addr <= {pr, pc};
          p_wr_data <= cur_max[7:0];

          sub     <= 2'd0;
          cur_max <= -8'sd128;

          if (pc == 2'd3) begin
            pc <= 2'd0;
            if (pr == 2'd3) begin
              pool_done <= 1'b1;
              state     <= S_IDLE;
            end else begin
              pr    <= pr + 2'd1;
              state <= S_ACC;
            end
          end else begin
            pc    <= pc + 2'd1;
            state <= S_ACC;
          end
        end

        default: state <= S_IDLE;
      endcase
    end
  end

endmodule

`default_nettype wire
