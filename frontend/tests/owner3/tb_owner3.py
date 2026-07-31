import re
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, NextTimeStep, ReadOnly, RisingEdge, Timer

# Owner3 tests cover the integration FSM and the software-visible Wishbone contract.
(
    CONTROL_ADDR,
    STATUS_ADDR,
    VERSION_ADDR,
    A_PUSH_ADDR,
    B_PUSH_ADDR,
    PP_CTRL_ADDR,
    PP_MULT_ADDR,
    PP_SHIFT_ADDR,
    C_MEM32_BASE,
    Q_MEM8_BASE,
    P_MEM8_BASE,
    RESULT_BASE,
) = (
    0x0000_0000,
    0x0000_0004,
    0x0000_0008,
    0x0000_0100,
    0x0000_0104,
    0x0000_0500,
    0x0000_0504,
    0x0000_0508,
    0x0000_1000,
    0x0000_1100,
    0x0000_1140,
    0x0000_1200,
)
(CTRL_START, CTRL_CLEAR, CTRL_IRQ_EN) = (1 << 0, 1 << 1, 1 << 2)
(STAT_BUSY, STAT_DONE, STAT_A_LOADED, STAT_B_LOADED) = (1 << 0, 1 << 1, 1 << 2, 1 << 3)
(PP_EN, PP_RELU_EN, PP_POOL2X2_EN, PP_KEEP_RAW32) = (1 << 0, 1 << 1, 1 << 2, 1 << 3)
RAW_WORD_BASE = 0x1234_0000

def _repo_root() -> Path:

    here = Path(__file__).resolve()
    for base in (here.parent, *here.parents):
        if (base / "rtl" / "include").exists() or (base / "rtl" / "accel.vh").exists():
            return base
    raise FileNotFoundError(f"Could not locate the repository root for {here}")

# Depths are derived from the RTL header so stream lengths follow the build.
def _parse_accel_vh(repo_root: Path) -> dict:

    vh_path = None
    for candidate in (
        repo_root / "rtl" / "include" / "accel.vh",
        repo_root / "rtl" / "accel.vh",
    ):
        if candidate.exists():
            vh_path = candidate
            break
    if vh_path is None:
        raise FileNotFoundError(f"Could not locate accel.vh under {repo_root}")
    wanted = {
        "ACCEL_TM",
        "ACCEL_TN",
        "ACCEL_K_MAX",
        "ACCEL_P",
        "ACCEL_A_W",
        "ACCEL_B_W",
        "ACCEL_PSUM_W",
    }
    pat = re.compile(r"^\s*`define\s+(ACCEL_[A-Z0-9_]+)\s+([0-9]+)\s*$")
    defs = {}
    for line in vh_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        m = pat.match(line)
        if m and m.group(1) in wanted:
            defs[m.group(1)] = int(m.group(2))
    missing = wanted - set(defs)
    if missing:
        raise RuntimeError(f"Missing accel defines in accel.vh: {sorted(missing)}")
    defs["ACCEL_A_DEPTH"] = defs["ACCEL_TM"] * defs["ACCEL_K_MAX"]
    defs["ACCEL_B_DEPTH"] = defs["ACCEL_K_MAX"] * defs["ACCEL_TN"]
    defs["ACCEL_C_DEPTH"] = defs["ACCEL_TM"] * defs["ACCEL_TN"]
    return defs

CFG = _parse_accel_vh(_repo_root())

def _hasattrs(dut, *names):
    return all(hasattr(dut, name) for name in names)

def _maybe_sig(dut, *names):
    return next((getattr(dut, name) for name in names if hasattr(dut, name)), None)

# Port signatures select the applicable subset when this file is reused across tops.
def _is_cfg_status_regs(dut):
    return _hasattrs(dut, "start_req", "clear_req", "start_out", "clear_out")

def _is_gemm_top(dut):
    return _hasattrs(dut, "clk", "rst_n", "a_valid", "b_valid", "c_valid", "c_addr")

def _has_wb_accel_iface(dut):
    return _hasattrs(
        dut, "wb_clk_i", "wb_rst_i", "wbs_adr_i", "wbs_ack_o", "irq_o"
    )

def _is_periph(dut):
    return _has_wb_accel_iface(dut)

def _is_wrapper(dut):
    return _has_wb_accel_iface(dut) and _hasattrs(
        dut,
        "la_data_out",
        "io_out",
        "io_oeb",
    )

def _skip_unless(dut, predicate, label):

    if predicate(dut):
        return False
    dut._log.info("Skipping %s test on top %s", label, getattr(dut, "_name", "<unknown>"))
    return True

# Wishbone packs the lowest result address into byte lane zero.
def _pack_u8_le(values):
    word = 0
    for idx, value in enumerate(values):
        word |= (int(value) & 0xFF) << (8 * idx)
    return word & 0xFFFF_FFFF

def _expected_raw_word(addr):
    return (RAW_WORD_BASE + addr) & 0xFFFF_FFFF

def _expected_q_byte(addr):
    return (addr ^ 0xA5) & 0xFF

def _expected_p_byte(addr):
    return (0xC0 + addr) & 0xFF

def _expected_q_pack_word(word_index):
    return _pack_u8_le(_expected_q_byte(word_index * 4 + lane) for lane in range(4))

def _expected_p_pack_word(word_index):
    return _pack_u8_le(_expected_p_byte(word_index * 4 + lane) for lane in range(4))

async def _settle_comb():
    await Timer(1, unit="ns")
    await ReadOnly()

async def _wait_cycles_ro(clk, cycles):
    for _ in range(cycles):
        await RisingEdge(clk)
        await ReadOnly()

# Hold each beat until ready to exercise the top-level stream contract.
async def _drive_stream(
    dut, valid_name, ready_name, data_name, count, timeout_cycles=200
):
    valid = getattr(dut, valid_name)
    ready = getattr(dut, ready_name)
    data = getattr(dut, data_name)
    mask = (1 << len(data)) - 1
    await NextTimeStep()
    valid.value = 0
    data.value = 0
    await RisingEdge(dut.clk)
    for beat in range(count):
        data.value = beat & mask
        valid.value = 1
        for _ in range(timeout_cycles):
            await ReadOnly()
            if int(ready.value):
                await RisingEdge(dut.clk)
                break
            await RisingEdge(dut.clk)
        else:
            raise AssertionError(
                f"{valid_name}/{ready_name} handshake timed out after {timeout_cycles} cycles"
            )
        await NextTimeStep()
        valid.value = 0
        data.value = 0
        await RisingEdge(dut.clk)
    valid.value = 0
    data.value = 0

# Memory-window reads take an extra cycle, so wait for ACK instead of assuming latency.
class WishboneMaster:

    def __init__(self, dut):
        self.dut = dut
        self.clk = dut.wb_clk_i

    async def idle(self):
        self.dut.wbs_stb_i.value = 0
        self.dut.wbs_cyc_i.value = 0
        self.dut.wbs_we_i.value = 0
        self.dut.wbs_dat_i.value = 0
        self.dut.wbs_adr_i.value = 0
        self.dut.wbs_sel_i.value = 0xF

    async def reset(self, cycles=5):
        await self.idle()
        self.dut.wb_rst_i.value = 1
        for _ in range(cycles):
            await RisingEdge(self.clk)
        await NextTimeStep()
        self.dut.wb_rst_i.value = 0
        await RisingEdge(self.clk)
        await self.idle()

    async def write(self, addr, data, sel=0xF, timeout_cycles=500):
        await NextTimeStep()
        self.dut.wbs_adr_i.value, self.dut.wbs_dat_i.value = addr, data & 0xFFFF_FFFF
        self.dut.wbs_sel_i.value, self.dut.wbs_we_i.value = sel & 0xF, 1
        self.dut.wbs_stb_i.value, self.dut.wbs_cyc_i.value = 1, 1
        waited = 0
        while waited < timeout_cycles:
            await RisingEdge(self.clk)
            waited += 1
            await ReadOnly()
            if int(self.dut.wbs_ack_o.value):
                break
        else:
            raise AssertionError(f"Wishbone write to 0x{addr:08x} timed out")
        await NextTimeStep()
        await self.idle()
        await RisingEdge(self.clk)
        return waited

    async def read(self, addr, sel=0xF, timeout_cycles=500):
        await NextTimeStep()
        self.dut.wbs_adr_i.value, self.dut.wbs_dat_i.value = addr, 0
        self.dut.wbs_sel_i.value, self.dut.wbs_we_i.value = sel & 0xF, 0
        self.dut.wbs_stb_i.value, self.dut.wbs_cyc_i.value = 1, 1
        waited, data = 0, 0
        while waited < timeout_cycles:
            await RisingEdge(self.clk)
            waited += 1
            await ReadOnly()
            if int(self.dut.wbs_ack_o.value):
                data = int(self.dut.wbs_dat_o.value) & 0xFFFF_FFFF
                break
        else:
            raise AssertionError(f"Wishbone read from 0x{addr:08x} timed out")
        await NextTimeStep()
        await self.idle()
        await RisingEdge(self.clk)
        return data, waited

    async def wait_status(self, mask, expected_bits, attempts=300):
        for _ in range(attempts):
            status, _ = await self.read(STATUS_ADDR)
            if (status & mask) == expected_bits:
                return status
        raise AssertionError(
            f"STATUS never reached mask 0x{mask:08x} == 0x{expected_bits:08x}"
        )

# Return a ready bus master so every peripheral test starts from the same state.
async def _start_periph_clock_and_reset(dut):
    cocotb.start_soon(Clock(dut.wb_clk_i, 10, unit="ns").start())
    wb = WishboneMaster(dut)
    await wb.reset()
    return wb

async def _load_input_streams(wb):
    first_a_latency = first_b_latency = None
    for index in range(CFG["ACCEL_A_DEPTH"]):
        latency = await wb.write(A_PUSH_ADDR, index)
        first_a_latency = latency if first_a_latency is None else first_a_latency
    for index in range(CFG["ACCEL_B_DEPTH"]):
        latency = await wb.write(B_PUSH_ADDR, 0x80 | index)
        first_b_latency = latency if first_b_latency is None else first_b_latency
    await wb.wait_status(
        STAT_A_LOADED | STAT_B_LOADED,
        STAT_A_LOADED | STAT_B_LOADED,
        attempts=100,
    )
    return first_a_latency, first_b_latency

# Program shadow registers before START snapshots them into the working config.
async def _configure_pp(wb, pp_ctrl, mult=0, shift=0):
    await wb.write(PP_CTRL_ADDR, pp_ctrl)
    await wb.write(PP_MULT_ADDR, mult & 0xFFFF_FFFF)
    await wb.write(PP_SHIFT_ADDR, shift & 0xFFFF_FFFF)

async def _start_operation(wb, irq_enable=False):
    ctrl_value = CTRL_IRQ_EN if irq_enable else 0
    await wb.write(CONTROL_ADDR, ctrl_value)
    await wb.write(CONTROL_ADDR, ctrl_value | CTRL_START)

async def _clear_operation(wb, irq_enable=False):
    await wb.write(CONTROL_ADDR, (CTRL_IRQ_EN if irq_enable else 0) | CTRL_CLEAR)

async def _setup_started_periph(
    dut, *, pp_ctrl=0, mult=0, shift=0, irq_enable=False
):
    wb = await _start_periph_clock_and_reset(dut)
    await _configure_pp(wb, pp_ctrl, mult=mult, shift=shift)
    await _load_input_streams(wb)
    await _start_operation(wb, irq_enable=irq_enable)
    return wb

async def _wait_for_done_after_start(
    wb, dut, *, attempts, early_message, early_cycles=5
):
    await _wait_cycles_ro(dut.wb_clk_i, early_cycles)
    early_status, _ = await wb.read(STATUS_ADDR)
    assert (early_status & STAT_DONE) == 0, early_message
    return await wb.wait_status(STAT_DONE, STAT_DONE, attempts=attempts)

async def _wait_for_status(wb, mask, expected_bits, *, attempts, message):
    for _ in range(attempts):
        status, _ = await wb.read(STATUS_ADDR)
        if (status & mask) == expected_bits:
            return status
    raise AssertionError(message)

async def _assert_word_window(wb, base_addr, count, expected_fn, *, label):
    for index in range(count):
        word, _ = await wb.read(base_addr + 4 * index)
        assert word == expected_fn(index), f"{label}[{index}] mismatch"

# RESULT must mirror the bank selected by the accepted job configuration.
async def _assert_window_and_result(wb, base_addr, count, expected_fn, *, label):
    for index in range(count):
        window_word, _ = await wb.read(base_addr + 4 * index)
        result_word, _ = await wb.read(RESULT_BASE + 4 * index)
        expected = expected_fn(index)
        assert window_word == expected, f"{label}[{index}] mismatch"
        assert result_word == expected, f"RESULT[{index}] mismatch for {label}"

# Clear is deliberately gated by completion, while status bits pass through.
@cocotb.test()
async def test_cfg_status_regs_contract(dut):
    if _skip_unless(dut, _is_cfg_status_regs, "cfg_status_regs"):
        return
    done_gate = _maybe_sig(dut, "done_sticky_in", "done_in", "clear_allow_in", "done_latched_in")
    assert done_gate is not None, "cfg_status_regs needs one of done_sticky_in / done_in / clear_allow_in / done_latched_in"
    dut.start_req.value = 0
    dut.clear_req.value = 0
    dut.a_loaded_in.value = 0
    dut.b_loaded_in.value = 0
    dut.busy_in.value = 0
    done_gate.value = 0
    await _settle_comb()
    assert int(dut.start_out.value) == 0
    assert int(dut.clear_out.value) == 0
    assert int(dut.a_loaded_out.value) == 0
    assert int(dut.b_loaded_out.value) == 0
    assert int(dut.busy_out.value) == 0
    await Timer(1, unit="ns")
    dut.start_req.value = 1
    dut.busy_in.value = 0
    await _settle_comb()
    assert int(dut.start_out.value) == 1, "start_out should propagate a start request when idle"
    await Timer(1, unit="ns")
    dut.start_req.value = 0
    dut.clear_req.value = 1
    done_gate.value = 0
    await _settle_comb()
    assert int(dut.clear_out.value) == 0, "clear_out must stay low before final done permission"
    await Timer(1, unit="ns")
    done_gate.value = 1
    dut.a_loaded_in.value = 1
    dut.b_loaded_in.value = 1
    dut.busy_in.value = 1
    await _settle_comb()
    assert int(dut.clear_out.value) == 1, "clear_out should assert when clear is requested after final done"
    assert int(dut.a_loaded_out.value) == 1
    assert int(dut.b_loaded_out.value) == 1
    assert int(dut.busy_out.value) == 1
    if hasattr(dut, "done_out"):
        assert int(dut.done_out.value) == 1

# Exercise load -> start -> run -> done -> clear across the assembled datapath.
@cocotb.test()
async def test_gemm_accel_top_sequence(dut):
    if _skip_unless(dut, _is_gemm_top, "gemm_accel_top_b"):
        return
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut.rst_n.value = 0
    dut.a_valid.value = 0
    dut.b_valid.value = 0
    dut.c_ready.value = 1
    dut.a_data.value = 0
    dut.b_data.value = 0
    dut.start.value = 0
    dut.clear.value = 0
    await ClockCycles(dut.clk, 5)
    await NextTimeStep()
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)
    await ReadOnly()
    assert int(dut.done.value) == 0
    await _drive_stream(dut, "a_valid", "a_ready", "a_data", CFG["ACCEL_A_DEPTH"])
    await _drive_stream(dut, "b_valid", "b_ready", "b_data", CFG["ACCEL_B_DEPTH"])
    await RisingEdge(dut.clk)
    await ReadOnly()
    assert int(dut.a_loaded_out.value) == 1, "A loader should report loaded after A_DEPTH beats"
    assert int(dut.b_loaded_out.value) == 1, "B loader should report loaded after B_DEPTH beats"
    await NextTimeStep()
    dut.start.value = 1
    core_start_seen = False
    start_accept_seen = False
    await ReadOnly()
    if hasattr(dut, "core_start") and int(dut.core_start.value):
        core_start_seen = True
    if hasattr(dut, "start_accept") and int(dut.start_accept.value):
        start_accept_seen = True
    for _ in range(3):
        await RisingEdge(dut.clk)
        await ReadOnly()
        if hasattr(dut, "core_start") and int(dut.core_start.value):
            core_start_seen = True
        if hasattr(dut, "start_accept") and int(dut.start_accept.value):
            start_accept_seen = True
        if core_start_seen and (not hasattr(dut, "start_accept") or start_accept_seen):
            break
    await NextTimeStep()
    dut.start.value = 0
    if hasattr(dut, "core_start"):
        assert core_start_seen, "core_start should pulse around the external START request"
    if hasattr(dut, "start_accept"):
        assert start_accept_seen, "start_accept should pulse only when the top really accepts START"
    busy_seen = False
    done_seen = False
    for _ in range(max(8 * CFG["ACCEL_C_DEPTH"], 200)):
        await RisingEdge(dut.clk)
        await ReadOnly()
        if int(dut.busy.value):
            busy_seen = True
        if int(dut.done.value):
            done_seen = True
            break
    assert busy_seen, "busy should assert for at least part of the active run"
    assert done_seen, "done should assert after the output path completes"
    await NextTimeStep()
    dut.clear.value = 1
    await RisingEdge(dut.clk)
    await ReadOnly()
    await NextTimeStep()
    dut.clear.value = 0
    await ClockCycles(dut.clk, 3)
    await ReadOnly()
    assert int(dut.done.value) == 0, "done should clear after CLEAR"
    assert int(dut.a_loaded_out.value) == 0, "A loader should clear after CLEAR"
    assert int(dut.b_loaded_out.value) == 0, "B loader should clear after CLEAR"

# Register reads ACK immediately; stream pushes may wait for loader readiness.
@cocotb.test()
async def test_tpu_wb_regmap_and_push_ack(dut):
    if _skip_unless(dut, _is_periph, "tpu_wb_periph_b"):
        return
    wb = await _start_periph_clock_and_reset(dut)
    version0, latency0 = await wb.read(VERSION_ADDR)
    version1, latency1 = await wb.read(VERSION_ADDR)
    assert latency0 == 1 and latency1 == 1, "ordinary Wishbone reads should ACK in one cycle"
    assert version0 == version1, "VERSION should be stable across reads"
    assert version0 != 0, "VERSION should be a non-zero constant"
    await _configure_pp(wb, PP_EN | PP_RELU_EN | PP_POOL2X2_EN | PP_KEEP_RAW32, 0x8765_4321, 0xFFFF_FFFF)
    pp_ctrl, _ = await wb.read(PP_CTRL_ADDR)
    pp_mult, _ = await wb.read(PP_MULT_ADDR)
    pp_shift, _ = await wb.read(PP_SHIFT_ADDR)
    assert pp_ctrl == (PP_EN | PP_RELU_EN | PP_POOL2X2_EN | PP_KEEP_RAW32)
    assert pp_mult == 0x8765_4321
    assert pp_shift == 0x0000_001F, "PP_SHIFT should expose a zero-extended 5-bit state"
    unmapped_data, unmapped_latency = await wb.read(0x0000_0ABC)
    assert unmapped_latency == 1, "unmapped accesses should still ACK in one cycle"
    assert unmapped_data == 0, "unmapped reads should return zero"
    first_a_latency, first_b_latency = await _load_input_streams(wb)
    assert first_a_latency >= 1
    assert first_b_latency >= 1
    status, _ = await wb.read(STATUS_ADDR)
    assert (status & STAT_A_LOADED) != 0
    assert (status & STAT_B_LOADED) != 0

# Raw mode checks sticky DONE, IRQ behavior, result aliases, and retirement.
@cocotb.test()
async def test_tpu_wb_raw_result_window_and_clear(dut):
    if _skip_unless(dut, _is_periph, "tpu_wb_periph_b"):
        return
    wb = await _setup_started_periph(dut, pp_ctrl=0, mult=1, shift=0, irq_enable=True)
    await _wait_for_done_after_start(wb, dut, attempts=500, early_message="DONE must stay low early in the run")
    status, _ = await wb.read(STATUS_ADDR)
    assert (status & STAT_DONE) != 0
    assert (int(dut.irq_o.value) & 0x1) == 1, "IRQ should reflect irq_en && done_sticky after completion"
    await _assert_window_and_result(wb, C_MEM32_BASE, CFG["ACCEL_C_DEPTH"], _expected_raw_word, label="C_MEM32")
    await _clear_operation(wb, irq_enable=True)
    await _wait_for_status(
        wb, STAT_DONE | STAT_A_LOADED | STAT_B_LOADED, 0,
        attempts=20, message="CLEAR should remove DONE sticky and clear loaded flags",
    )
    assert (int(dut.irq_o.value) & 0x1) == 0, "IRQ should drop after CLEAR"

# A START received in DONE must not destroy the completed job's visible results.
@cocotb.test()
async def test_tpu_wb_rejected_start_in_done_keeps_result_valid(dut):
    if _skip_unless(dut, _is_periph, "tpu_wb_periph_b"):
        return
    wb = await _setup_started_periph(dut, pp_ctrl=0, mult=1, shift=0, irq_enable=False)
    await wb.wait_status(STAT_DONE, STAT_DONE, attempts=500)
    status_before, _ = await wb.read(STATUS_ADDR)
    raw_before, _ = await wb.read(C_MEM32_BASE)
    result_before, _ = await wb.read(RESULT_BASE)
    assert (status_before & STAT_DONE) != 0, "DONE should remain asserted once the run completes"
    assert raw_before == _expected_raw_word(0)
    assert result_before == _expected_raw_word(0)
    await _start_operation(wb, irq_enable=False)
    status_after, _ = await wb.read(STATUS_ADDR)
    raw_after, _ = await wb.read(C_MEM32_BASE)
    result_after, _ = await wb.read(RESULT_BASE)
    assert (status_after & STAT_DONE) != 0, "Rejected START in DONE must not clear the latched completion state"
    assert raw_after == _expected_raw_word(0), "Rejected START in DONE must not invalidate RAW results"
    assert result_after == _expected_raw_word(0), "Rejected START in DONE must not invalidate RESULT view"

# An early START is a rejected pulse, not a request that waits for future inputs.
@cocotb.test()
async def test_tpu_wb_early_start_before_inputs_is_ignored(dut):
    if _skip_unless(dut, _is_periph, "tpu_wb_periph_b"):
        return
    wb = await _start_periph_clock_and_reset(dut)
    await _configure_pp(wb, 0, mult=1, shift=0)
    await _start_operation(wb, irq_enable=False)
    await _wait_cycles_ro(dut.wb_clk_i, 5)
    status_after_early_start, _ = await wb.read(STATUS_ADDR)
    result_after_early_start, _ = await wb.read(RESULT_BASE)
    assert (status_after_early_start & (STAT_BUSY | STAT_DONE | STAT_A_LOADED | STAT_B_LOADED)) == 0
    assert result_after_early_start == 0, "Early START without inputs must not fabricate visible results"
    await _load_input_streams(wb)
    await _wait_cycles_ro(dut.wb_clk_i, 20)
    status_after_load, _ = await wb.read(STATUS_ADDR)
    result_after_load, _ = await wb.read(RESULT_BASE)
    assert (status_after_load & (STAT_A_LOADED | STAT_B_LOADED)) == (STAT_A_LOADED | STAT_B_LOADED)
    assert (status_after_load & (STAT_BUSY | STAT_DONE)) == 0, "Rejected START must not stay pending after inputs arrive"
    assert result_after_load == 0, "No accepted START means result windows must remain invalid"
    await _start_operation(wb, irq_enable=False)
    await wb.wait_status(STAT_DONE, STAT_DONE, attempts=500)
    final_result, _ = await wb.read(RESULT_BASE)
    assert final_result == _expected_raw_word(0), "A later accepted START should still launch a normal run"

# Verify the packed quantized bank and the raw-result override independently.
@cocotb.test()
async def test_tpu_wb_q_window_and_keep_raw32(dut):
    if _skip_unless(dut, _is_periph, "tpu_wb_periph_b"):
        return
    wb = await _setup_started_periph(dut, pp_ctrl=PP_EN | PP_RELU_EN, mult=0x1111_2222, shift=5, irq_enable=False)
    await _wait_for_done_after_start(
        wb, dut, attempts=500, early_message="DONE must stay low before all requant outputs are accepted",
    )
    await _assert_window_and_result(wb, Q_MEM8_BASE, CFG["ACCEL_C_DEPTH"] // 4, _expected_q_pack_word, label="Q_PACK")
    out_of_range_result, _ = await wb.read(RESULT_BASE + 4 * 20)
    assert out_of_range_result == 0
    await _clear_operation(wb, irq_enable=False)
    await _wait_for_status(wb, STAT_DONE, 0, attempts=20, message="CLEAR should remove DONE before the next KEEP_RAW32 run")
    await _configure_pp(wb, PP_EN | PP_RELU_EN | PP_KEEP_RAW32, mult=0x0000_0100, shift=0xFFFF_FFFF)
    pp_shift, _ = await wb.read(PP_SHIFT_ADDR)
    assert pp_shift == 0x0000_001F
    await _load_input_streams(wb)
    await _start_operation(wb, irq_enable=False)
    await wb.wait_status(STAT_DONE, STAT_DONE, attempts=500)
    await _assert_word_window(wb, RESULT_BASE, 4, _expected_raw_word, label="RESULT")
    q_word0, _ = await wb.read(Q_MEM8_BASE + 4 * 0)
    assert q_word0 == _expected_q_pack_word(0), "Q memory should still contain quantized bytes"

# Pooling changes both completion timing and the dimensions of the RESULT view.
@cocotb.test()
async def test_tpu_wb_pool_window(dut):
    if _skip_unless(dut, _is_periph, "tpu_wb_periph_b"):
        return
    wb = await _setup_started_periph(
        dut, pp_ctrl=PP_EN | PP_RELU_EN | PP_POOL2X2_EN, mult=0xCAFE_BABE, shift=2, irq_enable=False,
    )
    await _wait_for_done_after_start(wb, dut, attempts=700, early_message="DONE must remain low before pooling finishes")
    await _assert_window_and_result(wb, P_MEM8_BASE, 4, _expected_p_pack_word, label="P_PACK")
    out_of_range_result, _ = await wb.read(RESULT_BASE + 4 * 4)
    assert out_of_range_result == 0

# Writes during a run affect the next job only because working config is latched.
@cocotb.test()
async def test_tpu_wb_pp_reconfig_applies_on_next_start_only(dut):
    if _skip_unless(dut, _is_periph, "tpu_wb_periph_b"):
        return
    wb = await _setup_started_periph(
        dut, pp_ctrl=PP_EN | PP_RELU_EN | PP_POOL2X2_EN, mult=0x1111_2222, shift=3, irq_enable=False,
    )
    await _wait_cycles_ro(dut.wb_clk_i, 8)
    await _configure_pp(wb, 0, mult=0xDEAD_BEEF, shift=7)
    pp_ctrl_shadow, _ = await wb.read(PP_CTRL_ADDR)
    pp_mult_shadow, _ = await wb.read(PP_MULT_ADDR)
    pp_shift_shadow, _ = await wb.read(PP_SHIFT_ADDR)
    assert pp_ctrl_shadow == 0, "Software-visible PP shadow config should update immediately"
    assert pp_mult_shadow == 0xDEAD_BEEF
    assert pp_shift_shadow == 0x0000_0007
    await wb.wait_status(STAT_DONE, STAT_DONE, attempts=700)
    first_result, _ = await wb.read(RESULT_BASE + 4 * 0)
    first_pool_word, _ = await wb.read(P_MEM8_BASE + 4 * 0)
    assert first_result == _expected_p_pack_word(0), "Mid-run PP reconfig must not change the active operation's result view"
    assert first_pool_word == _expected_p_pack_word(0), "Mid-run PP reconfig must not prevent the active pooling stage from completing"
    await _clear_operation(wb, irq_enable=False)
    await _wait_for_status(wb, STAT_DONE, 0, attempts=20, message="CLEAR should remove DONE before the next PP run")
    await _load_input_streams(wb)
    await _start_operation(wb, irq_enable=False)
    await wb.wait_status(STAT_DONE, STAT_DONE, attempts=500)
    second_result, _ = await wb.read(RESULT_BASE + 4 * 0)
    second_raw_word, _ = await wb.read(C_MEM32_BASE + 4 * 0)
    assert second_result == _expected_raw_word(0), "The next accepted START should latch and use the updated shadow config"
    assert second_raw_word == _expected_raw_word(0)

@cocotb.test()
async def test_user_project_wrapper_smoke(dut):
    if _skip_unless(dut, _is_wrapper, "user_project_wrapper"):
        return
    wb = await _start_periph_clock_and_reset(dut)
    await _settle_comb()
    assert int(dut.la_data_out.value) == 0, "Wrapper should drive LA outputs low by default"
    assert int(dut.io_out.value) == 0, "Wrapper should drive unused GPIO outputs low"
    assert int(dut.io_oeb.value) == (1 << len(dut.io_oeb)) - 1, "Wrapper should tri-state unused GPIOs"
    version0, latency0 = await wb.read(VERSION_ADDR)
    version1, latency1 = await wb.read(VERSION_ADDR)
    assert latency0 == 1 and latency1 == 1
    assert version0 == version1
    assert version0 != 0
