import os
import re
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import (
    ClockCycles,
    FallingEdge,
    NextTimeStep,
    ReadOnly,
    RisingEdge,
    Timer,
)

# Owner2 tests focus on row buffering, scalar serialization, and backpressure.
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

# Read P and matrix dimensions from the build header used by the DUT.
def _parse_accel_vh(repo_root: Path) -> dict:

    candidates = [
        repo_root / "rtl" / "include" / "accel.vh",
        repo_root / "rtl" / "accel.vh",
    ]

    vh_path = None
    for candidate in candidates:
        if candidate.exists():
            vh_path = candidate
            break

    if vh_path is None:
        tried = ", ".join(str(p) for p in candidates)
        raise FileNotFoundError(f"Could not find accel header. Tried: {tried}")

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
        raise RuntimeError(f"Missing accel defines in {vh_path}: {sorted(missing)}")

    defs["ACCEL_A_DEPTH"] = defs["ACCEL_TM"] * defs["ACCEL_K_MAX"]
    return defs

CFG = _parse_accel_vh(_repo_root())

# Identify the unloader by its full row-input and scalar-output contract.
def _is_owner2_dut(dut) -> bool:
    return all(
        hasattr(dut, name)
        for name in (
            "clk",
            "rst_n",
            "c_row_valid",
            "c_row_ready",
            "c_row_data_flat",
            "c_m_base",
            "c_n_base",
            "c_row_off",
            "c_row_last",
            "c_valid",
            "c_ready",
            "c_data",
            "c_addr",
            "output_done",
        )
    )

def _skip_unless(dut, predicate, label):

    if predicate(dut):
        return False
    dut._log.info("Skipping %s test on top %s", label, getattr(dut, "_name", "<unknown>"))
    return True

# Lane zero occupies the least-significant slice, matching accel.vh.
def _pack_row(values, lane_width: int) -> int:
    packed = 0
    mask = (1 << lane_width) - 1
    for lane, value in enumerate(values):
        packed |= (int(value) & mask) << (lane * lane_width)
    return packed

# Convert tile sideband back into the row-major scalar C address.
def _expected_addr(tn: int, m_base: int, n_base: int, row_off: int, lane: int) -> int:
    m = m_base + row_off
    n = n_base + lane
    return m * tn + n

# The systolic core emits each tile bottom row first.
def _owner1_stream_rows(tm: int, tn: int, p: int):

    rows = []
    for m_base in range(0, tm, p):
        for n_base in range(0, tn, p):
            last_block = (m_base == (tm - p)) and (n_base == (tn - p))
            for row_off in range(p - 1, -1, -1):
                rows.append(
                    {
                        "m_base": m_base,
                        "n_base": n_base,
                        "row_off": row_off,
                        "row_last": 1 if (last_block and row_off == 0) else 0,
                    }
                )
    return rows

def _infer_p_from_dut(dut) -> int:
    lane_width = len(dut.c_data)
    row_flat_width = len(dut.c_row_data_flat)
    if lane_width == 0 or (row_flat_width % lane_width) != 0:
        raise RuntimeError(
            "Cannot infer ACCEL_P from DUT widths: "
            f"c_row_data_flat={row_flat_width}, c_data={lane_width}"
        )
    return row_flat_width // lane_width

def _expected_p_from_env() -> int | None:

    s = os.environ.get("ACCEL_P", "").strip()
    if s == "":
        return None
    try:
        p = int(s, 0)
    except ValueError as e:
        raise RuntimeError(f"Invalid ACCEL_P env '{s}' (expected int)") from e
    if p not in (1, 2, 4, 8):
        raise RuntimeError(f"Invalid ACCEL_P env {p} (expected 1/2/4/8)")
    return p

def _assert_expected_p_matches_dut(p: int) -> None:
    exp_p = _expected_p_from_env()
    assert p in (1, 2, 4, 8), f"Unexpected P={p} (expected 1/2/4/8)"
    if exp_p is not None:
        assert p == exp_p, (
            f"Requested ACCEL_P={exp_p} (env), but DUT compiled with P={p}. "
            "Check that the build passes -DACCEL_P=... to the HDL compiler."
        )

async def _settle() -> None:
    await Timer(1, unit="ns")
    await ReadOnly()

async def _wait_for_c_row_ready(dut, timeout_cycles: int = 100, label: str = "c_row_ready") -> None:

    if int(dut.c_row_ready.value):
        return

    for _ in range(timeout_cycles):
        await RisingEdge(dut.clk)
        await ReadOnly()
        if int(dut.c_row_ready.value):
            return

    raise AssertionError(f"Timed out waiting for {label}")

async def _reset_dut(dut) -> None:

    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())

    dut.rst_n.value = 0
    dut.c_row_valid.value = 0
    dut.c_row_data_flat.value = 0
    dut.c_m_base.value = 0
    dut.c_n_base.value = 0
    dut.c_row_off.value = 0
    dut.c_row_last.value = 0
    dut.c_ready.value = 0

    await ClockCycles(dut.clk, 5)
    await NextTimeStep()
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)

# Keep valid asserted through stalls; dropping it early would hide FIFO bugs.
async def _push_row(
    dut,
    lanes,
    m_base: int,
    n_base: int,
    row_off: int,
    row_last: int,
    timeout_cycles: int = 100,
) -> None:

    lane_width = len(dut.c_data)
    packed = _pack_row(lanes, lane_width)

    await _wait_for_c_row_ready(dut, timeout_cycles, "c_row_ready before launching a row")

    await NextTimeStep()
    dut.c_row_data_flat.value = packed
    dut.c_m_base.value = m_base
    dut.c_n_base.value = n_base
    dut.c_row_off.value = row_off
    dut.c_row_last.value = row_last
    dut.c_row_valid.value = 1

    for _ in range(timeout_cycles):
        await ReadOnly()
        if int(dut.c_row_ready.value):
            await RisingEdge(dut.clk)
            break
        await RisingEdge(dut.clk)
    else:
        raise AssertionError("Timed out waiting for the c_row_valid/c_row_ready handshake")

    await NextTimeStep()
    dut.c_row_valid.value = 0
    dut.c_row_data_flat.value = 0
    dut.c_m_base.value = 0
    dut.c_n_base.value = 0
    dut.c_row_off.value = 0
    dut.c_row_last.value = 0

# Record only accepted beats so repeated stalled values are not double-counted.
async def _collect_outputs(dut, expected_count: int, timeout_cycles: int = 200):

    seen = []

    for _ in range(timeout_cycles):
        await FallingEdge(dut.clk)
        await ReadOnly()

        if int(dut.c_valid.value) and int(dut.c_ready.value):
            seen.append(
                (
                    int(dut.c_addr.value),
                    int(dut.c_data.value),
                    int(dut.output_done.value),
                )
            )
            if len(seen) == expected_count:
                return seen

    raise AssertionError(f"Expected {expected_count} output handshakes, got {len(seen)}")

async def _wait_for_c_valid(dut, timeout_cycles: int = 100) -> None:
    for _ in range(timeout_cycles):
        await FallingEdge(dut.clk)
        await ReadOnly()
        if int(dut.c_valid.value):
            return
    raise AssertionError("Timed out waiting for c_valid")

# A nominal row establishes lane ordering and confirms non-final rows do not finish.
@cocotb.test()
async def test_stream_unloader_single_row_nominal(dut):
    if _skip_unless(dut, _is_owner2_dut, "stream_unloader_C_b"):
        return

    tm = CFG["ACCEL_TM"]
    tn = CFG["ACCEL_TN"]
    p = _infer_p_from_dut(dut)
    _assert_expected_p_matches_dut(p)
    rows = _owner1_stream_rows(tm, tn, p)

    await _reset_dut(dut)

    row = rows[0]
    lanes = [0x101 + lane for lane in range(p)]

    await NextTimeStep()
    dut.c_ready.value = 1

    collector = cocotb.start_soon(_collect_outputs(dut, p, timeout_cycles=200))

    await _push_row(
        dut,
        lanes,
        m_base=row["m_base"],
        n_base=row["n_base"],
        row_off=row["row_off"],
        row_last=row["row_last"],
    )

    seen = await collector

    for lane, (addr, data, done_flag) in enumerate(seen):
        assert addr == _expected_addr(tn, row["m_base"], row["n_base"], row["row_off"], lane)
        assert data == lanes[lane]
        assert done_flag == 0, "output_done must stay low for non-final rows"

    await RisingEdge(dut.clk)
    await ReadOnly()
    assert int(dut.output_done.value) == 0

# Stall the first scalar and require address, data, and done timing to stay intact.
@cocotb.test()
async def test_stream_unloader_backpressure_and_final_done(dut):
    if _skip_unless(dut, _is_owner2_dut, "stream_unloader_C_b"):
        return

    tm = CFG["ACCEL_TM"]
    tn = CFG["ACCEL_TN"]
    p = _infer_p_from_dut(dut)
    _assert_expected_p_matches_dut(p)
    final_row = _owner1_stream_rows(tm, tn, p)[-1]

    await _reset_dut(dut)

    lanes = [0x201 + lane for lane in range(p)]

    await NextTimeStep()
    dut.c_ready.value = 0

    collector = cocotb.start_soon(_collect_outputs(dut, expected_count=p, timeout_cycles=400))

    await _push_row(
        dut,
        lanes,
        m_base=final_row["m_base"],
        n_base=final_row["n_base"],
        row_off=final_row["row_off"],
        row_last=final_row["row_last"],
    )

    await _wait_for_c_valid(dut)

    held_addr = int(dut.c_addr.value)
    held_data = int(dut.c_data.value)

    # Sample several clocks to catch accidental lane advancement while ready is low.
    for _ in range(3):
        assert int(dut.c_valid.value) == 1, "c_valid should remain asserted under backpressure"
        assert int(dut.c_addr.value) == held_addr, "c_addr must stay stable while c_ready=0"
        assert int(dut.c_data.value) == held_data, "c_data must stay stable while c_ready=0"
        assert int(dut.output_done.value) == 0, "output_done must not assert before the final handshake"
        await RisingEdge(dut.clk)
        await ReadOnly()

    await NextTimeStep()
    dut.c_ready.value = 1

    seen = await collector

    assert seen[0][0] == held_addr
    assert seen[0][1] == held_data

    for lane, (addr, data, done_flag) in enumerate(seen):
        assert addr == _expected_addr(
            tn,
            final_row["m_base"],
            final_row["n_base"],
            final_row["row_off"],
            lane,
        )
        assert data == lanes[lane]

        if lane != (p - 1):
            assert done_flag == 0, "output_done must stay low before the final scalar commits"

    done_seen = (seen[-1][2] == 1)
    if not done_seen:
        await RisingEdge(dut.clk)
        await ReadOnly()
        done_seen = (int(dut.output_done.value) == 1)

    assert done_seen, "output_done should assert with or immediately after the final scalar transfer"

    await RisingEdge(dut.clk)
    await ReadOnly()
    assert int(dut.c_row_ready.value) == 1, "c_row_ready should be high again after the row fully drains"

# Two rows exercise FIFO order across the serializer's row boundary.
@cocotb.test()
async def test_stream_unloader_two_rows_in_sequence(dut):
    if _skip_unless(dut, _is_owner2_dut, "stream_unloader_C_b"):
        return

    tm = CFG["ACCEL_TM"]
    tn = CFG["ACCEL_TN"]
    p = _infer_p_from_dut(dut)
    _assert_expected_p_matches_dut(p)
    owner1_rows = _owner1_stream_rows(tm, tn, p)
    non_final_rows = [row for row in owner1_rows if row["row_last"] == 0]

    await _reset_dut(dut)
    await NextTimeStep()
    dut.c_ready.value = 1

    assert len(non_final_rows) >= 2, "owner1 traversal should expose at least two non-final rows"
    rows = [
        {
            **non_final_rows[0],
            "lanes": [0x301 + lane for lane in range(p)],
        },
        {
            **non_final_rows[1],
            "lanes": [0x401 + lane for lane in range(p)],
        },
    ]

    seen = []
    for row in rows:
        collector = cocotb.start_soon(_collect_outputs(dut, expected_count=p, timeout_cycles=200))

        await _push_row(
            dut,
            row["lanes"],
            m_base=row["m_base"],
            n_base=row["n_base"],
            row_off=row["row_off"],
            row_last=row["row_last"],
        )

        row_seen = await collector
        seen.extend(row_seen)

        for lane, (addr, data, done_flag) in enumerate(row_seen):
            exp_addr = _expected_addr(tn, row["m_base"], row["n_base"], row["row_off"], lane)
            exp_data = row["lanes"][lane]

            assert addr == exp_addr
            assert data == exp_data
            assert done_flag == 0, "output_done must stay low for non-final rows"

        if row is not rows[-1]:
            await _wait_for_c_row_ready(dut, 100, "c_row_ready between consecutive rows")

    assert len(seen) == 2 * p

    await RisingEdge(dut.clk)
    await ReadOnly()
    assert int(dut.output_done.value) == 0, "output_done must stay low until owner1 marks the true final row"

# The full traversal proves that every row/lane maps to one unique C address.
@cocotb.test()
async def test_stream_unloader_full_matrix_address_coverage(dut):
    if _skip_unless(dut, _is_owner2_dut, "stream_unloader_C_b"):
        return

    tm = CFG["ACCEL_TM"]
    tn = CFG["ACCEL_TN"]
    p = _infer_p_from_dut(dut)
    _assert_expected_p_matches_dut(p)

    assert (tm % p) == 0 and (tn % p) == 0, f"P={p} must divide TM={tm} and TN={tn}"

    await _reset_dut(dut)
    await NextTimeStep()
    dut.c_ready.value = 1

    expected = []
    total_rows = 0
    final_done_seen = False

    for row in _owner1_stream_rows(tm, tn, p):
        total_rows += 1
        lanes = [((row["m_base"] + row["row_off"]) << 8) | (row["n_base"] + lane) for lane in range(p)]

        collector = cocotb.start_soon(_collect_outputs(dut, expected_count=p, timeout_cycles=200))

        await _push_row(
            dut,
            lanes,
            m_base=row["m_base"],
            n_base=row["n_base"],
            row_off=row["row_off"],
            row_last=row["row_last"],
        )

        row_seen = await collector

        expected.extend(
            (
                _expected_addr(tn, row["m_base"], row["n_base"], row["row_off"], lane),
                lanes[lane],
                1 if (row["row_last"] and lane == (p - 1)) else 0,
            )
            for lane in range(p)
        )

        for lane, (addr, data, done_flag) in enumerate(row_seen):
            exp_addr, exp_data, exp_done = expected[-p + lane]
            assert addr == exp_addr
            assert data == exp_data

            if exp_done:
                final_done_seen = final_done_seen or (done_flag == 1)
            else:
                assert done_flag == 0

    assert total_rows == (tm * tn) // p
    assert len(expected) == tm * tn
    assert {addr for addr, _, _ in expected} == set(range(tm * tn))

    if not final_done_seen:
        await RisingEdge(dut.clk)
        await ReadOnly()
        final_done_seen = (int(dut.output_done.value) == 1)

    assert final_done_seen, "output_done should complete the full-matrix transfer"

    await RisingEdge(dut.clk)
    await ReadOnly()
    assert int(dut.c_row_ready.value) == 1
