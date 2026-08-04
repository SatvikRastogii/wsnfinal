"""Hard gates for the five new protocols (PEGASIS, TEEN, APTEEN, NSGA-II,
Fuzzy-T2), plus the cross-protocol comparisons the spec calls out
explicitly. Plain script (pytest not installed) -- run via
`python tests/test_protocols.py`. Prints PASS/FAIL per check and exits
non-zero on any failure.

GA-based protocols (NSGA-II, Fuzzy-T2) use a SMALLER topology/round-count
than the LEACH-family checks below, purely to keep this test's wall-clock
time bounded -- NSGA-II's pop=40/generations=30 GA (the spec's own
defaults, left untouched) is genuinely expensive per reclustering event.
This is a test-harness speed choice, not a protocol-tuning one: the
properties checked (energy conservation, FND<=HND<=LND, pdr range,
determinism) are scale-independent.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from wsn_sim.config import SimConfig
from wsn_sim.engine import _derive_seed, _run_round, run_single
from wsn_sim.network import Network
from wsn_sim.protocols.apteen import APTEENProtocol
from wsn_sim.protocols.fuzzy_t2 import FuzzyT2Protocol
from wsn_sim.protocols.leach import LEACHProtocol
from wsn_sim.protocols.nsga2 import NSGA2Protocol
from wsn_sim.protocols.pegasis import PEGASISProtocol
from wsn_sim.protocols.teen import TEENProtocol

FAILURES = []


def check_true(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"{status}: {name}")
    if not cond:
        FAILURES.append(name)


TIMING_PER_ROUND = {"setup_time_ms"}
TIMING_SUMMARY = {"total_runtime_s", "peak_memory_kb", "mean_setup_ms"}


def _strip(d, keys):
    return {k: v for k, v in d.items() if k not in keys}


def run_hard_gates(proto_label, factory, cfg, run_index=0):
    """Energy conservation, FND<=HND<=LND, pdr in [0,100], determinism."""
    print(f"--- {proto_label} (n_nodes={cfg.n_nodes}, max_rounds={cfg.max_rounds}) ---")

    net = Network(cfg, run_index)
    protocol = factory()
    proto_rng = np.random.default_rng(_derive_seed(run_index, protocol.name))
    channel_rng = np.random.default_rng(_derive_seed(run_index, protocol.name, "channel"))
    all_latencies = []
    records = []
    for round_idx in range(cfg.max_rounds):
        if not net.alive.any():
            break
        rec = _run_round(net, protocol, cfg, round_idx, proto_rng, channel_rng, all_latencies)
        records.append(rec)

    initial_total = float(net.initial_energy.sum())
    final_total = float(net.energy.sum())
    total_consumed = net.total_consumed()
    gap = abs(initial_total - final_total - total_consumed)
    check_true(f"[{proto_label}] energy conservation |initial-final-consumed|={gap:.3e} <= 1e-9 J", gap <= 1e-9)

    _, summary = run_single(factory, cfg, run_index=run_index)
    fnd, hnd, lnd = summary["fnd"], summary["hnd"], summary["lnd"]
    fnd_cmp = fnd if fnd is not None else lnd
    hnd_cmp = hnd if hnd is not None else lnd
    check_true(
        f"[{proto_label}] FND<=HND<=LND (fnd={fnd}, hnd={hnd}, lnd={lnd}, censored={summary['lnd_censored']})",
        fnd_cmp <= hnd_cmp <= lnd,
    )

    pdr = summary["pdr_percent"]
    check_true(f"[{proto_label}] pdr_percent in [0,100] (got {pdr!r})", 0.0 <= pdr <= 100.0)

    records_a, summary_a = run_single(factory, cfg, run_index=run_index)
    records_b, summary_b = run_single(factory, cfg, run_index=run_index)
    records_a_s = [_strip(r, TIMING_PER_ROUND) for r in records_a]
    records_b_s = [_strip(r, TIMING_PER_ROUND) for r in records_b]
    check_true(
        f"[{proto_label}] determinism: identical run_index -> byte-identical per-round records "
        f"({len(records_a)} rounds)",
        records_a_s == records_b_s,
    )
    check_true(
        f"[{proto_label}] determinism: summary records identical (excluding wall-clock timing)",
        _strip(summary_a, TIMING_SUMMARY) == _strip(summary_b, TIMING_SUMMARY),
    )

    return summary


def main():
    # max_rounds capped well below the 7000-round default cap purely to
    # bound THIS TEST FILE's wall-clock time (TEEN/APTEEN's reactive
    # suppression means they routinely run to the round cap uncensored at
    # n_nodes=100 -- a real, correct property of reactive protocols, see
    # protocols/teen.py, not something being tuned around here). The
    # correctness properties checked (energy conservation, FND<=HND<=LND
    # ordering, pdr range, determinism) do not depend on reaching the cap.
    default_cfg = SimConfig(max_rounds=2000)  # n_nodes=100, per_enabled=True
    ga_cfg = SimConfig(n_nodes=30, max_rounds=300)  # smaller still: GA cost, see module docstring

    run_hard_gates("pegasis", lambda: PEGASISProtocol(), default_cfg)
    run_hard_gates("teen", lambda: TEENProtocol(), default_cfg)
    run_hard_gates("apteen", lambda: APTEENProtocol(), default_cfg)
    run_hard_gates("nsga2", lambda: NSGA2Protocol(), ga_cfg)
    run_hard_gates("fuzzy_t2", lambda: FuzzyT2Protocol(), ga_cfg)

    print()
    print("=== Cross-protocol packet-volume ordering (same run_index/sensed stream) ===")
    cmp_cfg = default_cfg  # identical topology/sensed stream across protocols at this run_index

    # Use packets_sent (data sends attempted), not just BS-delivered throughput,
    # since that is the metric the spec's "sends fewer data packets" refers to.
    # Each protocol run ONCE at cmp_cfg/run_index=0 and reused below for both
    # the packet-volume ordering check and the PEGASIS-vs-LEACH latency check.
    leach_records, leach_summary = run_single(lambda: LEACHProtocol(), cmp_cfg, run_index=0)
    teen_records, _ = run_single(lambda: TEENProtocol(), cmp_cfg, run_index=0)
    apteen_records, _ = run_single(lambda: APTEENProtocol(), cmp_cfg, run_index=0)
    _, pegasis_summary = run_single(lambda: PEGASISProtocol(), cmp_cfg, run_index=0)

    leach_sent = sum(r["packets_sent"] for r in leach_records)
    teen_sent = sum(r["packets_sent"] for r in teen_records)
    apteen_sent = sum(r["packets_sent"] for r in apteen_records)

    check_true(
        f"TEEN sends strictly fewer data packets than LEACH (teen={teen_sent}, leach={leach_sent})",
        teen_sent < leach_sent,
    )
    check_true(
        f"APTEEN sends strictly more than TEEN and strictly fewer than LEACH "
        f"(teen={teen_sent}, apteen={apteen_sent}, leach={leach_sent})",
        teen_sent < apteen_sent < leach_sent,
    )

    print()
    print("=== PEGASIS latency vs LEACH (chain depth trades energy for latency) ===")
    check_true(
        f"PEGASIS mean_latency_ms strictly higher than LEACH's "
        f"(pegasis={pegasis_summary['mean_latency_ms']:.4f}, "
        f"leach={leach_summary['mean_latency_ms']:.4f})",
        pegasis_summary["mean_latency_ms"] > leach_summary["mean_latency_ms"],
    )

    print()
    print("=== NSGA-II GA convergence logging mechanics (small-scale smoke) ===")
    # Small n_nodes/round-count purely to keep THIS TEST fast -- the window
    # (conv_round_min/max) and divergence threshold are shrunk to match, so
    # the *mechanism* (skip round 0, wait for real energy divergence, log
    # both knee-point and best-per-objective) is exercised without paying
    # for a ~1000-round GA run at n_nodes=100. The real, information-bearing
    # log at production scale is generated separately by
    # scripts/generate_nsga2_convergence.py (see docs/ASSUMPTIONS.md /
    # the Part 1 report for the actual convergence verdict).
    conv_cfg = SimConfig(n_nodes=30, max_rounds=60, ga_interval=5)
    proto = NSGA2Protocol(conv_round_min=20, conv_round_max=40, conv_energy_std_threshold=1e-5)
    run_single(lambda: proto, conv_cfg, run_index=0)
    log = proto.convergence_log
    check_true("NSGA-II convergence log has one row per generation (30)", len(log) == conv_cfg.generations)
    check_true(
        "NSGA-II convergence logging fired after round 0 (energy had diverged)",
        proto._convergence_round is not None and proto._convergence_round > 0,
    )
    if len(log) == conv_cfg.generations:
        expected_keys = {"generation", "knee_f1", "knee_f2", "knee_f3", "best_f1", "best_f2", "best_f3"}
        check_true(
            f"NSGA-II convergence row has knee_* and best_* columns (got {sorted(log[0].keys())})",
            expected_keys.issubset(log[0].keys()),
        )
        best_f1_gen0 = log[0]["best_f1"]
        best_f1_last = log[-1]["best_f1"]
        check_true(
            f"NSGA-II best-in-population f1 (round energy) is non-increasing gen0->gen"
            f"{conv_cfg.generations - 1} (elitist survival guarantees this) "
            f"(gen0={best_f1_gen0:.6f}, last={best_f1_last:.6f})",
            best_f1_last <= best_f1_gen0,
        )

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S): {FAILURES}")
        sys.exit(1)
    print("ALL test_protocols.py CHECKS PASSED")
    sys.exit(0)


if __name__ == "__main__":
    main()
