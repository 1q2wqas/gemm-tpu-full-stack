import json
import os
import random
import re
from pathlib import Path

import cocotb
import numpy as np
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge

# Core-level tests drive the operand memories directly and observe streamed rows.
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

# Matrix dimensions come from the same header used by the compiled RTL.
def _parse_accel_vh(repo_root: Path) -> dict:

    candidates = [
        repo_root / "rtl" / "include" / "accel.vh",
    ]
    vh = None
    for p in candidates:
        if p.exists():
            vh = p
            break
    if vh is None:
        raise FileNotFoundError(
            "accel.vh not found. Tried: " + ", ".join(str(p) for p in candidates)
        )

    lines = vh.read_text(encoding="utf-8", errors="ignore").splitlines()

    wanted = {
        "ACCEL_TM",
        "ACCEL_TN",
        "ACCEL_K_MAX",
        "ACCEL_A_W",
        "ACCEL_B_W",
        "ACCEL_PSUM_W",
    }

    defs = {}
    pat = re.compile(r"^\s*`define\s+(ACCEL_[A-Z0-9_]+)\s+([0-9]+)\s*$")
    for line in lines:
        m = pat.match(line)
        if m:
            k, v = m.group(1), int(m.group(2))
            if k in wanted:
                defs[k] = v

    missing = wanted - set(defs.keys())
    if missing:
        raise RuntimeError(f"Missing defines in accel.vh: {sorted(missing)}")
    return defs

# Port-based detection lets unrelated tops skip this suite cleanly.
def _is_owner1_dut(dut) -> bool:
    return all(
        hasattr(dut, name)
        for name in (
            "clk",
            "rst_n",
            "core_start",
            "core_done",
            "a_rd_addr_flat",
            "a_rd_data_flat",
            "b_rd_addr_flat",
            "b_rd_data_flat",
            "c_row_valid",
            "c_row_ready",
            "c_row_data_flat",
            "c_m_base",
            "c_n_base",
            "c_row_off",
        )
    )

def _skip_unless(dut, predicate, label):

    if predicate(dut):
        return False
    dut._log.info("Skipping %s test on top %s", label, getattr(dut, "_name", "<unknown>"))
    return True

# Derive P from port widths so the same test covers every sweep point.
def _infer_p_from_dut(dut, cfg: dict) -> int:

    psum_w = int(cfg["ACCEL_PSUM_W"])
    a_w = int(cfg["ACCEL_A_W"])
    b_w = int(cfg["ACCEL_B_W"])

    w_row = len(dut.c_row_data_flat)
    w_a = len(dut.a_rd_data_flat)
    w_b = len(dut.b_rd_data_flat)

    candidates = []
    for p in (1, 2, 4, 8):
        if (w_row == p * psum_w) and (w_a == p * a_w) and (w_b == p * b_w):
            candidates.append(p)

    if len(candidates) == 1:
        return candidates[0]

    if psum_w != 0 and (w_row % psum_w) == 0:
        p = w_row // psum_w
        return int(p)

    raise RuntimeError(
        "Cannot infer ACCEL_P from DUT widths. "
        f"c_row_data_flat={w_row}, a_rd_data_flat={w_a}, b_rd_data_flat={w_b}."
    )

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

def _to_u(x: int, width: int) -> int:

    return x & ((1 << width) - 1)

def _to_s(x_u: int, width: int) -> int:

    sign = 1 << (width - 1)
    return x_u - (1 << width) if (x_u & sign) else x_u

# Reset also initializes the external memory model inputs to known zeros.
async def _reset_dut(dut, *, c_row_ready: int) -> None:

    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())

    dut.rst_n.value = 0
    dut.core_start.value = 0
    dut.c_row_ready.value = c_row_ready
    dut.a_rd_data_flat.value = 0
    dut.b_rd_data_flat.value = 0

    for _ in range(5):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)

# Random output stalls verify both arithmetic and the unload handshake contract.
@cocotb.test()
async def test_gemm_core_random_backpressure(dut):
    if _skip_unless(dut, _is_owner1_dut, "gemm_core"):
        return

    cfg = _parse_accel_vh(_repo_root())

    TM = int(cfg["ACCEL_TM"])
    TN = int(cfg["ACCEL_TN"])
    K = int(cfg["ACCEL_K_MAX"])

    P = _infer_p_from_dut(dut, cfg)

    exp_p = _expected_p_from_env()
    if exp_p is not None:
        assert P == exp_p, (
            f"Requested ACCEL_P={exp_p} (env), but DUT compiled with P={P}. "
            "Check that the build passes -DACCEL_P=... to the HDL compiler."
        )

    A_W = len(dut.a_rd_data_flat) // P
    B_W = len(dut.b_rd_data_flat) // P
    PSUM_W = len(dut.c_row_data_flat) // P

    assert len(dut.a_rd_data_flat) == P * A_W
    assert len(dut.b_rd_data_flat) == P * B_W
    assert len(dut.c_row_data_flat) == P * PSUM_W
    assert P in (1, 2, 4, 8), f"Unexpected P={P} (expected 1/2/4/8)"
    assert (TM % P) == 0 and (TN % P) == 0, f"P={P} must divide TM={TM}, TN={TN}"

    dut._log.info(
        f"Config: TM={TM} TN={TN} K={K} P={P} A_W={A_W} B_W={B_W} PSUM_W={PSUM_W}"
    )

    await _reset_dut(dut, c_row_ready=0)

    # A fixed seed keeps failures reproducible while exercising signed extremes.
    rng = random.Random(1)

    A = np.array(
        [rng.randrange(-128, 128) for _ in range(TM * K)], dtype=np.int8
    ).reshape(TM, K)
    B = np.array(
        [rng.randrange(-128, 128) for _ in range(K * TN)], dtype=np.int8
    ).reshape(K, TN)
    C_golden = A.astype(np.int32) @ B.astype(np.int32)

    A_mem = A.reshape(-1)
    B_mem = B.reshape(-1)

    # Model combinational buffer reads from the addresses produced by the core.
    async def drive_ab():
        while True:
            await FallingEdge(dut.clk)

            a_addr_flat = int(dut.a_rd_addr_flat.value)
            b_addr_flat = int(dut.b_rd_addr_flat.value)

            a_addr_w = len(dut.a_rd_addr_flat) // P
            b_addr_w = len(dut.b_rd_addr_flat) // P

            a_data = 0
            b_data = 0
            for lane in range(P):
                a_addr = (a_addr_flat >> (lane * a_addr_w)) & ((1 << a_addr_w) - 1)
                b_addr = (b_addr_flat >> (lane * b_addr_w)) & ((1 << b_addr_w) - 1)

                assert 0 <= a_addr < A_mem.size, f"A addr out of range: {a_addr}"
                assert 0 <= b_addr < B_mem.size, f"B addr out of range: {b_addr}"

                a_val = int(A_mem[a_addr])
                b_val = int(B_mem[b_addr])

                a_data |= _to_u(a_val, A_W) << (lane * A_W)
                b_data |= _to_u(b_val, B_W) << (lane * B_W)

            dut.a_rd_data_flat.value = a_data
            dut.b_rd_data_flat.value = b_data

    cocotb.start_soon(drive_ab())

    dut.core_start.value = 1
    await RisingEdge(dut.clk)
    dut.core_start.value = 0

    seen = set()

    hold_active = False
    hold_snapshot = None

    max_cycles = 40000
    for _ in range(max_cycles):

        await FallingEdge(dut.clk)

        dut.c_row_ready.value = 1 if rng.random() < 0.7 else 0

        await ReadOnly()

        snap_valid = int(dut.c_row_valid.value)
        snap_ready = int(dut.c_row_ready.value)

        snap_shift = int(dut.mac_shift.value)

        snap = None
        if snap_valid:
            snap = {
                "data": int(dut.c_row_data_flat.value),
                "m_base": int(dut.c_m_base.value),
                "n_base": int(dut.c_n_base.value),
                "row_off": int(dut.c_row_off.value),
                "row_last": int(dut.c_row_last.value),
            }

        # Valid data and all address sideband must remain stable under backpressure.
        if snap_valid and (not snap_ready):
            if hold_active:
                assert snap == hold_snapshot, "ready=0 but output/sideband changed"
            else:
                hold_active = True
                hold_snapshot = snap
        else:
            hold_active = False
            hold_snapshot = None

        await RisingEdge(dut.clk)

        # The array may shift psums only on an accepted output row.
        exp_shift = 1 if (snap_valid and snap_ready) else 0
        assert snap_shift == exp_shift, (
            f"shift contract violated: mac_shift={snap_shift} exp={exp_shift} "
            f"(valid={snap_valid}, ready={snap_ready})"
        )

        # Reconstruct global C coordinates from tile base, row offset, and lane.
        if snap_valid and snap_ready:
            m_base = snap["m_base"]
            n_base = snap["n_base"]
            row_off = snap["row_off"]
            row_data_flat = snap["data"]

            for j in range(P):
                word_u = (row_data_flat >> (j * PSUM_W)) & ((1 << PSUM_W) - 1)
                word_s = _to_s(word_u, PSUM_W)

                m = m_base + row_off
                n = n_base + j
                idx = m * TN + n

                assert 0 <= m < TM and 0 <= n < TN, f"Out of range m={m} n={n}"
                assert idx not in seen, f"Duplicate output m={m} n={n}"
                seen.add(idx)

                exp = int(C_golden[m, n])
                assert word_s == exp, f"Mismatch C[{m},{n}] got={word_s} exp={exp}"

            if len(seen) == TM * TN:
                break

    assert len(seen) == TM * TN, f"Incomplete outputs {len(seen)}/{TM*TN}"

    done_seen = False
    for _ in range(50):
        await RisingEdge(dut.clk)
        if int(dut.core_done.value) == 1:
            done_seen = True
            break
    assert done_seen, "core_done not seen"

# With ready held high, measure the unobstructed cycle count for each P value.
@cocotb.test()
async def test_gemm_core_perf_nominal(dut):

    if _skip_unless(dut, _is_owner1_dut, "gemm_core"):
        return

    cfg = _parse_accel_vh(_repo_root())

    TM = int(cfg["ACCEL_TM"])
    TN = int(cfg["ACCEL_TN"])
    K = int(cfg["ACCEL_K_MAX"])

    P = _infer_p_from_dut(dut, cfg)

    A_W = len(dut.a_rd_data_flat) // P
    B_W = len(dut.b_rd_data_flat) // P
    PSUM_W = len(dut.c_row_data_flat) // P

    assert P in (1, 2, 4, 8)
    assert (TM % P) == 0 and (TN % P) == 0

    dut._log.info(f"[PERF] Config: TM={TM} TN={TN} K={K} P={P}")

    await _reset_dut(dut, c_row_ready=1)

    rng = random.Random(1234)
    A = np.array(
        [rng.randrange(-128, 128) for _ in range(TM * K)], dtype=np.int8
    ).reshape(TM, K)
    B = np.array(
        [rng.randrange(-128, 128) for _ in range(K * TN)], dtype=np.int8
    ).reshape(K, TN)
    C_golden = A.astype(np.int32) @ B.astype(np.int32)

    A_mem = A.reshape(-1)
    B_mem = B.reshape(-1)

    async def drive_ab():
        while True:
            await FallingEdge(dut.clk)

            a_addr_flat = int(dut.a_rd_addr_flat.value)
            b_addr_flat = int(dut.b_rd_addr_flat.value)

            a_addr_w = len(dut.a_rd_addr_flat) // P
            b_addr_w = len(dut.b_rd_addr_flat) // P

            a_data = 0
            b_data = 0
            for lane in range(P):
                a_addr = (a_addr_flat >> (lane * a_addr_w)) & ((1 << a_addr_w) - 1)
                b_addr = (b_addr_flat >> (lane * b_addr_w)) & ((1 << b_addr_w) - 1)

                assert 0 <= a_addr < A_mem.size, f"A addr out of range: {a_addr}"
                assert 0 <= b_addr < B_mem.size, f"B addr out of range: {b_addr}"

                a_val = int(A_mem[a_addr])
                b_val = int(B_mem[b_addr])

                a_data |= _to_u(a_val, A_W) << (lane * A_W)
                b_data |= _to_u(b_val, B_W) << (lane * B_W)

            dut.a_rd_data_flat.value = a_data
            dut.b_rd_data_flat.value = b_data

    cocotb.start_soon(drive_ab())

    dut.core_start.value = 1
    await RisingEdge(dut.clk)
    dut.core_start.value = 0

    cycle = 0
    first_valid_cycle = None
    first_fire_cycle = None
    last_fire_cycle = None
    done_cycle = None

    fire_count = 0
    elem_count = 0
    mac_ops_total = TM * TN * K

    seen = set()

    max_cycles = 100000
    while cycle < max_cycles:

        await FallingEdge(dut.clk)
        await ReadOnly()

        snap_valid = int(dut.c_row_valid.value)
        snap_ready = int(dut.c_row_ready.value)

        snap = None
        if snap_valid:
            snap = {
                "data": int(dut.c_row_data_flat.value),
                "m_base": int(dut.c_m_base.value),
                "n_base": int(dut.c_n_base.value),
                "row_off": int(dut.c_row_off.value),
            }

        await RisingEdge(dut.clk)
        await ReadOnly()
        cycle += 1

        if snap_valid and first_valid_cycle is None:
            first_valid_cycle = cycle

        if snap_valid and snap_ready:
            if first_fire_cycle is None:
                first_fire_cycle = cycle
            last_fire_cycle = cycle

            fire_count += 1
            elem_count += P

            m = snap["m_base"] + snap["row_off"]
            for j in range(P):
                n = snap["n_base"] + j
                idx = m * TN + n

                assert 0 <= m < TM and 0 <= n < TN, f"Out of range m={m} n={n}"
                assert idx not in seen, f"Duplicate output m={m} n={n}"
                seen.add(idx)

                word_u = (snap["data"] >> (j * PSUM_W)) & ((1 << PSUM_W) - 1)
                word_s = _to_s(word_u, PSUM_W)
                exp = int(C_golden[m, n])
                assert word_s == exp, f"Mismatch C[{m},{n}] got={word_s} exp={exp}"

        if int(dut.core_done.value):
            done_cycle = cycle
            break

    assert done_cycle is not None, "core_done not seen"
    assert first_valid_cycle is not None, "No valid output observed"
    assert first_fire_cycle is not None, "No output handshake observed"
    assert last_fire_cycle is not None
    assert len(seen) == TM * TN, f"Incomplete outputs {len(seen)}/{TM*TN}"

    expected_fire_count = (TM * TN) // P
    assert fire_count == expected_fire_count, (
        f"Unexpected fire_count={fire_count}, exp={expected_fire_count}"
    )
    assert elem_count == TM * TN, f"Unexpected elem_count={elem_count}, exp={TM*TN}"

    output_window_cycles = last_fire_cycle - first_fire_cycle + 1

    elem_per_cycle_output_window = elem_count / output_window_cycles
    elem_per_cycle_end_to_end = elem_count / done_cycle
    mac_per_cycle_end_to_end = mac_ops_total / done_cycle
    row_beats_per_cycle_output = fire_count / output_window_cycles

    metrics = {
        "P": P,
        "TM": TM,
        "TN": TN,
        "K": K,
        "clock_period_ns": 10,
        "first_valid_cycle": first_valid_cycle,
        "first_fire_cycle": first_fire_cycle,
        "last_fire_cycle": last_fire_cycle,
        "done_cycle": done_cycle,
        "output_window_cycles": output_window_cycles,
        "fire_count": fire_count,
        "elem_count": elem_count,
        "mac_ops_total": mac_ops_total,
        "row_beats_per_cycle_output": row_beats_per_cycle_output,
        "elem_per_cycle_output_window": elem_per_cycle_output_window,
        "elem_per_cycle_end_to_end": elem_per_cycle_end_to_end,
        "mac_per_cycle_end_to_end": mac_per_cycle_end_to_end,
    }

    dut._log.info("[PERF] " + json.dumps(metrics, ensure_ascii=False))

    out = Path.cwd() / f"perf_metrics_p{P}.json"
    out.write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")
