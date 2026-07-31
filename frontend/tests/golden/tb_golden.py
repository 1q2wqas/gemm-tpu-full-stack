import os
import re
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import NextTimeStep, ReadOnly, RisingEdge

# End-to-end reference tests cover GEMM, post-processing, and every bus view.
TPU_BASE = int(os.getenv("TPU_BASE", "0x0"), 0)

# Keep this map beside the RTL localparams so address mismatches fail visibly.
CONTROL_ADDR = TPU_BASE + 0x0000_0000
STATUS_ADDR = TPU_BASE + 0x0000_0004
VERSION_ADDR = TPU_BASE + 0x0000_0008
A_PUSH_ADDR = TPU_BASE + 0x0000_0100
B_PUSH_ADDR = TPU_BASE + 0x0000_0104
PP_CTRL_ADDR = TPU_BASE + 0x0000_0500
PP_MULT_ADDR = TPU_BASE + 0x0000_0504
PP_SHIFT_ADDR = TPU_BASE + 0x0000_0508
C_MEM32_BASE = TPU_BASE + 0x0000_1000
Q_MEM8_BASE = TPU_BASE + 0x0000_1100
P_MEM8_BASE = TPU_BASE + 0x0000_1140
RESULT_BASE = TPU_BASE + 0x0000_1200

CTRL_START = 1 << 0
CTRL_CLEAR = 1 << 1
CTRL_IRQ_EN = 1 << 2

STAT_BUSY = 1 << 0
STAT_DONE = 1 << 1
STAT_A_LOADED = 1 << 2
STAT_B_LOADED = 1 << 3

PP_EN = 1 << 0
PP_RELU_EN = 1 << 1
PP_POOL2X2_EN = 1 << 2
PP_KEEP_RAW32 = 1 << 3

def _repo_root() -> Path:

    env_root = os.environ.get("REPO_ROOT", "").strip()
    if env_root:
        env_path = Path(env_root).resolve()
        if (env_path / "rtl" / "include").exists():
            return env_path

    here = Path(__file__).resolve()
    for candidate in (here.parent, *here.parents):
        if (candidate / "rtl" / "include").exists():
            return candidate.resolve()

    raise FileNotFoundError(f"Could not locate the repository root for {here}")

# Read compiled dimensions from accel.vh instead of duplicating matrix sizes here.
def _parse_accel_vh(repo_root: Path) -> dict:

    vh_path = repo_root / "rtl" / "include" / "accel.vh"
    if not vh_path.exists():
        raise FileNotFoundError(f"Expected accel.vh next to cocotb: {vh_path}")

    wanted = {
        "ACCEL_TM",
        "ACCEL_TN",
        "ACCEL_K_MAX",
        "ACCEL_P",
        "ACCEL_A_W",
        "ACCEL_B_W",
        "ACCEL_PSUM_W",
    }
    defs = {}
    pat = re.compile(r"^\s*`define\s+(ACCEL_[A-Z0-9_]+)\s+([0-9]+)\s*$")

    for line in vh_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        match = pat.match(line)
        if match:
            key, value = match.group(1), int(match.group(2))
            if key in wanted:
                defs[key] = value

    missing = wanted - set(defs)
    if missing:
        raise RuntimeError(f"Missing accel defines in accel.vh: {sorted(missing)}")

    defs["ACCEL_A_DEPTH"] = defs["ACCEL_TM"] * defs["ACCEL_K_MAX"]
    defs["ACCEL_B_DEPTH"] = defs["ACCEL_K_MAX"] * defs["ACCEL_TN"]
    defs["ACCEL_C_DEPTH"] = defs["ACCEL_TM"] * defs["ACCEL_TN"]
    return defs

CFG = _parse_accel_vh(_repo_root())

def _to_u8(value: int) -> int:

    return value & 0xFF

def _to_s8(value: int) -> int:

    value &= 0xFF
    return value - 0x100 if value & 0x80 else value

def _to_u32(value: int) -> int:

    return value & 0xFFFF_FFFF

def _to_s32(value: int) -> int:

    value &= 0xFFFF_FFFF
    return value - 0x1_0000_0000 if value & 0x8000_0000 else value

# Four INT8 results occupy a Wishbone word in increasing-address byte order.
def _pack_u8_le(values) -> int:

    word = 0
    for idx, value in enumerate(values):
        word |= (_to_u8(value)) << (8 * idx)
    return word & 0xFFFF_FFFF

def _accel_addr_a(m_idx: int, k_idx: int) -> int:

    return m_idx * CFG["ACCEL_K_MAX"] + k_idx

def _accel_addr_b(k_idx: int, n_idx: int) -> int:

    return k_idx * CFG["ACCEL_TN"] + n_idx

def _accel_addr_c(m_idx: int, n_idx: int) -> int:

    return m_idx * CFG["ACCEL_TN"] + n_idx

# These fixtures mix signs and magnitudes without relying on random seeds.
def _fixture_a_value(m_idx: int, k_idx: int) -> int:

    value = ((m_idx * 13 + k_idx * 7 + 5) % 41) - 20
    if (m_idx ^ k_idx) & 1:
        value = -value
    return value

def _fixture_b_value(k_idx: int, n_idx: int) -> int:

    value = ((k_idx * 11 + n_idx * 5 + 3) % 37) - 18
    if ((k_idx + 2 * n_idx) % 3) == 0:
        value = -value
    return value

def _fixture_input_bytes():

    a_bytes = [0] * CFG["ACCEL_A_DEPTH"]
    b_bytes = [0] * CFG["ACCEL_B_DEPTH"]

    for m_idx in range(CFG["ACCEL_TM"]):
        for k_idx in range(CFG["ACCEL_K_MAX"]):
            a_bytes[_accel_addr_a(m_idx, k_idx)] = _to_u8(_fixture_a_value(m_idx, k_idx))

    for k_idx in range(CFG["ACCEL_K_MAX"]):
        for n_idx in range(CFG["ACCEL_TN"]):
            b_bytes[_accel_addr_b(k_idx, n_idx)] = _to_u8(_fixture_b_value(k_idx, n_idx))

    return a_bytes, b_bytes

FIXTURE_A_BYTES, FIXTURE_B_BYTES = _fixture_input_bytes()

# Match the RTL rule for halfway values on both sides of zero.
def _round_arshift_away0(value: int, shift: int) -> int:

    if shift == 0:
        return value
    abs_value = abs(value)
    quotient, remainder = divmod(abs_value, 1 << shift)
    if remainder >= (1 << (shift - 1)):
        quotient += 1
    return -quotient if value < 0 else quotient

def _assert_rounding_examples() -> None:

    cases = [
        (-4, 1, -2),
        (-1, 2, 0),
        (-8, 1, -4),
        (3, 1, 2),
    ]
    for value, shift, expected in cases:
        actual = _round_arshift_away0(value, shift)
        assert actual == expected, f"round_arshift_away0({value}, {shift}) -> {actual}, expected {expected}"

def _sat_int8(value: int) -> int:

    if value > 127:
        return 127
    if value < -128:
        return -128
    return value

# Accumulate in Python integers, then wrap once at the 32-bit memory boundary.
def _golden_raw_words(a_bytes, b_bytes):

    raw_words = [0] * CFG["ACCEL_C_DEPTH"]
    for m_idx in range(CFG["ACCEL_TM"]):
        for n_idx in range(CFG["ACCEL_TN"]):
            acc = 0
            for k_idx in range(CFG["ACCEL_K_MAX"]):
                a_s = _to_s8(a_bytes[_accel_addr_a(m_idx, k_idx)])
                b_s = _to_s8(b_bytes[_accel_addr_b(k_idx, n_idx)])
                acc += a_s * b_s
            raw_words[_accel_addr_c(m_idx, n_idx)] = _to_u32(acc)
    return raw_words

# Apply stages in hardware order: scale, optional ReLU, then signed INT8 saturation.
def _golden_q_bytes(raw_words, pp_ctrl: int, mult: int, shift: int):

    q_bytes = []
    pp_en = (pp_ctrl & PP_EN) != 0
    relu_en = (pp_ctrl & PP_RELU_EN) != 0
    mult_s = _to_s32(mult)
    shift &= 0x1F

    for raw_word in raw_words:
        raw_s = _to_s32(raw_word)
        if pp_en:
            pre_value = _round_arshift_away0(raw_s * mult_s, shift)
        else:
            pre_value = raw_s
        if relu_en and pre_value < 0:
            pre_value = 0
        q_bytes.append(_to_u8(_sat_int8(pre_value)))
    return q_bytes

# Pool over signed values even though the memory image is stored as raw bytes.
def _golden_p_bytes(q_bytes):

    pooled = [0] * 16
    for pr in range(4):
        for pc in range(4):
            best = -128
            for dr in range(2):
                for dc in range(2):
                    q_index = _accel_addr_c(2 * pr + dr, 2 * pc + dc)
                    best = max(best, _to_s8(q_bytes[q_index]))
            pooled[pr * 4 + pc] = _to_u8(best)
    return pooled

# Keep every output view so each Wishbone window can be checked independently.
def _golden_model(a_bytes, b_bytes, pp_ctrl: int, mult: int, shift: int):

    raw_words = _golden_raw_words(a_bytes, b_bytes)
    q_bytes = _golden_q_bytes(raw_words, pp_ctrl, mult, shift)
    p_bytes = _golden_p_bytes(q_bytes)

    q_words = [
        _pack_u8_le(q_bytes[word_index * 4 + lane] for lane in range(4))
        for word_index in range(CFG["ACCEL_C_DEPTH"] // 4)
    ]
    p_words = [
        _pack_u8_le(p_bytes[word_index * 4 + lane] for lane in range(4))
        for word_index in range(4)
    ]

    pp_en = (pp_ctrl & PP_EN) != 0
    pool_en = (pp_ctrl & PP_POOL2X2_EN) != 0
    keep_raw32 = (pp_ctrl & PP_KEEP_RAW32) != 0

    if keep_raw32 or not pp_en:
        result_words = list(raw_words)
    elif pool_en:
        result_words = list(p_words) + [0] * (CFG["ACCEL_C_DEPTH"] - len(p_words))
    else:
        result_words = list(q_words) + [0] * (CFG["ACCEL_C_DEPTH"] - len(q_words))

    return {
        "raw_words": raw_words,
        "q_bytes": q_bytes,
        "q_words": q_words,
        "p_bytes": p_bytes,
        "p_words": p_words,
        "result_words": result_words,
    }

# Guard the fixture itself so quantization tests exercise clipping and both signs.
def _assert_quant_fixture_coverage(golden: dict) -> None:

    q_bytes = golden["q_bytes"]
    assert any(byte == 0x00 for byte in q_bytes), "fixture should produce ReLU-clamped zeros"
    assert any(byte == 0x7F for byte in q_bytes), "fixture should exercise positive int8 saturation"
    assert any(byte not in (0x00, 0x7F) for byte in q_bytes), "fixture should keep non-saturated quantized values"

def _assert_quant_fixture_without_relu_coverage(golden: dict) -> None:

    q_signed = [_to_s8(byte) for byte in golden["q_bytes"]]
    assert any(value < 0 for value in q_signed), "fixture should produce negative quantized outputs without ReLU"
    assert any(value > 0 for value in q_signed), "fixture should produce positive quantized outputs without ReLU"

def _assert_pool_fixture_coverage(golden: dict) -> None:

    unique_values = {value for value in golden["p_bytes"]}
    assert len(unique_values) > 1, "fixture should produce non-trivial pooled outputs"

def _assert_pool_without_relu_coverage(golden: dict) -> None:

    p_signed = [_to_s8(byte) for byte in golden["p_bytes"]]
    assert any(value < 0 for value in p_signed), "fixture should produce negative pooled outputs without ReLU"
    assert any(value > 0 for value in p_signed), "fixture should produce positive pooled outputs without ReLU"

# The same Python module may be discovered for several simulation tops.
def _is_golden_bus_top(dut) -> bool:

    return (
        hasattr(dut, "wb_clk_i")
        and hasattr(dut, "wb_rst_i")
        and hasattr(dut, "wbs_adr_i")
        and hasattr(dut, "wbs_ack_o")
        and hasattr(dut, "irq_o")
    )

def _skip_unless(dut, predicate, label: str) -> bool:

    if predicate(dut):
        return False
    dut._log.info("Skipping %s test on top %s", label, getattr(dut, "_name", "<unknown>"))
    return True

# Push writes may stall behind stream backpressure, so transactions need timeouts.
class WishboneMaster:

    def __init__(self, dut):
        self.dut = dut
        self.clk = dut.wb_clk_i

    async def idle(self) -> None:
        self.dut.wbs_stb_i.value = 0
        self.dut.wbs_cyc_i.value = 0
        self.dut.wbs_we_i.value = 0
        self.dut.wbs_dat_i.value = 0
        self.dut.wbs_adr_i.value = 0
        self.dut.wbs_sel_i.value = 0xF

    async def reset(self, cycles: int = 5) -> None:
        await self.idle()
        self.dut.wb_rst_i.value = 1
        for _ in range(cycles):
            await RisingEdge(self.clk)
        await NextTimeStep()
        self.dut.wb_rst_i.value = 0
        await RisingEdge(self.clk)
        await self.idle()

    async def write(self, addr: int, data: int, sel: int = 0xF, timeout_cycles: int = 500) -> int:
        await NextTimeStep()
        self.dut.wbs_adr_i.value = addr
        self.dut.wbs_dat_i.value = data & 0xFFFF_FFFF
        self.dut.wbs_sel_i.value = sel & 0xF
        self.dut.wbs_we_i.value = 1
        self.dut.wbs_stb_i.value = 1
        self.dut.wbs_cyc_i.value = 1

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

    async def read(self, addr: int, sel: int = 0xF, timeout_cycles: int = 500):
        await NextTimeStep()
        self.dut.wbs_adr_i.value = addr
        self.dut.wbs_dat_i.value = 0
        self.dut.wbs_sel_i.value = sel & 0xF
        self.dut.wbs_we_i.value = 0
        self.dut.wbs_stb_i.value = 1
        self.dut.wbs_cyc_i.value = 1

        waited = 0
        data = 0
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

    async def wait_status(self, mask: int, expected_bits: int, attempts: int = 300) -> int:
        for _ in range(attempts):
            status, _ = await self.read(STATUS_ADDR)
            if (status & mask) == expected_bits:
                return status
        raise AssertionError(f"STATUS never reached mask 0x{mask:08x} == 0x{expected_bits:08x}")

async def _wait_cycles_ro(clk, cycles: int) -> None:

    for _ in range(cycles):
        await RisingEdge(clk)
        await ReadOnly()

async def _start_periph_clock_and_reset(dut) -> WishboneMaster:

    cocotb.start_soon(Clock(dut.wb_clk_i, 10, unit="ns").start())
    wb = WishboneMaster(dut)
    await wb.reset()
    return wb

# Each push is a Wishbone transaction whose ACK may wait for stream readiness.
async def _load_input_streams(wb: WishboneMaster, a_bytes=None, b_bytes=None):

    a_bytes = list(FIXTURE_A_BYTES if a_bytes is None else a_bytes)
    b_bytes = list(FIXTURE_B_BYTES if b_bytes is None else b_bytes)

    first_a_latency = None
    first_b_latency = None

    for value in a_bytes:
        latency = await wb.write(A_PUSH_ADDR, value)
        if first_a_latency is None:
            first_a_latency = latency

    for value in b_bytes:
        latency = await wb.write(B_PUSH_ADDR, value)
        if first_b_latency is None:
            first_b_latency = latency

    await wb.wait_status(
        STAT_A_LOADED | STAT_B_LOADED,
        STAT_A_LOADED | STAT_B_LOADED,
        attempts=100,
    )
    return a_bytes, b_bytes, first_a_latency, first_b_latency

async def _configure_pp(wb: WishboneMaster, pp_ctrl: int, mult: int = 0, shift: int = 0) -> None:

    await wb.write(PP_CTRL_ADDR, pp_ctrl)
    await wb.write(PP_MULT_ADDR, mult & 0xFFFF_FFFF)
    await wb.write(PP_SHIFT_ADDR, shift & 0xFFFF_FFFF)

async def _start_operation(wb: WishboneMaster, irq_enable: bool = False) -> None:

    ctrl_value = CTRL_IRQ_EN if irq_enable else 0
    await wb.write(CONTROL_ADDR, ctrl_value)
    await wb.write(CONTROL_ADDR, ctrl_value | CTRL_START)

async def _clear_operation(wb: WishboneMaster, irq_enable: bool = False) -> None:

    ctrl_value = CTRL_IRQ_EN if irq_enable else 0
    await wb.write(CONTROL_ADDR, ctrl_value | CTRL_CLEAR)

# Raw mode checks the accumulator memory and the selected RESULT alias together.
@cocotb.test()
async def test_golden_raw_windows(dut):

    if _skip_unless(dut, _is_golden_bus_top, "golden_bus_top"):
        return

    wb = await _start_periph_clock_and_reset(dut)
    await _configure_pp(wb, 0, mult=1, shift=0)
    a_bytes, b_bytes, _, _ = await _load_input_streams(wb)
    golden = _golden_model(a_bytes, b_bytes, 0, 1, 0)
    await _start_operation(wb, irq_enable=False)

    await wb.wait_status(STAT_DONE, STAT_DONE, attempts=500)

    status, _ = await wb.read(STATUS_ADDR)
    assert (status & STAT_DONE) != 0
    assert (status & (STAT_A_LOADED | STAT_B_LOADED)) == (STAT_A_LOADED | STAT_B_LOADED)

    for index, expected in enumerate(golden["raw_words"]):
        raw_word, _ = await wb.read(C_MEM32_BASE + 4 * index)
        result_word, _ = await wb.read(RESULT_BASE + 4 * index)
        assert raw_word == expected, f"C_MEM32[{index}] mismatch"
        assert result_word == expected, f"RESULT[{index}] should mirror RAW32 when PP is disabled"

# Quantized mode also checks that KEEP_RAW32 changes only the RESULT selection.
@cocotb.test()
async def test_golden_q_windows_and_keep_raw32(dut):

    if _skip_unless(dut, _is_golden_bus_top, "golden_bus_top"):
        return

    _assert_rounding_examples()

    wb = await _start_periph_clock_and_reset(dut)

    q_pp_ctrl = PP_EN | PP_RELU_EN
    q_mult = 9
    q_shift = 4
    await _configure_pp(wb, q_pp_ctrl, mult=q_mult, shift=q_shift)
    a_bytes, b_bytes, _, _ = await _load_input_streams(wb)
    golden_q = _golden_model(a_bytes, b_bytes, q_pp_ctrl, q_mult, q_shift)
    _assert_quant_fixture_coverage(golden_q)
    await _start_operation(wb, irq_enable=False)

    await wb.wait_status(STAT_DONE, STAT_DONE, attempts=500)

    for word_index, expected_q in enumerate(golden_q["q_words"]):
        q_word, _ = await wb.read(Q_MEM8_BASE + 4 * word_index)
        result_word, _ = await wb.read(RESULT_BASE + 4 * word_index)
        assert q_word == expected_q, f"Q_PACK[{word_index}] mismatch"
        assert result_word == expected_q, f"RESULT[{word_index}] should select Q output when PP is enabled"

    out_of_range_result, _ = await wb.read(RESULT_BASE + 4 * 20)
    assert out_of_range_result == 0

    await _clear_operation(wb, irq_enable=False)
    await wb.wait_status(
        STAT_DONE | STAT_A_LOADED | STAT_B_LOADED,
        0,
        attempts=40,
    )

    keep_raw_ctrl = PP_EN | PP_RELU_EN | PP_KEEP_RAW32
    keep_raw_mult = 5
    keep_raw_shift = 6
    await _configure_pp(wb, keep_raw_ctrl, mult=keep_raw_mult, shift=keep_raw_shift)

    a_bytes, b_bytes, _, _ = await _load_input_streams(wb)
    golden_keep_raw = _golden_model(a_bytes, b_bytes, keep_raw_ctrl, keep_raw_mult, keep_raw_shift)
    await _start_operation(wb, irq_enable=False)
    await wb.wait_status(STAT_DONE, STAT_DONE, attempts=500)

    for index in range(8):
        result_word, _ = await wb.read(RESULT_BASE + 4 * index)
        assert result_word == golden_keep_raw["raw_words"][index], "KEEP_RAW32 should force RESULT to expose raw C"

    q_word0, _ = await wb.read(Q_MEM8_BASE)
    assert q_word0 == golden_keep_raw["q_words"][0], "Q memory should still contain quantized bytes"

@cocotb.test()
async def test_golden_q_windows_without_relu(dut):

    if _skip_unless(dut, _is_golden_bus_top, "golden_bus_top"):
        return

    _assert_rounding_examples()

    wb = await _start_periph_clock_and_reset(dut)

    q_pp_ctrl = PP_EN
    q_mult = 9
    q_shift = 4
    await _configure_pp(wb, q_pp_ctrl, mult=q_mult, shift=q_shift)
    a_bytes, b_bytes, _, _ = await _load_input_streams(wb)
    golden_q = _golden_model(a_bytes, b_bytes, q_pp_ctrl, q_mult, q_shift)
    _assert_quant_fixture_without_relu_coverage(golden_q)
    await _start_operation(wb, irq_enable=False)

    await wb.wait_status(STAT_DONE, STAT_DONE, attempts=500)

    for word_index, expected_q in enumerate(golden_q["q_words"]):
        q_word, _ = await wb.read(Q_MEM8_BASE + 4 * word_index)
        result_word, _ = await wb.read(RESULT_BASE + 4 * word_index)
        assert q_word == expected_q, f"Q_PACK_NO_RELU[{word_index}] mismatch"
        assert result_word == expected_q, f"RESULT[{word_index}] should select Q output when PP is enabled without ReLU"

@cocotb.test()
async def test_golden_q_windows_negative_mult_and_large_shift(dut):

    if _skip_unless(dut, _is_golden_bus_top, "golden_bus_top"):
        return

    _assert_rounding_examples()

    wb = await _start_periph_clock_and_reset(dut)

    neg_mult_ctrl = PP_EN
    neg_mult = (-9) & 0xFFFF_FFFF
    neg_shift = 4
    await _configure_pp(wb, neg_mult_ctrl, mult=neg_mult, shift=neg_shift)
    a_bytes, b_bytes, _, _ = await _load_input_streams(wb)
    golden_neg = _golden_model(a_bytes, b_bytes, neg_mult_ctrl, neg_mult, neg_shift)
    _assert_quant_fixture_without_relu_coverage(golden_neg)
    await _start_operation(wb, irq_enable=False)

    await wb.wait_status(STAT_DONE, STAT_DONE, attempts=500)

    for word_index, expected_q in enumerate(golden_neg["q_words"]):
        q_word, _ = await wb.read(Q_MEM8_BASE + 4 * word_index)
        result_word, _ = await wb.read(RESULT_BASE + 4 * word_index)
        assert q_word == expected_q, f"Q_PACK_NEG_MULT[{word_index}] mismatch"
        assert result_word == expected_q, f"RESULT[{word_index}] mismatch for negative multiplier case"

    await _clear_operation(wb, irq_enable=False)
    await wb.wait_status(
        STAT_DONE | STAT_A_LOADED | STAT_B_LOADED,
        0,
        attempts=40,
    )

    large_shift_ctrl = PP_EN
    large_shift_mult = 0x1234_5678
    large_shift = 31
    await _configure_pp(wb, large_shift_ctrl, mult=large_shift_mult, shift=large_shift)
    pp_shift_readback, _ = await wb.read(PP_SHIFT_ADDR)
    assert pp_shift_readback == 31, "PP_SHIFT should keep only the low 5 bits"

    a_bytes, b_bytes, _, _ = await _load_input_streams(wb)
    golden_large_shift = _golden_model(a_bytes, b_bytes, large_shift_ctrl, large_shift_mult, large_shift)
    _assert_quant_fixture_without_relu_coverage(golden_large_shift)
    await _start_operation(wb, irq_enable=False)

    await wb.wait_status(STAT_DONE, STAT_DONE, attempts=500)

    for word_index, expected_q in enumerate(golden_large_shift["q_words"]):
        q_word, _ = await wb.read(Q_MEM8_BASE + 4 * word_index)
        result_word, _ = await wb.read(RESULT_BASE + 4 * word_index)
        assert q_word == expected_q, f"Q_PACK_SHIFT31[{word_index}] mismatch"
        assert result_word == expected_q, f"RESULT[{word_index}] mismatch for large-shift case"

@cocotb.test()
async def test_golden_pool_windows(dut):

    if _skip_unless(dut, _is_golden_bus_top, "golden_bus_top"):
        return

    wb = await _start_periph_clock_and_reset(dut)

    pool_pp_ctrl = PP_EN | PP_RELU_EN | PP_POOL2X2_EN
    pool_mult = 9
    pool_shift = 4
    await _configure_pp(wb, pool_pp_ctrl, mult=pool_mult, shift=pool_shift)
    a_bytes, b_bytes, _, _ = await _load_input_streams(wb)
    golden_pool = _golden_model(a_bytes, b_bytes, pool_pp_ctrl, pool_mult, pool_shift)
    _assert_quant_fixture_coverage(golden_pool)
    _assert_pool_fixture_coverage(golden_pool)
    await _start_operation(wb, irq_enable=False)

    await wb.wait_status(STAT_DONE, STAT_DONE, attempts=700)

    for word_index, expected_p in enumerate(golden_pool["p_words"]):
        p_word, _ = await wb.read(P_MEM8_BASE + 4 * word_index)
        result_word, _ = await wb.read(RESULT_BASE + 4 * word_index)
        assert p_word == expected_p, f"P_PACK[{word_index}] mismatch"
        assert result_word == expected_p, f"RESULT[{word_index}] should select pooled output"

    out_of_range_result, _ = await wb.read(RESULT_BASE + 4 * 4)
    assert out_of_range_result == 0

@cocotb.test()
async def test_golden_pool_windows_without_relu(dut):

    if _skip_unless(dut, _is_golden_bus_top, "golden_bus_top"):
        return

    wb = await _start_periph_clock_and_reset(dut)

    pool_pp_ctrl = PP_EN | PP_POOL2X2_EN
    pool_mult = 9
    pool_shift = 4
    await _configure_pp(wb, pool_pp_ctrl, mult=pool_mult, shift=pool_shift)
    a_bytes, b_bytes, _, _ = await _load_input_streams(wb)
    golden_pool = _golden_model(a_bytes, b_bytes, pool_pp_ctrl, pool_mult, pool_shift)
    _assert_quant_fixture_without_relu_coverage(golden_pool)
    _assert_pool_without_relu_coverage(golden_pool)
    await _start_operation(wb, irq_enable=False)

    await wb.wait_status(STAT_DONE, STAT_DONE, attempts=700)

    for word_index, expected_p in enumerate(golden_pool["p_words"]):
        p_word, _ = await wb.read(P_MEM8_BASE + 4 * word_index)
        result_word, _ = await wb.read(RESULT_BASE + 4 * word_index)
        assert p_word == expected_p, f"P_PACK_NO_RELU[{word_index}] mismatch"
        assert result_word == expected_p, f"RESULT[{word_index}] should select pooled output without ReLU"

# This control-flow case protects command gating and configuration snapshot timing.
@cocotb.test()
async def test_golden_control_flow_early_start_clear_and_reconfig(dut):

    if _skip_unless(dut, _is_golden_bus_top, "golden_bus_top"):
        return

    wb = await _start_periph_clock_and_reset(dut)

    raw_ctrl = 0
    raw_mult = 1
    raw_shift = 0
    golden_raw = _golden_model(FIXTURE_A_BYTES, FIXTURE_B_BYTES, raw_ctrl, raw_mult, raw_shift)

    quant_ctrl = PP_EN | PP_RELU_EN
    quant_mult = 9
    quant_shift = 4
    golden_quant = _golden_model(FIXTURE_A_BYTES, FIXTURE_B_BYTES, quant_ctrl, quant_mult, quant_shift)

    assert golden_raw["raw_words"][0] != golden_quant["q_words"][0], "control-flow test needs distinct RAW and Q result views"

    await _configure_pp(wb, raw_ctrl, mult=raw_mult, shift=raw_shift)

    await _start_operation(wb, irq_enable=False)
    await _wait_cycles_ro(dut.wb_clk_i, 8)

    early_status, _ = await wb.read(STATUS_ADDR)
    early_result, _ = await wb.read(RESULT_BASE)
    assert (early_status & (STAT_BUSY | STAT_DONE | STAT_A_LOADED | STAT_B_LOADED)) == 0
    assert early_result == 0, "rejected early START must not fabricate visible results"

    await _load_input_streams(wb)
    await _wait_cycles_ro(dut.wb_clk_i, 12)

    loaded_status, _ = await wb.read(STATUS_ADDR)
    idle_result, _ = await wb.read(RESULT_BASE)
    assert (loaded_status & (STAT_A_LOADED | STAT_B_LOADED)) == (STAT_A_LOADED | STAT_B_LOADED)
    assert (loaded_status & STAT_DONE) == 0, "ignored early START must not complete a run after inputs later arrive"
    assert idle_result == 0, "without an accepted START, result windows must stay invalid"

    await _configure_pp(wb, quant_ctrl, mult=quant_mult, shift=quant_shift)
    await _start_operation(wb, irq_enable=False)
    await _wait_cycles_ro(dut.wb_clk_i, 8)

    await _configure_pp(wb, raw_ctrl, mult=raw_mult, shift=raw_shift)
    pp_ctrl_shadow, _ = await wb.read(PP_CTRL_ADDR)
    pp_mult_shadow, _ = await wb.read(PP_MULT_ADDR)
    pp_shift_shadow, _ = await wb.read(PP_SHIFT_ADDR)
    assert pp_ctrl_shadow == raw_ctrl
    assert pp_mult_shadow == raw_mult
    assert pp_shift_shadow == raw_shift

    await wb.wait_status(STAT_DONE, STAT_DONE, attempts=500)

    first_q_word, _ = await wb.read(Q_MEM8_BASE)
    first_result_word, _ = await wb.read(RESULT_BASE)
    assert first_q_word == golden_quant["q_words"][0], "active quant run should still fill Q window with the originally latched config"
    assert first_result_word == golden_quant["q_words"][0], "mid-run shadow reconfig must not change the current run's RESULT view"

    await _clear_operation(wb, irq_enable=False)
    await wb.wait_status(
        STAT_DONE | STAT_A_LOADED | STAT_B_LOADED,
        0,
        attempts=40,
    )

    cleared_result, _ = await wb.read(RESULT_BASE)
    assert cleared_result == 0, "CLEAR should invalidate RESULT until the next accepted run completes"

    await _load_input_streams(wb)
    await _start_operation(wb, irq_enable=False)
    await wb.wait_status(STAT_DONE, STAT_DONE, attempts=500)

    second_result_word, _ = await wb.read(RESULT_BASE)
    second_raw_word, _ = await wb.read(C_MEM32_BASE)
    assert second_raw_word == golden_raw["raw_words"][0]
    assert second_result_word == golden_raw["raw_words"][0], "the next accepted START should latch and use the updated RAW shadow config"
