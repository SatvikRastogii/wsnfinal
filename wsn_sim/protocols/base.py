"""The narrow interface every clustering protocol must implement.

FAIRNESS BY CONSTRUCTION: a Protocol decides cluster structure and route
shape only. It never computes energy, never chooses a packet's bit count,
and never touches Network.spend or any energy array directly. The engine
(wsn_sim.engine) is the only code that spends energy, sizes packets, and
applies channel/aggregation rules.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class Transmission:
    """One packet a protocol wants sent this round.

    hop_depth is NOT a free-form annotation kept only for latency display --
    as of the engine-enforced aggregation rule (see wsn_sim.engine), it is
    semantically load-bearing: the engine executes every round's
    transmissions sorted by (hop_depth, src) ascending, specifically so that
    every packet feeding INTO a relay/CH/chain-fusion node (shallower
    hop_depth) is fully resolved before that node's own outgoing forward
    (deeper hop_depth) is processed. If a protocol mislabels hop_depth --
    e.g. gives a forwarded/aggregated packet the same hop_depth as the raw
    packets that feed it, instead of one more -- the engine may charge
    aggregation energy against an incomplete set of inbound bits, or the
    runtime causal-invariant check in engine.py may raise. Protocols 2-9
    (anything that forwards or fuses, not just direct-to-BS senders) MUST
    set hop_depth = (max hop_depth of the packets it is folding in) + 1.

    Fields:
        src: node index originating this packet.
        dst: node index, or the BS sentinel (wsn_sim.network.BS == -1).
        kind: 'data' or 'ctrl'. The protocol does NOT choose bit count --
            the engine maps 'data' -> cfg.data_bits, 'ctrl' -> cfg.ctrl_bits.
        slot_index: TDMA slot within the frame, used only for latency.
        hop_depth: cumulative hop count from the original source. See above
            -- this drives execution order and aggregation correctness, not
            just the latency formula.
        originates: does this node fold its OWN fresh sensor reading into
            this packet? This is genuine protocol logic (e.g. a TEEN-style
            node can suppress its own below-threshold reading while still
            relaying its members' data unchanged -- `originates=False` in
            that case) and is the ONE reading-related fact a protocol is
            trusted to declare.

    Deliberately NOT a field: how many readings this packet ends up
    representing once forwarding/aggregation is folded in. That count --
    "how many readings does this packet now represent?" -- is pure
    accounting, not protocol logic, and a protocol must not be able to
    influence it (a dishonest/buggy protocol could otherwise inflate its own
    apparent data_yield/PDR by just claiming a bigger number). The ENGINE
    computes it, once, per delivered hop:

        effective_readings(t) = int(t.originates) + (readings carried by
            whichever inbound packets were actually DELIVERED to t.src this
            round)

    via `incoming_readings`, tracked in engine.py alongside the existing
    `incoming_bits` (same bookkeeping shape, same place in the round loop).
    A protocol declares only the "did I sense-and-report?" bit; the engine
    alone turns that into a reading count.
    """

    src: int
    dst: int
    kind: str
    slot_index: int = 0
    hop_depth: int = 1
    originates: bool = True


@dataclass
class ClusterAssignment:
    """A round's cluster structure, as decided by a protocol.

    ch_ids: cluster head node indices this round (may be empty).
    member_of: member node index -> its cluster head node index. Nodes
        absent from member_of and not present in ch_ids are self-heads
        (they send directly to the BS this round).
    """

    ch_ids: list = field(default_factory=list)
    member_of: dict = field(default_factory=dict)


class Protocol(ABC):
    """Base class every clustering protocol subclasses."""

    name: str = "base"

    # Which control-traffic pricing model the engine applies this round
    # (`engine._charge_control_traffic` dispatches on this; the ENGINE still
    # owns every joule/bit decision -- this only tells it which structural
    # facts to price). One of:
    #   "distributed" -- LEACH-style ADV/JOIN-REQ/SCHEDULE, charged against
    #       `ClusterAssignment` alone (LEACH, TEEN, APTEEN).
    #   "chain"       -- no ADV/JOIN/SCHEDULE; hop-by-hop leader-token pass
    #       along `self.chain`, plus a BS rebuild broadcast on rebuild
    #       rounds (PEGASIS).
    #   "centralized" -- the BS already knows cluster structure; uplink node
    #       state piggybacks on data traffic (free), a BS assignment
    #       broadcast fires only on `self.reclustered_this_round`, and every
    #       CH still broadcasts its own TDMA schedule every round (NSGA-II,
    #       Fuzzy-T2, and later centralized protocols).
    control_model: str = "distributed"

    # "distributed" model only: how many EXTRA ctrl broadcasts (beyond the
    # base ADV/JOIN-REQ/SCHEDULE) each CH sends this round, each priced at
    # farthest-member distance with every member paying E_rx(ctrl). TEEN/
    # APTEEN set this to 1 for the HT/ST/TC threshold broadcast.
    extra_ch_broadcasts: int = 0

    # "chain" model only: the current ordered chain (list/tuple of node
    # indices, head-to-tail) and whether it was rebuilt THIS round.
    chain: tuple = ()
    chain_rebuilt_this_round: bool = False

    # "centralized" model only: whether the BS recomputed and broadcast a
    # new cluster assignment THIS round (vs. reusing the last one).
    reclustered_this_round: bool = False

    # Per-round algorithmic-workload counter. Reset to 0 by the ENGINE
    # immediately before each `setup_round` call (see wsn_sim.engine); a
    # protocol implementation increments it as it does work during EITHER
    # `setup_round` OR `route` -- BOTH phases of the round are counted. The
    # engine reads this attribute back right after `route` returns (i.e.
    # after both phases have run) and records it as the `ops_count`
    # per-round column; `ops_per_round` in the summary is just the mean of
    # that column.
    #
    # Widened read window: an earlier version of this engine read
    # `ops_this_round` immediately after `setup_round` returned, BEFORE
    # `route` was called, which silently dropped any ops a protocol counted
    # inside `route` -- undercounting any protocol (of the nine planned)
    # that does distance/fitness/forward-pass work in `route` rather than
    # `setup_round`. The window is now widened to cover both methods: reset
    # immediately before `setup_round`, read immediately after `route`
    # returns. A protocol author may do its counted work in either method
    # (or split across both) with no risk of under-reporting. See
    # docs/ASSUMPTIONS.md item 17 for the history of this correction.
    #
    # This is a COUNTED-OPERATIONS metric, not a traffic-volume proxy --
    # it must mean the same thing across all nine protocols for
    # cross-protocol comparison (e.g. NSGA-II's thousands of fitness
    # evaluations vs. LEACH's coin flip) to be meaningful at all. Count
    # exactly these, once each, every time they happen in a round:
    #   - every node-pair (or node-to-candidate) DISTANCE computation,
    #   - every fitness/objective function EVALUATION,
    #   - every neural-network forward PASS.
    # Do not count anything else (loop iterations, comparisons, packet
    # sends, ...) under this counter -- if it isn't one of the three above,
    # it isn't an "op" for this metric.
    ops_this_round: int = 0

    @abstractmethod
    def setup_round(self, net, round_idx: int, rng) -> ClusterAssignment:
        """Decide this round's cluster heads and membership.

        `rng` is a numpy Generator seeded independently of the topology/
        channel streams (see wsn_sim.engine for the seeding scheme) -- it is
        this protocol's own private randomness and does not affect, and is
        not affected by, any other protocol's run.
        """
        raise NotImplementedError

    @abstractmethod
    def route(self, net, assignment: ClusterAssignment, round_idx: int) -> list:
        """Return the list of Transmissions to execute this round."""
        raise NotImplementedError
