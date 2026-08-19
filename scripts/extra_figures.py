"""Figures the paper needs that analyze.py does not already produce.

analyze.py emits the seven per-channel figures plus the channel-sensitivity
panel. Three more earn their place in a 12-page paper:

  figA  packet error vs distance, with d0 and the sink-distance band marked.
        This is the figure that makes the two-channel design decision obvious
        before the reader reaches the methodology.
  figB  the full first-node-death distribution per protocol, not just its
        mean. GCN's bimodality and DQN's tightness are the whole of the
        temporal-credit-assignment finding and a mean +- std bar hides both.
  figC  mean head-to-sink distance against retry energy share, which is the
        mechanism behind the channel-conditional retraction in one picture.

figC reads results/analysis/energy_probe.csv (scripts/energy_probe.py).

Usage:  python scripts/extra_figures.py
"""

import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wsn_sim.config import SimConfig  # noqa: E402

OUT = "results/analysis/figures_paper"
ORDER = ["stub", "leach", "pegasis", "teen", "apteen", "nsga2", "fuzzy_t2", "som", "dqn", "gcn"]
NAMES = {"stub": "Direct", "leach": "LEACH", "pegasis": "PEGASIS", "teen": "TEEN",
         "apteen": "APTEEN", "nsga2": "NSGA-II", "fuzzy_t2": "Fuzzy T2", "som": "SOM",
         "dqn": "DQN", "gcn": "GCN"}
# One colour per generation, so the figures carry the paper's argument.
GEN_COLOR = {"stub": "#7a7a7a", "leach": "#1f77b4", "pegasis": "#1f77b4", "teen": "#1f77b4",
             "apteen": "#1f77b4", "nsga2": "#d95f02", "fuzzy_t2": "#d95f02",
             "som": "#2c8c4a", "dqn": "#2c8c4a", "gcn": "#2c8c4a"}

plt.rcParams.update({"font.size": 8, "axes.grid": True, "grid.alpha": 0.3,
                     "figure.dpi": 200, "savefig.bbox": "tight"})


def fig_per_curve() -> None:
    """PER against distance, annotated with the distances that actually occur.

    An earlier version of this figure shaded 150--158 m as "the sink hop".
    That is the FAR-CORNER distance, not the typical one: over 30 topologies
    the node-to-sink distance runs 50--158 m with a median of 104 m, so the
    shaded band is measured here rather than assumed.
    """
    from wsn_sim.network import Network
    cfg = SimConfig()
    df = pd.read_csv("results/validation/per_calibration.csv")
    d = np.concatenate([Network(cfg, i).dist_bs for i in range(30)])
    q25, q50, q75 = np.percentile(d, [25, 50, 75])

    fig, ax = plt.subplots(figsize=(3.4, 2.4))
    ax.axvspan(q25, q75, color="#2c8c4a", alpha=0.13, lw=0)
    ax.plot(df["distance_m"], df["per_4000bit"], color="#1f77b4", lw=1.6, zorder=3)
    ax.axvline(cfg.d0, color="#d95f02", ls="--", lw=1.0, zorder=2)
    ax.text(cfg.d0 - 3, 0.62, f"$d_0={cfg.d0:.1f}$ m", rotation=90, ha="right",
            va="center", fontsize=7, color="#d95f02")
    ax.axvline(q50, color="#2c8c4a", ls="-.", lw=1.0, zorder=2)
    ax.text(q50 + 3, 0.62, f"median node--sink\n{q50:.0f} m", fontsize=6.5,
            color="#1d5c31", va="center")
    # Where the two representative protocols actually put their heads.
    for x, lbl, xoff, yoff, ha in ((81.1, "DQN", -6, 34, "right"),
                                   (101.8, "LEACH", 6, 10, "left")):
        ax.plot([x], [0.0], marker="^", ms=5, color="black", clip_on=False, zorder=5)
        ax.annotate(f"{lbl} mean head {x:.0f} m", (x, 0.0), textcoords="offset points",
                    xytext=(xoff, yoff), ha=ha, fontsize=6.2)
    ax.set_xlabel("Distance (m)")
    ax.set_ylabel("Packet error rate\n(4000-bit packet)")
    ax.set_xlim(0, 200)
    ax.set_ylim(-0.03, 1.03)
    os.makedirs(OUT, exist_ok=True)
    fig.savefig(os.path.join(OUT, "figA_per_curve.png"))
    plt.close(fig)
    print(f"wrote figA_per_curve.png  (node-sink IQR {q25:.0f}-{q75:.0f} m, median {q50:.0f} m)")


def fig_fnd_distribution() -> None:
    rows = []
    for p in ORDER:
        path = f"results/lossy/summary/{p}_summary.csv"
        if not os.path.exists(path):
            continue
        rows.append((p, pd.read_csv(path)["fnd"].to_numpy(dtype=float)))
    fig, ax = plt.subplots(figsize=(7.0, 2.6))
    rng = np.random.default_rng(0)
    for i, (p, vals) in enumerate(rows):
        jitter = rng.uniform(-0.16, 0.16, size=len(vals))
        ax.scatter(np.full(len(vals), i) + jitter, vals, s=9, alpha=0.65,
                   color=GEN_COLOR[p], edgecolors="none", zorder=3)
        ax.hlines(vals.mean(), i - 0.32, i + 0.32, color="black", lw=1.4, zorder=4)
    ax.set_xticks(range(len(rows)))
    ax.set_xticklabels([NAMES[p] for p, _ in rows], rotation=20, ha="right")
    ax.set_ylabel("First node death (rounds)")
    handles = [plt.Line2D([], [], marker="o", ls="", color=c, label=lbl)
               for c, lbl in (("#7a7a7a", "baseline"), ("#1f77b4", "Gen. 1 heuristic"),
                              ("#d95f02", "Gen. 2 optimized"), ("#2c8c4a", "Gen. 3 learned"))]
    ax.legend(handles=handles, frameon=False, ncol=4, loc="upper left", fontsize=7)
    ax.set_ylim(0, None)
    os.makedirs(OUT, exist_ok=True)
    fig.savefig(os.path.join(OUT, "figB_fnd_distribution.png"))
    plt.close(fig)
    print("wrote figB_fnd_distribution.png  (30 runs per protocol, black bar = mean)")


def fig_mechanism() -> None:
    path = "results/analysis/energy_probe.csv"
    if not os.path.exists(path):
        print("skip figC: run scripts/energy_probe.py first")
        return
    cfg = SimConfig()
    df = pd.read_csv(path)
    df = df[df["channel"] == "lossy"]
    fig, ax = plt.subplots(figsize=(3.4, 2.6))
    for _, r in df.iterrows():
        p = r["protocol"]
        ax.scatter(r["mean_ch_bs_m"], r["retry_pct"], s=42, color=GEN_COLOR.get(p, "#333"),
                   zorder=3)
        ax.annotate(NAMES.get(p, p), (r["mean_ch_bs_m"], r["retry_pct"]),
                    textcoords="offset points", xytext=(5, 3), fontsize=7)
    ax.axvline(cfg.d0, color="#d95f02", ls="--", lw=1.0)
    ax.text(cfg.d0 + 1.5, ax.get_ylim()[1] * 0.95, "$d_0$", fontsize=7, color="#d95f02",
            va="top")
    ax.set_xlabel("Mean head-to-sink distance (m)")
    ax.set_ylabel("Share of energy spent\non retransmissions (%)")
    os.makedirs(OUT, exist_ok=True)
    fig.savefig(os.path.join(OUT, "figC_mechanism.png"))
    plt.close(fig)
    print("wrote figC_mechanism.png")


def fig_head_distance() -> None:
    """Where each protocol puts its heads, against the error curve.

    This is the honest version of the mechanism argument. Mean head distance
    alone does not explain the retry gap, because every protocol's mean sits
    below 120 m where PER is still ~0. What separates them is the upper tail.
    """
    path = "results/analysis/ch_distance_samples.csv"
    if not os.path.exists(path):
        print("skip figF: run scripts/energy_probe.py first")
        return
    cfg = SimConfig()
    d = pd.read_csv(path)
    per = pd.read_csv("results/validation/per_calibration.csv")
    show = [p for p in ["leach", "som", "nsga2", "fuzzy_t2", "dqn", "gcn"]
            if p in set(d["protocol"])]

    fig, ax = plt.subplots(figsize=(3.4, 2.7))
    ax2 = ax.twinx()
    ax2.plot(per["distance_m"], per["per_4000bit"], color="#999999", lw=1.2, zorder=1)
    ax2.set_ylabel("Packet error rate", color="#777777", fontsize=7)
    ax2.tick_params(axis="y", labelcolor="#777777", labelsize=7)
    ax2.set_ylim(0, 1.02)
    ax2.grid(False)

    for i, p in enumerate(show):
        v = d[d["protocol"] == p]["ch_bs_m"].to_numpy()
        ax.boxplot(v, positions=[i], orientation="horizontal", widths=0.6, showfliers=False,
                   patch_artist=True, zorder=3,
                   boxprops=dict(facecolor=GEN_COLOR[p], alpha=0.55, lw=0.7),
                   medianprops=dict(color="black", lw=1.1),
                   whiskerprops=dict(lw=0.7), capprops=dict(lw=0.7))
    ax.axvline(cfg.d0, color="#d95f02", ls="--", lw=1.0, zorder=2)
    ax.set_yticks(range(len(show)))
    ax.set_yticklabels([NAMES[p] for p in show], fontsize=7)
    ax.set_xlabel("Cluster-head-to-sink distance (m)")
    ax.set_xlim(0, 200)
    ax.set_zorder(ax2.get_zorder() + 1)
    ax.patch.set_visible(False)
    os.makedirs(OUT, exist_ok=True)
    fig.savefig(os.path.join(OUT, "figF_head_distance.png"))
    plt.close(fig)
    print("wrote figF_head_distance.png")


def fig_head_rotation() -> None:
    """How evenly head duty is shared. LEACH's epoch makes this exactly even."""
    path = "results/analysis/head_service_counts.csv"
    if not os.path.exists(path):
        print("skip figG: run scripts/energy_probe.py first")
        return
    df = pd.read_csv(path)
    show = [p for p in ["leach", "nsga2", "fuzzy_t2", "dqn", "gcn"] if p in set(df["protocol"])]
    fig, axes = plt.subplots(1, len(show), figsize=(7.0, 1.9), sharey=True)
    axes = np.atleast_1d(axes)
    for ax, p in zip(axes, show):
        v = np.sort(df[df["protocol"] == p]["rounds_as_head"].to_numpy())[::-1]
        ax.bar(np.arange(v.size), v, width=1.0, color=GEN_COLOR[p], lw=0)
        ax.set_title(NAMES[p], fontsize=8)
        ax.set_xlabel("Node (ranked)", fontsize=7)
        ax.tick_params(labelsize=6.5)
    axes[0].set_ylabel("Rounds served\nas head", fontsize=7)
    os.makedirs(OUT, exist_ok=True)
    fig.savefig(os.path.join(OUT, "figG_head_rotation.png"))
    plt.close(fig)
    print("wrote figG_head_rotation.png")


def fig_scale() -> None:
    path = "results/scale/scale_aggregate.csv"
    if not os.path.exists(path):
        print("skip figD/figE: run scripts/scale_sweep.py first")
        return
    df = pd.read_csv(path)
    sides = sorted(df["field_side"].unique())
    show = [p for p in ORDER if p in set(df["protocol"])]

    # Log y: first node death spans 22 to 6831 rounds across the grid, so a
    # linear shared axis renders the 150x150 panel as a flat line at the
    # bottom. Each protocol gets its own line style within its generation
    # colour, because ten lines in four colours cannot be told apart.
    styles = {}
    for gen_members in (["leach", "pegasis", "teen", "apteen"],
                        ["nsga2", "fuzzy_t2"], ["som", "dqn", "gcn"], ["stub"]):
        for k, p in enumerate(gen_members):
            styles[p] = ["-", "--", ":", "-."][k % 4]

    fig, axes = plt.subplots(1, len(sides), figsize=(7.2, 2.6), sharey=True)
    axes = np.atleast_1d(axes)
    for ax, side in zip(axes, sides):
        sub = df[df["field_side"] == side]
        for p in show:
            s = sub[sub["protocol"] == p].sort_values("n_nodes")
            if len(s) < 2:
                continue
            ax.plot(s["n_nodes"], s["fnd_mean"], marker="o", ms=3.5, lw=1.3,
                    color=GEN_COLOR[p], alpha=0.9, ls=styles[p], label=NAMES[p])
        ax.set_yscale("log")
        ax.set_title(f"{int(side)}$\\times${int(side)} m", fontsize=8)
        ax.set_xlabel("Nodes $N$")
        ax.set_xticks(sorted(sub["n_nodes"].unique()))
    axes[0].set_ylabel("First node death\n(rounds, log scale)")
    axes[-1].legend(frameon=False, fontsize=6, loc="center left",
                    bbox_to_anchor=(1.02, 0.5))
    os.makedirs(OUT, exist_ok=True)
    fig.savefig(os.path.join(OUT, "figD_scale_fnd.png"))
    plt.close(fig)
    print("wrote figD_scale_fnd.png")

    fig, ax = plt.subplots(figsize=(3.4, 2.5))
    for p in show:
        s = df[df["protocol"] == p].sort_values("density_per_ha")
        ax.plot(s["density_per_ha"], s["fnd_mean"], marker="o", ms=3, lw=1.0, ls=styles[p],
                color=GEN_COLOR[p], alpha=0.8, label=NAMES[p])
    ax.set_xscale("log")
    ax.set_xlabel("Node density (nodes/ha, log scale)")
    ax.set_ylabel("First node death (rounds)")
    ax.legend(frameon=False, fontsize=6, ncol=2)
    fig.savefig(os.path.join(OUT, "figE_scale_density.png"))
    plt.close(fig)
    print("wrote figE_scale_density.png")


if __name__ == "__main__":
    fig_per_curve()
    fig_fnd_distribution()
    fig_mechanism()
    fig_head_distance()
    fig_head_rotation()
    fig_scale()
