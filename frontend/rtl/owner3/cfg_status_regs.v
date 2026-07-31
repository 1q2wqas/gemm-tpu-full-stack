`default_nettype none

// Small policy layer between Wishbone command bits and accelerator status.
module cfg_status_regs (

    input  wire start_req,
    input  wire clear_req,

    input  wire a_loaded_in,
    input  wire b_loaded_in,
    input  wire busy_in,
    input  wire done_latched_in,

    output wire start_out,
    output wire clear_out,
    output wire a_loaded_out,
    output wire b_loaded_out,
    output wire busy_out,
    output wire done_out
);

assign start_out    = start_req;
// Ignore an early clear; software may only retire a completed transaction.
assign clear_out    = clear_req && done_latched_in;

assign a_loaded_out = a_loaded_in;
assign b_loaded_out = b_loaded_in;
assign busy_out     = busy_in;
assign done_out     = done_latched_in;

endmodule

`default_nettype wire
