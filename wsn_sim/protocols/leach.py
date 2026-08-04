"""LEACH (Low-Energy Adaptive Clustering Hierarchy).

Heinzelman, W.R., Chandrakasan, A.P., & Balakrishnan, H. (2000).
"Energy-Efficient Communication Protocol for Wireless Microsensor
Networks." In Proceedings of the 33rd Annual Hawaii International
Conference on System Sciences (HICSS-33), Maui, HI.

What is implemented here
-------------------------
- The paper's stochastic CH-election threshold, exactly as given:

      T(n) = p / (1 - p * (r mod round(1/p)))   if n has NOT been a CH
                                                  in the current epoch
      T(n) = 0                                   if n HAS been a CH
                                                  in the current epoch

  where `p` is `cfg.p_ch`, `r` is the current (0-based) round index, and
  the epoch length is `round(1/p)` (20 rounds at the default p=0.05). Each
  alive node not yet a CH this epoch draws u ~ U(0,1) from this protocol's
  own `rng` (the one passed into `setup_round` -- never a private
  Generator, per the engine's fairness-critical seeding scheme, see
  `wsn_sim.engine` module docstring) and self-elects as CH if u < T(n).
  The "already been CH this epoch" set resets every `round(1/p)` rounds and
  drops any node that has since died.
- Nearest-CH membership: every alive node that is not itself a CH this
  round joins whichever elected CH is closest to it by Euclidean distance
  (`net.dist`).
- The steady-state TDMA structure this induces: each member transmits to
  its CH in its own slot; the CH can only aggregate-and-forward to the BS
  once every member's slot has elapsed, which is what makes LEACH's
  latency scale with cluster size (see `route` below).

Realized CH count is intentionally left fully stochastic -- it fluctuates
around `p * N` per round by construction (this is a property of the
algorithm, not a bug), and is never clamped to any fixed number. A round
electing 0 CHs is a legitimate outcome: every alive node becomes a
self-head and transmits directly to the BS that round; nobody is
force-elected to avoid this. Note also a well-known property of this exact
threshold formula: T(n) -> 1 on the LAST round of each epoch for any node
not yet elected that epoch, which guarantees it becomes a CH that round --
this can produce a large CH-count spike on epoch-boundary rounds, which is
expected, not a fairness bug (see docs/ASSUMPTIONS.md item 22).

Deviations from the original paper
-----------------------------------
- All energy accounting, packet sizing, and channel/ARQ modeling is owned
  by the engine (`wsn_sim.engine` / `wsn_sim.radio`), never by this
  protocol -- a simulator-wide invariant (see `protocols/base.py`), not
  something specific to LEACH. This protocol never calls `net.spend`,
  never chooses a bit count, and never touches the channel model directly.
- ADV / JOIN-REQ / TDMA-SCHEDULE control-traffic accounting (including the
  ADV-vs-SCHEDULE audience asymmetry and the zero-member-CH special case)
  is likewise engine-owned and uniform across every clustering protocol
  (`engine._charge_control_traffic`), not reimplemented here. This module
  only decides cluster STRUCTURE (`ClusterAssignment`); the engine turns
  that structure into control-traffic energy charges on its own.
- The paper has nodes choose their CH based on the received signal
  strength of each CH's ADV broadcast; this implementation uses static
  Euclidean node-to-node distance (`net.dist`) instead, since nodes are
  static and the engine's own radio/channel model is itself a function of
  that same distance -- there is no independent RSSI signal to model here,
  so "join the CH with the strongest received ADV" and "join the nearest
  CH" coincide exactly in this simulator's physical model.
- Because cluster/membership STRUCTURE must be fully decided before the
  engine charges control traffic (`_charge_control_traffic` runs between
  `setup_round` and `route`, and reads `ClusterAssignment.member_of`
  directly), nearest-CH membership assignment -- and the ops-counting for
  it -- happens inside `setup_round`, not `route`. `route` only turns the
  already-decided `ClusterAssignment` into concrete `Transmission`s.
"""

import numpy as np

from ..network import BS
from .base import ClusterAssignment, Protocol, Transmission


class LEACHProtocol(Protocol):
    name = "leach"

    def __init__(self):
        # Nodes that have already been CH during the current epoch (reset
        # every round(1/p) rounds). Per-instance, not shared across runs --
        # engine.run_single constructs a fresh Protocol instance per
        # run_index via protocol_factory, so this never leaks between runs.
        self._ch_this_epoch = set()
        self._epoch_idx = None

    def setup_round(self, net, round_idx: int, rng) -> ClusterAssignment:
        cfg = net.cfg
        p = cfg.p_ch
        epoch_len = round(1.0 / p)

        epoch_idx = round_idx // epoch_len
        if epoch_idx != self._epoch_idx:
            self._epoch_idx = epoch_idx
            self._ch_this_epoch = set()
        # Drop dead nodes from the "already CH this epoch" bookkeeping --
        # a dead node can never be reconsidered as a CH candidate anyway
        # (it's excluded from alive_idx below), but the spec calls for
        # dropping it from this set explicitly.
        self._ch_this_epoch = {n for n in self._ch_this_epoch if net.alive[n]}

        r_mod = round_idx % epoch_len
        denom = 1.0 - p * r_mod

        alive_idx = np.flatnonzero(net.alive)
        ch_ids = []
        for n in alive_idx:
            n = int(n)
            if n in self._ch_this_epoch:
                continue  # T(n) = 0 -- already CH this epoch
            t_n = p / denom if denom > 0.0 else 1.0
            u = rng.random()
            if u < t_n:
                ch_ids.append(n)
                self._ch_this_epoch.add(n)

        # Nearest-CH membership for every alive non-CH node. This MUST be
        # decided here (not in route()) because engine._charge_control_
        # traffic reads ClusterAssignment.member_of before route() ever
        # runs. Ops counted here: one node-pair distance comparison per
        # (alive non-CH node, elected CH) pair -- the LOGICAL algorithmic
        # cost LEACH pays for membership, independent of how the engine's
        # precomputed distance matrix happens to make that comparison cheap
        # in practice. Coin flips above are NOT counted (not a distance
        # computation, fitness evaluation, or forward pass).
        member_of = {}
        if ch_ids:
            ch_id_set = set(ch_ids)
            ch_arr = np.array(ch_ids, dtype=int)
            non_ch_alive = [n for n in alive_idx.tolist() if n not in ch_id_set]
            for m in non_ch_alive:
                dists = net.dist[m, ch_arr]
                nearest = int(ch_arr[int(np.argmin(dists))])
                member_of[m] = nearest
            self.ops_this_round += len(non_ch_alive) * len(ch_ids)

        return ClusterAssignment(ch_ids=ch_ids, member_of=member_of)

    def route(self, net, assignment: ClusterAssignment, round_idx: int) -> list:
        members_by_ch = {}
        for m, c in assignment.member_of.items():
            members_by_ch.setdefault(c, []).append(m)

        transmissions = []

        for ch in assignment.ch_ids:
            # Members still attempt their send even if the CH happens to
            # have died from control-traffic charges between setup_round
            # and route() -- realistically they don't yet know the CH is
            # dead, and the engine correctly treats a send to a dead
            # destination as an attempted-but-lost packet. Only the CH's
            # OWN forward requires the CH to still be alive.
            members = sorted(m for m in members_by_ch.get(ch, []) if net.alive[m])
            for slot, m in enumerate(members):
                transmissions.append(
                    Transmission(
                        src=m, dst=ch, kind="data", slot_index=slot, hop_depth=1, originates=True
                    )
                )
            if net.alive[ch]:
                # The CH can only send its aggregated packet AFTER every
                # member's TDMA slot has elapsed -- slot_index is the frame
                # length (len(members)), NOT 0. This is what makes LEACH's
                # latency grow with cluster size; setting this to 0 would
                # silently corrupt mean_latency_ms/p95_latency_ms.
                transmissions.append(
                    Transmission(
                        src=ch,
                        dst=BS,
                        kind="data",
                        slot_index=len(members),
                        hop_depth=2,
                        originates=True,
                    )
                )

        # Self-heads: alive nodes that are neither a CH nor assigned to one
        # -- this only happens when zero CHs were elected this round (the
        # edge case where every alive non-CH node would otherwise have been
        # assigned a nearest CH in setup_round). Do not force-elect anyone.
        assigned_or_ch = set(assignment.ch_ids) | set(assignment.member_of.keys())
        alive_idx = np.flatnonzero(net.alive)
        for n in alive_idx:
            n = int(n)
            if n in assigned_or_ch:
                continue
            transmissions.append(
                Transmission(src=n, dst=BS, kind="data", slot_index=0, hop_depth=1, originates=True)
            )

        return transmissions
