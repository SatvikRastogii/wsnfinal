"""Run the benchmark: every protocol over paired topologies, writing CSVs.

Fairness note: run index `i` always uses seed `i` for the topology, shadowing and
sensed-value stream, so every protocol at index `i` sees a byte-identical world.
Protocol-internal randomness comes from a separate stream (see wsn_sim.engine).

Usage:
    python run_experiments.py --runs 30 --channel both
    python run_experiments.py --protocols leach pegasis --runs 5 --smoke
"""

import argparse
import dataclasses
import multiprocessing as mp
import os

import pandas as pd

from wsn_sim.config import SimConfig
from wsn_sim.engine import run_single
from wsn_sim.metrics import SUMMARY_COLUMNS, write_per_round_csv, write_summary_csv
from wsn_sim.protocols.apteen import APTEENProtocol
from wsn_sim.protocols.dqn import DQNProtocol
from wsn_sim.protocols.fuzzy_t2 import FuzzyT2Protocol
from wsn_sim.protocols.gcn import GCNProtocol
from wsn_sim.protocols.leach import LEACHProtocol
from wsn_sim.protocols.nsga2 import NSGA2Protocol
from wsn_sim.protocols.pegasis import PEGASISProtocol
from wsn_sim.protocols.som import SOMProtocol
from wsn_sim.protocols.stub import StubProtocol
from wsn_sim.protocols.teen import TEENProtocol

REGISTRY = {
    "leach": LEACHProtocol,
    "pegasis": PEGASISProtocol,
    "teen": TEENProtocol,
    "apteen": APTEENProtocol,
    "nsga2": NSGA2Protocol,
    "fuzzy_t2": FuzzyT2Protocol,
    "som": SOMProtocol,
    "dqn": DQNProtocol,
    "gcn": GCNProtocol,
    "stub": StubProtocol,
}

# Scalar summary fields that are wall-clock or allocator measurements. They are
# real data but not reproducible across runs, so determinism checks exclude them.
NONDETERMINISTIC_FIELDS = ("mean_setup_ms", "total_runtime_s", "peak_memory_kb")


def _one(args):
    proto_name, run_index, cfg, out_root = args
    # Only run 0 measures memory; tracemalloc's overhead would otherwise corrupt
    # the timing metrics (see run_single). Runs 1+ report honest wall-clock.
    records, summary = run_single(REGISTRY[proto_name], cfg, run_index, measure_memory=(run_index == 0))
    raw_dir = os.path.join(out_root, "raw", proto_name)
    os.makedirs(raw_dir, exist_ok=True)
    write_per_round_csv(records, os.path.join(raw_dir, f"run_{run_index:02d}.csv"))
    return summary


def run_suite(protocols, n_runs, cfg, out_root, jobs):
    os.makedirs(os.path.join(out_root, "summary"), exist_ok=True)
    tasks = [(p, i, cfg, out_root) for p in protocols for i in range(n_runs)]

    if jobs > 1:
        with mp.Pool(jobs) as pool:
            summaries = pool.map(_one, tasks)
    else:
        summaries = [_one(t) for t in tasks]

    by_protocol = {}
    for s in summaries:
        by_protocol.setdefault(s["protocol"], []).append(s)
    for name, rows in by_protocol.items():
        rows.sort(key=lambda r: r["run_id"])
        write_summary_csv(rows, os.path.join(out_root, "summary", f"{name}_summary.csv"))

    return aggregate(by_protocol, out_root)


def aggregate(by_protocol, out_root):
    """One row per protocol: mean and std of every scalar, plus n_censored_runs."""
    scalar_cols = [
        c for c in SUMMARY_COLUMNS if c not in ("run_id", "seed", "protocol", "lnd_censored")
    ]
    rows = []
    for name, recs in by_protocol.items():
        df = pd.DataFrame(recs)
        row = {"protocol": name, "n_censored_runs": int(df["lnd_censored"].sum())}
        for c in scalar_cols:
            vals = pd.to_numeric(df[c], errors="coerce")
            row[f"{c}_mean"] = vals.mean()
            row[f"{c}_std"] = vals.std(ddof=1) if len(vals) > 1 else 0.0
        rows.append(row)
    agg = pd.DataFrame(rows).sort_values("protocol")
    agg.to_csv(os.path.join(out_root, "aggregate.csv"), index=False)
    return agg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--protocols", nargs="+", default=list(REGISTRY))
    ap.add_argument("--runs", type=int, default=30)
    ap.add_argument("--rounds", type=int, default=None)
    ap.add_argument("--nodes", type=int, default=None)
    ap.add_argument("--channel", choices=["lossy", "ideal", "both"], default="lossy")
    ap.add_argument("--out", default="results")
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    ap.add_argument("--smoke", action="store_true", help="N=20, 200 rounds, 2 runs")
    args = ap.parse_args()

    base = {}
    if args.smoke:
        base.update(n_nodes=20, max_rounds=200)
        args.runs = 2
    if args.nodes is not None:
        base["n_nodes"] = args.nodes
    if args.rounds is not None:
        base["max_rounds"] = args.rounds

    channels = ["lossy", "ideal"] if args.channel == "both" else [args.channel]
    for ch in channels:
        cfg = dataclasses.replace(SimConfig(), per_enabled=(ch == "lossy"), **base)
        out_root = args.out if len(channels) == 1 else os.path.join(args.out, ch)
        print(f"\n=== channel={ch}  protocols={args.protocols}  runs={args.runs} "
              f"nodes={cfg.n_nodes} cap={cfg.max_rounds} jobs={args.jobs} ===")
        agg = run_suite(args.protocols, args.runs, cfg, out_root, args.jobs)
        cols = ["protocol", "fnd_mean", "hnd_mean", "lnd_mean", "n_censored_runs",
                "throughput_total_mean", "readings_delivered_total_mean", "pdr_percent_mean",
                "data_yield_mean", "mean_latency_ms_mean", "p95_latency_ms_mean",
                "mean_setup_ms_mean", "ops_per_round_mean", "total_control_packets_mean"]
        print(agg[[c for c in cols if c in agg.columns]].to_string(index=False))


if __name__ == "__main__":
    main()
