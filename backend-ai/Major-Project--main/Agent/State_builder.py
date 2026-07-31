"""
StateBuilder - Builds structured state from a single run

Inputs:
  - Raw metrics from Parser
  - runs_path - path to the design's runs directory (run_id extracted automatically)
  - design_name - name of the design
  - config_path - file path to the design's config.json (read from disk)
  - flow_success from Errors.py
  - Previous state (for calculating metric changes)

Output:
  - Structured state dict used by Memory and Decision Engine

Note: Best results, run histories, and memory summaries are handled
      by Memory.py - StateBuilder only deals with the current run.
"""

import json
import os
from datetime import datetime



class StateBuilder:

    def __init__(self):
        pass

    # ==================================================================
    # MAIN ENTRY POINT
    # ==================================================================

    def build_state(
        self,
        raw_metrics,
        runs_path,
        design_name,
        config_path,
        flow_success,
        error_summary,
        desired_metrics=None,
        previous_state=None,
    ):
        """
        Build structured state for the current run.

        Args:
            raw_metrics:    Dict from Parser e.g. {'power__total': '0.0056'}
            runs_path:      String - path to the design's runs directory
                            (run_id is extracted from the latest run folder name)
            design_name:    String - name of the design e.g. 'pm32'
            config_path:    String - file path to the design's config.json
            flow_success:   Bool from Errors.py - did the OpenLane flow pass?
            error_summary:  Dict from Errors.py if flow failed
                            e.g. {'failed_checks': 'antenna_check', 'type': 'signoff', 'recoverable': True}
            previous_state: Optional previous state dict (for metric changes)

        Returns:
            Dict with the structured state
        """

        # Extract run_id from the latest run folder name
        run_id = self._get_run_id(runs_path)

        # STEP 1: Read config.json from disk and check that it is not empty
        json_config = self._load_config(config_path)
        if json_config is None:
            return self._build_error_state(
                run_id, design_name, {},
                error_message=f"Could not read config file: {config_path}",
                recoverable=False,
            )

        # STEP 2: Parse whatever metrics are available (even on a failed run)
        # Normalise per-key so partial metrics from failed runs are still captured
        metrics = self._normalise_metrics(raw_metrics) if raw_metrics else {}
        if not metrics and raw_metrics:
            print(f"[StateBuilder] WARNING: No valid metrics could be parsed for {run_id}")

        # STEP 3: If flow failed, return error state with whatever metrics were parsed
        if not flow_success:
            return self._build_error_state(
                run_id=run_id,
                design_name=design_name,
                json_config=json_config,
                failed_checks=error_summary["failed_checks"],
                error_type=error_summary["error_type"],
                recoverable=error_summary["recoverable"],
                metrics=metrics,
                error_message=error_summary["message"],
            )
        
        # if not flow_success:
        #     # failed_checks = error_info.get("stage", "unknown") if error_info else "unknown"
        #     # err_type = error_info.get("type", "unknown") if error_info else "unknown"
        #     # recoverable = error_info.get("recoverable", False) if error_info else False

        #     return self._build_error_state(
        #         run_id, design_name, json_config,
        #         error_message=error_info,
        #         recoverable=True,
        #         metrics=metrics,
        #     )

        # STEP 4: If flow succeeded but no valid metrics, treat as recoverable error
        if not metrics:
            print(f"[StateBuilder] WARNING: No valid metrics for {run_id}")
            return self._build_error_state(
                run_id, design_name, json_config,
                error_message="Invalid or missing metric data from Parser",
                recoverable=True,
            )

        # STEP 5: Calculate metric changes if previous state exists
        metric_changes = {}
        if previous_state:
            prev_metrics = previous_state.get("metrics", {})
            metric_changes = self._calculate_changes(metrics, prev_metrics)

        # STEP 6: Fill any missing required metrics with None
        for name in (desired_metrics or []):
            if name not in metrics:
                metrics[name] = None
                print(f"[StateBuilder] WARNING: Missing metric '{name}', set to None")

        # STEP 7: Build and return the state
        state = {
            "run_id": run_id,
            "design_name": design_name,
            "timestamp": self._get_timestamp(),
            "success": True,
            "metrics": metrics,
            "metric_changes": metric_changes,
            "json_config": json_config,
        }

        return state

    # ==================================================================
    # ERROR STATE
    # ==================================================================

    def _build_error_state(
        self,
        *,
        run_id,
        design_name,
        json_config,
        error_message,
        recoverable=False,
        metrics=None,
        failed_checks=None,
        error_type=None,
    ):
        return {
            "run_id": run_id,
            "design_name": design_name,
            "timestamp": self._get_timestamp(),
            "success": False,  # <-- always false here
            "error": error_message,
            "error_type": error_type,
            "failed_checks": failed_checks or [],
            "recoverable": recoverable,
            "metrics": metrics or {},
            "metric_changes": {},
            "json_config": json_config,
        }
    # def _build_error_state(
    #     self, run_id, design_name, json_config,
    #     error_message, recoverable=False, metrics=None,
    # ):
    #     """Build state when flow failed or data was invalid."""
    #     return {
    #         "run_id": run_id,
    #         "design_name": design_name,
    #         "timestamp": self._get_timestamp(),
    #         "success": False,
    #         "error": error_message,
    #         "recoverable": recoverable,
    #         "metrics": metrics or {},
    #         "metric_changes": {},
    #         "json_config": json_config,
    #     }

    # ==================================================================
    # CONFIG FILE LOADING
    # ==================================================================

    def _load_config(self, config_path):
        """
        Read config.json from disk.

        Args:
            config_path: File path to config.json

        Returns:
            Dict with config contents, or None if file can't be read
        """
        try:
            with open(config_path, "r") as f:
                config = json.load(f)
            return config
        except FileNotFoundError:
            print(f"[StateBuilder] ERROR: Config file not found: {config_path}")
            return None
        except json.JSONDecodeError as e:
            print(f"[StateBuilder] ERROR: Invalid JSON in config file: {e}")
            return None

    # ==================================================================
    # VALIDATION
    # ==================================================================

    # ==================================================================
    # NORMALISATION
    # ==================================================================

    def _normalise_metrics(self, raw_metrics):
        """Convert metric values from strings to floats, skipping unparseable values."""
        metrics = {}
        for name, value in raw_metrics.items():
            try:
                metrics[name] = float(value)
            except (ValueError, TypeError):
                print(f"[StateBuilder] WARNING: Could not parse metric '{name}' = {value!r}, skipping")
        return metrics

    # ==================================================================
    # COMPARISON
    # ==================================================================

    def _calculate_changes(self, current, previous):
        """Calculate absolute and percentage change for each shared metric."""
        changes = {}

        for name, curr_val in current.items():
            if curr_val is None:
                continue
            if name in previous and previous[name] is not None:
                prev_val = previous[name]
                abs_change = curr_val - prev_val
                pct_change = (abs_change / prev_val * 100) if prev_val != 0 else 0.0

                changes[name] = {
                    "previous": prev_val,
                    "current": curr_val,
                    "absolute_change": abs_change,
                    "percentage_change": pct_change,
                }

        return changes

    # ==================================================================
    # UTILITIES
    # ==================================================================

    def _get_run_id(self, runs_path):
        """
        Extract run_id from the latest run folder name in the runs directory.

        Args:
            runs_path: Path to the design's runs directory

        Returns:
            String - the folder name of the latest run, or a generated fallback
        """
        try:
            all_run_dirs = [
                d for d in os.listdir(runs_path)
                if os.path.isdir(os.path.join(runs_path, d))
            ]

            if not all_run_dirs:
                print("[StateBuilder] WARNING: No run directories found, generating run_id")
                return self._generate_run_id()

            # Latest run = last when sorted alphabetically (matches Parser logic)
            latest_run = sorted(all_run_dirs)[-1]
            return latest_run

        except FileNotFoundError:
            print(f"[StateBuilder] WARNING: Runs path not found: {runs_path}")
            return self._generate_run_id()

    def _get_timestamp(self):
        return datetime.now().isoformat()

    def _generate_run_id(self):
        return f"RUN_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}"

    # ==================================================================
    # DEBUG DISPLAY
    # ==================================================================

    def print_state(self, state):
        """Print state in readable format for debugging."""
        print("\n" + "=" * 60)
        print("STATE")
        print("=" * 60)

        print(f"\nRun ID:  {state['run_id']}")
        print(f"Design:  {state['design_name']}")
        print(f"Success: {state['success']}")

        if not state["success"]:
            print(f"Error:   {state.get('error')}")
            print(f"Recoverable: {state.get('recoverable')}")
            return

        print(f"\nMetrics:")
        for name, value in state["metrics"].items():
            print(f"  {name}: {value}")

        if state["metric_changes"]:
            print(f"\nChanges from Previous:")
            for name, change in state["metric_changes"].items():
                pct = change["percentage_change"]
                arrow = "↓" if pct < 0 else "↑" if pct > 0 else "="
                print(f"  {arrow} {name}: {pct:+.2f}%")

        print(f"\nConfig: {state['json_config']}")
        print("=" * 60)
