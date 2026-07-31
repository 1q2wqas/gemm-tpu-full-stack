"""
Memory - Stores all states and generates memory summaries for Decision Engine

Job:
1. Receive structured state from StateBuilder
2. Append to all_history
3. If success: reset invalid counter; if failure and not recoverable: increment invalid counter
4. Generate memory summary (best run, previous successful run)
5. Check for plateau (all metrics flat over last N successful runs)
6. Return state + memory summary to Decision Engine
7. Save all history to JSON file for analysis

Memory does NOT judge whether changes are improvements - that is handled
by the Decision Engine and the LLM via a separate objective/context file.
"""

import json, os
from Agent.State_builder import StateBuilder

_state_builder = StateBuilder()


class Memory:

    def __init__(self, save_path=None, recent_run_limit=5):
        """
        Args:
            save_path:        File path for the memory JSON file.
                              If provided, Memory loads existing history on init
                              and saves after every process_state call.
            recent_run_limit: How many recent runs to include in the summary
        """
        self.save_path = save_path
        self.all_history = []
        self.invalid_counter = 0
        self.recent_run_limit = recent_run_limit
        self.best_run_id = None  # Set by LLM via set_best_run()

        # Load existing history from file if it exists
        if self.save_path:
            self._load_from_file()

    # ==================================================================
    # MAIN ENTRY POINT
    # ==================================================================

    def process_state(self, state):
        """
        Process a state from StateBuilder and return state + memory summary.

        Args:
            state: Dict from StateBuilder (has 'success' field)

        Returns:
            Dict with:
                'state'          - the original state (passed through)
                'memory_summary' - structured summary for Decision Engine
                'plateau'        - Bool, True if plateau detected
        """

        print("\n" + "=" * 60) # debugging / TO BE DELETED
        print("STORING FLOW RESULTS INTO MEMORY") # debugging / TO BE DELETED
        print("=" * 60) # debugging / TO BE DELETED

        self.all_history.append(state)

        # First run is always set as the best run
        if self.best_run_id is None:
            self.best_run_id = state["run_id"]
            print(f"[Memory] First run — set best_run_id to: {self.best_run_id}")

        if state["success"]:
            print("Processed successful state") # debugging / TO BE DELETED
            self.invalid_counter = 0
        else:
            print("Processed failed state") # debugging / TO BE DELETED
            if not state.get("recoverable", False):
                self.invalid_counter += 1

        memory_summary = self._generate_summary()
        plateau = self._check_plateau() if state["success"] else False

        self._save_to_file()

        return {
            "state": state,
            "memory_summary": memory_summary,
            "plateau": plateau,
        }

    # ==================================================================
    # MEMORY SUMMARY (sent to Decision Engine)
    # ==================================================================

    def _generate_summary(self):
        """
        Generate the memory summary for Decision Engine.

        Contains:
        - run_counts: total runs, successes, and failures
        - best_run: the LLM-selected best run (metrics + config)
        - previous_run: the run immediately before the current one (success or failure)
        """
        summary = {}

        successful = [s for s in self.all_history if s["success"]]
        failed = [s for s in self.all_history if not s["success"]]

        # --- Run counts ---
        summary["run_counts"] = {
            "total": len(self.all_history),
            "total_successful": len(successful),
            "total_failed": len(failed),
        }

        # --- Best run (as judged by LLM) ---
        best_state = self.get_best_state()
        summary["best_run"] = best_state if best_state else None

        # --- Metric changes: current run vs best run ---
        current = self.all_history[-1] if self.all_history else None
        if current and best_state and current["run_id"] != best_state["run_id"]:
            summary["current_vs_best_changes"] = _state_builder._calculate_changes(
                current.get("metrics", {}),
                best_state.get("metrics", {}),
            )
        else:
            summary["current_vs_best_changes"] = None

        # --- Previous run (the run before the current one, regardless of success/failure) ---
        if len(self.all_history) >= 2:
            summary["previous_run"] = self.all_history[-2]
        else:
            summary["previous_run"] = None

        return summary

    # ==================================================================
    # BEST RUN TRACKING (set by LLM)
    # ==================================================================

    def set_best_run(self, run_id):
        """Called after LLM response to record which run it judged as best."""
        self.best_run_id = run_id
        self._save_to_file()

    def get_best_state(self):
        """Return the full state for the LLM-selected best run."""
        if self.best_run_id is None:
            return None
        for s in self.all_history: # CHANGED BY MAXIMO
            if s["run_id"] == self.best_run_id:
                return s
        return None

    # ==================================================================
    # PLATEAU DETECTION
    # ==================================================================

    def _check_plateau(self):
        """
        Check if all metrics have been flat (within 6% variation)
        over the last N successful runs.
        """
        plateau_window = 5

        successful = [s for s in self.all_history if s["success"]]

        if len(successful) < plateau_window + 1:
            return False

        recent = successful[-plateau_window:]

        # Collect all metric names from recent runs
        all_metric_names = set()
        for s in recent:
            all_metric_names.update(s.get("metrics", {}).keys())

        # Check each metric for variation
        for metric_name in all_metric_names:
            values = []
            for s in recent:
                val = s.get("metrics", {}).get(metric_name)
                if val is not None:
                    values.append(val)

            if len(values) < plateau_window:
                continue

            min_val = min(values)
            max_val = max(values)

            if min_val == 0 and max_val == 0:
                continue

            if min_val != 0:
                variation = ((max_val - min_val) / abs(min_val)) * 100
            else:
                variation = 100.0

            if variation >= 6.0:
                return False

        print(f"[Memory] Plateau detected: all metrics within 6% over last {plateau_window} runs")
        return True

    # ==================================================================
    # FILE PERSISTENCE
    # ==================================================================

    def _save_to_file(self):
        """Save all history to JSON file."""
        if not self.save_path:
            return

        data = {
            "all_history": self.all_history,
            "invalid_counter": self.invalid_counter,
            "best_run_id": self.best_run_id,
        }

        try:
            with open(self.save_path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"[Memory] ERROR: Could not save to {self.save_path}: {e}")

    def _load_from_file(self):
        """Load existing history from JSON file."""
        if not self.save_path or not os.path.exists(self.save_path):
            return

        try:
            with open(self.save_path, "r") as f:
                data = json.load(f)

            self.all_history = data.get("all_history", [])
            self.invalid_counter = data.get("invalid_counter", 0)
            self.best_run_id = data.get("best_run_id", None)

            print(f"[Memory] Loaded {len(self.all_history)} previous states from {self.save_path}")

        except (json.JSONDecodeError, Exception) as e:
            print(f"[Memory] ERROR: Could not load {self.save_path}: {e}")

    # ==================================================================
    # ACCESSORS
    # ==================================================================

    def get_previous_state(self):
        """Get the most recent state (for StateBuilder)."""
        if self.all_history:
            return self.all_history[-1]
        return None

    def get_invalid_counter(self):
        """Get the invalid counter (for Governor)."""
        return self.invalid_counter

    # ==================================================================
    # DEBUG DISPLAY
    # ==================================================================

    def print_summary(self, memory_summary):
        """Print memory summary in readable format."""
        print("\n" + "=" * 60)
        print("MEMORY SUMMARY")
        print("=" * 60)

        counts = memory_summary["run_counts"]
        print(f"\nRuns: {counts['total']} total ({counts['total_successful']} successful, {counts['total_failed']} failed)")

        # Best run
        best = memory_summary.get("best_run")
        if best:
            print(f"\nBest Run: {best['run_id']} (success: {best['success']})")
        else:
            print(f"\nBest Run: none")

        # Previous run
        prev = memory_summary.get("previous_run")
        if prev:
            print(f"\nPrevious Run: {prev['run_id']}")


