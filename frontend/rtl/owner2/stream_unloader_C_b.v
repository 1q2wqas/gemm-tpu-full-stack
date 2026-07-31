`default_nettype none
`include "accel.vh"

`ifndef ACCEL_M_W
`define ACCEL_M_W 3
`endif
`ifndef ACCEL_N_W
`define ACCEL_N_W 3
`endif
`ifndef ACCEL_ROW_OFF_W
`define ACCEL_ROW_OFF_W 3
`endif
`ifndef ACCEL_M_BASE_W
`define ACCEL_M_BASE_W `ACCEL_M_W
`endif
`ifndef ACCEL_N_BASE_W
`define ACCEL_N_BASE_W `ACCEL_N_W
`endif

// Buffer P-wide result rows and emit scalar C writes with ready/valid flow control.
module stream_unloader_C_b (
    input  wire                          clk,
    input  wire                          rst_n,

    input  wire                              c_row_valid,
    output wire                              c_row_ready,
    input  wire [`ACCEL_P*`ACCEL_PSUM_W-1:0] c_row_data_flat,
    input  wire [`ACCEL_M_BASE_W-1:0]        c_m_base,
    input  wire [`ACCEL_N_BASE_W-1:0]        c_n_base,
    input  wire [`ACCEL_ROW_OFF_W-1:0]       c_row_off,
    input  wire                              c_row_last,

    output wire                           c_valid,
    input  wire                           c_ready,
    output wire [5:0]                     c_addr,
    output wire [`ACCEL_PSUM_W-1:0]       c_data,
    output reg                            output_done
  );

  localparam integer DEPTH = `ACCEL_P;

  // The row FIFO decouples array unload from scalar memory writes.
  reg [`ACCEL_P*`ACCEL_PSUM_W-1:0] fifo_data   [0:DEPTH-1];
  reg [`ACCEL_M_BASE_W-1:0]  fifo_m_base  [0:DEPTH-1];
  reg [`ACCEL_N_BASE_W-1:0]  fifo_n_base  [0:DEPTH-1];
  reg [`ACCEL_ROW_OFF_W-1:0] fifo_row_off [0:DEPTH-1];
  reg                              fifo_last   [0:DEPTH-1];

  // P is at most eight, so four-bit pointers cover every supported build.
  reg [3:0] wr_ptr, rd_ptr;
  reg [3:0] count;

  // hold_* is the row currently presented to the scalar output interface.
  reg                               ser_active;
  reg [3:0]                         lane_idx;
  reg [`ACCEL_P*`ACCEL_PSUM_W-1:0]  hold_data;
  reg [`ACCEL_M_BASE_W-1:0]         hold_m_base;
  reg [`ACCEL_N_BASE_W-1:0]         hold_n_base;
  reg [`ACCEL_ROW_OFF_W-1:0]        hold_row_off;
  reg                               hold_last;

  // Backpressure reaches the array only when every row slot is occupied.
  assign c_row_ready = (count < DEPTH);

  wire push = c_row_valid & c_row_ready;

  assign c_valid = ser_active;
  wire out_fire = c_valid & c_ready;

  // Hold the row stable and expose one lane per accepted output beat.
  assign c_data = hold_data[lane_idx*`ACCEL_PSUM_W +: `ACCEL_PSUM_W];

  wire [3:0] m_sum = {{(4-`ACCEL_M_BASE_W){1'b0}}, hold_m_base} + {{(4-`ACCEL_ROW_OFF_W){1'b0}}, hold_row_off};
  wire [3:0] n_sum = {{(4-`ACCEL_N_BASE_W){1'b0}}, hold_n_base} + {1'b0, lane_idx[2:0]};
  wire [2:0] m_idx = m_sum[2:0];
  wire [2:0] n_idx = n_sum[2:0];
  // C is fixed at 8 columns, so row-major addressing is (m << 3) + n.
  assign c_addr = ({m_idx, 3'b000} + {3'b000, n_idx});

  wire last_lane = (lane_idx == (DEPTH-1));
  wire pop = ser_active & out_fire & last_lane;

  // Simultaneous row push and completed-row pop leave occupancy unchanged.
  wire [3:0] count_next = count + (push ? 4'd1 : 4'd0) - (pop ? 4'd1 : 4'd0);

  function [3:0] inc_ptr;
    input [3:0] ptr;
    begin
      if (ptr == (DEPTH-1))
        inc_ptr = 4'd0;
      else
        inc_ptr = ptr + 4'd1;
    end
  endfunction

  always @(posedge clk or negedge rst_n)
  begin
    if (!rst_n)
    begin
      wr_ptr      <= 4'd0;
      rd_ptr      <= 4'd0;
      count       <= 4'd0;

      ser_active  <= 1'b0;
      lane_idx    <= 4'd0;

      hold_data   <= {(`ACCEL_P*`ACCEL_PSUM_W){1'b0}};
      hold_m_base <= 3'd0;
      hold_n_base <= 3'd0;
      hold_row_off<= 3'd0;
      hold_last   <= 1'b0;

      output_done <= 1'b0;
    end
    else
    begin
      output_done <= 1'b0;
      count <= count_next;

      if (push)
      begin
        fifo_data[wr_ptr]    <= c_row_data_flat;
        fifo_m_base[wr_ptr]  <= c_m_base;
        fifo_n_base[wr_ptr]  <= c_n_base;
        fifo_row_off[wr_ptr] <= c_row_off;
        fifo_last[wr_ptr]    <= c_row_last;
        wr_ptr <= inc_ptr(wr_ptr);
      end

      if (!ser_active)
      begin

        // Bypass the array input when the FIFO was empty at cycle start.
        if ((count == 0) && push)
        begin
          hold_data    <= c_row_data_flat;
          hold_m_base  <= c_m_base;
          hold_n_base  <= c_n_base;
          hold_row_off <= c_row_off;
          hold_last    <= c_row_last;
          ser_active   <= 1'b1;
          lane_idx     <= 4'd0;
        end
        else if (count != 0)
        begin

          // Load the oldest queued row; rd_ptr advances after its final lane.
          hold_data    <= fifo_data[rd_ptr];
          hold_m_base  <= fifo_m_base[rd_ptr];
          hold_n_base  <= fifo_n_base[rd_ptr];
          hold_row_off <= fifo_row_off[rd_ptr];
          hold_last    <= fifo_last[rd_ptr];
          ser_active   <= 1'b1;
          lane_idx     <= 4'd0;
        end
      end
      else
      begin

        if (out_fire)
        begin
          if (last_lane)
          begin

            rd_ptr     <= inc_ptr(rd_ptr);
            ser_active <= 1'b0;
            lane_idx   <= 4'd0;

            // Completion belongs to the final scalar beat, not the row enqueue.
            if (hold_last)
              output_done <= 1'b1;
          end
          else
          begin
            lane_idx <= lane_idx + 4'd1;
          end
        end
      end
    end
  end

endmodule

`default_nettype wire
