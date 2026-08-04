"""Engine hard gates. Plain script (pytest not installed) -- run via
`python tests/test_engine.py`. Prints PASS/FAIL per check and exits non-zero
on any failure.
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from wsn_sim import metrics
from wsn_sim.config import SimConfig, smoke_config
from wsn_sim.engine import _derive_seed, _run_round, _validate_no_double_forward, run_single
from wsn_sim.network import BS, Network
from wsn_sim.protocols.base import ClusterAssignment, Protocol, Transmission
from wsn_sim.protocols.stub import StubProtocol
from wsn_sim.radio import e_agg

FAILURES = []


def check_true(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"{status}: {name}")
    if not cond:
        FAILURES.append(name)


def check_raises(name, fn, exc_type):
    try:
        fn()
        ok = False
    except exc_type:
        ok = True
    except Exception as e:  # wrong exception type
        ok = False
        print(f"  (raised {type(e).__name__} instead of {exc_type.__name__}: {e})")
    status = "PASS" if ok else "FAIL"
    print(f"{status}: {name}")
    if not ok:
        FAILURES.append(name)


# ---------------------------------------------------------------------------
# 1-4, plus "no negative energy" checked every round (not just at the end):
# drive the real engine._run_round loop (the same function run_single calls)
# with full Network introspection between rounds.
# ---------------------------------------------------------------------------

def run_smoke_with_introspection(run_index=0):
    cfg = smoke_config()
    net = Network(cfg, run_index)
    protocol = StubProtocol()
    proto_rng = np.random.default_rng(_derive_seed(run_index, protocol.name))
    channel_rng = np.random.default_rng(_derive_seed(run_index, protocol.name, "channel"))
    all_latencies = []
    records = []
    prev_alive = cfg.n_nodes
    monotonic_ok = True
    no_negative_ok = True
    for round_idx in range(cfg.max_rounds):
        if not net.alive.any():
            break
        rec = _run_round(net, protocol, cfg, round_idx, proto_rng, channel_rng, all_latencies)
        records.append(rec)
        if net.energy.min() < 0.0:
            no_negative_ok = False
        if rec["alive_nodes"] > prev_alive:
            monotonic_ok = False
        prev_alive = rec["alive_nodes"]
    return cfg, net, records, monotonic_ok, no_negative_ok


def test_smoke_hard_gates():
    cfg, net, records, monotonic_ok, no_negative_ok = run_smoke_with_introspection(run_index=0)

    check_true(f"records produced ({len(records)} rounds executed)", len(records) > 0)

    # 1. Energy conservation: initial - final == total consumed, within 1e-9 J
    initial_total = float(net.initial_energy.sum())
    final_total = float(net.energy.sum())
    total_consumed = net.total_consumed()
    conservation_gap = abs(initial_total - final_total - total_consumed)
    check_true(
        f"(1) energy conservation: |initial-final-consumed| = {conservation_gap:.3e} J <= 1e-9 J",
        conservation_gap <= 1e-9,
    )

    # 2. No negative energy anywhere, ever (checked every round above)
    check_true("(2) no negative energy at any point in the run", no_negative_ok)
    check_true("(2b) no negative energy in final state", bool(net.energy.min() >= 0.0))

    # 4. alive_nodes monotonically non-increasing across rounds
    check_true("(4) alive_nodes monotonically non-increasing across rounds", monotonic_ok)

    # 5. FND <= HND <= LND (None/not-yet-occurred treated as occurring at the
    # censor round for ordering purposes, since "never happened by the cap"
    # is still consistent with FND <= HND <= LND)
    fnd, hnd, lnd, lnd_censored = metrics.compute_fnd_hnd_lnd(records, cfg.n_nodes)
    fnd_cmp = fnd if fnd is not None else lnd
    hnd_cmp = hnd if hnd is not None else lnd
    check_true(
        f"(5) FND <= HND <= LND (fnd={fnd}, hnd={hnd}, lnd={lnd}, censored={lnd_censored})",
        fnd_cmp <= hnd_cmp <= lnd,
    )

    # 6. pdr_percent in [0, 100] -- READING-based (see docs/ASSUMPTIONS.md /
    # Defect 1): readings_delivered_total / readings_attempted_total, not
    # packets_received_bs_total / packets_sent_total (the latter measures
    # aggregation depth, not delivery).
    readings_attempted_total = sum(r["readings_attempted"] for r in records)
    readings_delivered_total = sum(r["readings_delivered"] for r in records)
    packets_received_bs_total = sum(r["packets_received_bs"] for r in records)
    pdr_percent = (
        readings_delivered_total / readings_attempted_total * 100.0
        if readings_attempted_total > 0
        else 0.0
    )
    check_true(f"(6) pdr_percent in [0,100] (pdr_percent={pdr_percent:.4f})", 0.0 <= pdr_percent <= 100.0)

    # 3. Dead nodes never transmit or receive -- direct synthetic check
    # (the smoke run above cannot easily prove a NEGATIVE, so test it
    # directly against a manufactured pre-dead node instead).
    test_dead_nodes_never_transmit_or_receive()

    return cfg, records, fnd, hnd, lnd, lnd_censored, pdr_percent, packets_received_bs_total


def test_dead_nodes_never_transmit_or_receive():
    # Two isolated scenarios (isolated so a legitimate charge to a live node
    # in one scenario can never be mistaken for a charge to the dead node
    # under test in the other -- an earlier version of this test conflated
    # the two and produced a false failure).

    # Scenario A: the ONLY transmission this round originates from an
    # already-dead node. Nothing should be attempted or charged at all.
    class DeadSenderOnlyProtocol(Protocol):
        name = "dead_sender_only_probe"

        def setup_round(self, net, round_idx, rng):
            return ClusterAssignment(ch_ids=[], member_of={})

        def route(self, net, assignment, round_idx):
            return [Transmission(src=0, dst=BS, kind="data", hop_depth=1)]

    cfg_a = SimConfig(n_nodes=3, max_rounds=5, per_enabled=False, max_retx=0)
    net_a = Network(cfg_a, run_index=0)
    net_a.energy[0] = 0.0
    net_a.alive[0] = False  # node 0 already dead going into this round
    consumed_before_a = dict(net_a.consumed)
    rec_a = _run_round(
        net_a, DeadSenderOnlyProtocol(), cfg_a, 0,
        np.random.default_rng(0), np.random.default_rng(0), [],
    )
    check_true(
        "(3) an already-dead source is never counted as an attempted send",
        rec_a["packets_sent"] == 0,
    )
    check_true(
        "(3) an already-dead source is charged no energy at all this round",
        net_a.energy[0] == 0.0 and net_a.consumed == consumed_before_a,
    )

    # Scenario B: a LIVE node sends to an already-dead destination. The
    # send should still count as attempted (the source is alive and pays
    # its tx cost -- transmitting into a void is still a real radio cost),
    # but the dead destination must receive nothing, and the packet must
    # be lost (never reaches the BS / never delivered).
    class LiveSenderDeadDstProtocol(Protocol):
        name = "live_sender_dead_dst_probe"

        def setup_round(self, net, round_idx, rng):
            return ClusterAssignment(ch_ids=[], member_of={})

        def route(self, net, assignment, round_idx):
            return [Transmission(src=2, dst=1, kind="data", hop_depth=1)]

    cfg_b = SimConfig(n_nodes=3, max_rounds=5, per_enabled=False, max_retx=0)
    net_b = Network(cfg_b, run_index=0)
    net_b.energy[1] = 0.0
    net_b.alive[1] = False  # node 1 already dead going into this round
    rec_b = _run_round(
        net_b, LiveSenderDeadDstProtocol(), cfg_b, 0,
        np.random.default_rng(0), np.random.default_rng(0), [],
    )
    check_true(
        "(3) sending TO an already-dead node charges it no rx energy",
        net_b.energy[1] == 0.0,
    )
    check_true(
        "(3) a live sender to a dead destination is still an attempted send "
        "(it pays its own tx cost even though the packet is lost)",
        rec_b["packets_sent"] == 1,
    )
    check_true(
        "(3) the packet to a dead destination never reaches the BS "
        "(dst wasn't BS here, so packets_received_bs stays 0 regardless)",
        rec_b["packets_received_bs"] == 0,
    )
    check_true("(3) the live sender itself is not marked dead", bool(net_b.alive[2]))


# ---------------------------------------------------------------------------
# 7. Determinism: same (protocol, run_index) run twice -> byte-identical
#    per-round records.
# ---------------------------------------------------------------------------

_TIMING_FIELDS_PER_ROUND = {"setup_time_ms"}
_TIMING_FIELDS_SUMMARY = {"total_runtime_s", "peak_memory_kb", "mean_setup_ms"}


def _strip(d, keys):
    return {k: v for k, v in d.items() if k not in keys}


def test_determinism():
    # NOTE: setup_time_ms / total_runtime_s / peak_memory_kb / mean_setup_ms
    # are real wall-clock and allocator measurements of the run itself, not
    # simulated state -- they are inherently non-reproducible down to the
    # microsecond/byte, even given identical seeds, and are excluded from
    # this comparison for that reason (see docs/ASSUMPTIONS.md). Every field
    # that reflects actual simulated physics/protocol/channel outcomes
    # (energy, packets, deaths, latency, control traffic, ...) must still be
    # byte-identical, and is checked here.
    cfg = smoke_config()
    records_a, summary_a = run_single(lambda: StubProtocol(), cfg, run_index=0)
    records_b, summary_b = run_single(lambda: StubProtocol(), cfg, run_index=0)

    records_a_stripped = [_strip(r, _TIMING_FIELDS_PER_ROUND) for r in records_a]
    records_b_stripped = [_strip(r, _TIMING_FIELDS_PER_ROUND) for r in records_b]
    check_true(
        f"(7) determinism: identical (protocol, run_index) produces byte-identical "
        f"per-round records, excluding wall-clock timing fields ({len(records_a)} rounds)",
        records_a_stripped == records_b_stripped,
    )

    summary_a_stripped = _strip(summary_a, _TIMING_FIELDS_SUMMARY)
    summary_b_stripped = _strip(summary_b, _TIMING_FIELDS_SUMMARY)
    check_true(
        "(7b) determinism: summary records identical too, excluding wall-clock "
        "timing/memory fields",
        summary_a_stripped == summary_b_stripped,
    )


# ---------------------------------------------------------------------------
# 8. Sensed-value stream identical across two different protocol instances
#    on the same run_index -- proves protocols cannot perturb the shared
#    data process. Network never takes protocol identity as input, so two
#    independently constructed Network objects at the same run_index must
#    be identical regardless of how much/which protocol-side randomness is
#    burned in between.
# ---------------------------------------------------------------------------

def test_sensed_stream_shared_across_protocols():
    cfg = smoke_config()
    net_a = Network(cfg, run_index=5)
    # Simulate a protocol doing a lot of its own, unrelated random work.
    proto_rng_a = np.random.default_rng(_derive_seed(5, "protocol_A"))
    _ = proto_rng_a.random(10_000)

    net_b = Network(cfg, run_index=5)
    proto_rng_b = np.random.default_rng(_derive_seed(5, "a_completely_different_protocol_name"))
    _ = proto_rng_b.integers(0, 100, size=3)  # different amount/kind of draws

    check_true(
        "(8) sensed-value stream identical across two protocol instances (same run_index)",
        bool(np.array_equal(net_a.sensed, net_b.sensed)),
    )
    check_true(
        "(8b) topology (x,y) identical across two protocol instances (same run_index)",
        bool(np.array_equal(net_a.x, net_b.x)) and bool(np.array_equal(net_a.y, net_b.y)),
    )
    check_true(
        "(8c) shadowing identical across two protocol instances (same run_index)",
        bool(np.array_equal(net_a.shadow, net_b.shadow))
        and bool(np.array_equal(net_a.shadow_bs, net_b.shadow_bs)),
    )


# ---------------------------------------------------------------------------
# Bonus: engine-enforced aggregation must be tested directly (StubProtocol
# never creates CHs, so this can't be exercised via the smoke run).
# ---------------------------------------------------------------------------

class FakeAggProtocol(Protocol):
    """2 members (0,1) -> CH (2) -> BS, with hop_depth correctly labeled."""

    name = "fake_agg"

    def setup_round(self, net, round_idx, rng):
        return ClusterAssignment(ch_ids=[2], member_of={0: 2, 1: 2})

    def route(self, net, assignment, round_idx):
        return [
            Transmission(src=0, dst=2, kind="data", hop_depth=1, originates=True),
            Transmission(src=1, dst=2, kind="data", hop_depth=1, originates=True),
            # The CH itself does not originate a fresh reading here -- it
            # only relays its two members' readings -- so effective_readings
            # for this hop is engine-computed as 0 (own) + 2 (inbound) = 2.
            Transmission(src=2, dst=BS, kind="data", hop_depth=2, originates=False),
        ]


def test_aggregation_charge():
    cfg = SimConfig(n_nodes=5, max_rounds=5, per_enabled=False, max_retx=0)
    net = Network(cfg, run_index=0)
    protocol = FakeAggProtocol()
    proto_rng = np.random.default_rng(0)
    channel_rng = np.random.default_rng(0)
    all_latencies = []

    agg_before = net.consumed["agg"]
    rec = _run_round(net, protocol, cfg, 0, proto_rng, channel_rng, all_latencies)
    agg_after = net.consumed["agg"]

    expected_agg = e_agg(2 * cfg.data_bits, cfg)  # 2 successfully-received member packets
    actual_agg = agg_after - agg_before
    check_true(
        f"aggregation: CH charged e_agg on TOTAL received bits "
        f"(expected={expected_agg!r}, actual={actual_agg!r})",
        abs(actual_agg - expected_agg) < 1e-15,
    )
    check_true(
        "aggregation: exactly one packet reaches the BS this round",
        rec["packets_received_bs"] == 1,
    )
    check_true(
        "aggregation: BS packet carries both original readings (effective_readings=2)",
        rec["readings_delivered"] == 2,
    )
    check_true(
        "aggregation: packets_sent counts all 3 data sends (2 member + 1 CH forward)",
        rec["packets_sent"] == 3,
    )


def test_double_forward_raises():
    transmissions_bad = [
        Transmission(src=0, dst=2, kind="data", hop_depth=1),
        Transmission(src=2, dst=BS, kind="data", hop_depth=2),
        Transmission(src=2, dst=3, kind="data", hop_depth=2),  # 2nd outgoing from node 2
    ]
    check_raises(
        "engine raises ValueError when a receiving node emits >1 outgoing data packet",
        lambda: _validate_no_double_forward(transmissions_bad),
        ValueError,
    )


class MislabeledHopDepthProtocol(Protocol):
    """Deliberately mislabels hop_depth so the CH's forward sorts BEFORE its
    senders (src 3 and 4 > CH src 2), to trigger the causal-invariant check.
    """

    name = "mislabeled_hop_depth"

    def setup_round(self, net, round_idx, rng):
        return ClusterAssignment(ch_ids=[2], member_of={3: 2, 4: 2})

    def route(self, net, assignment, round_idx):
        return [
            Transmission(src=3, dst=2, kind="data", hop_depth=1),
            Transmission(src=4, dst=2, kind="data", hop_depth=1),
            # BUG: should be hop_depth=2 -- same depth as its own inputs
            # means (hop_depth, src) sorts this BEFORE src=3 and src=4.
            Transmission(src=2, dst=BS, kind="data", hop_depth=1),
        ]


def test_causal_invariant_raises_on_mislabeled_hop_depth():
    cfg = SimConfig(n_nodes=5, max_rounds=5, per_enabled=False, max_retx=0)
    net = Network(cfg, run_index=0)
    protocol = MislabeledHopDepthProtocol()
    proto_rng = np.random.default_rng(0)
    channel_rng = np.random.default_rng(0)
    all_latencies = []

    check_raises(
        "engine raises RuntimeError when hop_depth mislabeling breaks causal order",
        lambda: _run_round(net, protocol, cfg, 0, proto_rng, channel_rng, all_latencies),
        RuntimeError,
    )


# ---------------------------------------------------------------------------
# Defect 1 regression guard: reading-based pdr_percent must be 100.0 under a
# perfect channel (per_enabled=False) and no suppression, REGARDLESS of how
# deep the aggregation is. This is the exact scenario that exposed the bug:
# a packet-based ratio collapses toward 1/(aggregation fan-in) even though
# every single reading actually arrived. Checked three ways -- no
# aggregation (stub), heavy single-round aggregation (one cluster of 10),
# and a 3-deep relay chain (PEGASIS-like) -- so this fails loudly again if
# pdr_percent is ever made aggregation-sensitive in the future.
# ---------------------------------------------------------------------------

class SingleClusterAllOriginateProtocol(Protocol):
    """10 nodes, one cluster: members 1..9 -> CH 0 -> BS. Every node
    (including the CH) folds in its own fresh reading every round.
    """

    name = "single_cluster_probe"

    def setup_round(self, net, round_idx, rng):
        return ClusterAssignment(ch_ids=[0], member_of={i: 0 for i in range(1, 10)})

    def route(self, net, assignment, round_idx):
        transmissions = [
            Transmission(src=i, dst=0, kind="data", hop_depth=1, originates=True)
            for i in range(1, 10)
            if net.alive[i]
        ]
        if net.alive[0]:
            transmissions.append(
                Transmission(src=0, dst=BS, kind="data", hop_depth=2, originates=True)
            )
        return transmissions


class ThreeDeepChainProtocol(Protocol):
    """PEGASIS-like 3-hop chain: node 0 -> node 1 -> node 2 -> BS, with
    hop_depth strictly increasing 1 -> 2 -> 3 and every node folding in its
    own fresh reading in addition to whatever it relays.
    """

    name = "three_deep_chain_probe"

    def setup_round(self, net, round_idx, rng):
        return ClusterAssignment(ch_ids=[], member_of={})

    def route(self, net, assignment, round_idx):
        transmissions = []
        if net.alive[0]:
            transmissions.append(Transmission(src=0, dst=1, kind="data", hop_depth=1, originates=True))
        if net.alive[1]:
            transmissions.append(Transmission(src=1, dst=2, kind="data", hop_depth=2, originates=True))
        if net.alive[2]:
            transmissions.append(Transmission(src=2, dst=BS, kind="data", hop_depth=3, originates=True))
        return transmissions


def test_pdr_reading_based_perfect_channel_three_way():
    # (a) StubProtocol: no aggregation at all, every node direct-to-BS.
    cfg_stub = SimConfig(n_nodes=10, max_rounds=5, per_enabled=False, max_retx=0)
    _, summary_stub = run_single(lambda: StubProtocol(), cfg_stub, run_index=0)
    check_true(
        f"(D1-a) stub protocol, perfect channel, no aggregation: "
        f"pdr_percent == 100.0 exactly (got {summary_stub['pdr_percent']!r})",
        summary_stub["pdr_percent"] == 100.0,
    )

    # (b) Single cluster of 10 nodes: heavy same-round aggregation (9
    # members -> 1 CH -> 1 BS packet carrying all 10 readings). This is
    # exactly the scenario that demonstrated the bug: packets_received_bs /
    # packets_sent would report ~10%, while every reading actually arrived.
    cfg_cluster = SimConfig(n_nodes=10, max_rounds=5, per_enabled=False, max_retx=0)
    _, summary_cluster = run_single(lambda: SingleClusterAllOriginateProtocol(), cfg_cluster, run_index=0)
    check_true(
        f"(D1-b) single-cluster (10 nodes, heavy aggregation), perfect channel: "
        f"pdr_percent == 100.0 exactly (got {summary_cluster['pdr_percent']!r})",
        summary_cluster["pdr_percent"] == 100.0,
    )

    # (c) 3-deep chain (PEGASIS-like), hop_depth 1 -> 2 -> 3.
    cfg_chain = SimConfig(n_nodes=5, max_rounds=5, per_enabled=False, max_retx=0)
    _, summary_chain = run_single(lambda: ThreeDeepChainProtocol(), cfg_chain, run_index=0)
    check_true(
        f"(D1-c) 3-deep chain (PEGASIS-like), perfect channel: "
        f"pdr_percent == 100.0 exactly (got {summary_chain['pdr_percent']!r})",
        summary_chain["pdr_percent"] == 100.0,
    )


# ---------------------------------------------------------------------------
# Defect 3: StubProtocol does no computation, so ops_count/ops_per_round
# must report exactly 0.
# ---------------------------------------------------------------------------

def test_stub_ops_per_round_is_zero():
    cfg = smoke_config()
    records, summary = run_single(lambda: StubProtocol(), cfg, run_index=0)
    all_zero = all(r["ops_count"] == 0 for r in records)
    check_true(
        "(D3) StubProtocol: ops_count == 0 in every round (no computation done)",
        all_zero,
    )
    check_true(
        f"(D3) StubProtocol: ops_per_round == 0.0 (got {summary['ops_per_round']!r})",
        summary["ops_per_round"] == 0.0,
    )


def main():
    print("=== Hard gates 1,2,3,4,5,6 (smoke run + dead-node probe) ===")
    cfg, records, fnd, hnd, lnd, lnd_censored, pdr_percent, throughput_total = test_smoke_hard_gates()

    print()
    print("=== Hard gate 7: determinism ===")
    test_determinism()

    print()
    print("=== Hard gate 8: shared sensed-data stream across protocols ===")
    test_sensed_stream_shared_across_protocols()

    print()
    print("=== Bonus: engine-enforced aggregation ===")
    test_aggregation_charge()
    test_double_forward_raises()
    test_causal_invariant_raises_on_mislabeled_hop_depth()

    print()
    print("=== Defect 1 regression guard: reading-based PDR, three ways ===")
    test_pdr_reading_based_perfect_channel_three_way()

    print()
    print("=== Defect 3: StubProtocol ops_per_round == 0 ===")
    test_stub_ops_per_round_is_zero()

    print()
    print("=== StubProtocol smoke-run summary (run_index=0, smoke_config) ===")
    print(f"rounds executed : {len(records)}")
    print(f"FND             : {fnd}")
    print(f"HND             : {hnd}")
    print(f"LND             : {lnd}  (censored={lnd_censored})")
    print(f"throughput_total: {throughput_total}")
    print(f"pdr_percent     : {pdr_percent:.4f}")

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S): {FAILURES}")
        sys.exit(1)
    print("ALL test_engine.py CHECKS PASSED")
    sys.exit(0)


if __name__ == "__main__":
    main()
