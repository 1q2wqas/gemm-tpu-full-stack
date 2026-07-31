`default_nettype none

`include "accel.vh"

// Caravel-facing shell exposing the accelerator only through Wishbone and IRQ.
module user_project_wrapper (
    input  wire         wb_clk_i,
    input  wire         wb_rst_i,

    input  wire         wbs_stb_i,
    input  wire         wbs_cyc_i,
    input  wire         wbs_we_i,

    input  wire [31:0]  wbs_dat_i,
    input  wire [31:0]  wbs_adr_i,
    input  wire [3:0]   wbs_sel_i,

    output wire [31:0]  wbs_dat_o,
    output wire         wbs_ack_o,

    output wire [2:0]   irq_o,

    input  wire [127:0] la_data_in,
    output wire [127:0] la_data_out,
    input  wire [127:0] la_oenb,

    input  wire [`MPRJ_IO_PADS-1:0] io_in,
    output wire [`MPRJ_IO_PADS-1:0] io_out,
    output wire [`MPRJ_IO_PADS-1:0] io_oeb
);

tpu_wb_periph_b u_periph (
    .wb_clk_i   (wb_clk_i),
    .wb_rst_i   (wb_rst_i),

    .wbs_stb_i  (wbs_stb_i),
    .wbs_cyc_i  (wbs_cyc_i),
    .wbs_we_i   (wbs_we_i),

    .wbs_adr_i  (wbs_adr_i),
    .wbs_dat_i  (wbs_dat_i),
    .wbs_sel_i  (wbs_sel_i),

    .wbs_dat_o  (wbs_dat_o),
    .wbs_ack_o  (wbs_ack_o),

    .irq_o      (irq_o)
);

// Logic-analyzer and GPIO pins are unused; Wishbone is the only control path.
assign la_data_out = 128'd0;

assign io_out      = {`MPRJ_IO_PADS{1'b0}};
assign io_oeb      = {`MPRJ_IO_PADS{1'b1}};

endmodule

`default_nettype wire
