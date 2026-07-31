# GEMM TPU Full Stack

This repository places two related project snapshots in one monorepo:

- [`frontend/`](frontend/) contains the synthesizable GEMM accelerator RTL, its
  Wishbone integration, and Cocotb verification.
- [`backend-ai/`](backend-ai/) contains an AI-assisted optimisation loop that
  runs OpenLane, reads physical-design metrics, and proposes validated changes
  to an OpenLane configuration.

The two parts support the same broader goal—developing and optimising an ASIC
accelerator—but they remain separate tools. The backend is not automatically
wired to the RTL in `frontend/`; it must be pointed at a prepared design in an
external OpenLane2 workspace.

## Repository map

| Path | Purpose |
| --- | --- |
| [`frontend/`](frontend/) | GEMM TPU hardware design and verification. |
| [`frontend/rtl/`](frontend/rtl/) | Synthesizable Verilog-2001 source code. |
| [`frontend/sim/`](frontend/sim/) | Cocotb/Make simulation entry points. |
| [`frontend/tests/`](frontend/tests/) | Python drivers, scoreboards, and golden models. |
| [`backend-ai/`](backend-ai/) | Wrapper folder for the AI-assisted OpenLane tool. |
| [`backend-ai/Major-Project--main/`](backend-ai/Major-Project--main/) | Backend source, configuration, memory, and plotting utilities. |

## Frontend: GEMM accelerator

The default problem size is an 8 × 8 signed INT8 matrix multiplication with
signed INT32 accumulation:

```text
C[8x8] = A[8x8] x B[8x8]
```

The physical processing array is parameterised by `ACCEL_P`. Supported
regression values are `P = 1, 2, 4, 8`; the controller traverses the full 8 × 8
matrix in `P × P` output tiles.

### RTL folders

| Folder | What it contains |
| --- | --- |
| [`rtl/include/`](frontend/rtl/include/) | Shared dimensions, widths, flattened-bus helpers, and row-major address macros. |
| [`rtl/owner1_broadcast/`](frontend/rtl/owner1_broadcast/) | Simple baseline that broadcasts A/B values to a `P × P` outer-product array and serialises writeback. |
| [`rtl/owner1_flow_v1/`](frontend/rtl/owner1_flow_v1/) | Systolic implementation with boundary skew registers inside the array. |
| [`rtl/owner1_flow_v2/`](frontend/rtl/owner1_flow_v2/) | Systolic implementation that moves lane skew into the core's address schedule. This is the version used by the full golden build. |
| [`rtl/owner2/`](frontend/rtl/owner2/) | Input loaders, operand buffers, result-row serialisation, requantisation/ReLU, and max-pooling. |
| [`rtl/owner3/`](frontend/rtl/owner3/) | Top-level assembly, Wishbone registers/result windows, Caravel wrapper, and isolated-test stubs. |

## Backend: AI-assisted OpenLane optimisation

The backend repeatedly runs an external OpenLane design, extracts physical
metrics, gives the latest state to an LLM, validates the returned parameter
changes, and applies approved changes to the design's `config.json`.

### Backend folders

| Folder | What it contains |
| --- | --- |
| [`Actions/`](backend-ai/Major-Project--main/Actions/) | Parses and validates LLM suggestions, then applies approved configuration changes. |
| [`Agent/`](backend-ai/Major-Project--main/Agent/) | Builds run state, stores optimisation memory, creates prompts, and calls the model API. |
| [`Config/`](backend-ai/Major-Project--main/Config/) | User settings, path construction, editable-parameter bounds, and structured output schema. |
| [`Flow/`](backend-ai/Major-Project--main/Flow/) | Launches OpenLane through Nix, detects failures, reads `metrics.csv`, and handles termination. |
| [`Governance/`](backend-ai/Major-Project--main/Governance/) | API cost accounting and experimental stopping/improvement checks. |
| [`metric_plots/`](backend-ai/Major-Project--main/metric_plots/) | Generated optimisation plots. |
