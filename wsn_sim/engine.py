"""The round loop. This is the only place energy is spent, packets are
sized, aggregation is charged, and channel outcomes are drawn.

FAIRNESS-CRITICAL SEEDING
-------------------------
Three independent numpy Generator streams exist per (run_index, protocol):

  1. Topology stream -- np.random.default_rng(run_index), consumed entirely
     inside Network.__init__ (positions, initial energy, shadowing, sensed
     data). Depends on run_index ONLY, never on the protocol. Every protocol
     benchmarked at the same run_index sees a byte-identical world.
  2. Protocol stream -- seeded from blake2b(run_index, protocol_name), this
     protocol's own private randomness (e.g. random CH election). Different
     protocols get different, independent streams even at the same
     run_index; a protocol cannot see or influence another protocol's
     stream.
  3. Channel stream -- seeded from blake2b(run_index, protocol_name,
     "channel"), used ONLY for per-packet ARQ success draws. This is
     DELIBERATELY protocol-specific (unlike the topology stream): different
     protocols make different numbers of channel draws per round (more
     hops, more retries, different traffic volume), so a shared draw
     sequence would desync after round 1 regardless of what we seeded it
     with -- there is no "fair shared channel realization" to preserve here,
     only a fair *channel model* (the same PER formula, and the same
     per-link shadowing, which IS shared -- see Network.shadow). Keeping
     "channel outcome noise" and "static per-link shadowing" conceptually
     separate matters: shadowing is fairness-critical shared state, ARQ
     dice-rolls are legitimately per-protocol.
"""

import hashlib
import time
import tracemalloc

import numpy as np

from . import metrics
from .config import SimConfig
from .network import BS, Network
from .protocols.base import ClusterAssignment, Transmission
from .radio import e_agg


def _derive_seed(*parts) -> int:
    """Deterministic, process-stable seed derivation (NOT Python's hash())."""
    s = "|".join(str(p) for p in parts)
    digest = hashlib.blake2b(s.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big")


def _validate_no_double_forward(transmissions: list) -> None:
    """Structural pre-flight check: a node that receives data this round may
    emit at most one outgoing data packet. This is a protocol-authoring bug
    check, independent of channel luck -- it runs on the route()-returned
    list itself, before any energy/channel randomness is touched.
    """
    receivers = {t.dst for t in transmissions if t.kind == "data" and t.dst != BS}
    src_counts = {}
    for t in transmissions:
        if t.kind == "data":
            src_counts[t.src] = src_counts.get(t.src, 0) + 1
    for node in receivers:
        count = src_counts.get(node, 0)
        if count > 1:
            raise ValueError(
                f"protocol emitted {count} outgoing data packets from node "
                f"{node}, which also receives data this round -- a "
                f"receiving/forwarding node may emit at most one outgoing "
                f"data packet per round (engine-enforced aggregation rule)"
            )


def _charge_control_traffic(net: Network, cfg: SimConfig, protocol, assignment: ClusterAssignment) -> int:
    """Dispatch control-traffic accounting by `protocol.control_model`. The
    ENGINE still owns every joule/bit/audience decision in all three models
    -- a protocol only declares which model applies and supplies the
    structural facts (chain order, rebuild/recluster flags) the chosen
    model needs. See docs/ASSUMPTIONS.md for why a uniform LEACH-shaped
    charge is wrong for chain-based and centralized protocols.
    """
    model = protocol.control_model
    if model == "distributed":
        return _charge_control_distributed(net, cfg, assignment, protocol.extra_ch_broadcasts)
    if model == "chain":
        return _charge_control_chain(net, cfg, protocol)
    if model == "centralized":
        return _charge_control_centralized(net, cfg, protocol, assignment)
    raise ValueError(f"unknown control_model {model!r} on protocol {protocol.name!r}")


def _charge_control_distributed(
    net: Network, cfg: SimConfig, assignment: ClusterAssignment, extra_ch_broadcasts: int
) -> int:
    """Uniform LEACH-style control-traffic accounting, charged by the engine
    (never by the protocol). Returns the number of control packets sent.

    Sequence per cluster head: ADV broadcast -> JOIN-REQ per member ->
    TDMA SCHEDULE broadcast -> `extra_ch_broadcasts` extra broadcasts (TEEN/
    APTEEN's HT/ST/TC threshold announcement), each priced identically to
    the SCHEDULE step (farthest-member distance, members-only audience). See
    docs/ASSUMPTIONS.md for the ADV/SCHEDULE audience asymmetry and the
    zero-member-CH special case.
    """
    control_packets = 0
    members_by_ch = {}
    for m, c in assignment.member_of.items():
        members_by_ch.setdefault(c, []).append(m)
    ch_id_set = set(assignment.ch_ids)

    for ch in assignment.ch_ids:
        if not net.alive[ch]:
            continue
        members = members_by_ch.get(ch, [])

        if not members:
            # Zero-member CH: it broadcasts ADV before it can possibly know
            # whether anyone will join, so there is no real farthest-member
            # distance to price against -- charged at electronics-only cost
            # (d=0). It then skips the SCHEDULE broadcast entirely, because
            # by schedule time it already knows it has nobody to schedule.
            # e_tx_ctrl_zero is a precomputed constant, not indexable by
            # node pair (there is no "other node" at d=0) -- see
            # Network.__init__ and docs/ASSUMPTIONS.md.
            net.spend(ch, net.e_tx_ctrl_zero, "ctrl_tx")
            control_packets += 1
            for node in range(cfg.n_nodes):
                if node == ch or node in ch_id_set:
                    continue
                if net.alive[node]:
                    net.spend(node, net.e_rx_ctrl, "ctrl_rx")
            continue

        # farthest member, by index -- e_tx_ctrl[ch, farthest_idx] is
        # exactly e_tx(ctrl_bits, farthest_d, cfg) since farthest_idx is the
        # argmax of dist[ch, m] over members (this dynamic-distance case
        # still resolves through the precomputed table, since it's a real
        # node-to-node distance -- see docs/ASSUMPTIONS.md).
        farthest_idx = max(members, key=lambda m: net.dist[ch, m])

        # ADV: heard by every alive non-CH node (not just this CH's
        # eventual members), because a node must compare every CH's
        # advertisement to pick the nearest one BEFORE it can decide who to
        # join. This is intentionally a wider audience than SCHEDULE below.
        net.spend(ch, net.e_tx_ctrl[ch, farthest_idx], "ctrl_tx")
        control_packets += 1
        for node in range(cfg.n_nodes):
            if node == ch or node in ch_id_set:
                continue
            if net.alive[node]:
                net.spend(node, net.e_rx_ctrl, "ctrl_rx")

        # JOIN-REQ: each member announces itself to its own CH only.
        for m in members:
            if net.alive[m] and net.alive[ch]:
                net.spend(m, net.e_tx_ctrl[m, ch], "ctrl_tx")
                net.spend(ch, net.e_rx_ctrl, "ctrl_rx")
                control_packets += 1

        # TDMA SCHEDULE: heard only by actual members -- a node only needs
        # its OWN CH's slot assignment, other clusters' schedules are
        # irrelevant to it. This narrower audience (vs. ADV's wider one) is
        # intentional, not an oversight: do not "fix" it into symmetry.
        if net.alive[ch]:
            net.spend(ch, net.e_tx_ctrl[ch, farthest_idx], "ctrl_tx")
            control_packets += 1
            for m in members:
                if net.alive[m]:
                    net.spend(m, net.e_rx_ctrl, "ctrl_rx")

            # TEEN/APTEEN extra threshold broadcast(s): same pricing shape
            # as SCHEDULE (farthest-member distance, members-only audience),
            # repeated `extra_ch_broadcasts` times. 0 for LEACH (no-op).
            for _ in range(extra_ch_broadcasts):
                if not net.alive[ch]:
                    break
                net.spend(ch, net.e_tx_ctrl[ch, farthest_idx], "ctrl_tx")
                control_packets += 1
                for m in members:
                    if net.alive[m]:
                        net.spend(m, net.e_rx_ctrl, "ctrl_rx")

    return control_packets


def _charge_control_chain(net: Network, cfg: SimConfig, protocol) -> int:
    """PEGASIS-style chain control traffic: no ADV/JOIN/SCHEDULE at all.

    - Leader token passed hop-by-hop along `protocol.chain` (head to tail):
      for each of the (len(chain) - 1) consecutive links, the sender pays
      E_tx(ctrl, d_hop) and the receiver pays E_rx(ctrl). Each hop is priced
      independently (a mid-chain death just breaks that hop's charge, like
      every other control-traffic path in this engine).
    - On rounds where the chain is REBUILT, the BS broadcasts the new chain/
      leader order once; every alive node pays E_rx(ctrl) to hear it, and
      the BS (mains-powered) pays nothing. Priced as ONE control packet,
      mirroring how the distributed model counts one ADV broadcast per CH
      regardless of receiver count.
    """
    control_packets = 0
    chain = protocol.chain
    for i in range(len(chain) - 1):
        a, b = int(chain[i]), int(chain[i + 1])
        if net.alive[a]:
            net.spend(a, net.e_tx_ctrl[a, b], "ctrl_tx")
            control_packets += 1
            if net.alive[b]:
                net.spend(b, net.e_rx_ctrl, "ctrl_rx")

    if protocol.chain_rebuilt_this_round:
        for node in range(cfg.n_nodes):
            if net.alive[node]:
                net.spend(node, net.e_rx_ctrl, "ctrl_rx")
        control_packets += 1

    return control_packets


def _charge_control_centralized(net: Network, cfg: SimConfig, protocol, assignment: ClusterAssignment) -> int:
    """Centralized (BS-computed) control traffic: no ADV, no JOIN-REQ (the
    BS already told every node who its CH is).

    - Uplink node-state reports are piggybacked on data traffic already
      being sent -- charged NOTHING here (see docs/ASSUMPTIONS.md for the
      cost argument against a separate status-report packet).
    - On `protocol.reclustered_this_round` rounds only: the BS broadcasts
      the new assignment once; every alive node pays E_rx(ctrl), the BS
      pays nothing. Priced as ONE control packet, same convention as the
      chain-rebuild broadcast above.
    - EVERY round: each CH still broadcasts its own TDMA schedule (E_tx at
      farthest-member distance), each member pays E_rx(ctrl) -- identical
      pricing to the distributed model's SCHEDULE step, including the
      zero-member-CH skip.
    """
    control_packets = 0

    if protocol.reclustered_this_round:
        for node in range(cfg.n_nodes):
            if net.alive[node]:
                net.spend(node, net.e_rx_ctrl, "ctrl_rx")
        control_packets += 1

    members_by_ch = {}
    for m, c in assignment.member_of.items():
        members_by_ch.setdefault(c, []).append(m)

    for ch in assignment.ch_ids:
        if not net.alive[ch]:
            continue
        members = members_by_ch.get(ch, [])
        if not members:
            continue  # nothing to schedule, mirrors the distributed skip

        farthest_idx = max(members, key=lambda m: net.dist[ch, m])
        net.spend(ch, net.e_tx_ctrl[ch, farthest_idx], "ctrl_tx")
        control_packets += 1
        for m in members:
            if net.alive[m]:
                net.spend(m, net.e_rx_ctrl, "ctrl_rx")

    return control_packets


def _run_round(net, protocol, cfg, round_idx, proto_rng, channel_rng, all_latencies):
    consumed_before = net.total_consumed()

    protocol.ops_this_round = 0
    t0 = time.perf_counter()
    assignment = protocol.setup_round(net, round_idx, proto_rng)
    setup_time_ms = (time.perf_counter() - t0) * 1000.0

    control_packets = _charge_control_traffic(net, cfg, protocol, assignment)

    transmissions = protocol.route(net, assignment, round_idx)
    ops_count = protocol.ops_this_round
    _validate_no_double_forward(transmissions)

    # Execution order: (hop_depth, src) ascending -- NOT plain ascending src.
    # See docs/ASSUMPTIONS.md "hop_depth ordering correction". Plain
    # ascending-src order breaks causality whenever a forwarding node's
    # index is lower than one of its senders' (about half of all clusters on
    # a random topology), which corrupts aggregation totals. hop_depth
    # guarantees every packet feeding INTO a node is resolved before that
    # node's own forward is processed, for chains of arbitrary depth. src
    # remains the ascending tiebreak within a hop_depth tier, preserving
    # full determinism.
    ordered = sorted(transmissions, key=lambda t: (t.hop_depth, t.src))

    # Runtime causal-invariant safety net: count, per destination node, how
    # many inbound 'data' packets (real-node destinations only) are still
    # unresolved this round. If a node's own forward is ever processed while
    # packets destined for IT are still pending, that is a hop_depth
    # mislabeling bug in the protocol -- fail loudly rather than silently
    # producing a wrong (too-small) aggregation total.
    pending_inbound = {}
    for t in ordered:
        if t.kind == "data" and t.dst != BS:
            pending_inbound[t.dst] = pending_inbound.get(t.dst, 0) + 1

    incoming_bits = {}
    incoming_readings = {}
    agg_charged = set()

    packets_sent = 0
    packets_received_bs = 0
    readings_attempted = 0
    readings_delivered = 0

    for t in ordered:
        bits = cfg.data_bits if t.kind == "data" else cfg.ctrl_bits

        if t.kind == "data":
            pending_here = pending_inbound.get(t.src, 0)
            if pending_here > 0:
                raise RuntimeError(
                    f"causal invariant violated: node {t.src} forwarded a "
                    f"data packet in round {round_idx} while {pending_here} "
                    f"inbound packet(s) destined for it were still pending "
                    f"this round -- check hop_depth labeling (a forwarding "
                    f"node's hop_depth must exceed every packet it folds in)"
                )
            if incoming_bits.get(t.src, 0.0) > 0.0 and t.src not in agg_charged:
                net.spend(t.src, e_agg(incoming_bits[t.src], cfg), "agg")
                agg_charged.add(t.src)

        # effective_readings: pure engine accounting, not protocol-supplied
        # (see Transmission docstring / docs/ASSUMPTIONS.md) -- this
        # packet's own fresh reading (if any) plus whatever readings were
        # actually delivered INTO t.src this round from earlier hops.
        effective_readings = 0
        if t.kind == "data":
            effective_readings = int(t.originates) + incoming_readings.get(t.src, 0)

        delivered = False
        if net.alive[t.src]:
            if t.kind == "data":
                packets_sent += 1
                if t.originates:
                    readings_attempted += 1

            # PER lookup, not a per() call: PER is static (fixed by bits,
            # distance, per-link shadowing, all pinned at topology-build
            # time), so Network precomputes these tables once in __init__
            # and the engine's inner loop -- the hottest path in the whole
            # simulator -- just indexes into them. See docs/ASSUMPTIONS.md
            # for the exactness proof and the before/after timing.
            #
            # e_tx lookup, not an e_tx() call: e_tx is static for the same
            # reason PER is (it depends only on bits -- one of two fixed cfg
            # constants -- and distance, which is static per link), so
            # Network precomputes these tables too (mirroring the PER
            # tables exactly) and the engine indexes into them instead of
            # calling radio.e_tx(), which was profiled at ~46% of remaining
            # per-round time. e_rx doesn't depend on distance at all, so it
            # is cached as two plain floats rather than a table. Both
            # lookups are hoisted out of the retry loop below -- same value
            # on every attempt, no reason to redo it per attempt. See
            # docs/ASSUMPTIONS.md for the exactness proof and timing.
            if t.dst == BS:
                p = net.per_data_bs[t.src] if t.kind == "data" else net.per_ctrl_bs[t.src]
                e_tx_val = net.e_tx_data_bs[t.src] if t.kind == "data" else net.e_tx_ctrl_bs[t.src]
            else:
                p = net.per_data[t.src, t.dst] if t.kind == "data" else net.per_ctrl[t.src, t.dst]
                e_tx_val = (
                    net.e_tx_data[t.src, t.dst] if t.kind == "data" else net.e_tx_ctrl[t.src, t.dst]
                )
            e_rx_val = net.e_rx_data if t.kind == "data" else net.e_rx_ctrl

            for attempt in range(1 + cfg.max_retx):
                is_retry = attempt > 0
                tx_cat = "retry" if is_retry else ("data_tx" if t.kind == "data" else "ctrl_tx")
                if not net.spend(t.src, e_tx_val, tx_cat):
                    break  # source died mid-attempt -> packet lost

                if t.dst != BS:
                    if not net.alive[t.dst]:
                        break  # destination already dead -> packet lost
                    rx_cat = "retry" if is_retry else ("data_rx" if t.kind == "data" else "ctrl_rx")
                    if not net.spend(t.dst, e_rx_val, rx_cat):
                        break  # destination died mid-attempt -> packet lost

                u = channel_rng.random()
                if u >= p:
                    delivered = True
                    break
                # else: attempt failed on the channel, retry if any remain

        if t.kind == "data" and t.dst != BS:
            pending_inbound[t.dst] -= 1
            if delivered:
                incoming_bits[t.dst] = incoming_bits.get(t.dst, 0.0) + bits
                incoming_readings[t.dst] = incoming_readings.get(t.dst, 0) + effective_readings

        if delivered and t.kind == "data" and t.dst == BS:
            packets_received_bs += 1
            readings_delivered += effective_readings
            latency = t.slot_index * cfg.slot_ms + t.hop_depth * (cfg.tx_time_ms + cfg.proc_ms)
            all_latencies.append(latency)

    alive_nodes = int(net.alive.sum())
    total_residual = float(net.energy.sum())
    mean_residual_all = total_residual / cfg.n_nodes
    mean_residual_alive = float(net.energy[net.alive].mean()) if alive_nodes > 0 else 0.0
    energy_consumed_round = net.total_consumed() - consumed_before
    mean_latency_ms = 0.0
    if packets_received_bs > 0:
        # Recover exactly the latencies appended during this round: they are
        # the last `packets_received_bs` entries of all_latencies (one per
        # delivered packet, appended in delivery order this round).
        mean_latency_ms = float(np.mean(all_latencies[-packets_received_bs:]))

    return {
        "round": round_idx,
        "alive_nodes": alive_nodes,
        "num_ch": len(assignment.ch_ids),
        "total_residual_energy": total_residual,
        "mean_residual_energy_all": mean_residual_all,
        "mean_residual_energy_alive": mean_residual_alive,
        "packets_sent": packets_sent,
        "packets_received_bs": packets_received_bs,
        "readings_attempted": readings_attempted,
        "readings_delivered": readings_delivered,
        "control_packets": control_packets,
        "energy_consumed_round": energy_consumed_round,
        "mean_latency_ms": mean_latency_ms,
        "setup_time_ms": setup_time_ms,
        "ops_count": ops_count,
    }


def run_single(protocol_factory, cfg: SimConfig, run_index: int, measure_memory: bool = False):
    """Run one protocol instance for one topology (run_index).

    Returns (per_round_records, summary_record). protocol_factory is a
    zero-arg callable that constructs a fresh Protocol instance (so every
    run_index gets a clean protocol object with no leaked state).
    """
    protocol = protocol_factory()
    net = Network(cfg, run_index)

    proto_seed = _derive_seed(run_index, protocol.name)
    channel_seed = _derive_seed(run_index, protocol.name, "channel")
    proto_rng = np.random.default_rng(proto_seed)
    channel_rng = np.random.default_rng(channel_seed)

    per_round_records = []
    all_latencies = []

    # tracemalloc intercepts every allocation, and its overhead grows with the
    # number of traced blocks. Protocols that allocate many small NumPy
    # temporaries in Python loops (SOM's Kohonen sweep, NSGA-II's GA) were
    # measured ~9x slower than their true cost, while vectorized protocols
    # (LEACH, PEGASIS) were barely affected -- so timing and memory CANNOT be
    # measured in the same run without corrupting `mean_setup_ms`, which is a
    # reported metric. They are now measured in separate runs: this one reports
    # either honest timing or memory, never both. The other is NaN, and the
    # aggregator skips NaN.
    if measure_memory:
        tracemalloc.start()
    t_start = time.perf_counter()

    for round_idx in range(cfg.max_rounds):
        if not net.alive.any():
            break
        record = _run_round(net, protocol, cfg, round_idx, proto_rng, channel_rng, all_latencies)
        per_round_records.append(record)

    total_runtime_s = time.perf_counter() - t_start
    if measure_memory:
        _current_mem, peak_mem = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        total_runtime_s = float("nan")  # corrupted by tracemalloc overhead
        for r in per_round_records:
            r["setup_time_ms"] = float("nan")
    else:
        peak_mem = float("nan")

    summary = metrics.build_summary(
        per_round_records=per_round_records,
        all_latencies=all_latencies,
        net=net,
        cfg=cfg,
        run_index=run_index,
        protocol_name=protocol.name,
        total_runtime_s=total_runtime_s,
        peak_memory_bytes=peak_mem,
    )
    return per_round_records, summary
