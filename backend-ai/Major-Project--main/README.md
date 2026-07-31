# AI-Assisted OpenLane Optimisation Agent

This Python application automates an iterative OpenLane configuration search.
For every iteration it runs a design through OpenLane, records metrics and
failures, asks an LLM for a constrained configuration update, validates the
response, and applies approved changes to the design used by the next run.

The application operates on a design in an external OpenLane2 workspace. It
does not copy RTL from the monorepo or launch the TPU frontend automatically.

## Iteration flow

[`Main.py`](Main.py) performs these steps:

1. Build the design, run, prompt, memory, and notification paths.
2. Build a strict response schema from the current OpenLane configuration.
3. Run OpenLane inside a Nix development shell.
4. Inspect sign-off output and parse selected metrics from the latest
   `final/metrics.csv`.
5. Build a state record containing configuration, metrics, failures, and
   run-to-run changes.
6. Save that state and a compact summary in `memory.json`.
7. Create `prompt.json` and request a structured model response.
8. Validate immutable fields, parameter bounds, cross-field rules, and change
   size before applying an update.
9. Log token usage/cost and repeat until termination or the internal loop cap.

## Source layout

### `Actions/`

| File | Purpose |
| --- | --- |
| [`Validator.py`](Actions/Validator.py) | Parse model output and enforce schema consistency, editable parameter rules, cross-field constraints, and change policies. |
| [`Executor.py`](Actions/Executor.py) | Apply the validated patch to the external OpenLane `config.json` and report old/new values. |

### `Agent/`

| File | Purpose |
| --- | --- |
| [`State_builder.py`](Agent/State_builder.py) | Convert raw metrics and errors into a normalised state and calculate changes from the previous run. |
| [`Memory.py`](Agent/Memory.py) | Load/save run history, retain recent states, track the selected best run, and detect plateaus. |
| [`Decision_engine.py`](Agent/Decision_engine.py) | Combine current configuration and memory into the optimisation prompt; record best-run decisions. |
| [`Call_API.py`](Agent/Call_API.py) | Read `prompt.json`, call the OpenAI Responses API with the Pydantic output schema, and return a dictionary. |

### `Config/`

| File | Purpose |
| --- | --- |
| [`Settings.py`](Config/Settings.py) | Main user settings: design name, OpenLane timeout, reasoning level, API pricing, metrics, and Pydantic limits for editable parameters. |
| [`Setup_paths.py`](Config/Setup_paths.py) | Resolve the application directory and construct paths under `~/openlane2/my_designs/<design>/`. |
| [`Schema.py`](Config/Schema.py) | Read immutable fields from the current OpenLane config and build the structured model-output schema. |

### `Flow/`

| File | Purpose |
| --- | --- |
| [`Runner.py`](Flow/Runner.py) | Execute `nix develop <openlane2> --command openlane <config>` with a timer and timeout. |
| [`Errors.py`](Flow/Errors.py) | Classify timeout and sign-off failures, including antenna, LVS, DRC, timing, slew, and capacitance checks. |
| [`Parser.py`](Flow/Parser.py) | Find the newest run and select the desired values from `final/metrics.csv`. |
| [`Terminator.py`](Flow/Terminator.py) | Read the model's `terminate_flow` decision. |

### `Governance/`

| File | Purpose |
| --- | --- |
| [`API_cost.py`](Governance/API_cost.py) | Calculate and append per-call token costs to `api_costs.json`. |
| [`Governor.py`](Governance/Governor.py) | Experimental invalid-output, metric-validity, plateau, and improvement checks. It is not called by the current `Main.py` loop. |

### Root data and utility files

| File | Purpose |
| --- | --- |
| [`Main.py`](Main.py) | Application entry point and iteration coordinator. |
| [`memory.json`](memory.json) | Persistent run history used to give the next decision temporal context. |
| [`prompt.json`](prompt.json) | Generated structured prompt sent to the model. |
| [`api_costs.json`](api_costs.json) | Token and estimated cost records by run. |
| [`Plot_Convergence.py`](Plot_Convergence.py) | Plot normalised power, area, violation, timing, and composite convergence. |
| [`Results_Plotting.py`](Results_Plotting.py) | Generate a dashboard and detailed metric-group plots. |
| [`metric_plots/`](metric_plots/) | Default plot output directory. |
| [`restore_config.py`](restore_config.py) | Search the current tree for config and backup files; it does not restore a file automatically. |
| [`flow_end_notification.mp3`](flow_end_notification.mp3) | Sound played after an OpenLane run by the current macOS-oriented runner. |
| [`requirements.txt`](requirements.txt) | Python package versions used by the backend. |

`__pycache__/` folders and `.pyc` files are generated Python bytecode snapshots;
they are not source modules and are not needed for understanding the design.

## Setup

### 1. Prepare OpenLane2

By default, [`Config/Setup_paths.py`](Config/Setup_paths.py) expects:

```text
~/openlane2/
└── my_designs/
    └── <design_name>/
        ├── config.json
        └── runs/
```

Install/configure Nix and OpenLane2 there, or edit `Setup_paths.py` for a
different layout.

### 2. Select the design and limits

Edit [`Config/Settings.py`](Config/Settings.py):

- `design_name_str` selects the folder under `my_designs/` (currently `s1488`).
- `openlane_timeout_duration` limits each OpenLane subprocess.
- `reasoning_dict` configures model reasoning effort.
- `ConfigChanges` defines exactly which OpenLane parameters may change and
  their allowable types/ranges.
- `desired_metrics` selects values copied from OpenLane's `metrics.csv`.
- the API cost values are estimates used for local accounting.

To optimise the TPU, prepare a compatible TPU OpenLane design folder and set
`design_name_str` to that folder name. The
[`../../frontend/config.json`](../../frontend/config.json) file is only a
configuration snapshot; its RTL paths must be valid inside the chosen OpenLane
design workspace.

### 3. Install Python dependencies and API credentials

```bash
python -m pip install -r requirements.txt
```

Set `OPENAI_API_KEY` in the environment before starting the loop.

### 4. Check platform-specific commands

[`Flow/Runner.py`](Flow/Runner.py) currently invokes:

```text
nix develop <openlane2-path> --command openlane <config-path>
```

It also calls `afplay` for the completion sound. `afplay` is a macOS command;
disable or replace the notification function when running on Linux or Windows.

## Run

From this directory:

```bash
python Main.py
```

The process can be long-running and can modify the external design's
`config.json` after a response passes validation. Keep that design under version
control or make a recoverable backup before running the agent.

## Plot saved results

Both plotting scripts read `memory.json` and write to `metric_plots/` by
default. They also import `matplotlib` and `numpy`, which are not currently
listed in the backend `requirements.txt` and may need to be installed
separately:

```bash
python Plot_Convergence.py --memory memory.json --output metric_plots
python Results_Plotting.py --memory memory.json --output metric_plots
```

## Recommended reading order

1. [`Main.py`](Main.py)
2. [`Config/Settings.py`](Config/Settings.py) and
   [`Config/Setup_paths.py`](Config/Setup_paths.py)
3. [`Flow/Runner.py`](Flow/Runner.py), [`Flow/Errors.py`](Flow/Errors.py), and
   [`Flow/Parser.py`](Flow/Parser.py)
4. [`Agent/State_builder.py`](Agent/State_builder.py) and
   [`Agent/Memory.py`](Agent/Memory.py)
5. [`Agent/Decision_engine.py`](Agent/Decision_engine.py) and
   [`Agent/Call_API.py`](Agent/Call_API.py)
6. [`Actions/Validator.py`](Actions/Validator.py) and
   [`Actions/Executor.py`](Actions/Executor.py)
