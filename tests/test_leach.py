"""LEACH hard gates. Plain script (pytest not installed) -- run via
`python tests/test_leach.py`. Prints PASS/FAIL per check and exits non-zero
on any failure.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from wsn_sim.config import SimConfig
from wsn_sim.engine import run_single
from wsn_sim.protocols.leach import LEACHProtocol

FAILURES = []


def check_true(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"{status}: {name}")
    if not cond:
        FAILURES.append(name)


def main():
    cfg = SimConfig()  # default: n_nodes=100, max_rounds=7000, per_enabled=True

    records, summary = run_single(lambda: LEACHProtocol(), cfg, run_index=0)

    print(f"rounds executed: {len(records)}")

    # Energy conservation to 1e-9 J. Reconstruct net-level totals by
    # re-running with introspection (run_single doesn't return the Network
    # object), so do a dedicated introspected run instead.
    from wsn_sim.engine import _derive_seed, _run_round
    from wsn_sim.network import Network

    net = Network(cfg, run_index=0)
    protocol = LEACHProtocol()
    proto_rng = np.random.default_rng(_derive_seed(0, protocol.name))
    channel_rng = np.random.default_rng(_derive_seed(0, protocol.name, "channel"))
    all_latencies = []
    introspected_records = []
    num_ch_series = []
    for round_idx in range(cfg.max_rounds):
        if not net.alive.any():
            break
        rec = _run_round(net, protocol, cfg, round_idx, proto_rng, channel_rng, all_latencies)
        introspected_records.append(rec)
        num_ch_series.append(rec["num_ch"])

    initial_total = float(net.initial_energy.sum())
    final_total = float(net.energy.sum())
    total_consumed = net.total_consumed()
    conservation_gap = abs(initial_total - final_total - total_consumed)
    check_true(
        f"energy conservation: |initial-final-consumed| = {conservation_gap:.3e} J <= 1e-9 J",
        conservation_gap <= 1e-9,
    )

    # FND <= HND <= LND, all three actually reached (not None) on a
    # full-length default run.
    fnd = summary["fnd"]
    hnd = summary["hnd"]
    lnd = summary["lnd"]
    check_true(f"FND reached (not None): fnd={fnd}", fnd is not None)
    check_true(f"HND reached (not None): hnd={hnd}", hnd is not None)
    check_true(f"LND reached (not None, uncensored): lnd={lnd}, censored={summary['lnd_censored']}",
               lnd is not None and not summary["lnd_censored"])
    if fnd is not None and hnd is not None and lnd is not None:
        check_true(f"FND <= HND <= LND (fnd={fnd}, hnd={hnd}, lnd={lnd})", fnd <= hnd <= lnd)

    # pdr_percent in [0, 100]
    pdr = summary["pdr_percent"]
    check_true(f"pdr_percent in [0,100] (got {pdr!r})", 0.0 <= pdr <= 100.0)

    # Mean realized CH count over the run in a loose plausible band around
    # p*N = 0.05*100 = 5. NOT a target to tune toward -- a deliberately
    # loose sanity check (2.0 <= mean <= 9.0).
    mean_num_ch = float(np.mean(num_ch_series))
    check_true(
        f"mean realized CH count in plausible band [2.0, 9.0] around p*N=5.0 "
        f"(got {mean_num_ch:.4f})",
        2.0 <= mean_num_ch <= 9.0,
    )

    # CH count varies across rounds -- proves the election is stochastic,
    # not a fixed/clamped count.
    check_true(
        f"CH count varies across rounds, not constant "
        f"(min={min(num_ch_series)}, max={max(num_ch_series)}, "
        f"distinct values={len(set(num_ch_series))})",
        len(set(num_ch_series)) > 1,
    )

    # Determinism: same (protocol, run_index) twice gives identical
    # simulated fields (excluding wall-clock timing fields, same exclusion
    # rule as test_engine.py's determinism gate).
    TIMING_PER_ROUND = {"setup_time_ms"}
    TIMING_SUMMARY = {"total_runtime_s", "peak_memory_kb", "mean_setup_ms"}

    def strip(d, keys):
        return {k: v for k, v in d.items() if k not in keys}

    records_a, summary_a = run_single(lambda: LEACHProtocol(), cfg, run_index=1)
    records_b, summary_b = run_single(lambda: LEACHProtocol(), cfg, run_index=1)
    records_a_s = [strip(r, TIMING_PER_ROUND) for r in records_a]
    records_b_s = [strip(r, TIMING_PER_ROUND) for r in records_b]
    check_true(
        f"determinism: identical (protocol, run_index) produces byte-identical "
        f"per-round records ({len(records_a)} rounds)",
        records_a_s == records_b_s,
    )
    check_true(
        "determinism: summary records identical too (excluding wall-clock timing/memory)",
        strip(summary_a, TIMING_SUMMARY) == strip(summary_b, TIMING_SUMMARY),
    )

    print()
    print("=== LEACH default-config summary (run_index=0) ===")
    print(f"FND={fnd} HND={hnd} LND={lnd} (censored={summary['lnd_censored']})")
    print(f"pdr_percent={pdr:.4f}")
    print(f"mean_num_ch={mean_num_ch:.4f} (min={min(num_ch_series)}, max={max(num_ch_series)})")

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S): {FAILURES}")
        sys.exit(1)
    print("ALL test_leach.py CHECKS PASSED")
    sys.exit(0)


if __name__ == "__main__":
    main()
