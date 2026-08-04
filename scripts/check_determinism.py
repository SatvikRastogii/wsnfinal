"""Determinism gate: the same (protocol, run_index) must reproduce byte-identically.

Runs every protocol twice at the same seeds and diffs the full per-round record set and
the summary, excluding only the wall-clock and allocator fields, which no implementation
could reproduce to the microsecond (see docs/ASSUMPTIONS.md item 14).

    python scripts/check_determinism.py --runs 3 --rounds 400
"""

import argparse
import dataclasses
import math
import sys

sys.path.insert(0, ".")

from run_experiments import NONDETERMINISTIC_FIELDS, REGISTRY
from wsn_sim.config import SimConfig
from wsn_sim.engine import run_single

EXCLUDE_ROUND = {"setup_time_ms"}
EXCLUDE_SUMMARY = set(NONDETERMINISTIC_FIELDS)


def _same(x, y):
    if isinstance(x, float) and isinstance(y, float):
        return x == y or (math.isnan(x) and math.isnan(y))
    return x == y


def diff_run(proto, cfg, run_index):
    """Return a list of human-readable mismatches for one (protocol, run_index)."""
    bad = []
    r1, s1 = run_single(REGISTRY[proto], cfg, run_index)
    r2, s2 = run_single(REGISTRY[proto], cfg, run_index)

    if len(r1) != len(r2):
        return [f"{proto} run {run_index}: round count {len(r1)} vs {len(r2)}"]
    for i, (a, b) in enumerate(zip(r1, r2)):
        for k in a:
            if k in EXCLUDE_ROUND:
                continue
            if not _same(a[k], b[k]):
                bad.append(f"{proto} run {run_index} round {i}: {k} {a[k]!r} vs {b[k]!r}")
                if len(bad) > 5:
                    return bad
    for k in s1:
        if k in EXCLUDE_SUMMARY:
            continue
        if not _same(s1[k], s2[k]):
            bad.append(f"{proto} run {run_index} summary: {k} {s1[k]!r} vs {s2[k]!r}")
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--protocols", nargs="+", default=[p for p in REGISTRY if p != "stub"])
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--rounds", type=int, default=400)
    ap.add_argument("--nodes", type=int, default=100)
    ap.add_argument("--channel", choices=["lossy", "ideal"], default="lossy")
    args = ap.parse_args()

    cfg = dataclasses.replace(SimConfig(), n_nodes=args.nodes, max_rounds=args.rounds,
                              per_enabled=(args.channel == "lossy"))
    failures = 0
    for proto in args.protocols:
        bad = []
        for i in range(args.runs):
            bad += diff_run(proto, cfg, i)
        if bad:
            failures += 1
            print(f"{proto:10s} FAIL")
            for line in bad[:6]:
                print("   ", line)
        else:
            print(f"{proto:10s} PASS  ({args.runs} runs x {args.rounds} rounds identical)")

    print(f"\ndeterminism: {len(args.protocols) - failures}/{len(args.protocols)} protocols "
          f"reproduce exactly (excluding {sorted(EXCLUDE_SUMMARY | EXCLUDE_ROUND)})")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
