`default_nettype none

`include "accel.vh"

// Wishbone control plane, input-stream bridge, and result-memory front end.
module tpu_wb_periph_b (
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

    output wire [2:0]   irq_o
);

// Registers live below 0x1000; result windows are word-addressed above it.
localparam [31:0]
    CONTROL_ADDR  = 32'h0000_0000,
    STATUS_ADDR   = 32'h0000_0004,
    VERSION_ADDR  = 32'h0000_0008,
    A_PUSH_ADDR   = 32'h0000_0100,
    B_PUSH_ADDR   = 32'h0000_0104,
    PP_CTRL_ADDR  = 32'h0000_0500,
    PP_MULT_ADDR  = 32'h0000_0504,
    PP_SHIFT_ADDR = 32'h0000_0508,
    C_MEM32_BASE  = 32'h0000_1000,
    Q_MEM8_BASE   = 32'h0000_1100,
    P_MEM8_BASE   = 32'h0000_1140,
    RESULT_BASE   = 32'h0000_1200;

localparam [15:0]
    VERSION_MAJOR = 16'h0001,
    VERSION_MINOR = 16'h0000;

localparam [31:0]
    VERSION       = {VERSION_MAJOR, VERSION_MINOR};

wire wb_valid;
wire wb_write;
wire wb_read;

wire ctrl_write;
wire status_read;
wire version_read;
wire is_a_push;
wire is_b_push;

// Address classification also determines whether ACK is immediate or delayed.
wire known_read_addr;
wire known_write_addr;
wire known_push_addr;
wire unmapped_access;

wire pp_ctrl_write;
wire pp_mult_write;
wire pp_shift_write;

wire pp_ctrl_read;
wire pp_mult_read;
wire pp_shift_read;

wire pp_write;
wire pp_read;

wire c_mem_read;
wire q_pack_read;
wire p_pack_read;
wire result_view_read;
wire fast_read_addr;
wire slow_mem_read;

wire [5:0] c_mem_w;
wire [3:0] q_pack_w;
wire [1:0] p_pack_w;
wire [5:0] result_view_w;

wire start_sig;
wire clear_sig;
wire start_accept_sig;

wire a_loaded;
wire b_loaded;
wire busy_status;
wire done_status;

wire a_loaded_sig;
wire b_loaded_sig;
wire raw_busy_sig;
wire raw_done_sig;
wire busy_sig;
wire done_sig;

wire a_valid;
wire b_valid;
wire raw_c_valid;
wire a_ready;
wire b_ready;
wire raw_c_ready;

wire [`ACCEL_A_W-1:0]       a_data;
wire [`ACCEL_B_W-1:0]       b_data;
wire [`ACCEL_PSUM_W-1:0]    raw_c_data;
wire [`ACCEL_C_ADDR_W-1:0]  raw_c_addr;

wire rq_valid;
wire rq_ready;
wire [5:0] rq_addr;
wire [7:0] rq_q;

wire pool_done;
wire [5:0] q_rd_addr;
wire [7:0] q_rd_data;
wire       p_wr_en;
wire [3:0] p_wr_addr;
wire [7:0] p_wr_data;

wire a_handshake;
wire b_handshake;

reg         start_req;
reg         clear_req;
reg         irq_en;

// Register reads are combinational; memory windows return through mem_rdata_reg.
reg [31:0]  rdata_reg;
reg [31:0]  mem_rdata_reg;
reg         done_sticky;
reg         ack_reg;
reg         mem_ack_reg;

// A pending push owns the Wishbone cycle until the selected loader is ready.
reg                     push_pending;
reg                     a_pend_push;
reg                     b_pend_push;
reg [`ACCEL_A_W-1:0]    push_data_reg;
reg                     mem_read_pending;
reg                     mem_c_mem_sel;
reg                     mem_q_pack_sel;
reg                     mem_p_pack_sel;
reg                     mem_result_view_sel;
reg [5:0]               mem_c_mem_addr;
reg [3:0]               mem_q_pack_addr;
reg [1:0]               mem_p_pack_addr;
reg [5:0]               mem_result_view_addr;

// Software-facing settings may change while a previous job is still running.
reg                     pp_en;
reg                     relu_en;
reg                     pool_en;
reg                     keep_raw32;
reg signed [31:0]       pp_mult;
reg [4:0]               pp_shift;

// Working copies freeze the post-processing mode at start acceptance.
reg                     work_pp_en;
reg                     work_relu_en;
reg                     work_pool_en;
reg                     work_keep_raw32;
reg signed [31:0]       work_pp_mult;
reg [4:0]               work_pp_shift;

reg                     start_pool;

// Raw, requantized, and pooled results occupy separate software-visible banks.
reg [31:0]              c_mem [0:63];
reg [7:0]               q_mem [0:63];
reg [7:0]               p_mem [0:15];
reg                     c_mem_valid;
reg                     q_mem_valid;
reg                     p_mem_valid;

reg [`ACCEL_C_ADDR_W:0] rq_count;
reg                     rq_done_pulse;
wire                    rq_fire;

cfg_status_regs u_cfg_status (
    .start_req          (start_req),
    .clear_req          (clear_req),

    .a_loaded_in        (a_loaded_sig),
    .b_loaded_in        (b_loaded_sig),
    .busy_in            (busy_sig),
    .done_latched_in    (done_sticky),

    .start_out          (start_sig),
    .clear_out          (clear_sig),
    .a_loaded_out       (a_loaded),
    .b_loaded_out       (b_loaded),
    .busy_out           (busy_status),
    .done_out           (done_status)
);

gemm_accel_top_b u_top (
    .clk                (wb_clk_i),
    .rst_n              (~wb_rst_i),

    .a_valid            (a_valid),
    .b_valid            (b_valid),
    .c_valid            (raw_c_valid),

    .a_ready            (a_ready),
    .b_ready            (b_ready),
    .c_ready            (raw_c_ready),

    .a_data             (a_data),
    .b_data             (b_data),
    .c_data             (raw_c_data),

    .c_addr             (raw_c_addr),

    .a_loaded_out       (a_loaded_sig),
    .b_loaded_out       (b_loaded_sig),

    .start              (start_sig),
    .clear              (clear_sig),
    .start_accept       (start_accept_sig),
    .busy               (raw_busy_sig),
    .done               (raw_done_sig)
);

requant_relu_b u_relu (
    .clk                (wb_clk_i),
    .rst_n              (~wb_rst_i),

    .in_valid           (raw_c_valid),
    .in_ready           (raw_c_ready),
    .in_addr            (raw_c_addr),
    .in_data            (raw_c_data),

    .pp_en              (work_pp_en),
    .relu_en            (work_relu_en),
    .mult               (work_pp_mult),
    .shift              ({1'b0, work_pp_shift}),

    .out_valid          (rq_valid),
    .out_ready          (rq_ready),
    .out_addr           (rq_addr),
    .out_q              (rq_q)
);

maxpool2x2_b u_maxpool (
    .clk                (wb_clk_i),
    .rst_n              (~wb_rst_i),

    .pool_en            (work_pool_en),
    .start_pool         (start_pool),
    .pool_done          (pool_done),

    .q_rd_addr          (q_rd_addr),
    .q_rd_data          (q_rd_data),

    .p_wr_en            (p_wr_en),
    .p_wr_addr          (p_wr_addr),
    .p_wr_data          (p_wr_data)
);

// CONTROL writes become one-cycle START and CLEAR requests.
always @(posedge wb_clk_i) begin
    if (wb_rst_i) begin
        start_req <= 1'b0;
        clear_req <= 1'b0;
        irq_en    <= 1'b0;
    end else begin
        start_req <= 1'b0;
        clear_req <= 1'b0;

        if (ctrl_write) begin
            // START and CLEAR are write-one pulses; IRQ enable is persistent.
            if (wbs_dat_i[0])
                start_req <= 1'b1;
            if (wbs_dat_i[1])
                clear_req <= 1'b1;

            irq_en <= wbs_dat_i[2];
        end
    end
end

// These are shadow settings; the working copy below is stable during a job.
always @(posedge wb_clk_i) begin
    if (wb_rst_i) begin
        pp_en      <= 1'b0;
        relu_en    <= 1'b0;
        pool_en    <= 1'b0;
        keep_raw32 <= 1'b0;
        pp_mult    <= 32'd0;
        pp_shift   <= 5'd0;
    end else begin
        if (pp_ctrl_write) begin
            pp_en      <= wbs_dat_i[0];
            relu_en    <= wbs_dat_i[1];
            pool_en    <= wbs_dat_i[2];
            keep_raw32 <= wbs_dat_i[3];
        end

        if (pp_mult_write)
            pp_mult <= wbs_dat_i;

        if (pp_shift_write)
            pp_shift <= wbs_dat_i[4:0];
    end
end

always @(posedge wb_clk_i) begin
    if (wb_rst_i) begin
        work_pp_en       <= 1'b0;
        work_relu_en     <= 1'b0;
        work_pool_en     <= 1'b0;
        work_keep_raw32  <= 1'b0;
        work_pp_mult     <= 32'd0;
        work_pp_shift    <= 5'd0;
    end else if (start_accept_sig) begin
        // Mid-run register writes apply to the next job, not this one.
        work_pp_en       <= pp_en;
        work_relu_en     <= relu_en;
        work_pool_en     <= pool_en;
        work_keep_raw32  <= keep_raw32;
        work_pp_mult     <= pp_mult;
        work_pp_shift    <= pp_shift;
    end
end

// Capture each scalar accumulator result at its row-major C address.
always @(posedge wb_clk_i) begin
    if (raw_c_valid && raw_c_ready)
        c_mem[raw_c_addr] <= raw_c_data;
end

always @(posedge wb_clk_i) begin
    if (rq_valid && rq_ready)
        q_mem[rq_addr] <= rq_q;
end

always @(posedge wb_clk_i) begin
    if (p_wr_en)
        p_mem[p_wr_addr] <= p_wr_data;
end

// Mark each result bank valid only after its producer has completed the frame.
always @(posedge wb_clk_i) begin
    if (wb_rst_i || clear_sig || start_accept_sig) begin
        c_mem_valid <= 1'b0;
        q_mem_valid <= 1'b0;
        p_mem_valid <= 1'b0;
    end else begin
        if (raw_done_sig)
            c_mem_valid <= 1'b1;

        if (rq_done_pulse)
            q_mem_valid <= 1'b1;

        if (pool_done)
            p_mem_valid <= 1'b1;
    end
end

always @(posedge wb_clk_i) begin
    if (wb_rst_i || clear_sig) begin
        rq_count      <= {(`ACCEL_C_ADDR_W+1){1'b0}};
        rq_done_pulse <= 1'b0;
    end else begin
        rq_done_pulse <= 1'b0;

        if (rq_fire) begin
            // Count accepted requantized pixels, including the final address.
            if (rq_count == (`ACCEL_C_DEPTH-1)) begin
                rq_count      <= {(`ACCEL_C_ADDR_W+1){1'b0}};
                rq_done_pulse <= 1'b1;
            end else begin
                rq_count <= rq_count + {{`ACCEL_C_ADDR_W{1'b0}}, 1'b1};
            end
        end
    end
end

always @(posedge wb_clk_i) begin
    if (wb_rst_i)
        start_pool <= 1'b0;
    else
        start_pool <= rq_done_pulse && work_pp_en && work_pool_en;
end

always @(posedge wb_clk_i) begin
    if (wb_rst_i) begin
        ack_reg       <= 1'b0;
        mem_ack_reg   <= 1'b0;
        push_pending  <= 1'b0;
        a_pend_push   <= 1'b0;
        b_pend_push   <= 1'b0;
        push_data_reg <= {`ACCEL_A_W{1'b0}};
        mem_rdata_reg        <= 32'b0;
        mem_read_pending     <= 1'b0;
        mem_c_mem_sel        <= 1'b0;
        mem_q_pack_sel       <= 1'b0;
        mem_p_pack_sel       <= 1'b0;
        mem_result_view_sel  <= 1'b0;
        mem_c_mem_addr       <= 6'd0;
        mem_q_pack_addr      <= 4'd0;
        mem_p_pack_addr      <= 2'd0;
        mem_result_view_addr <= 6'd0;
    end else begin
        ack_reg     <= 1'b0;
        mem_ack_reg <= 1'b0;

        // Array reads are acknowledged one cycle later than register reads.
        if (mem_read_pending) begin
            ack_reg          <= 1'b1;
            mem_ack_reg      <= 1'b1;
            mem_read_pending <= 1'b0;

            if (mem_c_mem_sel) begin
                mem_rdata_reg <= c_mem_valid ? c_mem[mem_c_mem_addr] : 32'b0;
            end else if (mem_q_pack_sel) begin
                if (q_mem_valid) begin
                    mem_rdata_reg <= {
                        q_mem[{mem_q_pack_addr, 2'b11}],
                        q_mem[{mem_q_pack_addr, 2'b10}],
                        q_mem[{mem_q_pack_addr, 2'b01}],
                        q_mem[{mem_q_pack_addr, 2'b00}]
                    };
                end else begin
                    mem_rdata_reg <= 32'b0;
                end
            end else if (mem_p_pack_sel) begin
                if (p_mem_valid) begin
                    mem_rdata_reg <= {
                        p_mem[{mem_p_pack_addr, 2'b11}],
                        p_mem[{mem_p_pack_addr, 2'b10}],
                        p_mem[{mem_p_pack_addr, 2'b01}],
                        p_mem[{mem_p_pack_addr, 2'b00}]
                    };
                end else begin
                    mem_rdata_reg <= 32'b0;
                end
            end else if (mem_result_view_sel) begin
                if (work_keep_raw32 || !work_pp_en) begin
                    mem_rdata_reg <= c_mem_valid ? c_mem[mem_result_view_addr] : 32'b0;
                end else if (work_pool_en) begin
                    if (p_mem_valid && (mem_result_view_addr < 6'd4)) begin
                        mem_rdata_reg <= {
                            p_mem[{mem_result_view_addr[1:0], 2'b11}],
                            p_mem[{mem_result_view_addr[1:0], 2'b10}],
                            p_mem[{mem_result_view_addr[1:0], 2'b01}],
                            p_mem[{mem_result_view_addr[1:0], 2'b00}]
                        };
                    end else begin
                        mem_rdata_reg <= 32'b0;
                    end
                end else begin
                    if (q_mem_valid && (mem_result_view_addr < 6'd16)) begin
                        mem_rdata_reg <= {
                            q_mem[{mem_result_view_addr[3:0], 2'b11}],
                            q_mem[{mem_result_view_addr[3:0], 2'b10}],
                            q_mem[{mem_result_view_addr[3:0], 2'b01}],
                            q_mem[{mem_result_view_addr[3:0], 2'b00}]
                        };
                    end else begin
                        mem_rdata_reg <= 32'b0;
                    end
                end
            end else begin
                mem_rdata_reg <= 32'b0;
            end
        end else begin

            if (known_write_addr || fast_read_addr || unmapped_access)
                ack_reg <= 1'b1;

            if (slow_mem_read) begin
                // Latch both the window and index before the synchronous response.
                mem_read_pending     <= 1'b1;
                mem_c_mem_sel        <= c_mem_read;
                mem_q_pack_sel       <= q_pack_read;
                mem_p_pack_sel       <= p_pack_read;
                mem_result_view_sel  <= result_view_read;
                mem_c_mem_addr       <= c_mem_w;
                mem_q_pack_addr      <= q_pack_w;
                mem_p_pack_addr      <= p_pack_w;
                mem_result_view_addr <= result_view_w;
            end

            if (!push_pending) begin
                // A Wishbone push stays pending until the stream side accepts it.
                if (is_a_push) begin
                    push_pending  <= 1'b1;
                    a_pend_push   <= 1'b1;
                    b_pend_push   <= 1'b0;
                    push_data_reg <= wbs_dat_i[`ACCEL_A_W-1:0];
                end else if (is_b_push) begin
                    push_pending  <= 1'b1;
                    a_pend_push   <= 1'b0;
                    b_pend_push   <= 1'b1;
                    push_data_reg <= wbs_dat_i[`ACCEL_B_W-1:0];
                end
            end

            if (a_handshake) begin
                ack_reg      <= 1'b1;
                push_pending <= 1'b0;
                a_pend_push  <= 1'b0;
                b_pend_push  <= 1'b0;
            end

            if (b_handshake) begin
                ack_reg      <= 1'b1;
                push_pending <= 1'b0;
                a_pend_push  <= 1'b0;
                b_pend_push  <= 1'b0;
            end
        end
    end
end

// Completion remains visible until software issues a valid clear command.
always @(posedge wb_clk_i) begin
    if (wb_rst_i) begin
        done_sticky <= 1'b0;
    end else begin
        if (clear_sig)
            done_sticky <= 1'b0;
        else if (done_sig)
            done_sticky <= 1'b1;
    end
end

always @(*) begin
    rdata_reg = 32'b0;

    if (status_read) begin
        rdata_reg[0] = busy_status;
        rdata_reg[1] = done_sticky;
        rdata_reg[2] = a_loaded;
        rdata_reg[3] = b_loaded;
    end else if (version_read) begin
        rdata_reg = VERSION;
    end else if (pp_ctrl_read) begin
        rdata_reg[0] = pp_en;
        rdata_reg[1] = relu_en;
        rdata_reg[2] = pool_en;
        rdata_reg[3] = keep_raw32;
    end else if (pp_mult_read) begin
        rdata_reg = pp_mult;
    end else if (pp_shift_read) begin
        rdata_reg = {27'b0, pp_shift};
    end
end

assign wb_valid         = wbs_stb_i && wbs_cyc_i;
assign wb_write         = wb_valid && wbs_we_i;
assign wb_read          = wb_valid && !wbs_we_i;

assign ctrl_write       = wb_write && (wbs_adr_i == CONTROL_ADDR);
assign status_read      = wb_read  && (wbs_adr_i == STATUS_ADDR);
assign version_read     = wb_read  && (wbs_adr_i == VERSION_ADDR);
assign is_a_push        = wb_write && (wbs_adr_i == A_PUSH_ADDR);
assign is_b_push        = wb_write && (wbs_adr_i == B_PUSH_ADDR);

// mem_ack_reg selects the registered data on the matching memory ACK cycle.
assign wbs_dat_o        = mem_ack_reg ? mem_rdata_reg : rdata_reg;
assign wbs_ack_o        = ack_reg;
assign irq_o            = {2'b00, irq_en && done_sticky};

assign a_valid          = push_pending && a_pend_push;
assign b_valid          = push_pending && b_pend_push;

assign a_data           = push_data_reg;
assign b_data           = push_data_reg;

assign a_handshake      = a_valid && a_ready;
assign b_handshake      = b_valid && b_ready;

assign pp_ctrl_write    = wb_write && (wbs_adr_i == PP_CTRL_ADDR);
assign pp_mult_write    = wb_write && (wbs_adr_i == PP_MULT_ADDR);
assign pp_shift_write   = wb_write && (wbs_adr_i == PP_SHIFT_ADDR);

assign pp_ctrl_read     = wb_read && (wbs_adr_i == PP_CTRL_ADDR);
assign pp_mult_read     = wb_read && (wbs_adr_i == PP_MULT_ADDR);
assign pp_shift_read    = wb_read && (wbs_adr_i == PP_SHIFT_ADDR);

assign pp_write         = pp_ctrl_write || pp_mult_write || pp_shift_write;
assign pp_read          = pp_ctrl_read  || pp_mult_read  || pp_shift_read;
assign fast_read_addr   = status_read   || version_read  || pp_read;
assign slow_mem_read    = c_mem_read    || q_pack_read   || p_pack_read ||
                          result_view_read;

assign rq_ready         = 1'b1;
assign rq_fire          = rq_valid && rq_ready;
assign q_rd_data        = q_mem[q_rd_addr];

// Done follows the last enabled stage in the selected processing path.
assign done_sig         = (work_pp_en && work_pool_en) ? pool_done      :
                          (work_pp_en)                 ? rq_done_pulse  :
                                                        raw_done_sig;

assign busy_sig         = raw_busy_sig ||
                          (raw_done_sig && !(done_sticky || done_sig));

assign c_mem_read       = wb_read &&
                          (wbs_adr_i >= C_MEM32_BASE) &&
                          (wbs_adr_i <= C_MEM32_BASE + 32'hFF);

// INT8 banks expose four consecutive bytes per 32-bit Wishbone word.
assign q_pack_read      = wb_read &&
                          (wbs_adr_i >= Q_MEM8_BASE) &&
                          (wbs_adr_i <= Q_MEM8_BASE + 32'h3F) &&
                          (wbs_adr_i[1:0] == 2'b00);

assign p_pack_read      = wb_read &&
                          (wbs_adr_i >= P_MEM8_BASE) &&
                          (wbs_adr_i <= P_MEM8_BASE + 32'h0F);

// RESULT_BASE presents raw, requantized, or pooled data through one window.
assign result_view_read = wb_read &&
                          (wbs_adr_i >= RESULT_BASE) &&
                          (wbs_adr_i <= RESULT_BASE + 32'hFF);

assign c_mem_w          = (wbs_adr_i - C_MEM32_BASE) >> 2;
assign q_pack_w         = (wbs_adr_i - Q_MEM8_BASE)  >> 2;
assign p_pack_w         = (wbs_adr_i - P_MEM8_BASE)  >> 2;
assign result_view_w    = (wbs_adr_i - RESULT_BASE)  >> 2;

assign known_read_addr  = fast_read_addr || slow_mem_read;

assign known_write_addr = ctrl_write || pp_write;
assign known_push_addr  = is_a_push  || is_b_push;

// Unknown addresses still receive an ACK with zero data, avoiding a wedged bus.
assign unmapped_access  = wb_valid && !(known_read_addr  ||
                                        known_write_addr ||
                                        known_push_addr);

endmodule

`default_nettype wire
