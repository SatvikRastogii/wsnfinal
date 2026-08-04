"""Hard gates for the three learned/centralized protocols added after the
original nine-protocol build: SOM, DQN, GCN. Plain script (pytest not
installed) -- run via `python tests/test_learned_protocols.py`. Prints
PASS/FAIL per check and exits non-zero on any failure.

DQN and GCN require their frozen weight files (`models/dqn_weights.npz`,
`models/gcn_weights.npz`) to already exist -- run `scripts/train_dqn.py`
and `scripts/train_gcn.py` first. This file does NOT train anything itself
(training is a separate, one-off, offline step per the spec).

Small topology/round-count for SOM/DQN/GCN (n_nodes=30) purely to keep this
test's wall-clock time bounded, same rationale as test_protocols.py's
ga_cfg for NSGA-II/Fuzzy-T2 -- the properties checked (energy conservation,
FND<=HND<=LND, pdr range, determinism, frozen-eval invariance) are
scale-independent.
"""

import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from wsn_sim.config import SimConfig
from wsn_sim.engine import _derive_seed, _run_round, run_single
from wsn_sim.network import Network
from wsn_sim.protocols.dqn import DQNProtocol
from wsn_sim.protocols.gcn import GCNProtocol
from wsn_sim.protocols.som import SOMProtocol

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
    """Energy conservation, FND<=HND<=LND, pdr in [0,100], determinism --
    identical shape to test_protocols.py's run_hard_gates.
    """
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


def check_frozen_eval(proto_label, factory, cfg, run_index=0):
    """DQN/GCN-specific: weights must be BYTE-IDENTICAL before and after a
    full evaluation run (no training, no in-place mutation), and running
    the SAME frozen weights against the SAME topology twice must produce
    IDENTICAL cluster-head decisions every round (not just identical final
    summaries -- the full per-round ch_ids sequence).
    """
    protocol = factory()
    params_before = {k: v.copy() for k, v in protocol._params.items()}

    net = Network(cfg, run_index)
    proto_rng = np.random.default_rng(_derive_seed(run_index, protocol.name))
    channel_rng = np.random.default_rng(_derive_seed(run_index, protocol.name, "channel"))
    ch_sequence = []
    for round_idx in range(cfg.max_rounds):
        if not net.alive.any():
            break
        assignment = protocol.setup_round(net, round_idx, proto_rng)
        ch_sequence.append(tuple(sorted(assignment.ch_ids)))
        protocol.route(net, assignment, round_idx)  # not executed by engine, just exercised

    params_after = protocol._params
    unchanged = all(np.array_equal(params_before[k], params_after[k]) for k in params_before)
    check_true(f"[{proto_label}] frozen weights never mutated across a full evaluation run", unchanged)

    # Re-run from scratch with a fresh protocol instance (fresh weight load) -- must reproduce
    # the exact same CH sequence, proving decisions are a pure function of (frozen weights, state).
    protocol2 = factory()
    net2 = Network(cfg, run_index)
    proto_rng2 = np.random.default_rng(_derive_seed(run_index, protocol2.name))
    ch_sequence2 = []
    for round_idx in range(cfg.max_rounds):
        if not net2.alive.any():
            break
        assignment = protocol2.setup_round(net2, round_idx, proto_rng2)
        ch_sequence2.append(tuple(sorted(assignment.ch_ids)))

    check_true(
        f"[{proto_label}] identical frozen weights -> identical CH sequence across independent runs "
        f"({len(ch_sequence)} rounds)",
        ch_sequence == ch_sequence2,
    )


def main():
    som_cfg = SimConfig(n_nodes=30, max_rounds=300)
    learned_cfg = SimConfig(n_nodes=30, max_rounds=300)

    run_hard_gates("som", lambda: SOMProtocol(), som_cfg)

    try:
        dqn_summary = run_hard_gates("dqn", lambda: DQNProtocol(), learned_cfg)
        check_frozen_eval("dqn", lambda: DQNProtocol(), learned_cfg)
    except FileNotFoundError as e:
        print(f"SKIPPED dqn checks: {e}")

    try:
        gcn_summary = run_hard_gates("gcn", lambda: GCNProtocol(), learned_cfg)
        check_frozen_eval("gcn", lambda: GCNProtocol(), learned_cfg)
    except FileNotFoundError as e:
        print(f"SKIPPED gcn checks: {e}")

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S): {FAILURES}")
        sys.exit(1)
    print("ALL test_learned_protocols.py CHECKS PASSED")
    sys.exit(0)


if __name__ == "__main__":
    main()
