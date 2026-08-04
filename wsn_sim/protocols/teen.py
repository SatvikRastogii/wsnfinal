"""TEEN (Threshold sensitive Energy Efficient sensor Network protocol).

Manjeshwar, A., & Agrawal, D. P. (2001). "TEEN: A Routing Protocol for
Enhanced Efficiency in Wireless Sensor Networks." In Proceedings 15th
International Parallel and Distributed Processing Symposium (IPDPS 2001)
Workshops, pp. 2009-2015.

What is implemented here
-------------------------
- Clustering (CH election + nearest-CH membership) is IDENTICAL to LEACH:
  this class subclasses `LEACHProtocol` and reuses its `setup_round`
  unchanged (see `protocols/leach.py`). TEEN's actual contribution over
  LEACH is purely the REACTIVE reporting rule below -- it changes nothing
  about how clusters form.
- Reactive (threshold-sensitive) reporting, per the paper: a node
  transmits its own sensor reading this round iff

      sensed >= cfg.ht                      (Hard Threshold)
      AND |sensed - last_sent| >= cfg.st    (Soft Threshold)

  where `last_sent` is the value of the last reading THIS node actually
  transmitted, tracked per-node in `self._last_sent` (persisted across
  rounds on the protocol instance, per the "never your own RNG, do store
  your own bookkeeping" convention). Sensed values are read from
  `net.sensed[round_idx]`, the engine's shared, run_index-seeded sensor
  stream (see `network.py` -- every protocol at a given run_index sees the
  identical sensed value for a given node/round). A node that has never
  transmitted has no `last_sent` baseline, so it transmits the first time
  it crosses HT -- the ST gate does not apply yet (there is nothing to
  compare against).
- A node that fails the gate is SUPPRESSED: no `Transmission` is emitted
  for it at all this round -- not a lost packet, never attempted. This is
  the real, intended TEEN behaviour and exactly the energy saving the
  paper is built around; `readings_attempted` correctly excludes it (see
  `docs/ASSUMPTIONS.md` item 15).
- A cluster head forwards to the BS iff it has at least one thing to send:
  its own reading passed the threshold gate, OR at least one of its
  members attempted a transmission this round (see "Deviations" below for
  why "attempted," not "successfully delivered," is the operative test).
  `originates` on the CH's own BS-bound packet is `True` only if the CH's
  OWN reading passed -- a CH purely relaying suppressed its own reading and
  sets `originates=False`, matching the engine-level aggregation contract
  (`docs/ASSUMPTIONS.md` items 5 and 16).
- The TDMA frame SHAPE (which slot each member would use, and when the
  CH's own slot falls) is still dictated by cluster size, same as LEACH --
  reactive suppression means a slot goes unused, not that the schedule
  shrinks.
- The engine additionally charges ONE extra per-CH broadcast this round
  (`extra_ch_broadcasts = 1`, priced by
  `engine._charge_control_distributed` exactly like the SCHEDULE step) for
  the HT/ST threshold announcement every CH makes to its cluster -- this
  module only declares the count; it never prices it.

Deviations from the original paper
-----------------------------------
- All energy accounting and packet sizing remains engine-owned (see
  `protocols/base.py`); this module only decides WHETHER a node has
  something to report and to whom.
- "≥1 member packet was delivered to it" (the natural-language rule for
  when a CH forwards) is implemented as "≥1 member packet was ATTEMPTED
  this round," not "successfully received through the lossy channel."
  This is a causality requirement, not a convenience simplification:
  `route()` must return the WHOLE round's Transmission list before the
  engine has drawn ANY channel outcomes (see `engine._run_round`), so
  whether a specific member's packet actually survives the channel cannot
  be known yet at the point the CH's forwarding decision is made.
  "Did anyone attempt to send me something this round" is the only version
  of that fact a protocol can act on causally; the engine still
  charges/aggregates strictly on what is actually delivered, per the
  existing engine-wide aggregation rule.
- EXPECTED, not a bug: with default `cfg.ht=55.0`, `cfg.st=1.0` against the
  ~N(50, 6.4^2) stationary sensed distribution, TEEN may not reach LND
  within the round cap -- nodes that rarely cross HT spend very little
  energy and can outlast the cap. `lnd_censored=True` correctly reports
  this; HT/ST are NOT tuned to avoid it, since that would defeat the point
  of benchmarking a genuinely reactive protocol.
"""

import numpy as np

from ..network import BS
from .base import ClusterAssignment, Transmission
from .leach import LEACHProtocol


class TEENProtocol(LEACHProtocol):
    name = "teen"
    control_model = "distributed"
    extra_ch_broadcasts = 1

    def __init__(self):
        super().__init__()
        self._last_sent = {}

    def _wants_to_send(self, node: int, sensed_value: float, cfg, round_idx: int) -> bool:
        """Hard+soft threshold gate. Updates `self._last_sent` as a side
        effect ONLY when the node actually decides to transmit (matching
        `last_sent`'s definition: the last value actually sent).
        `round_idx` is unused here but kept in the signature so APTEEN can
        override this method with the same call shape (it needs round_idx
        for its count-time clause).
        """
        last = self._last_sent.get(node)
        if sensed_value < cfg.ht:
            return False
        if last is not None and abs(sensed_value - last) < cfg.st:
            return False
        self._last_sent[node] = sensed_value
        return True

    def route(self, net, assignment: ClusterAssignment, round_idx: int) -> list:
        cfg = net.cfg
        sensed = net.sensed[round_idx]

        members_by_ch = {}
        for m, c in assignment.member_of.items():
            members_by_ch.setdefault(c, []).append(m)

        transmissions = []

        for ch in assignment.ch_ids:
            all_members = sorted(m for m in members_by_ch.get(ch, []) if net.alive[m])
            any_member_sent = False
            for slot, m in enumerate(all_members):
                if self._wants_to_send(m, float(sensed[m]), cfg, round_idx):
                    any_member_sent = True
                    transmissions.append(
                        Transmission(
                            src=m, dst=ch, kind="data", slot_index=slot,
                            hop_depth=1, originates=True,
                        )
                    )

            if not net.alive[ch]:
                continue
            own_sends = self._wants_to_send(ch, float(sensed[ch]), cfg, round_idx)
            if own_sends or any_member_sent:
                transmissions.append(
                    Transmission(
                        src=ch, dst=BS, kind="data", slot_index=len(all_members),
                        hop_depth=2, originates=own_sends,
                    )
                )

        # Self-heads: zero-CH round edge case, same as LEACH -- each
        # applies the identical reactive gate for its own direct-to-BS send.
        assigned_or_ch = set(assignment.ch_ids) | set(assignment.member_of.keys())
        alive_idx = np.flatnonzero(net.alive)
        for n in alive_idx:
            n = int(n)
            if n in assigned_or_ch:
                continue
            if self._wants_to_send(n, float(sensed[n]), cfg, round_idx):
                transmissions.append(
                    Transmission(src=n, dst=BS, kind="data", slot_index=0, hop_depth=1, originates=True)
                )

        return transmissions
