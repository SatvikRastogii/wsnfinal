"""Measure WHERE each protocol's energy goes, and where it puts its heads.

The headline tables say fuzzy T2 and DQN beat LEACH on first node death under
loss and not without it. This script measures the mechanism directly from the
engine's own accounting rather than inferring it from PDR:

  * `net.consumed` split by category -- retransmission energy is its own
    category, so the ARQ cost is not tangled up with ordinary transmit cost;
  * every cluster-head-to-sink distance, not just its mean. The mean alone is
    misleading: LEACH's mean head sits at ~102 m where the packet error rate
    is still near zero, so any retry-energy gap has to come from the upper
    tail of that distribution, and a mean cannot show a tail;
  * how many rounds each node spent as a head, which is what separates DQN's
    tight first-death distribution from GCN's bimodal one.

All protocols run on the SAME seed, so the comparison is paired.

Outputs (results/analysis/):
    energy_probe.csv          one row per protocol x channel
    ch_distance_samples.csv   every head-to-sink distance observed
    head_service_counts.csv   per node, rounds served as head

Usage:  python scripts/energy_probe.py [--rounds 1100] [--seed 0]
"""

import argparse
import dataclasses
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from run_experiments import REGISTRY  # noqa: E402
from wsn_sim import engine as eng  # noqa: E402
from wsn_sim.config import SimConfig  # noqa: E402

PROTOCOLS = ["leach", "pegasis", "nsga2", "fuzzy_t2", "som", "dqn", "gcn"]
OUT = "results/analysis"


def probe(proto: str, lossy: bool, rounds: int, seed: int):
    """Run one protocol on one seed, capturing the Network and head choices.

    The Network subclass is a capture hook, not a behaviour change: it only
    records a reference to the instance the engine builds, so energy
    accounting and RNG consumption are untouched.
    """
    cfg = dataclasses.replace(SimConfig(), max_rounds=rounds, per_enabled=lossy)
    grabbed = {}
    real_network = eng.Network

    class Spy(real_network):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            grabbed["net"] = self

    eng.Network = Spy
    try:
        factory = REGISTRY[proto]
        ch_distances = []
        service = np.zeros(cfg.n_nodes, dtype=int)

        class Wrapped(factory):
            def setup_round(self, net, r, rng):
                ca = super().setup_round(net, r, rng)
                for c in ca.ch_ids:
                    ch_distances.append(float(net.dist_bs[c]))
                    service[c] += 1
                return ca

        Wrapped.name = factory.name
        eng.run_single(Wrapped, cfg, seed)
    finally:
        eng.Network = real_network

    net = grabbed["net"]
    cons = dict(net.consumed)
    total = sum(cons.values())
    d = np.asarray(ch_distances, dtype=float)
    pct = lambda k: 100.0 * cons.get(k, 0.0) / total if total else 0.0  # noqa: E731

    summary = {
        "protocol": proto,
        "channel": "lossy" if lossy else "ideal",
        "total_J": total,
        "retry_J": cons.get("retry", 0.0),
        "retry_pct": pct("retry"),
        "ctrl_pct": pct("ctrl_tx") + pct("ctrl_rx"),
        "data_tx_pct": pct("data_tx"),
        "data_rx_pct": pct("data_rx"),
        "agg_pct": pct("agg"),
        "n_head_slots": int(d.size),
        "mean_ch_bs_m": float(d.mean()) if d.size else float("nan"),
        # The tail is the part that matters: PER is ~0 below 120 m and rises
        # steeply after, so the share of head slots beyond 120 m is the direct
        # predictor of retry energy.
        "p90_ch_bs_m": float(np.percentile(d, 90)) if d.size else float("nan"),
        "p99_ch_bs_m": float(np.percentile(d, 99)) if d.size else float("nan"),
        "pct_heads_beyond_120m": float(100.0 * (d > 120).mean()) if d.size else float("nan"),
        "pct_heads_beyond_d0": float(100.0 * (d > cfg.d0).mean()) if d.size else float("nan"),
        # Head-duty concentration: 1.0 would mean one node did every round.
        "head_gini": gini(service),
        "max_head_share": float(service.max() / service.sum()) if service.sum() else float("nan"),
    }
    return summary, d, service


def gini(counts: np.ndarray) -> float:
    """Gini coefficient of head-duty distribution across nodes."""
    x = np.sort(np.asarray(counts, dtype=float))
    n = x.size
    if n == 0 or x.sum() == 0:
        return float("nan")
    idx = np.arange(1, n + 1)
    return float((2.0 * (idx * x).sum()) / (n * x.sum()) - (n + 1.0) / n)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=1100,
                    help="just past LEACH's lossy FND, so every protocol is still alive")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--protocols", nargs="+", default=PROTOCOLS)
    args = ap.parse_args()

    rows, dist_rows, service_rows = [], [], []
    for p in args.protocols:
        for lossy in (True, False):
            s, d, service = probe(p, lossy, args.rounds, args.seed)
            rows.append(s)
            print(f"  {p:9s} {s['channel']:6s} retry={s['retry_pct']:5.2f}%  "
                  f"ctrl={s['ctrl_pct']:5.2f}%  mean_d={s['mean_ch_bs_m']:6.1f}m  "
                  f"p90={s['p90_ch_bs_m']:6.1f}m  >120m={s['pct_heads_beyond_120m']:5.1f}%  "
                  f"gini={s['head_gini']:.3f}", flush=True)
            if lossy:
                dist_rows.append(pd.DataFrame({"protocol": p, "ch_bs_m": d}))
                service_rows.append(pd.DataFrame({
                    "protocol": p, "node": np.arange(service.size), "rounds_as_head": service}))

    os.makedirs(OUT, exist_ok=True)
    pd.DataFrame(rows).to_csv(os.path.join(OUT, "energy_probe.csv"), index=False)
    pd.concat(dist_rows, ignore_index=True).to_csv(
        os.path.join(OUT, "ch_distance_samples.csv"), index=False)
    pd.concat(service_rows, ignore_index=True).to_csv(
        os.path.join(OUT, "head_service_counts.csv"), index=False)
    print(f"\nwrote energy_probe.csv, ch_distance_samples.csv, head_service_counts.csv "
          f"to {OUT}/  (seed={args.seed}, {args.rounds} rounds)")


if __name__ == "__main__":
    main()
