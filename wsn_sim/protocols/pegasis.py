"""PEGASIS (Power-Efficient GAthering in Sensor Information Systems).

Lindsey, S., & Raghavendra, C. S. (2002). "PEGASIS: Power-Efficient
Gathering in Sensor Information Systems." IEEE Aerospace Conference
Proceedings, Vol. 3, pp. 1125-1130.

What is implemented here
-------------------------
- Greedy chain construction: starting from the alive node FARTHEST from the
  BS, repeatedly append the nearest not-yet-chained alive node (the classic
  greedy nearest-neighbor chain the paper describes for the common case of
  global location knowledge).
- Chain REBUILD policy: node positions are static, so the only thing that
  can invalidate an existing chain is a node dying. The chain is rebuilt
  whenever the alive-node count has dropped since the last build (and
  unconditionally on the first round it runs). `self.chain_rebuilt_this_round`
  records this for the engine's `"chain"` control model
  (`engine._charge_control_chain`), which prices the rebuild-broadcast
  differently from a steady no-rebuild round.
- Leader election: `leader = chain[round_idx mod len(chain)]` -- a cheap,
  fixed round-robin over CURRENT chain positions, matching the paper's
  token-passing leader rotation.
- Data gathering: every round, data flows INWARD from BOTH ends of the
  chain toward the leader, fusing (aggregating) at every intermediate hop
  -- each non-leader node sends exactly one outgoing packet to its
  chain-neighbour on the leader side. The leader sends exactly one fused
  packet to the BS. `hop_depth` increases strictly along each of the two
  inbound directions (1 at the chain end, up to the leader's own hop_depth,
  which is always the deepest), matching the engine's `(hop_depth, src)`
  execution order and enforced-aggregation rule (see `protocols/base.py`
  and `docs/ASSUMPTIONS.md` item 5).
- `slot_index` is always 0: PEGASIS has no TDMA frame to wait out (unlike
  LEACH). Round latency instead comes entirely from chain depth via
  `hop_depth` (sequential fuse-and-forward) -- this is intended, correct
  behaviour: PEGASIS trades latency for energy relative to LEACH.

Deviations from the original paper
-----------------------------------
- All energy accounting and packet sizing is engine-owned, as with every
  protocol in this simulator (see `protocols/base.py`); this module only
  decides chain structure and routing.
- Control traffic (token pass-along, chain-rebuild broadcast) is priced
  entirely by the engine's `"chain"` control model
  (`engine._charge_control_chain`), not by this module -- this module only
  exposes `self.chain` and `self.chain_rebuilt_this_round`.
- The paper allows a cheaper local repair (patching only the two links
  broken by a death) instead of a full rebuild; this implementation always
  rebuilds the WHOLE chain from scratch on any death for simplicity -- same
  greedy chain, just recomputed globally rather than patched locally.
  Flagged here rather than silently narrowing the paper's repair strategy.
- The paper's leader additionally performs the final data-fusion step; the
  fusion ENERGY cost (`e_agg`) is engine-charged uniformly to every
  receiving/forwarding node along the chain (not just the leader), per the
  simulator-wide aggregation rule.
"""

import numpy as np

from ..network import BS
from .base import ClusterAssignment, Protocol, Transmission


class PEGASISProtocol(Protocol):
    name = "pegasis"
    control_model = "chain"

    def __init__(self):
        self.chain = ()
        self.chain_rebuilt_this_round = False
        self._last_alive_count = None

    def _build_chain(self, net):
        """Greedy nearest-neighbor chain, O(n^2) distance comparisons.
        Returns (chain_list, ops_counted).
        """
        alive_idx = np.flatnonzero(net.alive).tolist()
        ops = 0
        if not alive_idx:
            return [], ops

        dist_bs = net.dist_bs
        start = alive_idx[0]
        best_d = dist_bs[start]
        for i in alive_idx[1:]:
            ops += 1
            if dist_bs[i] > best_d:
                best_d = dist_bs[i]
                start = i

        remaining = set(alive_idx)
        remaining.remove(start)
        chain = [start]
        current = start
        while remaining:
            best = None
            best_d = None
            for cand in remaining:
                d = net.dist[current, cand]
                ops += 1
                if best_d is None or d < best_d:
                    best_d = d
                    best = cand
            chain.append(best)
            remaining.remove(best)
            current = best
        return chain, ops

    def setup_round(self, net, round_idx: int, rng) -> ClusterAssignment:
        alive_count = int(net.alive.sum())
        need_rebuild = self._last_alive_count is None or alive_count < self._last_alive_count

        if need_rebuild:
            chain, ops = self._build_chain(net)
            self.chain = tuple(chain)
            self.ops_this_round += ops
            self.chain_rebuilt_this_round = True
            self._last_alive_count = alive_count
        else:
            self.chain_rebuilt_this_round = False

        n = len(self.chain)
        if n == 0:
            return ClusterAssignment(ch_ids=[], member_of={})
        leader_idx = round_idx % n
        leader = int(self.chain[leader_idx])
        # ch_ids carries the current leader only, for the `num_ch` metric
        # column -- PEGASIS elects exactly one active "head" per round.
        # member_of is left empty: chain adjacency (not CH membership) is
        # what determines routing here, and the "chain" control model does
        # not read ClusterAssignment.member_of at all.
        return ClusterAssignment(ch_ids=[leader], member_of={})

    def route(self, net, assignment: ClusterAssignment, round_idx: int) -> list:
        chain = self.chain
        n = len(chain)
        if n == 0:
            return []
        leader_idx = round_idx % n
        leader = int(chain[leader_idx])

        transmissions = []

        # Left side (positions 0..leader_idx-1) feeds RIGHTWARD toward the
        # leader: hop_depth 1 at the chain's far end, +1 per hop -- this is
        # exactly `1 + max(hop_depth of what it folds in)` because position
        # `pos` folds in position `pos-1`'s packet (hop_depth = pos).
        left_len = leader_idx
        for pos in range(left_len):
            node = int(chain[pos])
            nxt = int(chain[pos + 1])
            if net.alive[node]:
                transmissions.append(
                    Transmission(
                        src=node, dst=nxt, kind="data", slot_index=0,
                        hop_depth=pos + 1, originates=True,
                    )
                )

        # Right side (positions n-1..leader_idx+1) feeds LEFTWARD toward the
        # leader, same depth logic mirrored from the other end.
        right_len = n - leader_idx - 1
        for k in range(right_len):
            pos = n - 1 - k
            node = int(chain[pos])
            nxt = int(chain[pos - 1])
            if net.alive[node]:
                transmissions.append(
                    Transmission(
                        src=node, dst=nxt, kind="data", slot_index=0,
                        hop_depth=k + 1, originates=True,
                    )
                )

        # Leader: folds both inbound streams (if present) plus its own
        # reading, forwards ONE fused packet to the BS. Its hop_depth must
        # exceed the deepest packet feeding into it from either side.
        if net.alive[leader]:
            incoming_depths = [d for d in (left_len, right_len) if d > 0]
            leader_depth = (max(incoming_depths) if incoming_depths else 0) + 1
            transmissions.append(
                Transmission(
                    src=leader, dst=BS, kind="data", slot_index=0,
                    hop_depth=leader_depth, originates=True,
                )
            )

        return transmissions
