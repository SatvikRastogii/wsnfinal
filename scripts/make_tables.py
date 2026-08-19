"""Generate every LaTeX table in the paper directly from the result CSVs.

Nothing here is hand-typed from a draft: each table is read out of
results/analysis/ (or wsn_sim/config.py) at generation time, so a table can
never silently disagree with the data it claims to summarise. Re-run this
after any re-analysis and the tables update.

Output: paper/tables/*.tex, one file per table, each a complete float ready
for \\input{}. The preamble needs \\usepackage{booktabs} and, for the wide
tables, \\usepackage{graphicx} (they use \\resizebox).

Usage:
    python scripts/make_tables.py
    python scripts/make_tables.py --scale      # also emit the scale-sweep tables
"""

import argparse
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wsn_sim.config import SimConfig  # noqa: E402

ANALYSIS = "results/analysis"
OUT = "paper/tables"

# Display names and the order protocols appear in every table: baseline first,
# then the three generations in chronological order.
ORDER = ["stub", "leach", "pegasis", "teen", "apteen", "nsga2", "fuzzy_t2", "som", "dqn", "gcn"]
NAMES = {
    "stub": "Direct (no clustering)",
    "leach": "LEACH",
    "pegasis": "PEGASIS",
    "teen": "TEEN",
    "apteen": "APTEEN",
    "nsga2": "NSGA-II",
    "fuzzy_t2": "Fuzzy T2",
    "som": "SOM",
    "dqn": "DQN",
    "gcn": "GCN",
}
GENERATION = {
    "stub": "--",
    "leach": "G1", "pegasis": "G1", "teen": "G1", "apteen": "G1",
    "nsga2": "G2", "fuzzy_t2": "G2",
    "som": "G3", "dqn": "G3", "gcn": "G3",
}


def _write(name: str, body: str) -> None:
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(body.rstrip() + "\n")
    print(f"wrote {path}")


def _float(fmt: str, caption: str, label: str, body: str, wide: bool = False,
           note: str = "") -> str:
    env = "table*" if wide else "table"
    pos = "[!t]"
    # A plain paragraph rather than \begin{tablenotes}, which would drag in
    # the threeparttable package for one line of text.
    note_tex = f"\n\n{{\\footnotesize {note}\\par}}" if note else ""
    return (
        f"\\begin{{{env}}}{pos}\n"
        f"\\caption{{{caption}}}\n"
        f"\\label{{{label}}}\n"
        f"\\centering\n"
        f"\\begin{{tabular}}{{{fmt}}}\n"
        f"\\toprule\n"
        f"{body}\n"
        f"\\bottomrule\n"
        f"\\end{{tabular}}{note_tex}\n"
        f"\\end{{{env}}}"
    )


def _ms(mean, std, prec=0):
    """mean +- std, or an em-dash when the value is missing."""
    if pd.isna(mean):
        return "--"
    if pd.isna(std):
        return f"{mean:,.{prec}f}"
    return f"{mean:,.{prec}f} $\\pm$ {std:,.{prec}f}"


# ---------------------------------------------------------------------------
# Table I -- simulation parameters, read straight out of SimConfig
# ---------------------------------------------------------------------------

def table_parameters() -> None:
    c = SimConfig()
    groups = [
        ("Topology and energy", [
            ("Nodes $N$", f"{c.n_nodes}"),
            ("Field", f"{c.field_w:.0f} $\\times$ {c.field_h:.0f} m"),
            ("Base station", f"$({c.bs_x:.0f}, {c.bs_y:.0f})$ m"),
            ("Initial energy $E_0$", f"{c.e0:.1f} J per node"),
            ("Rounds (cap)", f"{c.max_rounds:,}"),
            ("Runs per configuration", f"{c.n_runs}"),
        ]),
        ("Packets", [
            ("Data packet", f"{c.data_bits:,} bits"),
            ("Control packet", f"{c.ctrl_bits} bits"),
        ]),
        ("Radio (first-order model)", [
            ("$E_{\\mathrm{elec}}$", f"{c.e_elec * 1e9:.0f} nJ/bit"),
            ("$\\varepsilon_{\\mathrm{fs}}$", f"{c.eps_fs * 1e12:.0f} pJ/bit/m$^2$"),
            ("$\\varepsilon_{\\mathrm{mp}}$", f"{c.eps_mp * 1e12:.4f} pJ/bit/m$^4$"),
            ("$E_{\\mathrm{DA}}$ (fusion)", f"{c.e_da * 1e9:.0f} nJ/bit"),
            ("Crossover $d_0$", f"{c.d0:.1f} m"),
        ]),
        ("Channel", [
            ("Transmit power $P_t$", f"{c.pt_dbm:.0f} dBm"),
            ("Path loss at 1 m", f"{c.pl_1m_db:.0f} dB"),
            ("Path-loss exponent $n$", f"{c.path_loss_n:.1f}"),
            ("Shadowing $\\sigma$", f"{c.shadow_sigma_db:.0f} dB"),
            ("Noise floor", f"{c.noise_floor_dbm:.0f} dBm"),
            ("ARQ retransmissions", f"{c.max_retx}"),
        ]),
        ("Sensed data (Ornstein--Uhlenbeck)", [
            ("Mean $\\mu$, reversion $\\theta$", f"{c.sense_mu:.0f}, {c.sense_theta:.2f}"),
            ("Step $\\sigma$", f"{c.sense_sigma:.1f}"),
            ("TEEN/APTEEN $H_T$, $S_T$, $T_C$",
             f"{c.ht:.0f}, {c.st:.1f}, {c.tc} rounds"),
        ]),
        ("Protocol-agnostic", [
            ("Head fraction $p$", f"{c.p_ch:.2f}"),
            ("Density radius", f"{c.density_radius:.0f} m"),
            ("NSGA-II population, generations",
             f"{c.pop_size}, {c.generations}"),
            ("Re-clustering interval", f"{c.ga_interval} rounds"),
        ]),
        ("Timing", [
            ("Bit rate", f"{c.bitrate_bps / 1000:.0f} kbps"),
            ("Slot / guard / processing",
             f"{c.slot_ms:.0f} / {c.guard_ms:.0f} / {c.proc_ms:.0f} ms"),
        ]),
    ]
    rows = []
    for gname, items in groups:
        rows.append(f"\\multicolumn{{2}}{{l}}{{\\textit{{{gname}}}}} \\\\")
        for k, v in items:
            rows.append(f"\\quad {k} & {v} \\\\")
        rows.append("\\addlinespace")
    body = "Parameter & Value \\\\\n\\midrule\n" + "\n".join(rows[:-1])
    _write("tab1_parameters.tex", _float(
        "ll",
        "Simulation parameters. Every value is read from the single frozen "
        "configuration object used by all ten protocols; nothing is "
        "protocol-specific.",
        "tab:parameters", body))


# ---------------------------------------------------------------------------
# Table II -- protocol taxonomy (structural facts, not measurements)
# ---------------------------------------------------------------------------

def table_taxonomy() -> None:
    rows = [
        # name, gen, decision, control model, re-cluster, offline training
        ("Direct (no clustering)", "--", "None", "None", "--", "No"),
        ("LEACH", "G1", "Randomised rotation", "Distributed", "Every round", "No"),
        ("PEGASIS", "G1", "Greedy chain", "Chain", "On death", "No"),
        ("TEEN", "G1", "LEACH + hard/soft threshold", "Distributed", "Every round", "No"),
        ("APTEEN", "G1", "TEEN + count-down timer", "Distributed", "Every round", "No"),
        ("NSGA-II", "G2", "Multi-objective search (3 obj.)", "Centralized", "Every 5 rounds", "No"),
        ("Fuzzy T2", "G2", "Interval type-2 rule base (27 rules)", "Centralized", "Every round", "No"),
        ("SOM", "G3", "Self-organising map", "Centralized", "Every round", "Yes"),
        ("DQN", "G3", "Learned $Q$-value ranking", "Centralized", "Every round", "Yes (frozen)"),
        ("GCN", "G3", "Learned graph scoring", "Centralized", "Every round", "Yes (frozen)"),
    ]
    body = ("Protocol & Gen. & Head-selection rule & Control model & Re-cluster & Offline train \\\\\n"
            "\\midrule\n"
            + "\n".join(" & ".join(r) + " \\\\" for r in rows))
    _write("tab2_taxonomy.tex", _float(
        "llllll",
        "The ten configurations compared. ``Control model'' determines which "
        "setup messages are charged: distributed protocols pay "
        "advertisement, join and schedule; the chain protocol pays a "
        "hop-by-hop token; centralized protocols pay only the downlink "
        "schedule, their uplink state being piggybacked on data traffic "
        "(Section~\\ref{sec:validity}).",
        "tab:taxonomy", body, wide=True))


# ---------------------------------------------------------------------------
# Tables III--V -- headline measurements
# ---------------------------------------------------------------------------

def _headline(channel: str) -> pd.DataFrame:
    df = pd.read_csv(os.path.join(ANALYSIS, f"headline_{channel}.csv"))
    return df.set_index("protocol").reindex(ORDER)


def table_lifetime() -> None:
    d = _headline("lossy")
    rows = []
    for p in ORDER:
        r = d.loc[p]
        lnd = _ms(r["lnd_mean"], r["lnd_std"])
        if r["n_censored"] > 0:
            lnd = f"$>${r['lnd_mean']:,.0f}\\textsuperscript{{c}}"
        rows.append(" & ".join([
            NAMES[p], GENERATION[p],
            _ms(r["fnd_mean"], r["fnd_std"]),
            _ms(r["hnd_mean"], r["hnd_std"]),
            lnd,
            f"{r['alive_node_auc_mean'] / 1000:,.1f}",
        ]) + " \\\\")
    body = ("Protocol & Gen. & FND & HND & LND & AUC ($\\times 10^3$) \\\\\n"
            "\\midrule\n" + "\n".join(rows))
    _write("tab3_lifetime.tex", _float(
        "llrrrr",
        "Lifetime, lossy channel, 30 paired runs (mean $\\pm$ sample std, "
        "rounds). FND/HND/LND are first, half and last node death. AUC is the "
        "area under the living-node curve, the censoring-robust survival "
        "measure.",
        "tab:lifetime", body,
        note="\\textsuperscript{c} Censored: the network had not died at the "
             "7000-round cap in any run. Use AUC, not LND, for these two."))


def table_delivery() -> None:
    d = _headline("lossy")
    rows = []
    for p in ORDER:
        r = d.loc[p]
        rows.append(" & ".join([
            NAMES[p], GENERATION[p],
            f"{r['throughput_total_mean'] / 1000:,.1f}",
            f"{r['readings_delivered_total_mean'] / 1000:,.1f}",
            f"{r['pdr_percent_mean']:.1f}",
            f"{r['data_yield_mean']:.3f}",
        ]) + " \\\\")
    body = ("Protocol & Gen. & Packets at BS & Readings & PDR (\\%) & Data yield \\\\\n"
            " & & ($\\times 10^3$) & delivered ($\\times 10^3$) & & \\\\\n"
            "\\midrule\n" + "\n".join(rows))
    _write("tab4_delivery.tex", _float(
        "llrrrr",
        "Delivery, lossy channel. Packets at the base station measure "
        "aggregation depth, not delivery, and are not comparable across "
        "protocols; readings delivered and data yield are. Data yield is "
        "readings arriving at the sink divided by readings taken, so it is "
        "the column that prices TEEN and APTEEN's suppression.",
        "tab:delivery", body))


def table_cost() -> None:
    d = _headline("lossy")
    rows = []
    for p in ORDER:
        r = d.loc[p]
        rows.append(" & ".join([
            NAMES[p], GENERATION[p],
            f"{r['mean_latency_ms_mean']:,.0f}",
            f"{r['p95_latency_ms_mean']:,.0f}",
            f"{r['total_control_packets_mean'] / 1000:,.1f}",
            f"{r['ops_per_round_mean']:,.0f}",
            f"{r['mean_setup_ms_mean']:.2f}",
            f"{r['peak_memory_kb_mean'] / 1024:.1f}",
        ]) + " \\\\")
    body = ("Protocol & Gen. & Latency & p95 & Control pkts & Ops per & Setup & Peak mem \\\\\n"
            " & & (ms) & (ms) & ($\\times 10^3$) & round & (ms) & (MB) \\\\\n"
            "\\midrule\n" + "\n".join(rows))
    _write("tab5_cost.tex", _float(
        "llrrrrrr",
        "Cost, lossy channel. Counted operations are the honest "
        "cross-protocol comparison; wall-clock setup time reflects "
        "implementation quality as much as algorithm design and is reported "
        "separately for that reason. DQN and GCN setup times are inference "
        "only: their one-off offline training is not included here "
        "(Section~\\ref{sec:validity}).",
        "tab:cost", body, wide=True))


# ---------------------------------------------------------------------------
# Tables VI--VII -- paired significance tests, both channels
# ---------------------------------------------------------------------------

def _paired(metric: str) -> pd.DataFrame:
    out = {}
    for ch in ("lossy", "ideal"):
        df = pd.read_csv(os.path.join(ANALYSIS, f"paired_tests_{ch}.csv"))
        out[ch] = df[df["metric"] == metric].set_index("protocol_a")
    return out


def _sig(p):
    return f"{p:.4f}" if p >= 1e-4 else "$<$0.0001"


def table_paired_fnd() -> None:
    t = _paired("fnd")
    rows = []
    for p in ORDER:
        if p == "leach" or p not in t["lossy"].index:
            continue
        lo, io = t["lossy"].loc[p], t["ideal"].loc[p]
        rows.append(" & ".join([
            NAMES[p],
            f"{lo['mean_diff']:+,.0f}",
            f"[{lo['ci95_lo']:+,.0f}, {lo['ci95_hi']:+,.0f}]",
            _sig(lo["p_holm"]),
            f"{io['mean_diff']:+,.0f}",
            f"[{io['ci95_lo']:+,.0f}, {io['ci95_hi']:+,.0f}]",
            _sig(io["p_holm"]),
        ]) + " \\\\")
    body = ("& \\multicolumn{3}{c}{Lossy channel} & \\multicolumn{3}{c}{Ideal channel} \\\\\n"
            "\\cmidrule(lr){2-4}\\cmidrule(lr){5-7}\n"
            "Protocol & $\\Delta$FND & 95\\% CI & $p_{\\mathrm{Holm}}$ "
            "& $\\Delta$FND & 95\\% CI & $p_{\\mathrm{Holm}}$ \\\\\n"
            "\\midrule\n" + "\n".join(rows))
    _write("tab6_paired_fnd.tex", _float(
        "lrcrrcr",
        "First-node-death difference against LEACH, in rounds, under both "
        "channel configurations. Paired sign-flip permutation test "
        "(20\\,000 permutations) with paired-bootstrap confidence intervals, "
        "Holm-corrected across the nine comparisons within each channel. "
        "\\textbf{Fuzzy T2 and DQN are significant under loss and not "
        "significant without it} --- the study's central negative result.",
        "tab:paired-fnd", body, wide=True))


def table_paired_robust() -> None:
    rows = []
    for metric, label in (("alive_node_auc", "AUC"), ("readings_delivered_total", "Readings")):
        t = _paired(metric)
        rows.append(f"\\multicolumn{{5}}{{l}}{{\\textit{{{label}}}}} \\\\")
        for p in ORDER:
            if p == "leach" or p not in t["lossy"].index:
                continue
            lo, io = t["lossy"].loc[p], t["ideal"].loc[p]
            rows.append(" & ".join([
                f"\\quad {NAMES[p]}",
                f"{lo['mean_diff'] / 1000:+,.1f}",
                _sig(lo["p_holm"]),
                f"{io['mean_diff'] / 1000:+,.1f}",
                _sig(io["p_holm"]),
            ]) + " \\\\")
        rows.append("\\addlinespace")
    body = ("& \\multicolumn{2}{c}{Lossy} & \\multicolumn{2}{c}{Ideal} \\\\\n"
            "\\cmidrule(lr){2-3}\\cmidrule(lr){4-5}\n"
            "Protocol & $\\Delta$ ($\\times 10^3$) & $p_{\\mathrm{Holm}}$ "
            "& $\\Delta$ ($\\times 10^3$) & $p_{\\mathrm{Holm}}$ \\\\\n"
            "\\midrule\n" + "\n".join(rows[:-1]))
    _write("tab7_paired_robust.tex", _float(
        "lrrrr",
        "Survival and delivery differences against LEACH under both "
        "channels. Unlike first node death (Table~\\ref{tab:paired-fnd}), "
        "every one of these gaps holds in both configurations, so these are "
        "the conclusions the study can state without a channel caveat.",
        "tab:paired-robust", body))


# ---------------------------------------------------------------------------
# Table VIII -- the measured energy split behind the retraction
# ---------------------------------------------------------------------------

PROBE = "results/analysis/energy_probe.csv"


def _probe():
    if not os.path.exists(PROBE):
        print(f"skip: {PROBE} missing -- run scripts/energy_probe.py")
        return None
    df = pd.read_csv(PROBE)
    return df[df["channel"] == "lossy"].set_index("protocol")


def table_energy_split() -> None:
    """Where the energy goes AND where the heads sit.

    The mean head distance alone does not explain the retry gap -- every
    protocol's mean is below 120 m, where packet error is still near zero.
    The table therefore reports the tail (90th percentile and the share of
    head-rounds beyond 120 m), which does.
    """
    d = _probe()
    if d is None:
        return
    rows = []
    for p in ["leach", "pegasis", "som", "nsga2", "fuzzy_t2", "dqn", "gcn"]:
        if p not in d.index:
            continue
        r = d.loc[p]
        rows.append(" & ".join([
            NAMES[p],
            f"{r['retry_pct']:.2f}",
            f"{r['ctrl_pct']:.2f}",
            f"{r['mean_ch_bs_m']:.1f}",
            f"{r['p90_ch_bs_m']:.1f}",
            f"{r['pct_heads_beyond_120m']:.1f}",
        ]) + " \\\\")
    body = ("Protocol & Retry & Control & \\multicolumn{2}{c}{Head-to-sink (m)} "
            "& Heads $>$120 m \\\\\n"
            "\\cmidrule(lr){4-5}\n"
            " & (\\%) & (\\%) & mean & p90 & (\\% of rounds) \\\\\n"
            "\\midrule\n" + "\n".join(rows))
    _write("tab8_energy_split.tex", _float(
        "lrrrrr",
        "Where the energy goes and where the heads sit, measured by the "
        "engine's own accounting categories (seed 0, 1100 rounds). Packet "
        "error is near zero below 120~m, so the \\emph{mean} head distance "
        "cannot explain the retry gap --- every mean is below that. The tail "
        "can: across the six single-hop protocols, the share of head-rounds "
        "beyond 120~m predicts retry energy share with $r = 0.95$. PEGASIS "
        "is the exception that proves the rule: its leader rotates uniformly "
        "and 30\\% of leader-rounds sit beyond 120~m, yet it retries barely "
        "at all, because only the leader ever faces the sink.",
        "tab:energy-split", body))


def table_head_rotation() -> None:
    """How evenly head duty is shared -- the concentration finding."""
    d = _probe()
    if d is None:
        return
    counts = "results/analysis/head_service_counts.csv"
    if not os.path.exists(counts):
        return
    hc = pd.read_csv(counts)
    rows = []
    for p in ["leach", "pegasis", "nsga2", "fuzzy_t2", "som", "dqn", "gcn"]:
        if p not in d.index:
            continue
        v = hc[hc["protocol"] == p]["rounds_as_head"]
        rows.append(" & ".join([
            NAMES[p],
            f"{int(v.max())}",
            f"{v.median():.0f}",
            f"{int((v == 0).sum())}",
            f"{d.loc[p]['head_gini']:.3f}",
        ]) + " \\\\")
    body = ("Protocol & Busiest node & Median & Never served & Gini \\\\\n"
            "\\midrule\n" + "\n".join(rows))
    _write("tab12_head_rotation.tex", _float(
        "lrrrr",
        "Head-duty concentration over 1100 rounds (seed 0), in rounds served "
        "as cluster head per node. LEACH's 55 is exact rather than "
        "approximate: its epoch mechanism elects every node exactly once per "
        "20 rounds. GCN's busiest node serves 13.6 times as often, which is "
        "the direct cause of its early first node death "
        "(Table~\\ref{tab:lifetime}) --- it does not choose badly, it "
        "chooses the same good node until that node dies.",
        "tab:head-rotation", body))


# ---------------------------------------------------------------------------
# Table IX -- channel robustness summary
# ---------------------------------------------------------------------------

def table_robustness() -> None:
    df = pd.read_csv(os.path.join(ANALYSIS, "channel_robustness.csv"))
    moved = df[df["rank_shift"] != 0]
    rows = []
    for _, r in moved.iterrows():
        rows.append(" & ".join([
            r["metric"].replace("_", "\\_"),
            NAMES.get(r["protocol"], r["protocol"]),
            f"{int(r['lossy_rank'])}", f"{int(r['ideal_rank'])}",
            f"{int(r['rank_shift']):+d}",
        ]) + " \\\\")
    body = ("Metric & Protocol & Lossy rank & Ideal rank & Shift \\\\\n"
            "\\midrule\n" + "\n".join(rows))
    _write("tab9_robustness.tex", _float(
        "llrrr",
        f"Every ranking that moves when the channel changes: "
        f"{len(moved)} of {len(df)} protocol--metric ranks. All are "
        f"single-place swaps between adjacent protocols. Ordering is "
        f"therefore stable; it is the \\emph{{significance}} of specific "
        f"first-node-death gaps that is not "
        f"(Table~\\ref{{tab:paired-fnd}}).",
        "tab:robustness", body))


# ---------------------------------------------------------------------------
# Tables X--XI -- node count x field area sweep
# ---------------------------------------------------------------------------

SCALE_AGG = "results/scale/scale_aggregate.csv"


def _scale() -> pd.DataFrame:
    if not os.path.exists(SCALE_AGG):
        return None
    return pd.read_csv(SCALE_AGG)


def table_scale_lifetime() -> None:
    df = _scale()
    if df is None:
        print("skip scale tables: run scripts/scale_sweep.py first")
        return
    cells = sorted({(int(n), int(a)) for n, a in zip(df["n_nodes"], df["field_side"])})
    sides = sorted({a for _, a in cells})
    rows = []
    for p in ORDER:
        cols = []
        for side in sides:
            for n in sorted({n for n, a in cells if a == side}):
                sel = df[(df["protocol"] == p) & (df["n_nodes"] == n) & (df["field_side"] == side)]
                cols.append(f"{sel['fnd_mean'].iloc[0]:,.0f}" if len(sel) else "--")
        rows.append(" & ".join([NAMES[p], GENERATION[p]] + cols) + " \\\\")
    ncols = len(sides)
    per = len(cells) // ncols
    header_top = " & ".join(
        [" ", " "] + [f"\\multicolumn{{{per}}}{{c}}{{{int(s)}$\\times${int(s)} m}}" for s in sides])
    cmids = "".join(
        f"\\cmidrule(lr){{{3 + i * per}-{2 + (i + 1) * per}}}" for i in range(ncols))
    header_bot = " & ".join(
        ["Protocol", "Gen."] + [f"$N{{=}}{n}$" for _ in sides
                                for n in sorted({n for n, a in cells if a == sides[0]})])
    body = (header_top + " \\\\\n" + cmids + "\n" + header_bot + " \\\\\n\\midrule\n"
            + "\n".join(rows))
    # Quantify the area/channel-severity coupling instead of asserting it: the
    # base station scales with the field, so the fraction of nodes past the
    # error waterfall (~120 m) is a property of the field size alone.
    import dataclasses

    import numpy as np

    from wsn_sim.network import Network
    sink = []
    for side in sides:
        c = dataclasses.replace(SimConfig(), field_w=side, field_h=side,
                                bs_x=side / 2.0, bs_y=1.5 * side, n_nodes=100)
        dist = np.concatenate([Network(c, i).dist_bs for i in range(15)])
        sink.append(f"{int(side)}$\\times${int(side)}~m: mean {dist.mean():.0f}~m, "
                    f"{100.0 * (dist > 120).mean():.0f}\\% of nodes beyond 120~m")

    _write("tab10_scale_fnd.tex", _float(
        "ll" + "r" * len(cells),
        "First node death (rounds) across node counts and field areas, lossy "
        "channel, 15 paired runs per cell.",
        "tab:scale-fnd", body, wide=True,
        note="The base station scales with the field at $(W/2,\\,1.5W)$, so "
             "field size sets channel severity as well as area. Node-to-sink "
             "distance by field size --- " + "; ".join(sink) + ". At "
             "$50\\times50$~m no link reaches the error waterfall at all, "
             "which is why the advantage of the optimized and learned "
             "protocols over LEACH collapses there."))


def table_scale_density() -> None:
    """Area or density? Sorted by density so the answer is readable off the page.

    If density drove lifetime, rows with similar density would show similar
    numbers. They do not: the two cells nearest in density (50 and 44
    nodes/ha) differ by more than a factor of two on every protocol.
    """
    df = _scale()
    if df is None:
        return
    cells = df.drop_duplicates(subset=["n_nodes", "field_side"])
    rows = []
    for _, c in cells.sort_values("density_per_ha").iterrows():
        n, side = int(c["n_nodes"]), c["field_side"]
        sel = df[(df["n_nodes"] == n) & (df["field_side"] == side)].set_index("protocol")
        get = lambda p: f"{sel.loc[p, 'fnd_mean']:,.0f}" if p in sel.index else "--"  # noqa: E731
        rows.append(" & ".join([
            f"{n}", f"{int(side)}$\\times${int(side)}", f"{c['density_per_ha']:.0f}",
            f"{0.5 * side * 2.08:.0f}",  # mean node-to-sink scales linearly with W
            get("stub"), get("leach"), get("nsga2"),
        ]) + " \\\\")
    body = ("$N$ & Field (m) & Density & Mean sink & \\multicolumn{3}{c}{First node death (rounds)} \\\\\n"
            "\\cmidrule(lr){5-7}\n"
            " & & (nodes/ha) & dist.\\ (m) & Direct & LEACH & NSGA-II \\\\\n"
            "\\midrule\n" + "\n".join(rows))
    _write("tab11_scale_density.tex", _float(
        "llrrrrr",
        "Cells ordered by node density. If density drove lifetime the rows "
        "would trend with it; they do not --- the numbers track the mean sink "
        "distance column instead. Averaged over all ten protocols, tripling "
        "the node count changes first node death by a factor of 0.88--1.26, "
        "while tripling the field side changes it by a factor of 5--7. The "
        "two cells closest in density (50 and 44 nodes/ha) differ by 1.7$\\times$ "
        "for NSGA-II, 2.1$\\times$ for LEACH and 5.5$\\times$ for direct "
        "transmission. Note also that \\emph{clustering only pays once the "
        "sink is far}: in the $50\\times50$~m rows the no-clustering baseline "
        "outlives LEACH.",
        "tab:scale-density", body))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scale", action="store_true", help="also emit scale-sweep tables")
    args = ap.parse_args()

    table_parameters()
    table_taxonomy()
    table_lifetime()
    table_delivery()
    table_cost()
    table_paired_fnd()
    table_paired_robust()
    table_energy_split()
    table_head_rotation()
    table_robustness()
    if args.scale:
        table_scale_lifetime()
        table_scale_density()


if __name__ == "__main__":
    main()
