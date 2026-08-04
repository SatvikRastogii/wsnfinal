"""Aggregate the sweep into paper-ready tables and figures.

Reads results/<channel>/{summary,raw}/ and writes results/analysis/.

Statistics are paired: run index i is the same topology, shadowing and sensed-value
stream for every protocol, so per-run differences are meaningful and a paired test is
strictly stronger than comparing two means with their standard deviations. scipy is not
a dependency here, so the paired test is a sign-flip permutation test and the interval
is a paired bootstrap -- both exact-by-construction and assumption-free about normality.

Usage:
    python analyze.py                       # both channels, all figures
    python analyze.py --channels lossy      # headline only
"""

import argparse
import os
import sys

import numpy as np
import pandas as pd

# The report contains +-, >= and arrows. On Windows stdout defaults to cp1252, which
# cannot encode them and would crash the print at the very end, after all the work.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

N_PERM = 20000
N_BOOT = 20000
STAT_SEED = 12345

# Order protocols by class, so every table and figure groups them the same way and the
# control-traffic confound (docs/TRADEOFFS.md A1) is visible as a block rather than
# scattered through an alphabetical list.
CLASS_OF = {
    "leach": "distributed", "teen": "distributed", "apteen": "distributed",
    "pegasis": "chain",
    "nsga2": "centralized", "fuzzy_t2": "centralized", "som": "centralized",
    "dqn": "centralized", "gcn": "centralized",
    "stub": "baseline",
}
ORDER = ["stub", "leach", "teen", "apteen", "pegasis",
         "nsga2", "fuzzy_t2", "som", "dqn", "gcn"]


def _sorted_protocols(names):
    known = [p for p in ORDER if p in names]
    return known + sorted(n for n in names if n not in ORDER)


def load_summaries(root, channel):
    """dict protocol -> per-run summary DataFrame, indexed by run_id."""
    d = os.path.join(root, channel, "summary")
    out = {}
    for fn in sorted(os.listdir(d)):
        if not fn.endswith("_summary.csv"):
            continue
        name = fn[: -len("_summary.csv")]
        out[name] = pd.read_csv(os.path.join(d, fn)).sort_values("run_id").reset_index(drop=True)
    return out


def load_raw_mean(root, channel, protocol, column, max_rounds=None):
    """Mean of `column` across runs, per round, padded to the longest run.

    Padding matters and is column-specific: a dead network has 0 alive nodes and 0
    residual energy forever after, so those pad with 0. Anything else pads with NaN and
    is averaged over the runs that actually reached that round -- otherwise the curve
    would show a protocol getting quieter rather than being dead.
    """
    d = os.path.join(root, channel, "raw", protocol)
    series = []
    for fn in sorted(os.listdir(d)):
        s = pd.read_csv(os.path.join(d, fn))[column].to_numpy(dtype=float)
        series.append(s)
    n = max(len(s) for s in series)
    if max_rounds:
        n = min(n, max_rounds)
    pad = 0.0 if column in ("alive_nodes", "total_residual_energy",
                            "mean_residual_energy_all") else np.nan
    mat = np.full((len(series), n), pad, dtype=float)
    for i, s in enumerate(series):
        k = min(len(s), n)
        mat[i, :k] = s[:k]
    with np.errstate(invalid="ignore"):
        return np.nanmean(mat, axis=0)


# ----------------------------------------------------------------- paired statistics

def _nanmean(x):
    """np.nanmean without the all-NaN RuntimeWarning.

    An all-NaN column is a real state here, not an error: `fnd` is NaN when no node died
    inside the round cap, which happens on short configurations and could happen to a
    very frugal protocol on the real cap too.
    """
    x = np.asarray(x, dtype=float)
    return float(np.mean(x[np.isfinite(x)])) if np.isfinite(x).any() else np.nan


def paired_permutation(a, b, n_perm=N_PERM, seed=STAT_SEED):
    """Two-sided paired sign-flip permutation test on the mean difference a - b.

    Returns (mean_diff, p_value, n_pairs). Pairs where either side is NaN are dropped,
    which is why n_pairs is returned -- a censored lnd shrinks the usable sample and the
    reader needs to see that.
    """
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    ok = np.isfinite(a) & np.isfinite(b)
    d = a[ok] - b[ok]
    n = len(d)
    if n < 2:
        return (float(np.mean(d)) if n else np.nan), np.nan, n
    obs = float(np.mean(d))
    if np.allclose(d, 0.0):
        return obs, 1.0, n
    rng = np.random.default_rng(seed)
    signs = rng.choice([-1.0, 1.0], size=(n_perm, n))
    null = (signs * d).mean(axis=1)
    # +1 in both terms: the observed arrangement is itself one of the possible sign
    # assignments, so p is never reported as exactly 0.
    p = (np.sum(np.abs(null) >= abs(obs) - 1e-12) + 1) / (n_perm + 1)
    return obs, float(p), n


def paired_bootstrap_ci(a, b, n_boot=N_BOOT, seed=STAT_SEED, alpha=0.05):
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    ok = np.isfinite(a) & np.isfinite(b)
    d = a[ok] - b[ok]
    if len(d) < 2:
        return np.nan, np.nan
    rng = np.random.default_rng(seed + 1)
    idx = rng.integers(0, len(d), size=(n_boot, len(d)))
    means = d[idx].mean(axis=1)
    return float(np.quantile(means, alpha / 2)), float(np.quantile(means, 1 - alpha / 2))


def holm_bonferroni(pvals):
    """Holm step-down adjusted p-values. Order-preserving, no independence assumption."""
    p = np.asarray(pvals, dtype=float)
    ok = np.isfinite(p)
    adj = np.full_like(p, np.nan)
    idx = np.where(ok)[0]
    order = idx[np.argsort(p[idx])]
    m = len(order)
    running = 0.0
    for rank, i in enumerate(order):
        val = (m - rank) * p[i]
        running = max(running, val)
        adj[i] = min(1.0, running)
    return adj


def pairwise_table(summaries, metric, baseline=None):
    """Paired comparison table for one metric.

    With `baseline`, every protocol is compared against it (n-1 comparisons). Without,
    every unordered pair is compared. Holm correction is applied across the whole family
    of comparisons in the table.
    """
    names = _sorted_protocols(summaries)
    pairs = ([(p, baseline) for p in names if p != baseline] if baseline
             else [(x, y) for i, x in enumerate(names) for y in names[i + 1:]])
    rows = []
    for x, y in pairs:
        a, b = summaries[x][metric].to_numpy(), summaries[y][metric].to_numpy()
        diff, p, n = paired_permutation(a, b)
        lo, hi = paired_bootstrap_ci(a, b)
        rows.append({
            "metric": metric, "protocol_a": x, "protocol_b": y, "n_pairs": n,
            "mean_a": _nanmean(a), "mean_b": _nanmean(b),
            "mean_diff": diff, "ci95_lo": lo, "ci95_hi": hi, "p_raw": p,
        })
    df = pd.DataFrame(rows)
    if len(df):
        df["p_holm"] = holm_bonferroni(df["p_raw"].to_numpy())
        df["significant_005"] = df["p_holm"] < 0.05
    return df


# ------------------------------------------------------------------------- headline

HEADLINE = [
    ("fnd", "FND"), ("hnd", "HND"), ("lnd", "LND"),
    ("alive_node_auc", "alive AUC"),
    ("readings_delivered_total", "readings"), ("throughput_total", "BS packets"),
    ("pdr_percent", "PDR %"), ("data_yield", "yield"),
    ("mean_latency_ms", "latency ms"), ("p95_latency_ms", "p95 ms"),
    ("total_control_packets", "ctrl pkts"),
    ("ops_per_round", "ops/round"), ("mean_setup_ms", "setup ms"),
    ("peak_memory_kb", "peak KiB"),
]


def headline_table(summaries):
    rows = []
    for name in _sorted_protocols(summaries):
        df = summaries[name]
        row = {"protocol": name, "class": CLASS_OF.get(name, "?"),
               "n_runs": len(df), "n_censored": int(df["lnd_censored"].sum())}
        for col, _ in HEADLINE:
            v = pd.to_numeric(df[col], errors="coerce")
            row[f"{col}_mean"] = v.mean()
            row[f"{col}_std"] = v.std(ddof=1) if v.notna().sum() > 1 else np.nan
            row[f"{col}_min"] = v.min()
            row[f"{col}_max"] = v.max()
        rows.append(row)
    return pd.DataFrame(rows)


def markdown_headline(h):
    """Compact mean +- std table. Censored LND is marked so it is never read as measured."""
    lines = ["| protocol | class | FND | HND | LND | alive AUC | readings | PDR % | yield |",
             "|---|---|---|---|---|---|---|---|---|"]
    for _, r in h.iterrows():
        lnd = f"{r['lnd_mean']:.0f}"
        if r["n_censored"] > 0:
            lnd = f"≥{lnd} ({int(r['n_censored'])}/{int(r['n_runs'])} cens.)"
        lines.append(
            f"| {r['protocol']} | {r['class']} | {r['fnd_mean']:.0f} ± {r['fnd_std']:.0f} | "
            f"{r['hnd_mean']:.0f} ± {r['hnd_std']:.0f} | {lnd} | {r['alive_node_auc_mean']:.0f} | "
            f"{r['readings_delivered_total_mean']:.0f} | {r['pdr_percent_mean']:.1f} | "
            f"{r['data_yield_mean']:.3f} |")
    return "\n".join(lines)


def channel_robustness(sums_by_channel, metric):
    """Does each protocol's rank on `metric` survive the lossy/ideal switch?

    This is the operational form of the Pt-sensitivity caveat (docs/TRADEOFFS.md A2):
    a conclusion that flips between channels is a conclusion about transmit power.
    """
    chans = list(sums_by_channel)
    if len(chans) < 2:
        return pd.DataFrame()
    names = _sorted_protocols(sums_by_channel[chans[0]])
    rows = []
    means = {c: {n: pd.to_numeric(sums_by_channel[c][n][metric], errors="coerce").mean()
                 for n in names} for c in chans}
    ranks = {c: {n: r for r, n in enumerate(
        sorted(names, key=lambda k: -means[c][k]), start=1)} for c in chans}
    for n in names:
        rows.append({"metric": metric, "protocol": n,
                     **{f"{c}_mean": means[c][n] for c in chans},
                     **{f"{c}_rank": ranks[c][n] for c in chans},
                     "rank_shift": ranks[chans[1]][n] - ranks[chans[0]][n]})
    return pd.DataFrame(rows)


# -------------------------------------------------------------------------- figures

def make_figures(root, channel, summaries, outdir):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    os.makedirs(outdir, exist_ok=True)
    names = _sorted_protocols(summaries)
    cmap = plt.get_cmap("tab10")
    colors = {n: cmap(i % 10) for i, n in enumerate(names)}

    def save(fig, fn):
        fig.tight_layout()
        fig.savefig(os.path.join(outdir, fn), dpi=200)
        plt.close(fig)

    # 1. alive-node curves -- the figure every other lifetime number summarizes
    fig, ax = plt.subplots(figsize=(8, 5))
    for n in names:
        y = load_raw_mean(root, channel, n, "alive_nodes")
        ax.plot(np.arange(len(y)), y, label=n, color=colors[n], lw=1.4)
    ax.set(xlabel="round", ylabel="alive nodes (mean over runs)",
           title=f"Node survival — {channel} channel")
    ax.legend(fontsize=8, ncol=2)
    ax.grid(alpha=0.3)
    save(fig, "fig1_alive_nodes.png")

    # 2. three lifetime points side by side, because they disagree (TRADEOFFS A4)
    fig, ax = plt.subplots(figsize=(9, 5))
    x = np.arange(len(names))
    for k, (col, lab) in enumerate([("fnd", "FND"), ("hnd", "HND"), ("lnd", "LND")]):
        m = [pd.to_numeric(summaries[n][col], errors="coerce").mean() for n in names]
        e = [pd.to_numeric(summaries[n][col], errors="coerce").std(ddof=1) for n in names]
        ax.bar(x + (k - 1) * 0.27, m, 0.27, yerr=e, capsize=2, label=lab)
    for i, n in enumerate(names):
        if summaries[n]["lnd_censored"].sum() > 0:
            ax.text(i + 0.27, pd.to_numeric(summaries[n]["lnd"], errors="coerce").mean(),
                    "†", ha="center", va="bottom", fontsize=13)
    ax.set(ylabel="round", title=f"Lifetime at three points — {channel}  († LND censored)")
    ax.set_xticks(x, names, rotation=30, ha="right")
    ax.legend()
    ax.grid(alpha=0.3, axis="y")
    save(fig, "fig2_lifetime_points.png")

    # 3. residual energy depletion
    fig, ax = plt.subplots(figsize=(8, 5))
    for n in names:
        y = load_raw_mean(root, channel, n, "total_residual_energy")
        ax.plot(np.arange(len(y)), y, label=n, color=colors[n], lw=1.4)
    ax.set(xlabel="round", ylabel="total residual energy (J)",
           title=f"Network energy depletion — {channel}")
    ax.legend(fontsize=8, ncol=2)
    ax.grid(alpha=0.3)
    save(fig, "fig3_energy.png")

    # 4. lifetime vs delivery -- the actual trade surface
    fig, ax = plt.subplots(figsize=(7, 5.5))
    for n in names:
        xv = pd.to_numeric(summaries[n]["alive_node_auc"], errors="coerce").mean()
        yv = pd.to_numeric(summaries[n]["readings_delivered_total"], errors="coerce").mean()
        ax.scatter(xv, yv, s=90, color=colors[n], zorder=3)
        ax.annotate(n, (xv, yv), textcoords="offset points", xytext=(6, 4), fontsize=9)
    ax.set(xlabel="alive-node AUC (node·rounds)", ylabel="readings delivered",
           title=f"Lifetime vs delivered data — {channel}")
    ax.grid(alpha=0.3)
    save(fig, "fig4_lifetime_vs_delivery.png")

    # 5. control traffic -- makes the centralized subsidy (TRADEOFFS A1) visible
    fig, ax = plt.subplots(figsize=(8, 4.5))
    vals = [pd.to_numeric(summaries[n]["total_control_packets"], errors="coerce").mean()
            for n in names]
    ax.bar(names, vals, color=[colors[n] for n in names])
    ax.set(yscale="log", ylabel="control packets per run (log)",
           title=f"Control traffic — {channel}\n"
                 "centralized protocols piggyback uplink state; see TRADEOFFS.md A1")
    ax.tick_params(axis="x", rotation=30)
    ax.grid(alpha=0.3, axis="y")
    save(fig, "fig5_control_traffic.png")

    # 6. computational cost, counted vs measured, both log
    fig, ax = plt.subplots(figsize=(7, 5.5))
    for n in names:
        xv = pd.to_numeric(summaries[n]["ops_per_round"], errors="coerce").mean()
        yv = pd.to_numeric(summaries[n]["mean_setup_ms"], errors="coerce").mean()
        if not (np.isfinite(xv) and np.isfinite(yv)) or xv <= 0 or yv <= 0:
            continue
        ax.scatter(xv, yv, s=90, color=colors[n], zorder=3)
        ax.annotate(n, (xv, yv), textcoords="offset points", xytext=(6, 4), fontsize=9)
    ax.set(xscale="log", yscale="log", xlabel="counted ops per round",
           ylabel="measured setup ms per round",
           title=f"Computational cost: counted vs measured — {channel}")
    ax.grid(alpha=0.3, which="both")
    save(fig, "fig6_compute_cost.png")

    # 7. PDR against survival, so PDR is never read alone (TRADEOFFS A5)
    fig, ax = plt.subplots(figsize=(7, 5.5))
    for n in names:
        xv = pd.to_numeric(summaries[n]["alive_node_auc"], errors="coerce").mean()
        yv = pd.to_numeric(summaries[n]["pdr_percent"], errors="coerce").mean()
        ax.scatter(xv, yv, s=90, color=colors[n], zorder=3)
        ax.annotate(n, (xv, yv), textcoords="offset points", xytext=(6, 4), fontsize=9)
    ax.set(xlabel="alive-node AUC (node·rounds)", ylabel="PDR %",
           title=f"PDR is survivorship-biased — {channel}")
    ax.grid(alpha=0.3)
    save(fig, "fig7_pdr_survivorship.png")


def make_channel_figure(sums_by_channel, outdir):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    chans = list(sums_by_channel)
    if len(chans) < 2:
        return
    names = _sorted_protocols(sums_by_channel[chans[0]])
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    for ax, metric, lab in zip(axes, ["fnd", "readings_delivered_total"],
                               ["FND (round)", "readings delivered"]):
        x = np.arange(len(names))
        for k, c in enumerate(chans):
            m = [pd.to_numeric(sums_by_channel[c][n][metric], errors="coerce").mean()
                 for n in names]
            ax.bar(x + (k - 0.5) * 0.38, m, 0.38, label=c)
        ax.set(ylabel=lab, title=f"{lab}: lossy vs ideal")
        ax.set_xticks(x, names, rotation=30, ha="right")
        ax.legend()
        ax.grid(alpha=0.3, axis="y")
    fig.suptitle("Conclusions stable across both channels are about the protocol; "
                 "conclusions that flip are about transmit power (TRADEOFFS.md A2)",
                 fontsize=9)
    fig.tight_layout()
    fig.savefig(os.path.join(outdir, "fig8_channel_sensitivity.png"), dpi=200)
    plt.close(fig)


# --------------------------------------------------------------------- verification

def verify_aggregate(root, channel, summaries, protocol):
    """Recompute one protocol's aggregate row from the per-run CSVs and diff it.

    This is the plan's step-7 gate: aggregate.csv must be reproducible by hand from the
    summaries, not merely plausible.
    """
    agg = pd.read_csv(os.path.join(root, channel, "aggregate.csv"))
    row = agg[agg["protocol"] == protocol]
    if row.empty:
        return [f"{protocol}: MISSING from aggregate.csv"]
    row = row.iloc[0]
    df = summaries[protocol]
    out, bad = [], 0
    for col, _ in HEADLINE:
        v = pd.to_numeric(df[col], errors="coerce")
        for stat, mine in (("mean", v.mean()),
                           ("std", v.std(ddof=1) if v.notna().sum() > 1 else np.nan)):
            key = f"{col}_{stat}"
            if key not in row:
                continue
            theirs = float(row[key])
            same = ((np.isnan(mine) and np.isnan(theirs))
                    or np.isclose(mine, theirs, rtol=1e-9, atol=1e-9, equal_nan=True))
            if not same:
                bad += 1
                out.append(f"  MISMATCH {key}: recomputed {mine!r} vs aggregate {theirs!r}")
    ncens = int(df["lnd_censored"].sum())
    if ncens != int(row["n_censored_runs"]):
        bad += 1
        out.append(f"  MISMATCH n_censored_runs: {ncens} vs {int(row['n_censored_runs'])}")
    head = (f"aggregate.csv verification [{channel}/{protocol}]: "
            f"{'PASS' if bad == 0 else f'FAIL ({bad} mismatches)'}")
    return [head] + out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default="results")
    ap.add_argument("--channels", nargs="+", default=["lossy", "ideal"])
    ap.add_argument("--baseline", default="leach",
                    help="protocol every other is paired against in the stats table")
    ap.add_argument("--no-figures", action="store_true")
    args = ap.parse_args()

    outdir = os.path.join(args.results, "analysis")
    os.makedirs(outdir, exist_ok=True)
    channels = [c for c in args.channels
                if os.path.isdir(os.path.join(args.results, c, "summary"))]
    if not channels:
        raise SystemExit(f"no channel directories found under {args.results}")

    sums_by_channel, report = {}, []
    for ch in channels:
        s = load_summaries(args.results, ch)
        sums_by_channel[ch] = s

        h = headline_table(s)
        h.to_csv(os.path.join(outdir, f"headline_{ch}.csv"), index=False)
        report += [f"\n## {ch} channel — headline\n", markdown_headline(h), ""]

        stats = []
        for metric in ("fnd", "hnd", "alive_node_auc", "readings_delivered_total",
                       "pdr_percent", "data_yield", "mean_latency_ms",
                       "total_control_packets"):
            t = pairwise_table(s, metric, baseline=args.baseline)
            if len(t):
                stats.append(t)
        if stats:
            st = pd.concat(stats, ignore_index=True)
            st.to_csv(os.path.join(outdir, f"paired_tests_{ch}.csv"), index=False)
            sig = st[(st["metric"] == "fnd")]
            report.append(f"### {ch}: FND vs {args.baseline} "
                          f"(paired permutation, Holm-corrected)\n")
            report.append("| protocol | mean FND | Δ vs baseline | 95% CI | p (Holm) | sig |")
            report.append("|---|---|---|---|---|---|")
            for _, r in sig.iterrows():
                report.append(
                    f"| {r['protocol_a']} | {r['mean_a']:.0f} | {r['mean_diff']:+.0f} | "
                    f"[{r['ci95_lo']:+.0f}, {r['ci95_hi']:+.0f}] | {r['p_holm']:.4f} | "
                    f"{'yes' if r['significant_005'] else 'no'} |")
            report.append("")

        target = args.baseline if args.baseline in s else sorted(s)[0]
        report += verify_aggregate(args.results, ch, s, target) + [""]

        if not args.no_figures:
            make_figures(args.results, ch, s, os.path.join(outdir, f"figures_{ch}"))

    if len(channels) > 1:
        rob = pd.concat([channel_robustness(sums_by_channel, m)
                         for m in ("fnd", "hnd", "alive_node_auc",
                                   "readings_delivered_total")], ignore_index=True)
        rob.to_csv(os.path.join(outdir, "channel_robustness.csv"), index=False)
        flips = rob[rob["rank_shift"] != 0]
        report.append("\n## Channel robustness (rank shift lossy → ideal)\n")
        report.append(f"{len(flips)} of {len(rob)} protocol-metric ranks move when the "
                      "channel changes. A rank that moves is a statement about transmit "
                      "power, not about the protocol (TRADEOFFS.md A2).\n")
        if len(flips):
            report.append("| metric | protocol | lossy rank | ideal rank | shift |")
            report.append("|---|---|---|---|---|")
            for _, r in flips.iterrows():
                report.append(f"| {r['metric']} | {r['protocol']} | {int(r['lossy_rank'])} | "
                              f"{int(r['ideal_rank'])} | {int(r['rank_shift']):+d} |")
        if not args.no_figures:
            make_channel_figure(sums_by_channel, outdir)

    text = "\n".join(report)
    with open(os.path.join(outdir, "REPORT.md"), "w", encoding="utf-8") as f:
        f.write("# Analysis report\n\nGenerated by analyze.py. See docs/TRADEOFFS.md "
                "for what each caveat means.\n" + text + "\n")
    print(text)
    print(f"\nwrote {outdir}")


if __name__ == "__main__":
    main()
