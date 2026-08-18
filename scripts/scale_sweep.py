"""Node-count x field-area sweep: 3 node counts x 3 field sizes, lossy channel.

Design decisions (locked; see docs/AREA_AND_NODE_COMPARISON.md):
  * Base station scales WITH the field: BS = (W/2, 1.5*W). This keeps the
    deployment geometrically self-similar, and it means the sink hop scales
    with the field -- at 50x50 every link sits below d0, at 150x150 every
    link sits deep in the packet-error waterfall. That is a real confound
    between "bigger area" and "worse channel"; it is documented rather than
    engineered away, and mean CH->BS distance is reported per cell so a
    reader can separate the two.
  * density_radius scales with the field (25 m at 100x100, so 0.25*W). It is
    a SimConfig field read identically by every protocol, so scaling it is a
    shared environment choice, not per-protocol tuning. Held fixed it would
    cover 78% of a 50x50 field and 9% of a 150x150 one, silently changing
    what the feature means across the sweep.
  * DQN and GCN use their FROZEN N=100 / 100x100 weights everywhere. This
    measures out-of-distribution transfer, which is exactly the claim
    docs/TRADEOFFS.md declines to make. No retraining anywhere in this sweep.
  * Everything else (E0, packet sizes, radio constants, p_ch, max_rounds,
    thresholds) is unchanged from the headline study.

Run index i seeds the topology, shadowing and sensed stream identically for
every protocol within a cell, so comparisons inside a cell stay paired.
Comparisons ACROSS cells are not paired -- different N means a different
number of nodes to seed -- and must not be tested as if they were.

Usage:
    python scripts/scale_sweep.py --runs 15
    python scripts/scale_sweep.py --runs 15 --only 50x50   # one cell
"""

import argparse
import dataclasses
import os
import sys
import time

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from run_experiments import REGISTRY, run_suite  # noqa: E402
from wsn_sim.config import SimConfig  # noqa: E402

NODE_COUNTS = (50, 100, 150)
FIELD_SIDES = (50.0, 100.0, 150.0)

# Ordered so the cheapest cells finish first and a partial sweep is still useful.
CELLS = [(n, w) for w in FIELD_SIDES for n in NODE_COUNTS]


def cell_config(n_nodes: int, side: float) -> SimConfig:
    return dataclasses.replace(
        SimConfig(),
        n_nodes=n_nodes,
        field_w=side,
        field_h=side,
        bs_x=side / 2.0,
        bs_y=1.5 * side,
        density_radius=0.25 * side,
        per_enabled=True,
    )


def cell_dir(out_root: str, n_nodes: int, side: float) -> str:
    return os.path.join(out_root, f"n{n_nodes}_a{int(side)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=15)
    ap.add_argument("--out", default="results/scale")
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    ap.add_argument("--protocols", nargs="+", default=list(REGISTRY))
    ap.add_argument("--only", default=None, help="restrict to one field side, e.g. 50x50")
    ap.add_argument("--skip-existing", action="store_true",
                    help="skip a cell whose aggregate.csv already exists")
    args = ap.parse_args()

    # NSGA-II writes results/validation/nsga2_convergence.csv as a side effect
    # of its first reclustering on run 0. That artifact is meant to document the
    # HEADLINE configuration, so a sweep over other configurations must not
    # overwrite it. Set before any worker is spawned so children inherit it.
    os.environ["WSN_SUPPRESS_VALIDATION_WRITE"] = "1"

    cells = CELLS
    if args.only:
        side = float(args.only.split("x")[0])
        cells = [c for c in CELLS if c[1] == side]

    t_start = time.time()
    for n_nodes, side in cells:
        out = cell_dir(args.out, n_nodes, side)
        if args.skip_existing and os.path.exists(os.path.join(out, "aggregate.csv")):
            print(f"--- skip n={n_nodes} field={int(side)}x{int(side)} (already done)")
            continue
        cfg = cell_config(n_nodes, side)
        print(f"\n=== n={n_nodes}  field={int(side)}x{int(side)}  "
              f"BS=({cfg.bs_x:.0f},{cfg.bs_y:.0f})  density_radius={cfg.density_radius:.1f}m  "
              f"runs={args.runs}  jobs={args.jobs} ===", flush=True)
        t0 = time.time()
        agg = run_suite(args.protocols, args.runs, cfg, out, args.jobs)
        agg.insert(0, "field_side", side)
        agg.insert(0, "n_nodes", n_nodes)
        agg.to_csv(os.path.join(out, "aggregate.csv"), index=False)
        print(f"    done in {(time.time() - t0) / 60:.1f} min  "
              f"[total {(time.time() - t_start) / 60:.1f} min]", flush=True)

    combine(args.out)


def combine(out_root: str) -> None:
    """Stack every finished cell into one tidy table."""
    frames = []
    for n_nodes, side in CELLS:
        path = os.path.join(cell_dir(out_root, n_nodes, side), "aggregate.csv")
        if not os.path.exists(path):
            continue
        df = pd.read_csv(path)
        df["n_nodes"] = n_nodes
        df["field_side"] = side
        df["density_per_ha"] = n_nodes / (side * side) * 10000.0
        frames.append(df)
    if not frames:
        print("no cells finished yet")
        return
    combined = pd.concat(frames, ignore_index=True)
    dest = os.path.join(out_root, "scale_aggregate.csv")
    combined.to_csv(dest, index=False)
    print(f"\nwrote {dest}  ({len(frames)} cells, {len(combined)} rows)")


if __name__ == "__main__":
    main()
