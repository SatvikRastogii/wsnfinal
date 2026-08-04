"""APTEEN (Adaptive Periodic TEEN).

Manjeshwar, A., & Agrawal, D. P. (2002). "APTEEN: A Hybrid Protocol for
Efficient Routing and Comprehensive Information Retrieval in Wireless
Sensor Networks." In Proceedings 16th International Parallel and
Distributed Processing Symposium (IPDPS 2002), pp. 195-202.

What is implemented here
-------------------------
Everything from `TEENProtocol` (see `protocols/teen.py` for the full
citation, clustering reuse, and reactive HT/ST gate) PLUS one addition:
a node also transmits if it has NOT transmitted for `cfg.tc` rounds (the
Count Time / max reporting interval), regardless of whether the HT/ST
gates would otherwise suppress it. This is APTEEN's periodic/proactive
half layered on top of TEEN's purely-reactive rule -- the paper's hybrid
behaviour.

`self._last_sent_round` (per-node, instance-persisted, same convention as
TEEN's `self._last_sent`) tracks the round index of each node's last
ACTUAL transmission; a node that has never transmitted is treated as
overdue from round 0 (`last_sent_round = -1`), so it force-sends by round
`cfg.tc - 1` at the latest even if it never once crosses HT.

Deviations from the original paper
-----------------------------------
- Only the reporting-frequency mechanism (HT/ST reactive gate + TC count
  time) is implemented; the paper's broader "queries" (attribute-based,
  historical, one-time) are out of scope here -- this simulator has no
  query channel, only periodic sensing and reporting.
- Everything else -- clustering, control-traffic pricing, energy/packet
  accounting -- is identical to TEEN, which is identical to LEACH; see
  those modules' docstrings for the full deviation list.
- EXPECTED: because of the TC clause, APTEEN sends strictly more data
  packets than TEEN (periodic force-sends on top of the reactive gate) but
  strictly fewer than LEACH (which sends unconditionally every round) --
  this is the intended trade-off point between LEACH and TEEN, not a bug.
"""

from .teen import TEENProtocol


class APTEENProtocol(TEENProtocol):
    name = "apteen"

    def __init__(self):
        super().__init__()
        self._last_sent_round = {}

    def _wants_to_send(self, node: int, sensed_value: float, cfg, round_idx: int) -> bool:
        last = self._last_sent.get(node)
        last_round = self._last_sent_round.get(node, -1)

        reactive_pass = sensed_value >= cfg.ht and (last is None or abs(sensed_value - last) >= cfg.st)
        count_time_pass = (round_idx - last_round) >= cfg.tc

        if reactive_pass or count_time_pass:
            self._last_sent[node] = sensed_value
            self._last_sent_round[node] = round_idx
            return True
        return False
