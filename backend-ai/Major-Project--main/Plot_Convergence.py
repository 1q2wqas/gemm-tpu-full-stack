"""
plot_convergence.py - Shows whether the LLM is converging toward a balanced best run.

Each run gets a composite score (0-100) built from four equally-weighted pillars:
    - Power      (lower is better)
    - Area       (lower is better)
    - Violations (lower is better — slew, fanout, cap, antenna, DRC)
    - Timing     (lower skew magnitude is better)

Each pillar is normalised across all runs so scores are comparable regardless of units.
A score of 100 = best observed value for that pillar.
A score of 0   = worst observed value for that pillar.

The final composite score is the weighted average of all four pillars.
A radar chart also shows the per-pillar breakdown for every run.

Usage:
    python plot_convergence.py
    python plot_convergence.py --memory path/to/memory.json --output plots/
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
# SCORING CONFIG
# Each entry: (metric_key, weight, lower_is_better)
# Weights within a pillar are normalised automatically.
# =============================================================================

PILLARS = {
    "Power": {
        "weight": 1.0,
        "metrics": [
            ("power__total",            1.0, True),
        ],
    },
    "Area": {
        "weight": 1.0,
        "metrics": [
            ("design__instance__area",  0.6, True),
            ("design__die__area",       0.4, True),
        ],
    },
    "Violations": {
        "weight": 1.5,   # penalise violations more heavily
        "metrics": [
            ("design__max_slew_violation__count",  1.0, True),
            ("design__max_fanout_violation__count",1.0, True),
            ("design__max_cap_violation__count",   1.0, True),
            ("route__antenna_violation__count",    1.0, True),
            ("route__drc_errors",                  1.0, True),
            ("timing__setup_vio__count",           1.0, True),
            ("timing__hold_vio__count",            1.0, True),
        ],
    },
    "Timing": {
        "weight": 1.0,
        "metrics": [
            ("clock__skew__worst_setup", 0.5, True),   # use abs value
            ("clock__skew__worst_hold",  0.5, True),   # use abs value
        ],
    },
}

STYLE = {
    "bg":         "#0f1117",
    "axes_bg":    "#1a1d27",
    "grid":       "#2a2d3a",
    "text":       "#e0e0e0",
    "label":      "#a0a0b0",
    "best_vline": "#f1c40f",
}

PILLAR_COLORS = {
    "Power":      "#e74c3c",
    "Area":       "#2980b9",
    "Violations": "#e67e22",
    "Timing":     "#27ae60",
}


# =============================================================================
# DATA LOADING
# =============================================================================

def load_runs(memory_path):
    with open(memory_path, "r") as f:
        data = json.load(f)

    if "all_history" in data:
        runs = [r for r in data["all_history"] if r.get("success", False)]
    elif "success_history" in data:
        runs = data["success_history"]
    else:
        print("ERROR: Unrecognised memory.json format")
        sys.exit(1)

    if not runs:
        print("ERROR: No successful runs found in memory.json")
        sys.exit(1)

    best_run_id = data.get("best_run_id")
    print(f"Loaded {len(runs)} successful run(s).  Best run: {best_run_id}")
    return runs, best_run_id


# =============================================================================
# SCORING
# =============================================================================

def get_metric(run, key):
    """Return absolute value for skew metrics, raw value otherwise."""
    val = run.get("metrics", {}).get(key)
    if val is None:
        return None
    if "skew" in key:
        return abs(val)
    return val


def normalise_series(values, lower_is_better):
    """
    Map a list of floats to [0, 100] where 100 = best.
    None entries stay None and are excluded from min/max.
    """
    valid = [v for v in values if v is not None]
    if not valid:
        return [None] * len(values)

    mn, mx = min(valid), max(valid)
    if mn == mx:
        return [100.0 if v is not None else None for v in values]

    normed = []
    for v in values:
        if v is None:
            normed.append(None)
        else:
            ratio = (v - mn) / (mx - mn)          # 0 = min, 1 = max
            score = (1 - ratio) if lower_is_better else ratio
            normed.append(score * 100)
    return normed


def compute_scores(runs):
    """
    Returns:
        pillar_scores  - dict pillar_name -> list of scores (one per run)
        composite      - list of composite scores (one per run)
    """
    n = len(runs)
    pillar_scores = {}

    for pillar_name, cfg in PILLARS.items():
        metric_cfgs = cfg["metrics"]
        total_weight = sum(w for _, w, _ in metric_cfgs)

        # Collect and normalise each metric
        weighted_normed = []
        for key, weight, lower_is_better in metric_cfgs:
            raw = [get_metric(r, key) for r in runs]
            normed = normalise_series(raw, lower_is_better)
            weighted_normed.append((normed, weight / total_weight))

        # Average across metrics within the pillar (weighted)
        pillar = []
        for i in range(n):
            vals = [(nv[i], w) for nv, w in weighted_normed if nv[i] is not None]
            if vals:
                score = sum(v * w for v, w in vals) / sum(w for _, w in vals)
            else:
                score = None
            pillar.append(score)

        pillar_scores[pillar_name] = pillar

    # Composite = weighted average of pillars
    total_pillar_weight = sum(cfg["weight"] for cfg in PILLARS.values())
    composite = []
    for i in range(n):
        vals = [
            (pillar_scores[p][i], PILLARS[p]["weight"])
            for p in PILLARS
            if pillar_scores[p][i] is not None
        ]
        if vals:
            score = sum(v * w for v, w in vals) / sum(w for _, w in vals)
        else:
            score = None
        composite.append(score)

    return pillar_scores, composite


# =============================================================================
# PLOTTING
# =============================================================================

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


def plot_convergence(runs, best_run_id, pillar_scores, composite, output_dir):
    """Main convergence plot: composite score + per-pillar stacked view."""

    n = len(runs)
    x = np.arange(n)
    run_labels = [f"R{i+1}" for i in range(n)]

    best_idx = next((i for i, r in enumerate(runs) if r["run_id"] == best_run_id), None)

    fig = plt.figure(figsize=(18, 12))
    fig.patch.set_facecolor(STYLE["bg"])

    gs = fig.add_gridspec(2, 2, hspace=0.45, wspace=0.35,
                          left=0.07, right=0.97, top=0.90, bottom=0.08)

    ax_main   = fig.add_subplot(gs[0, :])   # full-width composite score
    ax_pillar = fig.add_subplot(gs[1, 0])   # per-pillar lines
    ax_delta  = fig.add_subplot(gs[1, 1])   # run-to-run improvement delta

    apply_dark_theme(fig, [ax_main, ax_pillar, ax_delta])

    design = runs[0].get("design_name", "unknown")
    fig.suptitle(
        f"LLM Convergence  —  {design}   ({n} runs)",
        color=STYLE["text"], fontsize=15, fontweight="bold"
    )

    # -------------------------------------------------------------------------
    # 1. COMPOSITE SCORE (main panel)
    # -------------------------------------------------------------------------
    valid_x    = [x[i] for i, v in enumerate(composite) if v is not None]
    valid_comp = [v     for v in composite if v is not None]

    ax_main.plot(valid_x, valid_comp, color="#f1c40f",
                 linewidth=2.5, marker="o", markersize=7, zorder=4, label="Composite score")
    ax_main.fill_between(valid_x, valid_comp, alpha=0.12, color="#f1c40f")

    # Rolling average (window=5) to show trend
    if len(valid_comp) >= 5:
        window = 5
        rolling = np.convolve(valid_comp, np.ones(window) / window, mode="valid")
        rx = valid_x[window - 1:]
        ax_main.plot(rx, rolling, color="#ffffff", linewidth=1.5,
                     linestyle="--", alpha=0.5, label=f"{window}-run rolling avg")

    if best_idx is not None:
        ax_main.axvline(best_idx, color=STYLE["best_vline"],
                        linewidth=2, linestyle=":", alpha=0.9,
                        label=f"Best run (R{best_idx+1})")

    # Annotate max score achieved
    if valid_comp:
        peak_val = max(valid_comp)
        peak_x   = valid_x[valid_comp.index(peak_val)]
        ax_main.annotate(
            f"Peak: {peak_val:.1f}",
            xy=(peak_x, peak_val),
            xytext=(peak_x + max(1, n * 0.03), peak_val - 5),
            color="#f1c40f", fontsize=8,
            arrowprops=dict(arrowstyle="->", color="#f1c40f", lw=1),
        )

    ax_main.set_xlim(-0.5, n - 0.5)
    ax_main.set_ylim(0, 105)
    ax_main.set_xticks(x)
    ax_main.set_xticklabels(run_labels, fontsize=7, rotation=45 if n > 20 else 0)
    ax_main.set_ylabel("Composite Score  (0 = worst, 100 = best)", fontsize=9)
    ax_main.set_title("Overall Convergence Score", fontsize=10, color=STYLE["text"])
    ax_main.legend(fontsize=8, facecolor=STYLE["axes_bg"],
                   edgecolor=STYLE["grid"], labelcolor=STYLE["text"], loc="lower right")

    # Colour background by score band
    for threshold, color, alpha in [(80, "#27ae60", 0.05), (50, "#f39c12", 0.04), (0, "#e74c3c", 0.03)]:
        ax_main.axhspan(threshold, 105 if threshold == 80 else threshold + 30,
                        color=color, alpha=alpha, zorder=0)

    # -------------------------------------------------------------------------
    # 2. PER-PILLAR LINES
    # -------------------------------------------------------------------------
    for pillar_name, scores in pillar_scores.items():
        color = PILLAR_COLORS[pillar_name]
        vx = [x[i] for i, v in enumerate(scores) if v is not None]
        vy = [v for v in scores if v is not None]
        if vy:
            ax_pillar.plot(vx, vy, color=color, linewidth=1.8,
                           marker="o", markersize=4, label=pillar_name)

    if best_idx is not None:
        ax_pillar.axvline(best_idx, color=STYLE["best_vline"],
                          linewidth=1.5, linestyle=":", alpha=0.8)

    ax_pillar.set_xlim(-0.5, n - 0.5)
    ax_pillar.set_ylim(0, 105)
    ax_pillar.set_xticks(x[::max(1, n // 15)])
    ax_pillar.set_xticklabels([run_labels[i] for i in range(0, n, max(1, n // 15))],
                               fontsize=7, rotation=45)
    ax_pillar.set_ylabel("Pillar Score (0–100)", fontsize=9)
    ax_pillar.set_title("Per-Pillar Breakdown", fontsize=10, color=STYLE["text"])
    ax_pillar.legend(fontsize=7.5, facecolor=STYLE["axes_bg"],
                     edgecolor=STYLE["grid"], labelcolor=STYLE["text"])

    # -------------------------------------------------------------------------
    # 3. RUN-TO-RUN DELTA (improvement per step)
    # -------------------------------------------------------------------------
    deltas = []
    delta_x = []
    for i in range(1, len(composite)):
        if composite[i] is not None and composite[i - 1] is not None:
            deltas.append(composite[i] - composite[i - 1])
            delta_x.append(i)

    bar_colors = ["#27ae60" if d >= 0 else "#e74c3c" for d in deltas]
    ax_delta.bar(delta_x, deltas, color=bar_colors, alpha=0.8, width=0.7, zorder=3)
    ax_delta.axhline(0, color=STYLE["label"], linewidth=0.8, linestyle="-")

    if best_idx is not None:
        ax_delta.axvline(best_idx, color=STYLE["best_vline"],
                         linewidth=1.5, linestyle=":", alpha=0.8)

    # Rolling mean of deltas
    if len(deltas) >= 5:
        rm = np.convolve(deltas, np.ones(5) / 5, mode="valid")
        ax_delta.plot(delta_x[4:], rm, color="#ffffff",
                      linewidth=1.5, linestyle="--", alpha=0.6, label="5-run avg trend")
        ax_delta.legend(fontsize=7, facecolor=STYLE["axes_bg"],
                        edgecolor=STYLE["grid"], labelcolor=STYLE["text"])

    ax_delta.set_xlim(-0.5, n - 0.5)
    ax_delta.set_xticks(x[::max(1, n // 15)])
    ax_delta.set_xticklabels([run_labels[i] for i in range(0, n, max(1, n // 15))],
                              fontsize=7, rotation=45)
    ax_delta.set_ylabel("Score Change vs Previous Run", fontsize=9)
    ax_delta.set_title("Run-to-Run Improvement  (green = better, red = worse)", fontsize=10, color=STYLE["text"])

    # -------------------------------------------------------------------------
    # Save
    # -------------------------------------------------------------------------
    out_path = os.path.join(output_dir, "convergence.png")
    fig.savefig(out_path, dpi=150, bbox_inches="tight", facecolor=STYLE["bg"])
    plt.close(fig)
    print(f"Saved: {out_path}")
    return out_path


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Plot LLM convergence toward balanced best run")
    parser.add_argument("--memory", default="memory.json", help="Path to memory.json")
    parser.add_argument("--output", default="metric_plots",  help="Output directory")
    args = parser.parse_args()

    if not os.path.exists(args.memory):
        print(f"ERROR: memory.json not found at: {args.memory}")
        sys.exit(1)

    os.makedirs(args.output, exist_ok=True)

    runs, best_run_id = load_runs(args.memory)
    pillar_scores, composite = compute_scores(runs)

    # Print summary table
    print(f"\n{'Run':<6} {'Power':>7} {'Area':>7} {'Violations':>11} {'Timing':>7} {'Composite':>10}")
    print("-" * 52)
    for i, (run, comp) in enumerate(zip(runs, composite)):
        row = [f"R{i+1:<4}"]
        for p in ["Power", "Area", "Violations", "Timing"]:
            v = pillar_scores[p][i]
            row.append(f"{v:>7.1f}" if v is not None else f"{'N/A':>7}")
        row.append(f"{comp:>10.1f}" if comp is not None else f"{'N/A':>10}")
        marker = "  ← best" if run["run_id"] == best_run_id else ""
        print("".join(row) + marker)

    plot_convergence(runs, best_run_id, pillar_scores, composite, args.output)
    print("\nDone.")


if __name__ == "__main__":
    main()