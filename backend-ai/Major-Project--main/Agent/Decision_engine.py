"""
Dry Run Decision Engine - Builds the prompt and saves to prompt.json
No API call, no settings.py needed. Just paste the output into DeepSeek chat.

Usage:
    1. Set the paths below to match your design
    2. Run: python dry_run_decision_engine.py
    3. Open prompt.json
    4. Paste system_prompt as system message in DeepSeek chat
    5. Paste the rest as the user message
    6. See what changes DeepSeek suggests
"""

import json, os, sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "Actions"))

# --- System prompt (static, same every run) ---
SYSTEM_PROMPT = """
You are an expert ASIC design engineer optimising a Verilog hardware accelerator using OpenLane2.

You are given:
• current_run metrics + config
• previous_run metrics + config
• best_run metrics + config
• flow_success and error details

---

PRIMARY OBJECTIVES (in order of importance):

1. Achieve a successful OpenLane run (flow_success = true)
   - success is defined as full sign-off (no antenna/DRC/LVS/STA violations)
2. Once successful runs exist, optimise:
   - timing (performance)
   - power
   - area

---

REFERENCE RULE:

• ALL changes must be derived from best_run config
• Do NOT base decisions on current_run if it is worse than best_run
• If current_run is better, update best_run accordingly

---

CLOCK PERIOD RULE (CRITICAL SINGLE SOURCE OF TRUTH):

• CLOCK_PERIOD is a GLOBAL DESIGN CONSTRAINT
• It MUST ONLY exist as ONE uniform value in the configuration (top-level)
• You must fill it in within the top level of the JSON AND within the nested PDK/SCL configurations (THEY MUST BE THE SAME VALUE)
• All timing behaviour (SDC generation, STA constraints) derives from the top-level CLOCK_PERIOD ONLY

---

CORE BEHAVIOUR:

CASE 1 — NO SUCCESSFUL RUN YET:

• Focus ONLY on achieving sign-off
• Be exploratory (larger changes allowed, up to ±15%)
• You may modify up to 3 parameters per step

CRITICAL RULE (congestion/antenna failures):
If routing congestion or antenna issues occur:
• MUST reduce:
  - PL_TARGET_DENSITY
  - FP_CORE_UTIL

• MAY increase:
  - GLB_RT_ADJUSTMENT
  - GLB_RT_OVERFLOW_ITERS

• NEVER increase density/utilisation when congestion exists

---

CASE 2 — SUCCESSFUL RUN EXISTS:

• Focus on optimisation only (PPA improvement)
• Make small changes (≤ ±5%)
• Modify at most 2 parameters per step
• Do NOT destabilise a working design

---

GENERAL RULES:

• Do NOT repeat ineffective changes
• If a change worsens results, reverse direction
• Keep modifications minimal and targeted
• Avoid unnecessary parameter drift

---

BEST RUN HANDLING (CRITICAL):

The best_run is the PRIMARY reference configuration.

Rules:
• All updated configurations MUST be derived from best_run
• If current_run < best_run → ignore current_run direction
• If current_run > best_run → update best_run

Best run update conditions:
• must show clear improvement in valid PPA metrics
• must not introduce instability or violations

---

WHEN NO SUCCESSFUL RUN EXISTS:

• best_run may still contain failed designs
• use it only as a baseline reference
• objective is to reach first sign-off state, not refine metrics

---

AFTER FIRST SUCCESSFUL RUN:

• best_run becomes stable anchor
• future changes must be incremental refinements
• only explore wider parameter space if:
  - stagnation occurs, OR
  - system regresses into failure

---

ERROR RESPONSE PRIORITY ORDER:

1. Follow explicit error message instructions (HIGHEST PRIORITY)
2. Fix sign-off violations (STA/DRC/LVS)
3. Fix congestion / routing / antenna issues
4. Apply heuristic optimisation
5. Only then explore improvements

---

OUTPUT REQUIREMENT:

Return ONLY valid JSON:

{
  "current_settings": {...},
  "updated_settings": {...},
  "updated_parameters": {...},
  "reasoning": "...",
  "is_best_run": true/false,
  "terminate_flow": true/false
}
"""


def load_config(config_path):
    """Load config.json from disk."""
    try:
        with open(config_path, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"ERROR: Config file not found: {config_path}")
        return None
    except json.JSONDecodeError as e:
        print(f"ERROR: Invalid JSON in config file: {e}")
        return None


def load_memory(memory_path):
    """Load memory.json and return a summary with only run counts, best run, and previous run."""
    if not os.path.exists(memory_path):
        print(f"WARNING: No memory file found at {memory_path}, using empty memory")
        return {
            "run_counts": {"total": 0, "total_successful": 0, "total_failed": 0},
            "best_run": None,
            "previous_run": None,
            "plateau": False,
        }

    try:
        with open(memory_path, "r") as f:
            data = json.load(f)

        all_history = data.get("all_history", [])
        successful = [s for s in all_history if s["success"]]
        failed = [s for s in all_history if not s["success"]]

        # --- Best run (LLM-selected) ---
        best_run_id = data.get("best_run_id")
        best_run = None
        if best_run_id:
            for s in all_history:
                if s["run_id"] == best_run_id:
                    best_run = s
                    break

        # --- Previous run (the run before the current one, regardless of success/failure) ---
        previous_run = all_history[-2] if len(all_history) >= 2 else None

        return {
            "run_counts": {
                "total": len(all_history),
                "total_successful": len(successful),
                "total_failed": len(failed),
            },
            "best_run": best_run,
            "previous_run": previous_run,
        }

    except (json.JSONDecodeError, Exception) as e:
        print(f"ERROR: Could not load memory file: {e}")
        return None


def get_latest_state(memory_path, design_name):
    """Get the most recent state from memory to use as current state."""
    if not os.path.exists(memory_path):
        return {
            "run_id": "no_runs_yet",
            "design_name": design_name,
            "flow_success": True,
            "error": None,
            "recoverable": None,
            "metrics": {},
            "metric_changes": {},
        }

    try:
        with open(memory_path, "r") as f:
            data = json.load(f)

        all_history = data.get("all_history", [])

        if not all_history:
            return {
                "run_id": "no_runs_yet",
                "design_name": design_name,
                "flow_success": True,
                "error": None,
                "recoverable": None,
                "metrics": {},
                "metric_changes": {},
            }

        latest = all_history[-1]

        return {
            "run_id": latest.get("run_id", "unknown"),
            "design_name": latest.get("design_name", design_name),
            "flow_success": latest.get("success", False),
            "error": latest.get("error") if not latest.get("success") else None,
            "recoverable": latest.get("recoverable") if not latest.get("success") else None,
            "metrics": latest.get("metrics", {}),
            "metric_changes": latest.get("metric_changes", {}),
        }

    except (json.JSONDecodeError, Exception) as e:
        print(f"ERROR: Could not read state from memory: {e}")
        return None


def save_llm_response(response, run_id, responses_path="llm_responses.json"):
    """
    Append an LLM response to the responses JSON file.

    Args:
        response:       The parsed LLM response dict
        run_id:         The run_id this response relates to
        responses_path: Path to the responses JSON file
    """
    # Load existing responses
    if os.path.exists(responses_path):
        try:
            with open(responses_path, "r") as f:
                data = json.load(f)
        except (json.JSONDecodeError, Exception):
            data = {"responses": []}
    else:
        data = {"responses": []}

    # Append new response with timestamp and run_id
    data["responses"].append({
        "timestamp": datetime.now().isoformat(),
        "run_id": run_id,
        "changes": response.get("changes", {}),
        "reasoning": response.get("reasoning", ""),
        "best_run_id": response.get("best_run_id", None),
    })

    with open(responses_path, "w") as f:
        json.dump(data, f, indent=2)

    print(f"[DecisionEngine] Response saved to {responses_path}")



def update_best_run_from_llm(validation_result, memory):
    """
    Read the LLM's best_run judgement from a ValidationResult and update
    Memory's best_run_id accordingly.

    Args:
        validation_result: ValidationResult returned by Validator.validate_llm_response()
        memory:            The Memory instance managing run history

    Returns:
        The run_id that was set as best, or None if no update was made.
    """
    best_run = validation_result.parsed_is_best_run

    # First run — always set as best regardless of LLM judgement
    if not memory.best_run_id:
        if not memory.all_history:
            print("[DecisionEngine] WARNING: First run but no runs in memory.")
            return None
        run_id = memory.all_history[-1]["run_id"]
        memory.set_best_run(run_id)
        print(f"[DecisionEngine] First run — automatically set best_run to: {run_id}")
        return run_id

    if best_run is None:
        print("[DecisionEngine] best_run not provided by LLM — best_run_id unchanged.")
        return None

    if best_run:
        # Current run is better — update best_run to the most recent run
        if not memory.all_history:
            print("[DecisionEngine] WARNING: best_run=True but no runs in memory.")
            return None
        run_id = memory.all_history[-1]["run_id"]
        memory.set_best_run(run_id)
        print(f"[DecisionEngine] best_run=True — updated best_run to current run: {run_id}")
        return run_id
    else:
        # Current run is not better than best run — keep best_run_id unchanged
        print("[DecisionEngine] best_run=False — current run did not beat the best run, best_run_id unchanged.")
        return None


def build_and_save_prompt(config_path, memory_path, design_name, prompt_output="prompt.json"):
    """
    Build the full prompt and save to prompt.json.

    Args:
        config_path:    Path to the design's config.json
        memory_path:    Path to Memory.py's save file (memory.json)
        design_name:    Name of the design e.g. "pm32"
        prompt_output:  Where to save the prompt (default: prompt.json)
    """
    
    print("\n" + "=" * 60) # debugging / TO BE DELETED
    print("BUILDING AND SAVING LLM PROMPT") # debugging / TO BE DELETED
    print("=" * 60) # debugging / TO BE DELETED

    # Load all data
    config = load_config(config_path)
    if config is None:
        print("CONFIG LOAD FAILED")
        return

    memory_summary = load_memory(memory_path)
    if memory_summary is None:
        print("MEMORY LOAD FAILED")
        return

    current_state = get_latest_state(memory_path, design_name)
    if current_state is None:
        print("STATE LOAD FAILED")
        return

    # Build the prompt
    prompt_data = {
        "system_prompt": SYSTEM_PROMPT,
        "current_state": current_state,
        "memory_summary": memory_summary,
        "current_config": config,
        "task": (
            "Based on the current_state and memory_summary, propose changes to current_config "
            "that will improve the design metrics. Also set best_run = true or best_run = false depending on whether you"
            "think current_state or memory_summary.best_run has the better overall metrics respectively. Respond with ONLY valid JSON."
        ),
    }

    # Save to file
    try:
        with open(prompt_output, "w") as f:
            json.dump(prompt_data, f, indent=2)
        print(f"Prompt saved to {prompt_output}")

    except Exception as e:
        print(f"ERROR: Could not save prompt: {e}")
