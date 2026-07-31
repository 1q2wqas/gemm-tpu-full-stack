"""
plot_metrics.py - Plots key metrics across all OpenLane runs from memory.json

Usage:
    python plot_metrics.py
    python plot_metrics.py --memory path/to/memory.json
    python plot_metrics.py --memory memory.json --output results/

Output:
    - One PNG per metric group saved to output directory
    - A summary dashboard PNG combining all groups
"""

import json
import argparse
import os
import sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np


# =============================================================================
# METRIC GROUPS - organise metrics into logical categories for subplots
# =============================================================================

METRIC_GROUPS = {
    "Power": {
        "metrics": [
            ("power__total",            "Total Power (W)",    "#e74c3c"),
            ("power__internal__total",  "Internal Power (W)", "#e67e22"),
            ("power__switching__total", "Switching Power (W)","#f39c12"),
            ("power__leakage__total",   "Leakage Power (W)",  "#d35400"),
        ],
        "lower_is_better": True,
    },
    "Area": {
        "metrics": [
            ("design__instance__area",  "Instance Area (µm²)", "#2980b9"),
            ("design__die__area",       "Die Area (µm²)",      "#1abc9c"),
            ("design__core__area",      "Core Area (µm²)",     "#16a085"),
        ],
        "lower_is_better": True,
    },
    "Instance Counts": {
        "metrics": [
            ("design__instance__count",           "Std Cell Count",        "#8e44ad"),
            ("design__instance__count__hold_buffer",  "Hold Buffers",      "#9b59b6"),
            ("design__instance__count__setup_buffer", "Setup Buffers",     "#6c3483"),
        ],
        "lower_is_better": True,
    },
    "Utilisation": {
        "metrics": [
            ("design__instance__utilization",           "Core Utilisation", "#27ae60"),
        ],
        "lower_is_better": False,
    },
    "Timing - Clock Skew": {
        "metrics": [
            ("clock__skew__worst_hold",  "Worst Hold Skew (ns)",  "#c0392b"),
            ("clock__skew__worst_setup", "Worst Setup Skew (ns)", "#e74c3c"),
        ],
        "lower_is_better": True,
    },
    "Timing - Slack & Violations": {
        "metrics": [
            ("timing__setup__wns",       "Setup WNS (ns)",        "#2c3e50"),
            ("timing__hold__wns",        "Hold WNS (ns)",         "#7f8c8d"),
            ("timing__setup__tns",       "Setup TNS (ns)",        "#95a5a6"),
            ("timing__hold__tns",        "Hold TNS (ns)",         "#bdc3c7"),
            ("timing__setup_vio__count", "Setup Violations",      "#e74c3c"),
            ("timing__hold_vio__count",  "Hold Violations",       "#c0392b"),
        ],
        "lower_is_better": True,
    },
    "DRC & Signal Integrity": {
        "metrics": [
            ("design__max_slew_violation__count", "Slew Violations",    "#e67e22"),
            ("design__max_fanout_violation__count","Fanout Violations",  "#f39c12"),
            ("design__max_cap_violation__count",   "Cap Violations",     "#d35400"),
            ("route__antenna_violation__count",    "Antenna Violations", "#c0392b"),
            ("route__drc_errors",                  "DRC Errors",        "#e74c3c"),
            ("design__lvs_error__count",           "LVS Errors",        "#922b21"),
        ],
        "lower_is_better": True,
    },
    "Routing": {
        "metrics": [
            ("route__wirelength", "Wire Length (µm)", "#1a5276"),
            ("route__vias",       "Via Count",        "#2874a6"),
        ],
        "lower_is_better": True,
    },
}


# =============================================================================
# DATA LOADING
# =============================================================================

def load_runs(memory_path):
    """Load all successful runs from memory.json."""
    with open(memory_path, "r") as f:
        data = json.load(f)

    # Support both old format (success_history) and new format (all_history)
    if "all_history" in data:
        runs = [r for r in data["all_history"] if r.get("success", False)]
    elif "success_history" in data:
        runs = data["success_history"]
    else:
        print("ERROR: Unrecognised memory.json format — expected 'all_history' or 'success_history'")
        sys.exit(1)

    if not runs:
        print("ERROR: No successful runs found in memory.json")
        sys.exit(1)

    best_run_id = data.get("best_run_id")
    print(f"Loaded {len(runs)} successful run(s). Best run: {best_run_id}")
    return runs, best_run_id


def extract_series(runs, metric_key):
    """Extract a time-series list of (run_index, value) for a given metric."""
    values = []
    for i, run in enumerate(runs):
        val = run.get("metrics", {}).get(metric_key)
        values.append((i, val))
    return values


# =============================================================================
# PLOTTING HELPERS
# =============================================================================

STYLE = {
    "bg":           "#0f1117",
    "axes_bg":      "#1a1d27",
    "grid":         "#2a2d3a",
    "text":         "#e0e0e0",
    "label":        "#a0a0b0",
    "best_vline":   "#f1c40f",
    "marker_size":  7,
    "linewidth":    2.0,
}


def apply_dark_theme(fig, axes_list):
    fig.patch.set_facecolor(STYLE["bg"])
    for ax in axes_list:
        ax.set_facecolor(STYLE["axes_bg"])
        ax.tick_params(colors=STYLE["label"], labelsize=8)
        ax.xaxis.label.set_color(STYLE["label"])
        ax.yaxis.label.set_color(STYLE["label"])
        ax.title.set_color(STYLE["text"])
        for spine in ax.spines.values():
            spine.set_edgecolor(STYLE["grid"])
        ax.grid(True, color=STYLE["grid"], linewidth=0.6, linestyle="--", alpha=0.7)
        ax.set_axisbelow(True)


def short_run_label(run_id, idx):
    """Shorten run ID for x-axis tick e.g. 'RUN_2026-04-17_20-12-13' -> 'R1'."""
    return f"R{idx + 1}"


def plot_group(group_name, group_cfg, runs, best_run_id, output_dir):
    """Plot all metrics in a group as a single figure with one subplot each."""
    metrics = group_cfg["metrics"]
    lower_is_better = group_cfg["lower_is_better"]
    run_labels = [short_run_label(r["run_id"], i) for i, r in enumerate(runs)]
    run_ids    = [r["run_id"] for r in runs]
    x = np.arange(len(runs))

    # Find best_run index
    best_idx = None
    if best_run_id:
        for i, r in enumerate(runs):
            if r["run_id"] == best_run_id:
                best_idx = i
                break

    # How many metrics actually have data?
    active = [(key, label, color) for key, label, color in metrics
              if any(r.get("metrics", {}).get(key) is not None for r in runs)]

    if not active:
        print(f"  Skipping '{group_name}' — no data found")
        return None

    n = len(active)
    ncols = min(2, n)
    nrows = (n + ncols - 1) // ncols

    fig, axes = plt.subplots(nrows, ncols, figsize=(7 * ncols, 4 * nrows), squeeze=False)
    fig.suptitle(group_name, color=STYLE["text"], fontsize=14, fontweight="bold", y=1.01)

    all_axes = [axes[r][c] for r in range(nrows) for c in range(ncols)]
    apply_dark_theme(fig, all_axes)

    for idx, (metric_key, metric_label, color) in enumerate(active):
        ax = all_axes[idx]
        values = [r.get("metrics", {}).get(metric_key) for r in runs]

        # Separate valid / missing
        valid_x     = [x[i] for i, v in enumerate(values) if v is not None]
        valid_vals  = [v for v in values if v is not None]

        if not valid_vals:
            ax.set_visible(False)
            continue

        ax.plot(valid_x, valid_vals, color=color,
                linewidth=STYLE["linewidth"], marker="o",
                markersize=STYLE["marker_size"], zorder=3, label=metric_label)

        # Shade improvement direction
        if valid_vals:
            target = min(valid_vals) if lower_is_better else max(valid_vals)
            ax.axhline(target, color=color, alpha=0.25, linewidth=1, linestyle=":")

        # Best run vertical line
        if best_idx is not None and best_idx < len(x):
            ax.axvline(best_idx, color=STYLE["best_vline"],
                       linewidth=1.5, linestyle="--", alpha=0.8, label="Best run")

        ax.set_xticks(x)
        ax.set_xticklabels(run_labels, rotation=45, ha="right", fontsize=7)
        ax.set_ylabel(metric_label, fontsize=8)
        ax.set_xlabel("Run", fontsize=8)
        ax.set_title(metric_label, fontsize=9, color=STYLE["text"], pad=6)

        # Format y-axis for very small numbers (power)
        max_abs = max(abs(v) for v in valid_vals) if valid_vals else 1
        if max_abs < 0.001:
            ax.yaxis.set_major_formatter(ticker.ScalarFormatter(useMathText=True))
            ax.ticklabel_format(style="sci", axis="y", scilimits=(0, 0))
            ax.yaxis.get_offset_text().set_color(STYLE["label"])

        # Annotate first and last values
        if len(valid_vals) >= 2:
            ax.annotate(f"{valid_vals[0]:.3g}", (valid_x[0], valid_vals[0]),
                        textcoords="offset points", xytext=(4, 6),
                        fontsize=6, color=STYLE["label"])
            ax.annotate(f"{valid_vals[-1]:.3g}", (valid_x[-1], valid_vals[-1]),
                        textcoords="offset points", xytext=(4, 6),
                        fontsize=6, color=STYLE["label"])

        ax.legend(fontsize=6, loc="upper right",
                  facecolor=STYLE["axes_bg"], edgecolor=STYLE["grid"],
                  labelcolor=STYLE["text"])

    # Hide unused subplots
    for idx in range(len(active), len(all_axes)):
        all_axes[idx].set_visible(False)

    plt.tight_layout()
    safe_name = group_name.replace(" ", "_").replace("/", "-").replace("&", "and")
    out_path = os.path.join(output_dir, f"{safe_name}.png")
    fig.savefig(out_path, dpi=150, bbox_inches="tight", facecolor=STYLE["bg"])
    plt.close(fig)
    print(f"  Saved: {out_path}")
    return out_path


def plot_dashboard(runs, best_run_id, output_dir):
    """
    Single overview dashboard — one line per key metric, all on one figure.
    Shows the most important single metric per group.
    """
    SUMMARY_METRICS = [
        ("power__total",                    "Total Power (W)",           "#e74c3c"),
        ("design__instance__area",          "Instance Area (µm²)",       "#2980b9"),
        ("design__instance__utilization",   "Utilisation",               "#27ae60"),
        ("clock__skew__worst_setup",        "Worst Setup Skew (ns)",     "#e67e22"),
        ("design__max_slew_violation__count","Slew Violations",          "#f39c12"),
        ("route__wirelength",               "Wire Length (µm)",          "#1a5276"),
        ("route__drc_errors",               "DRC Errors",                "#c0392b"),
        ("design__instance__count",         "Std Cell Count",            "#8e44ad"),
    ]

    run_labels = [short_run_label(r["run_id"], i) for i, r in enumerate(runs)]
    x = np.arange(len(runs))

    best_idx = None
    if best_run_id:
        for i, r in enumerate(runs):
            if r["run_id"] == best_run_id:
                best_idx = i
                break

    ncols = 4
    nrows = 2
    fig, axes = plt.subplots(nrows, ncols, figsize=(22, 10))
    fig.suptitle(
        f"OpenLane Run Summary Dashboard  —  {runs[0]['design_name']}",
        color=STYLE["text"], fontsize=16, fontweight="bold", y=1.01
    )

    all_axes = [axes[r][c] for r in range(nrows) for c in range(ncols)]
    apply_dark_theme(fig, all_axes)

    for idx, (metric_key, metric_label, color) in enumerate(SUMMARY_METRICS):
        ax = all_axes[idx]
        values = [r.get("metrics", {}).get(metric_key) for r in runs]
        valid_x    = [x[i] for i, v in enumerate(values) if v is not None]
        valid_vals = [v for v in values if v is not None]

        if not valid_vals:
            ax.text(0.5, 0.5, "No data", transform=ax.transAxes,
                    ha="center", va="center", color=STYLE["label"])
            ax.set_title(metric_label, fontsize=9, color=STYLE["text"])
            continue

        ax.plot(valid_x, valid_vals, color=color,
                linewidth=2.2, marker="o", markersize=8, zorder=3)
        ax.fill_between(valid_x, valid_vals, alpha=0.12, color=color)

        if best_idx is not None:
            ax.axvline(best_idx, color=STYLE["best_vline"],
                       linewidth=1.5, linestyle="--", alpha=0.9,
                       label=f"Best (R{best_idx+1})")
            ax.legend(fontsize=6, facecolor=STYLE["axes_bg"],
                      edgecolor=STYLE["grid"], labelcolor=STYLE["text"])

        ax.set_xticks(x)
        ax.set_xticklabels(run_labels, rotation=45, ha="right", fontsize=8)
        ax.set_title(metric_label, fontsize=9, color=STYLE["text"], pad=6)
        ax.set_xlabel("Run", fontsize=8)

        max_abs = max(abs(v) for v in valid_vals) if valid_vals else 1
        if max_abs < 0.001:
            ax.yaxis.set_major_formatter(ticker.ScalarFormatter(useMathText=True))
            ax.ticklabel_format(style="sci", axis="y", scilimits=(0, 0))
            ax.yaxis.get_offset_text().set_color(STYLE["label"])

        # Delta annotation
        if len(valid_vals) >= 2:
            delta_pct = (valid_vals[-1] - valid_vals[0]) / abs(valid_vals[0]) * 100 if valid_vals[0] != 0 else 0
            arrow = "▼" if delta_pct < 0 else "▲"
            delta_color = "#2ecc71" if delta_pct < 0 else "#e74c3c"
            ax.text(0.97, 0.05, f"{arrow} {abs(delta_pct):.1f}%",
                    transform=ax.transAxes, ha="right", va="bottom",
                    fontsize=8, color=delta_color, fontweight="bold")

    plt.tight_layout()
    out_path = os.path.join(output_dir, "00_dashboard.png")
    fig.savefig(out_path, dpi=150, bbox_inches="tight", facecolor=STYLE["bg"])
    plt.close(fig)
    print(f"  Saved dashboard: {out_path}")
    return out_path


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Plot OpenLane run metrics from memory.json")
    parser.add_argument("--memory", default="memory.json", help="Path to memory.json")
    parser.add_argument("--output", default="metric_plots",  help="Output directory for plots")
    args = parser.parse_args()

    if not os.path.exists(args.memory):
        print(f"ERROR: memory.json not found at: {args.memory}")
        sys.exit(1)

    os.makedirs(args.output, exist_ok=True)

    print(f"\nLoading runs from: {args.memory}")
    runs, best_run_id = load_runs(args.memory)

    print(f"\nGenerating dashboard...")
    plot_dashboard(runs, best_run_id, args.output)

    print(f"\nGenerating per-group plots...")
    for group_name, group_cfg in METRIC_GROUPS.items():
        print(f"  [{group_name}]")
        plot_group(group_name, group_cfg, runs, best_run_id, args.output)

    print(f"\nDone. All plots saved to: {os.path.abspath(args.output)}/")


if __name__ == "__main__":
    main()