# GEMM TPU RTL and Verification

This folder contains a parameterised signed-INT8 GEMM accelerator, optional
INT8 post-processing, a Wishbone software interface, and Cocotb verification.

The default configuration computes:

```text
C[8x8] = A[8x8] x B[8x8]
```

A and B contain signed INT8 values. Each output is accumulated as signed INT32.
`ACCEL_P` selects the physical `P × P` PE array; regressions cover
`P = 1, 2, 4, 8` while the logical matrix remains 8 × 8.

## Design overview

The complete build in [`sim/golden/Makefile`](sim/golden/Makefile) combines:

1. Flow v2 compute RTL from [`rtl/owner1_flow_v2/`](rtl/owner1_flow_v2/).
2. Buffering, streaming, and post-processing from
   [`rtl/owner2/`](rtl/owner2/).
3. Top-level and Wishbone integration from [`rtl/owner3/`](rtl/owner3/).

The data path is:

```text
Wishbone pushes -> A/B loaders -> A/B buffers -> GEMM core
-> P-wide result rows -> C serializer -> raw result memory
-> optional requant/ReLU -> optional 2x2 max-pool -> result windows
```

## Features

- 8 × 8 signed INT8 matrix multiplication with INT32 accumulation
- Configurable `P × P` systolic PE array (`P = 1, 2, 4, 8`)
- Output-stationary dataflow with backpressure-aware row-stream drain
- Optional INT32-to-INT8 requantisation, ReLU, and 2 × 2 max-pooling
- Wishbone slave interface for SoC integration
- Cocotb verification with a NumPy golden model

## Directory structure

### `rtl/`

All RTL source files are written in synthesizable Verilog-2001.

- `rtl/include/` — Shared `accel.vh` parameters, widths, and macros.
- `rtl/owner1_broadcast/` — Broadcast baseline compute core.
- `rtl/owner1_flow_v1/` — Systolic core with array-side input skew registers.
- `rtl/owner1_flow_v2/` — Systolic core with scheduled input pre-skew; used by
  the complete build.
- `rtl/owner2/` — Stream loaders, A/B buffers, C unloader, requantisation/ReLU,
  and max-pooling.
- `rtl/owner3/` — Top-level integration, Wishbone peripheral, Caravel-style
  wrapper, and isolated-test stubs.

### `sim/`

Makefile-based Cocotb simulation entry points:

- `sim/owner1/` — Flow v2 compute-core tests.
- `sim/owner2/` — Data-movement and post-processing block tests.
- `sim/owner3/` — Top-level and Wishbone tests with deterministic stubs.
- `sim/golden/` — Complete Flow v2, owner2, and owner3 integration.

### `tests/`

Cocotb test suites containing stream drivers, Wishbone transactions,
backpressure checks, and the NumPy reference model.

### `.github/workflows/`

Preserved GitHub Actions configuration for the Cocotb regression jobs.

### Root files

- `config.json` — OpenLane design configuration snapshot.
- `requirements.txt` — Python verification dependencies.
- `.gitignore` — Simulator, virtual-environment, and cache exclusions.
