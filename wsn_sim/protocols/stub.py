"""StubProtocol: the trivial no-clustering baseline used to test the engine.

Every alive node sends one 'data' Transmission direct to the BS. There are
no cluster heads, so none of the engine's control-traffic or aggregation
machinery is ever exercised by this protocol -- those paths are covered by
dedicated synthetic scenarios in tests/test_engine.py instead.
"""

import numpy as np

from ..network import BS
from .base import ClusterAssignment, Protocol, Transmission


class StubProtocol(Protocol):
    name = "stub"

    def setup_round(self, net, round_idx: int, rng) -> ClusterAssignment:
        return ClusterAssignment(ch_ids=[], member_of={})

    def route(self, net, assignment: ClusterAssignment, round_idx: int) -> list:
        alive_idx = np.flatnonzero(net.alive)
        return [
            Transmission(
                src=int(i),
                dst=BS,
                kind="data",
                slot_index=pos,
                hop_depth=1,
                originates=True,
            )
            for pos, i in enumerate(alive_idx)
        ]
