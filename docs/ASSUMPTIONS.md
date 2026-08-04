# ASSUMPTIONS.md — Step 1 (Core Engine)

Every place the spec was ambiguous, silent, or (in one case) internally
inconsistent, and what was decided instead. Ordered roughly by where in the
codebase each decision lives.

## 1. Frozen-dataclass computed properties (`config.py`)

`d0`, `tx_time_ms`, `slot_ms` are implemented as `@property` methods rather
than fields, because the dataclass is frozen (fields can't be derived at
construction time without `object.__setattr__` trickery, which is worse).
Verified by hand: `d0 = sqrt(10e-12/0.0013e-12) ≈ 87.706 m`, inside the
spec's own asserted bounds (87.0, 88.5). `tx_time_ms = 16.0`, `slot_ms =
20.0`, matching the spec exactly.

## 2. Channel rng stream (`engine.py`)

The spec pins the protocol-rng seed formula
(`blake2b(run_index|protocol_name)`) but not the "engine's per-round channel
rng" used for ARQ success draws. **Coordinator ruling**: seed it the same
way, salted with `"channel"`:
`blake2b(f"{run_index}|{protocol_name}|channel")`.

This stream **desyncs across protocols immediately** — different protocols
make different numbers of channel draws per round (different traffic
volume, different retry counts), so there is no meaningful sense in which
two protocols could see "the same channel realization" packet-by-packet.
That's expected and fine. The fairness-critical piece of the channel is the
**static per-link shadowing** (`Network.shadow` / `Network.shadow_bs`),
drawn once from the topology stream keyed by `run_index` alone, and *that*
is byte-identical across all protocols. These two are conceptually
different things — "the physical channel geometry is fair" vs. "the exact
sequence of coin-flips that channel produces is fair" — and only the first
one needs to hold. They are kept in clearly separate code paths so a future
reader doesn't conflate them.

## 3. Control-traffic ADV vs. SCHEDULE audience asymmetry (`engine.py`,
`_charge_control_traffic`)

Confirmed intentional by the coordinator, not a spec bug. ADV is charged as
a receive cost to *every* alive non-CH node, because a node must hear every
CH's advertisement to pick the nearest one before it can decide who to
join. TDMA SCHEDULE is charged only to *actual members*, because a node
only needs its own CH's slot assignment — other clusters' schedules are
irrelevant to it. Implemented literally as written, with an inline comment
at the exact spot in `engine.py` so nobody "fixes" it into symmetry later.

Control traffic (ADV/JOIN-REQ/SCHEDULE) has **no ARQ/retry** — it is a flat
one-shot charge. The spec's numbered ARQ steps are scoped to
`protocol.route()`-returned Transmissions only; control accounting is
described separately and uniformly, with no retry semantics mentioned.

## 4. `data_yield` denominator (`metrics.py`)

"Total readings taken" isn't defined in the spec. Approved reading: one
sensor reading is taken by every alive node every round, independent of
whether it is transmitted or suppressed (this is exactly the gap TEEN-style
threshold protocols will exploit in later steps — sensing happens every
round regardless of the transmit decision). So "total readings taken" ==
`alive_node_auc` (sum of `alive_nodes` across all recorded rounds), and
`data_yield = readings_delivered_total / alive_node_auc`.

## 5. CH/relay aggregation — engine-enforced, not passive (`engine.py`)

Originally drafted as passive bookkeeping ("charge e_agg if a node happens
to receive and forward"). **Coordinator correction**: this must be actively
enforced, generally (any receiving-and-forwarding node, not just
LEACH-style CHs — must cover PEGASIS-style fusion at every chain hop
unchanged):

- A node that receives ≥1 data packet(s) this round and forwards pays
  `e_agg` on the TOTAL bits it *actually received* (post-channel-loss —
  only from packets that were successfully delivered to it), charged
  automatically. A protocol cannot opt out.
- Such a node may emit **at most one** outgoing data packet per round.
  `_validate_no_double_forward` performs a structural pre-flight check on
  the raw `route()`-returned list (based on `src`/`dst`/`kind` alone,
  independent of channel randomness) and raises `ValueError` if a node that
  is the `dst` of ≥1 data Transmission is also the `src` of >1 data
  Transmission in the same round. This is a protocol-correctness bug check,
  not a runtime energy fact.

### 5a. Execution-order correction: `(hop_depth, src)`, not plain `src`

The original spec text said to execute each round's transmissions in
**plain ascending `src` order**, purely for determinism. Implementing
enforced aggregation exposed that this is actually **wrong** whenever a
forwarding node's index is *lower* than one of its senders' — e.g. a CH
with index 5 receiving from a member with index 7: under pure ascending-src
execution, node 5's own outgoing send would execute *before* node 7's send
arrives, so the aggregation charge would be based on an incomplete bit
total. This isn't a hypothetical edge case — on a random topology, roughly
half of all CH/member index pairings will have this shape.

**Coordinator-confirmed correction**: sort each round's transmissions by
the composite key `(hop_depth, src)` ascending, with `src` as the tiebreak
within a hop_depth tier. `hop_depth` ("cumulative hop count from the
original source") already exists on `Transmission` for exactly this
purpose. This guarantees every packet feeding INTO a node (shallower
hop_depth) is fully resolved before that node's own outgoing forward
(deeper hop_depth) is processed — for chains of arbitrary depth, so it
covers both single-hop LEACH-style CH→BS stars and multi-hop PEGASIS-style
chains uniformly, unlike a two-phase non-BS/BS split (which only works for
single-hop stars and would silently break at chain depth 3+).

This makes `hop_depth` **semantically load-bearing**, not a latency-only
annotation — documented prominently in `protocols/base.py` so protocols 2-9
label it correctly: a forwarding/fusing node's `hop_depth` must exceed the
hop_depth of every packet it folds in.

### 5b. Runtime causal-invariant check

Beyond the pre-flight structural check (5), a cheap runtime assertion in
the round loop tracks, per destination node, how many inbound data packets
are still unresolved ("pending") this round. If a node's own forward is
ever processed while packets destined for *it* are still pending, that
means the `(hop_depth, src)` sort did not actually establish causal order —
almost certainly because a protocol mislabeled `hop_depth` (e.g. gave a
fused packet the same depth as its inputs instead of `max(inputs)+1`). This
raises `RuntimeError` immediately rather than silently producing a
too-small (wrong) aggregation total that would look plausible for weeks.

## 6. Zero-member CH (`engine.py`, `_charge_control_traffic`)

A CH with zero members still "pays 1 ctrl broadcast" per the original spec,
but "farthest member" is undefined when there are no members. Coordinator
ruling, in two halves:

- **ADV is still sent**, priced at electronics-only cost
  (`e_tx(ctrl_bits, 0.0, cfg)`), because the CH broadcasts ADV *before* it
  can possibly know whether anyone will join — there is no real distance to
  charge against yet.
- **The TDMA SCHEDULE broadcast is skipped entirely** for a zero-member CH
  (no charge, not counted in `control_packets`), because by schedule time
  the CH already knows it has nobody to schedule.

Not exercised by `StubProtocol` (which never creates CHs at all) — this
path is currently untested by the required hard gates and will need a
dedicated unit test once a real clustering protocol exists in a later step.

## 7. FND/HND/LND granularity (`metrics.py`)

Approved unchanged: derived purely from each round's recorded `alive_nodes`
count (not sub-round death instants, which aren't observable at this
granularity). FND = first round where `alive_nodes < n_nodes`. HND = first
round where cumulative deaths ≥ `ceil(n_nodes/2)`. LND = first round where
`alive_nodes == 0`; if never reached before the round cap, LND is reported
as the last executed round index with `lnd_censored=True`. FND/HND are
`None` (→ NaN in CSV) if that event never occurs within the recorded rounds
at all (e.g. a short smoke run that ends before half the nodes die) — the
spec doesn't give a fallback value for "never happened," and `None` is more
honest than silently substituting a number that didn't actually occur.

## 8. `mean_residual_energy_final` (`metrics.py`)

Ambiguous whether this should count dead nodes as zero (the "_all" variant)
or exclude them (the "_alive" variant). Chose the "_all" variant (dead
nodes count as zero energy), matching the more common WSN-literature
convention for a single end-of-run residual-energy figure, and because
`mean_residual_energy_alive` on the very last recorded round is a less
useful comparison figure across protocols with very different death
timing.

## 9. `ops_per_round` (`metrics.py`) — SUPERSEDED, see item 17

The spec names this column but never defines it. Originally defined here as
the average number of data-packet send attempts (`packets_sent`) per
executed round (`packets_sent_total / n_rounds_executed`) — a rough
per-round workload indicator for profiling. This is a placeholder-quality
definition precisely because the spec gave no formula, flagged at the time
as something to "revisit if a specific meaning was intended."

**Superseded (Defect 3, item 17 below)**: that placeholder measured traffic
volume, not computational cost, which made it useless for the metric's
actual purpose — comparing algorithmic workload across protocols with wildly
different per-round computation (NSGA-II's fitness evaluations vs. LEACH's
coin flip). Redefined as a protocol-reported, engine-mediated COUNTED-ops
metric; see item 17 for the full reasoning and definition.

## 10. `mean_latency_ms` / `p95_latency_ms` at the summary level
(`metrics.py`)

Computed from the raw list of every delivered packet's latency across the
*whole run* (an `all_latencies` list accumulated internally by
`engine.run_single` and passed into `metrics.build_summary`), not as an
average of each round's `mean_latency_ms` column. Averaging per-round means
would silently over-weight low-traffic rounds; the raw-list approach is the
statistically correct one for both the mean and the p95.

## 11. Shadowing matrix construction (`network.py`)

Drawn as one `n x n` normal-distributed array from the topology rng, then
symmetrized by folding the lower triangle onto the upper (`shadow = tril(raw,
-1) + tril(raw, -1).T`), rather than scattering `n*(n-1)/2` draws into a
triangular index directly. This "wastes" half the random draws (the upper
triangle of the raw matrix is discarded) but is far simpler and still a
one-shot, once-per-topology cost (negligible even at `n_nodes=100`).
Fairness only requires that the *same* draw scheme be used for every
protocol at a given `run_index` — which order/method of scattering random
numbers achieves that is an implementation detail, not a spec requirement.

## 12. `Network` role array

`Network.role` is present (a placeholder integer array) but unused in Step
1 — `num_ch` and cluster membership are derived purely from each round's
`ClusterAssignment` object, not from any persisted mutable state on
`Network`. This avoids inventing role-encoding semantics the spec never
specified.

## 13. Read-only protocol access to `Network`

Protocols receive the real `Network` object (not a proxy/read-only view) —
enforced by documentation/convention (see docstrings in `network.py` and
`protocols/base.py`) rather than a wrapper class, per the "no plugin
systems, no speculative abstraction" constraint on this build. Only
`engine.py` ever calls `Network.spend`.

## 14. Determinism scope excludes wall-clock/memory-profiling fields
(`tests/test_engine.py`)

The determinism hard gate ("run the same (protocol, run_index) twice; per-
round records must be byte-identical") was tested by running
`run_single` twice and diffing every field. The only fields that ever
differed were `setup_time_ms` (per-round) and `total_runtime_s` /
`peak_memory_kb` / `mean_setup_ms` (summary) — real wall-clock timing and
allocator measurements of the run itself, which are inherently
non-reproducible to the microsecond/byte even with identical seeds (this
was directly confirmed: every other field, including energy, packet
counts, deaths, and latency, was exactly identical across both runs). The
determinism test therefore strips these four timing/memory fields before
comparing, and documents why here rather than silently expecting literal
wall-clock reproducibility, which no implementation could satisfy.

## 15. Defect 1 (CRITICAL) — `pdr_percent` corrected from packet-based to
reading-based (`engine.py`, `metrics.py`)

**Found broken, then corrected — the reasoning is preserved here, not just
the new formula.**

The original definition was
`pdr_percent = packets_received_bs_total / packets_sent_total * 100`. This
is a real ratio, but it measures the wrong thing once aggregation exists:
every CH-style fold of N source packets into 1 BS packet permanently
divides this ratio by (roughly) N, *regardless of whether every single
reading actually arrived*.

**Demonstration that forced the fix**: a single cluster of 10 nodes (9
members + 1 CH, all folding a fresh reading in every round), run with
`per_enabled=False` (a perfect channel — zero loss, by construction every
reading that is sent arrives) gave:

- `data_yield = 1.000` — correct: every reading taken was delivered.
- `pdr_percent = 10.00%` (old, packet-based formula) — because 10 source
  packets became 1 BS packet, and 1/10 = 10%.

That 10% has nothing to do with delivery — it is exactly the aggregation
fan-in ratio wearing a "delivery rate" label. Worse, it is *protocol-shape*
sensitive in a way that would silently masquerade as a *protocol-quality*
difference in the final results table: LEACH (shallow, ~1 CH per ~20 nodes)
would land around a few percent, PEGASIS (a long chain collapsing to one
packet at the BS) would land near 1%, and neither number would say anything
about which protocol actually gets more data through — only about how many
hops each protocol happens to fold data across.

**Fix**: PDR is now reading-based, so it is comparable across protocols with
different aggregation depth:

    pdr_percent = readings_delivered_total / readings_attempted_total * 100

`readings_attempted` (new per-round column, immediately before
`readings_delivered`; `readings_attempted_total` in the summary, immediately
before `readings_delivered_total`) counts an original sensor reading at the
moment it is INJECTED into the network — an alive node folding its own
fresh reading (`Transmission.originates=True`, see Defect 2 below) into a
packet it sends this round — regardless of whether that packet is later
lost. This is what makes it a genuine loss-rate denominator: a lost reading
still counts as attempted, so loss actually moves the ratio, unlike the old
formula where loss was invisible unless it happened to change the
aggregation topology.

Readings a protocol deliberately SUPPRESSES (TEEN/APTEEN below-threshold —
`originates=False` and no packet emitted at all for that node this round)
are correctly excluded from this denominator: suppression is intended
behaviour, not loss, and folding it in would make a protocol that
aggressively (and correctly) suppresses look artificially lossy. This is
exactly what keeps `pdr_percent` (a loss-rate metric) conceptually distinct
from `data_yield` (a "how much of everything sensed came through" metric),
whose denominator remains `alive_node_auc` — literally every reading TAKEN,
suppressed or not (see item 4 above) — unchanged by this fix.

Re-verified with the same perfect-channel setup, three ways (stub / one
10-node cluster / a 3-deep PEGASIS-like chain, hop_depth 1→2→3) in
`tests/test_engine.py::test_pdr_reading_based_perfect_channel_three_way`:
`pdr_percent == 100.0` exactly in all three, independent of aggregation
depth — this is now the standing regression guard against `pdr_percent`
ever becoming aggregation-sensitive again.

## 16. Defect 2 (FAIRNESS) — `Transmission.payload_readings` removed;
replaced by engine-computed `effective_readings` (`protocols/base.py`,
`engine.py`)

`Transmission.payload_readings` was protocol-supplied, which meant a
protocol could simply declare a bigger number and inflate its own apparent
`data_yield`/PDR — the same category of fairness bug that reading/packet
sizing and aggregation charging were already engine-owned to prevent (see
item 5 above: "the engine is the only code that spends energy, sizes
packets, and applies channel/aggregation rules").

**Fix**: `payload_readings` is gone. In its place, `Transmission.originates:
bool = True` records only the one fact that genuinely IS protocol logic —
"does this node fold its own fresh sensor reading into this packet?" (e.g. a
TEEN-style node legitimately sets `originates=False` on a round it
suppresses its own below-threshold reading while still relaying its
members' data unchanged). The ENGINE alone turns that boolean into a
reading count, per hop, as pure accounting the protocol cannot influence:

    effective_readings(t) = int(t.originates) + incoming_readings.get(t.src, 0)

`incoming_readings` is tracked in `engine._run_round` in exactly the same
place and the same shape as the pre-existing `incoming_bits` — incremented
by a delivered packet's `effective_readings` when that packet lands on its
destination. `readings_delivered` (per round) sums `effective_readings` only
for packets that reach the BS; `readings_attempted` (Defect 1) counts
`t.originates` at injection time, independent of delivery. Updated
`protocols/stub.py` and every test (`tests/test_engine.py`) accordingly —
`FakeAggProtocol`'s CH transmission now sets `originates=False` (it relays
its 2 members' readings only, contributing no reading of its own), which is
the same "2 readings delivered" outcome as before, now arrived at via
engine arithmetic instead of a protocol-declared number.

## 17. Defect 3 — `ops_per_round` redefined from traffic volume to counted
algorithmic workload (`protocols/base.py`, `engine.py`, `metrics.py`)

Item 9 above flagged the original `ops_per_round` definition
(`packets_sent_total / n_rounds_executed`) as a "placeholder-quality
definition precisely because the spec gave no formula." That placeholder
measured *traffic volume*, not *computational cost*, and this is one of the
nine headline metrics precisely BECAUSE it is supposed to carry the latter:
comparing NSGA-II (thousands of fitness evaluations per round) against
LEACH (a single per-node coin flip) on packet counts would show them as
identical in "ops" the moment they send the same number of packets, which
defeats the entire point of the metric.

**Fix**: `Protocol` gains an integer instance attribute `ops_this_round`,
reset to `0` by the ENGINE immediately before each `setup_round` call
(`engine._run_round`, right before `protocol.setup_round(...)` is invoked).
A protocol implementation increments it as it does work. The engine reads
`protocol.ops_this_round` back immediately after `setup_round` returns and
records it as the new per-round column `ops_count`; the summary
`ops_per_round` is the mean of `ops_count` across executed rounds.

What counts as one "op" is stated once, in `protocols/base.py`, so it means
the same thing across all nine protocols (the whole point of a
cross-protocol comparison metric): every node-pair distance computation,
every fitness/objective evaluation, and every neural-network forward pass —
nothing else (not loop iterations, not comparisons, not packet sends).
`StubProtocol` does no computation of any of those three kinds, so it
reports `ops_count == 0` every round and `ops_per_round == 0.0` — asserted
in `tests/test_engine.py::test_stub_ops_per_round_is_zero`.

**Scoping caveat — CORRECTED, see item 20**: an earlier version of this
engine read `ops_this_round` immediately after `setup_round` returned,
BEFORE `route` was called, discarding any ops a protocol counted inside its
own `route`. Flagged at the time rather than fixed unilaterally, since the
original spec wording was explicit about the read point. **Coordinator
ruling (item 20): fix it** — the read window is now widened to cover both
`setup_round` and `route`.

## 20. Defect 5 — `ops_this_round` read window widened to cover `route()`
too (`engine.py`, `protocols/base.py`)

Item 17 flagged (but did not fix) a real under-reporting bug: `ops_count`
was captured immediately after `setup_round` returned, before `route` ran.
Any protocol that does its distance/fitness/forward-pass counting inside
`route` instead of (or in addition to) `setup_round` would have that work
silently discarded the moment the counter reset at the top of the next
round — never read, never reported. This is exactly the kind of thing the
"nine protocols" caveat in item 17 warned about. LEACH (item 22) turns out
to decide CH election AND nearest-CH membership both inside `setup_round`
(membership must be finalized there, since `_charge_control_traffic` reads
`ClusterAssignment.member_of` before `route` ever runs), so LEACH alone
does not actually exercise this under-reporting bug — but the fix is made
unconditionally regardless, since the underlying defect (silently dropping
any future protocol's route()-side ops) is real independent of whether
LEACH happens to trigger it, and the remaining 7 planned protocols are not
yet known to be safe from it.

**Fix**: `protocol.ops_this_round` is now reset to 0 immediately before
`setup_round` (unchanged) and read back immediately after `route` returns
(moved from immediately after `setup_round`), in `engine._run_round`.
`setup_time_ms` is UNCHANGED — it still measures only the wall-clock time
of `setup_round` itself (the clustering decision), not `route`. Only the
`ops_count` read point moved. `protocols/base.py`'s docstring on
`ops_this_round` is updated to say both phases are counted.

## 18. Defect 4 (PERFORMANCE) — PER lookup tables precomputed once per
topology, not recomputed per packet per attempt (`network.py`, `engine.py`)

`radio.per(bits, d, shadow, cfg)` is a pure function of three things that
are all FIXED the moment a topology is built: the two possible bit counts
(`cfg.data_bits`, `cfg.ctrl_bits` — protocols never choose bit count, see
item 15 above), the static node-node/node-BS distances, and the static
per-link shadowing (drawn once in `Network.__init__`, see item 11 above —
nodes are static, so this never changes across rounds). The engine was
nonetheless calling `per()` fresh for every attempted transmission, every
retry attempt, every round — the actual `radio.ber`/`snr_db`/`path_loss_db`
chain (several `log`/`exp`/`clip` calls each) run again and again on inputs
that were already known at round 0.

**Fix**: `Network.__init__` now precomputes four lookup tables right after
`dist`/`dist_bs`/`shadow`/`shadow_bs` are built (no rng draws involved, so
this cannot perturb the fairness-critical seeding order documented at the
top of this file):

    per_data[i, j]    = per(cfg.data_bits, dist[i, j], shadow[i, j], cfg)
    per_ctrl[i, j]    = per(cfg.ctrl_bits, dist[i, j], shadow[i, j], cfg)
    per_data_bs[i]    = per(cfg.data_bits, dist_bs[i], shadow_bs[i], cfg)
    per_ctrl_bs[i]    = per(cfg.ctrl_bits, dist_bs[i], shadow_bs[i], cfg)

`engine._run_round`'s inner ARQ loop now indexes into these tables instead
of calling `per()` — and does so ONCE per transmission (hoisted out of the
per-attempt retry loop, where the old code was recomputing the identical
value on every retry too, an extra layer of the same waste).

**Exactness proof performed before accepting this**: captured the full
per-round records for `StubProtocol` at `n_nodes=100`, `max_rounds=300`,
`run_index=0` (default `per_enabled=True`) BEFORE this change, then re-ran
the identical scenario AFTER. Every simulated field across all 300 rounds
was bit-identical; the only field that ever differed was `setup_time_ms`
(real wall-clock timing of the round itself, already known to be
non-reproducible even under identical seeds — see item 14). Summary-level
fields matched exactly too, excluding the timing/memory fields item 14
already excludes.

**Timing**: ~45.4 ms/round before → ~22.0 ms/round after (~2.06x), measured
as the mean of 3 repeated runs of the same scenario.

**Remaining hotspot** (profiled, not touched — reported per instruction not
to speculatively rewrite anything beyond what was asked): `radio.e_tx` is
now the dominant cost (~46% of remaining per-round time in a `cProfile`
run), for the same underlying reason `per()` was slow — it wraps every
scalar call in `np.asarray`/`np.where`, which carries real per-call overhead
even for a single float. Unlike PER, `e_tx` is NOT purely static (it is
still a function of `d` alone, which IS static per link, but the amount
`bits` charged only takes two fixed values, same as PER) — the same
lookup-table strategy would very likely apply here too (e.g.
`e_tx_data[i,j]`/`e_tx_data_bs[i]`/`e_tx_ctrl[i,j]`/`e_tx_ctrl_bs[i]`,
mirroring the four PER tables), but that wasn't part of the requested fix
and is flagged here for a decision rather than implemented speculatively.
`SimConfig.d0`/`.tx_time_ms`/`.slot_ms` being recomputed `@property`s on
every access (tens of thousands of times per run) also showed up as a minor
but real line item in the profile.

## 19. `packets_sent` / `control_packets` scope

`packets_sent` (per-round CSV column) counts only `kind == 'data'`
Transmissions attempted by their source node (once per packet, not per
retry) — it does not include control packets, which have their own
separate `control_packets` counter from `_charge_control_traffic`. A
`kind == 'ctrl'` Transmission returned by a protocol's own `route()` (if
any protocol ever does that, none does in Step 1) would go through the ARQ
loop and be charged energy, but is not counted in either `packets_sent` or
`control_packets` — this is an unlikely/unused path in Step 1 and is flagged
here rather than silently defined away.

## 21. Defect 6 (PERFORMANCE) — `e_tx`/`e_rx` lookup tables precomputed,
`SimConfig.d0`/`.tx_time_ms`/`.slot_ms` cached (`network.py`, `engine.py`,
`config.py`)

Item 18's "remaining hotspot" note flagged (but did not fix, per
instruction not to speculatively rewrite beyond the requested fix) that
`radio.e_tx` was profiled at ~46% of remaining per-round time after the PER
precompute, for the same underlying reason `per()` was slow: every call
wraps a scalar in `np.asarray`/`np.where`, real per-call overhead even for
one float. `e_tx(bits, d, cfg)` is static for the identical reason PER is
static — `bits` is always one of two fixed `cfg` constants, `d` is a static
per-link distance fixed once the topology is built — so the same
lookup-table strategy applies directly.

**Fix**, mirroring the four PER tables exactly: `Network.__init__` now also
precomputes `e_tx_data[i,j]`, `e_tx_ctrl[i,j]`, `e_tx_data_bs[i]`,
`e_tx_ctrl_bs[i]`, plus `e_rx_data`/`e_rx_ctrl` as two plain Python floats
(e_rx has no distance dependence, so a table would be pointless — same
value for every link). `engine._run_round`'s ARQ loop now indexes into
these instead of calling `e_tx()`/`e_rx()`, hoisted out of the per-attempt
retry loop exactly like the PER lookup already was (same value every
retry). `engine._charge_control_traffic` was updated the same way: the
zero-member-CH case now uses a precomputed scalar `Network.e_tx_ctrl_zero`
(`e_tx(ctrl_bits, 0.0, cfg)`, a single constant — no node pair to index by
at d=0), and the ADV/SCHEDULE farthest-member broadcast now looks up
`e_tx_ctrl[ch, farthest_idx]` (the farthest member's *index*, not just its
distance, is now tracked so the table can be indexed) instead of calling
`e_tx(ctrl_bits, farthest_d, cfg)`. Neither table precompute consumes any
rng draws, so the fairness-critical seeding order is unaffected.

Also fixed the config-side line item from the same profile:
`SimConfig.d0`/`.tx_time_ms`/`.slot_ms` were plain `@property`s recomputed
(sqrt / division / property-chain) on every access — tens of thousands of
times per run (`d0` inside every `e_tx` table build and inside `radio.e_tx`
generally; `tx_time_ms`/`slot_ms` once per delivered BS packet for the
latency formula). Changed to `functools.cached_property`: each value is
computed once and cached in `instance.__dict__` on first access.
`cached_property.__get__` writes directly into `instance.__dict__` rather
than going through `setattr`, so this is safe on a frozen dataclass (frozen
only blocks `setattr`, and `SimConfig` has no `__slots__`, so it still has a
normal `__dict__` for `cached_property` to use) — confirmed by hand:
`SimConfig().__dict__` shows `d0`/`tx_time_ms`/`slot_ms` populated after
first access.

**Exactness proof performed before accepting this**, identical protocol to
item 18: captured the full per-round records for `StubProtocol` at
`n_nodes=100`, `max_rounds=300`, `run_index=0` (default `per_enabled=True`)
BEFORE this change, then re-ran the identical scenario AFTER. Every
simulated field across all 300 rounds was bit-identical (verified via a
direct dict-equality diff, not just eyeballing); the only fields that ever
differed were the wall-clock/memory fields item 14 already excludes
(`setup_time_ms` per-round; `total_runtime_s`/`peak_memory_kb`/
`mean_setup_ms` in the summary). All of `tests/test_radio.py`,
`tests/test_channel.py`, and `tests/test_engine.py` (including the existing
determinism hard gate) still pass unchanged after this fix.

**Timing**: measured as the mean of 3 repeated runs of the same scenario
(`n_nodes=100`, `max_rounds=300`, `run_index=0`, `StubProtocol`, default
`per_enabled=True`) on the same machine used for item 18's measurement:
~19.8 ms/round before → ~11.1 ms/round after (~1.8x further speedup on top
of item 18's PER-table fix; ~4.1x versus the pre-item-18 baseline of ~45.4
ms/round).

## 22. LEACH (Heinzelman et al. 2000) — first real clustering protocol
(`protocols/leach.py`)

See the module docstring in `protocols/leach.py` for the full citation and
exactly what was implemented / where it deviates from the original paper.
Notable engine-interaction decisions made here, not in the paper itself:

- **CH count is stochastic by design, never clamped.** The standard
  threshold `T(n)` makes the realized per-round CH count fluctuate around
  `p * N`; forcing an exact count would be a different (deterministic)
  algorithm, not LEACH. `tests/test_leach.py` asserts the *mean* over a full
  run lands in a loose plausible band and that the per-round count actually
  varies (proving the election is genuinely stochastic), not that any
  single round hits a target.
- **Zero-CH rounds** are a legitimate, unforced outcome of the threshold
  draw (more likely at low `p` / small `N`): every alive node becomes a
  self-head and sends directly to the BS that round. No node is
  force-elected to avoid this.
- **`slot_index` for the CH→BS hop is `len(members)`, not `0`.** The CH can
  only transmit its aggregated packet after every member's TDMA slot has
  elapsed, so pricing its own send at slot 0 would understate its latency
  and make LEACH look artificially fast — this is the mechanism by which
  LEACH's latency grows with cluster size, and getting it wrong would
  quietly corrupt `mean_latency_ms`/`p95_latency_ms`, two of the nine
  headline metrics.
- **`ops_this_round` is incremented during `setup_round`, not `route`** —
  the reverse of what might be expected. Nearest-CH membership assignment
  (the `(alive non-CH nodes) x (CHs)` distance comparisons being counted)
  has to be fully decided inside `setup_round`, because
  `engine._charge_control_traffic` reads the returned
  `ClusterAssignment.member_of` before `route` is ever called — membership
  cannot be deferred to `route` without desyncing the control-traffic
  charges (ADV/JOIN-REQ/SCHEDULE audiences and the farthest-member
  distance) from the membership `route` would otherwise use. `route` here
  only turns the already-decided assignment into concrete `Transmission`s
  and adds no further ops. (See item 20's note: LEACH does not actually
  need the widened read window for this reason, though the fix stands on
  its own merits for future protocols.)
- LEACH charges no energy and sizes no packet directly (per the "engine
  owns all of that" rule) — the engine's existing uniform
  `_charge_control_traffic` already prices LEACH-style ADV/JOIN-REQ/
  SCHEDULE control traffic without any protocol-specific code.

## 23. Per-protocol control-traffic models (`engine.py`, `protocols/base.py`)

Applying LEACH-shaped ADV/JOIN-REQ/SCHEDULE control traffic uniformly to
every protocol (as Step 1 did, when LEACH was the only protocol) is wrong
once chain-based and centralized protocols exist — they do not run an
ADV/JOIN handshake at all. `Protocol` gains a class attribute
`control_model: str` (`"distributed" | "chain" | "centralized"`, default
`"distributed"`), and `engine._charge_control_traffic` is now a thin
dispatcher (`_charge_control_distributed` / `_charge_control_chain` /
`_charge_control_centralized`) keyed on it. The ENGINE still makes every
joule/bit/audience decision in all three models — a protocol only declares
which model applies and exposes the structural facts (chain order, rebuild/
recluster flags) the chosen model needs to price. This mirrors the existing
rule that protocols never call `net.spend` or choose a bit count.

- **`"distributed"`** (LEACH, TEEN, APTEEN): byte-identical to the original
  ADV → JOIN-REQ → SCHEDULE sequence. TEEN/APTEEN additionally set a new
  `Protocol.extra_ch_broadcasts: int` (1 for both) — the HT/ST/TC threshold
  announcement — charged `extra_ch_broadcasts` times per CH, each priced
  identically to the SCHEDULE step (farthest-member distance E_tx, members-
  only E_rx audience). The engine reads this count off the protocol; it is
  never hardcoded to a protocol name.
- **`"chain"`** (PEGASIS): no ADV/JOIN/SCHEDULE at all. The protocol exposes
  `self.chain` (ordered node-index tuple) and `self.chain_rebuilt_this_round:
  bool`. Each of the `len(chain) - 1` consecutive links pays one E_tx(ctrl,
  d_hop) at the sender and one E_rx(ctrl) at the receiver (the leader-token
  hand-off). On a rebuild round, the BS broadcasts the new chain/leader
  order once (priced as 1 control packet, mirroring how 1 ADV broadcast is
  counted regardless of receiver count); every alive node pays E_rx(ctrl),
  the BS pays nothing (mains-powered).
- **`"centralized"`** (NSGA-II, Fuzzy-T2, and any later BS-side clustering
  protocol — SOM/DQN/GCN are named as future candidates): the BS computes
  cluster structure, so there is no ADV and no JOIN-REQ. The protocol
  exposes `self.reclustered_this_round: bool`. Uplink node-state (energy,
  position-derived features, etc.) is **piggybacked on data traffic already
  being sent and charged nothing** — seeding a genuinely separate node→BS
  status-report packet would be a modelling artifact, not a fair reflection
  of the protocol's own clustering cost:
      - a 200-bit status report at a representative >100 m node-to-BS
        distance falls on the d^4 multipath branch, costing
        `bits*e_elec + bits*eps_mp*d^4 = 200*50e-9 + 200*0.0013e-12*100^4
        ≈ 3.6e-5 J/node/round`;
      - over the full 7000-round cap that is `≈0.25 J`, roughly **25% of
        the entire 1 J initial energy budget** (`cfg.e0`), paid every round
        purely for reporting overhead that has nothing to do with whether
        the clustering decision itself is good;
      - charging that to every centralized protocol would sink NSGA-II and
        Fuzzy-T2's lifetime numbers for a reason unrelated to their
        clustering quality, so it is charged as free piggyback traffic on
        top of data packets that are already being sent regardless.
  On a `reclustered_this_round` round, the BS broadcasts the new assignment
  once (1 control packet, every alive node pays E_rx(ctrl), BS pays
  nothing). EVERY round (recluster or not), each CH still broadcasts its
  own TDMA schedule — same pricing as the distributed model's SCHEDULE step,
  including the zero-member-CH skip.

**Centralized protocols in this build**: NSGA-II (`protocols/nsga2.py`) and
the interval type-2 fuzzy controller (`protocols/fuzzy_t2.py`) are
centralized because the BS runs the entire selection algorithm (a
multi-objective GA / a fuzzy inference system) over globally-known node
state and dictates cluster heads and membership to the network — no node
makes an autonomous CH-election decision the way LEACH/TEEN/APTEEN nodes
do. Any later neural-scoring protocol (SOM/DQN/GCN) that likewise has the
BS run inference over global state and announce the result belongs in this
same category.

## 24. PEGASIS (Lindsey & Raghavendra 2002) — first `"chain"` protocol
(`protocols/pegasis.py`, `engine._charge_control_chain`)

See the module docstring in `protocols/pegasis.py` for the full citation
and paper-vs-implementation deviation list. Notable engine-interaction
decisions:

- **Whole-chain rebuild, not local repair, on any death.** The paper
  permits patching only the two links broken by a dead node; this build
  always reruns the full O(n^2) greedy nearest-neighbor construction
  instead. Simpler, and no less correct (same greedy chain, just
  recomputed globally) — flagged rather than silently narrowing the
  paper's repair strategy. `chain_rebuilt_this_round` is `True` exactly on
  rounds where the alive count dropped since the last build (and on the
  very first round PEGASIS runs), which is what the engine's `"chain"`
  control model prices the BS rebuild-broadcast against.
- **`hop_depth = position-from-chain-end + 1` on both inbound directions,
  leader's own BS hop always deepest.** This falls directly out of the
  chain structure (position `pos`'s only inbound packet is position
  `pos-1`'s, already proven to be `hop_depth = pos`), so the engine's
  `(hop_depth, src)` execution order and enforced-aggregation rule (see
  item 5) apply to a chain exactly as they already did to LEACH-style
  stars, with no chain-specific carve-out needed anywhere in `engine.py`.
- **`slot_index` is always 0.** PEGASIS has no TDMA frame; `hop_depth`
  alone drives `mean_latency_ms`/`p95_latency_ms` via the existing latency
  formula (`slot_index * slot_ms + hop_depth * (tx_time_ms + proc_ms)`).
  This is exactly the mechanism that makes PEGASIS's latency scale with
  chain depth and come out HIGHER than LEACH's — the intended energy/
  latency trade-off the paper is known for, confirmed empirically in
  `tests/test_protocols.py`.
- The chain-control-traffic model (`engine._charge_control_chain`) is a new
  THIRD `control_model` alongside `"distributed"`; see item 23.

## 25. TEEN (Manjeshwar & Agrawal 2001) (`protocols/teen.py`)

See the module docstring for the full citation and deviation list. The one
decision worth calling out again here: **"a CH forwards iff ... ≥1 member
packet was delivered to it" is implemented as "... was ATTEMPTED this
round,"** not "successfully received through the channel." `route()` must
return the whole round's `Transmission` list before the engine draws ANY
channel outcome, so "was this member packet successfully delivered" is not
a fact TEEN's `route()` can causally condition its own forwarding decision
on — only "did a member decide to send something" is available at that
point. The engine still charges/aggregates strictly on what is actually
delivered afterward; only the CH's decision of WHETHER to attempt its own
forward this round uses "attempted," not "delivered."

TEEN reuses `LEACHProtocol.setup_round` unchanged (subclassing, not
reimplementing) — clustering is identical to LEACH; TEEN's only
contribution is the reactive HT/ST reporting gate inside `route()`.
`extra_ch_broadcasts = 1` (the HT/ST threshold announcement) is declared
as a class attribute and priced uniformly by
`engine._charge_control_distributed` — TEEN never touches energy itself.

`tests/test_protocols.py` confirms TEEN sends strictly fewer data packets
than LEACH on the identical run_index/sensed stream (same topology, same
sensor readings, same channel model — only the reporting decision
differs), and that TEEN may run uncensored to the round cap at default
`cfg.ht`/`cfg.st` — expected, not tuned around.

## 26. APTEEN (Manjeshwar & Agrawal 2002) (`protocols/apteen.py`)

Subclasses `TEENProtocol`, overriding only `_wants_to_send` to add the
Count-Time (`cfg.tc`) force-send clause on top of TEEN's HT/ST gate — every
other method (clustering, routing shape, control-traffic declarations) is
inherited unchanged. A node that has never transmitted is treated as
"overdue since round -1," so it force-sends by round `cfg.tc - 1` at the
latest even if it never once crosses HT. Out of scope: the paper's
broader query mechanism (historical/one-time/attribute-based queries) —
this simulator has no query channel, only periodic sensing and reporting,
so only the reporting-FREQUENCY half of APTEEN (HT/ST reactive gate + TC
periodic override) is modeled. Confirmed in `tests/test_protocols.py`:
APTEEN sends strictly more data packets than TEEN (periodic force-sends
add traffic TEEN would have suppressed) and strictly fewer than LEACH
(which sends unconditionally every round).

## 27. NSGA-II (Deb et al. 2002) (`protocols/nsga2.py`)

See the module docstring for the full citation, objective definitions, and
genetic-operator definitions. Two implementation notes worth recording
here:

- **Performance**: the textbook-straightforward pure-Python double loop
  for fast non-dominated sort (calling a python `_dominates(a,b)` per pair)
  profiled as the dominant per-generation cost at `pop_size=40` — roughly
  80% of `_run_ga`'s wall-clock time. Rewritten to compute the full
  pairwise domination matrix with one vectorized numpy comparison
  (`obj[:,None,:] <= obj[None,:,:]` etc.) instead of `pop^2` individual
  Python-level calls; same sort semantics (verified: front membership and
  ranks unchanged), roughly 3x faster end to end. `_evaluate` similarly
  defers building the `member_of` dict (only needed for the ONE individual
  that ultimately wins the knee-point selection) until after the GA
  finishes, instead of building and discarding it for every one of the
  ~1240 individuals evaluated per reclustering.
- **`f2`/`f3` are not independently informative at round 0** (all nodes
  share the same starting energy, so `f2` is degenerate until the network
  heterogenizes through use; `f3`, cluster-size std, is a genuinely
  competing objective against `f1` and is NOT expected to improve
  monotonically generation-over-generation on its own — only the combined
  Pareto FRONT is guaranteed non-worsening under elitist `(mu+lambda)`
  survival, not every individual objective of whichever solution happens
  to be the current generation's knee point, since the knee point itself
  is a relative pick that can shift between differently-shaped fronts).
  `tests/test_protocols.py` checks convergence via `f1` (the round-energy
  objective), which decreases from generation 0 to generation 29 in
  practice, and logs the full per-generation triple to
  `results/validation/nsga2_convergence.csv` for direct inspection.

## 28. Interval Type-2 Fuzzy (`protocols/fuzzy_t2.py`)

See the module docstring for the full citation, the reproduced 27-rule
table, and the exact Karnik-Mendel type-reduction procedure implemented.
Two normalization choices not fully pinned down by the spec, decided here:

- Residual energy is normalized against each node's OWN
  `initial_energy` (not the global `cfg.e0`), so the score still means
  "fraction of my own starting budget left" if heterogeneity
  (`cfg.het_enabled`) is ever turned on.
- Distance-to-BS is normalized against the STATIC, all-node maximum
  `net.dist_bs.max()` (fixed once the topology is built), not a
  per-round alive-only maximum — this keeps the denominator stable across
  rounds instead of silently rescaling every node's distance score as
  far-away nodes happen to die.

Fuzzy-T2 shares its re-clustering cadence (`cfg.ga_interval`) and
carry-forward-between-reclusterings logic (drop dead CHs, rejoin nearest
surviving CH, else self-head) with NSGA-II verbatim — both are
`control_model = "centralized"` and both are meant to be compared on equal
re-clustering footing.

## 29. DQN (`protocols/dqn.py`, `scripts/train_dqn.py`) — reward/horizon fix,
value-divergence fix, and the FINAL verdict vs. random CH rotation

This is the closing entry on DQN tuning; the pre-registered stopping rule
(decided before this run, see below) says the result recorded here is final
regardless of outcome.

**History of two distinct, sequential defects, both a-priori specification
errors rather than a wrong-gradient bug** (the gradient check in
`tests/test_nn.py` was clean throughout):

1. **Reward/horizon mismatch.** The original spec used `gamma=0.95`
   (effective horizon ~20 rounds) with a reward dominated by
   `-(E_round/E_REF)` (minimize THIS round's energy). FND happens at round
   ~1000-2000, 50x past that horizon, so the agent was structurally blind to
   the outcome it was judged on, and the dominant reward term actively
   taught CH concentration near the BS (cheapest way to cut this round's
   energy), the opposite of lifetime extension. Fixed by `gamma=0.999`
   (~1000-round horizon) and replacing the reward's cluster-size-std term
   with a residual-energy-std term (weight 2.0), which directly rewards the
   even energy distribution FND measures.
2. **Value divergence (deadly triad).** Even after fix (1), the 30-episode
   learning curve produced under that reward/horizon combination showed
   textbook divergence: loss fell early, then rose again before training
   ended, and total reward degraded rather than improved episode-over-
   episode. With `gamma=0.999` and ~2000-2700-round episodes, undiscounted
   return magnitude reaches `1/(1-gamma)=1000x` a single step's reward, so Q
   targets can grow far faster than the 4-16-2 network's ability to track
   them — bootstrapping + function approximation + off-policy replay, the
   classic three ingredients.

**Fix (2): three stabilizers plus one training-adequacy change**, applied
together in `scripts/train_dqn.py`:

  (a) **Reward standardization** — a running (Welford) mean/std of observed
      raw rewards (`RunningNormalizer`) standardizes every reward before it
      enters the replay buffer / TD target. Rescales the value function by a
      (slowly-converging) constant; does not change which action has higher
      Q, hence not the optimal policy. Raw reward is still what is summed
      into the logged `total_reward`, so the curve stays comparable
      pre/post-fix.
  (b) **TD-target clipping (±20, standardized-reward scale) and global-norm
      gradient clipping (max norm 10.0)** — bound how far one bad
      bootstrap/minibatch can drag the online network.
  (c) **Training extended 30 -> 100 episodes** (seeds 100..129 cycled,
      disjoint from both the evaluation seeds 0..29 and the holdout guard
      seeds 130..134), with epsilon decay rescaled to still anneal
      1.0 -> 0.05 across the new episode count.

**Which of these were actually needed — evidence from controlled 30-episode
ablations** (same seeds 100-129, same reward, same everything else; only
reward-standardization and clipping toggled on/off, run to isolate credit;
these ablations are diagnostic-only, run outside the repo, and did not
touch the frozen weights/CSV that ships in this repo):

| variant                        | mean_loss trend (ep0→ep29)              | targets exceeding ±20 (would-clip fraction, late training) |
|---------------------------------|------------------------------------------|---------------------------------------------------------|
| neither fix (the original bug) | 0.08→0.29→falls to 0.04, reward worsens ep0 -1450.9 → ep29 -1745.7 | ~76-80% of minibatch targets |
| reward-norm ONLY (no clipping)  | 0.6-0.8 (ep1-15) then RISES to 1.2-1.8 (ep22-29) — still diverges | grows 0% → 42% |
| clipping ONLY (no reward-norm)  | falls monotonically to 0.01-0.02 — looks great, is not: | 70-80% of targets hit the clip every episode by ep15+ (saturation, not convergence) |
| BOTH together                   | bounded 0.6-1.0 the whole run, no drift  | 0% most episodes, brief peak ~11% (ep21-24), a rare safety net as designed |

Conclusions:
- **Reward standardization and TD-target/grad clipping are both
  load-bearing; neither alone reproduces the stability of having both.**
  Standardization alone still diverges once the bootstrap term outgrows the
  reward scale (42% would-clip by ep29). Clipping alone "converges" only by
  saturating against the clip boundary on the large majority of updates —
  a flattering loss curve masking, not fixing, the underlying value blowup.
- **Extending 30 → 100 episodes is not itself what fixes the divergence** —
  the "both" ablation is already stable within 30 episodes. It is a
  training-adequacy decision (more topologies seen before freezing a
  4-feature scoring function), matching the concern already on record in
  `scripts/train_dqn.py` that 30 episodes is thin. The epsilon-decay
  rescaling is bookkeeping consequent to that episode-count change, not an
  independent stabilizer.
- The full, canonical 100-episode run (all four measures active,
  reproduced byte-identically across two independent executions of
  `scripts/train_dqn.py`, confirming determinism) keeps `mean_loss` bounded
  in roughly 0.5-1.2 for the entire 100 episodes (one ep0 outlier at 3.15,
  then settles) with no monotonic rise — see
  `results/validation/dqn_learning_curve.csv`. This is a materially
  different shape from the pre-fix 30-episode curve (loss fell to 0.039 by
  episode 21, then rose to 0.212 by episode 29; total reward degraded
  monotonically -1446 → -2091).

**Final verdict — frozen greedy DQN vs. random CH rotation, 5 held-out
seeds (130-134, disjoint from training 100-129 and evaluation 0-29):**

| eval_seed | frozen_greedy_fnd | random_baseline_fnd |
|-----------|-------------------|----------------------|
| 130       | 1457              | 1222                 |
| 131       | 1534              | 1116                 |
| 132       | 1504              | 1249                 |
| 133       | 1508              | 1124                 |
| 134       | 1435              | 1170                 |
| **mean**  | **1487.6**        | **1176.2**           |

DQN wins on 5/5 held-out seeds, mean FND +26.5% over random rotation. This
is the reverse of the pre-divergence-fix result on the same 5 seeds (frozen
greedy mean FND 773 vs. random mean FND 1176, DQN losing by ~34%) — i.e.
the win comes from removing the numerical defect (divergence), not from
retuning the reward, architecture, or feature set, which were fixed before
this defect was even diagnosed and were not touched again here.

**Pre-registered stopping rule (decided before this run):** this is the
last iteration on DQN. The result above — DQN beats random rotation — is
reported as-is. No further reward function, architecture, feature set, or
hyperparameter change will be attempted to alter this outcome, win or lose,
per the pre-commitment against tuning a protocol until it wins.

---

## 30. GCN concentrates cluster-head duty; FND is its weak point, not its lifetime

Measured, not assumed. Over a real 400-round run on seed 0 (energy feedback
live, so scores do respond to depletion), counting how many CH slots each
node served out of 2000 total:

| protocol | distinct nodes ever CH | busiest node's CH slots | uniform share |
|---|---|---|---|
| LEACH | 100 | 20 | 20 |
| GCN | 79 | 106 | 20 |

LEACH's epoch mechanism rotates CH duty perfectly by construction: every node
serves exactly 20 times. GCN over-serves its favourites by ~5x and never uses
21 of the 100 nodes at all.

The consequence shows up in the lifetime metrics as a split verdict, and the
split is the interesting result:

| protocol | FND | HND | LND |
|---|---|---|---|
| GCN | 294 | 1843 | 3251 |
| LEACH | 1040 | 1698 | 2158 |

GCN's *first* death is 3.5x earlier than LEACH's, while its half- and
last-death are both **later**. It is not a worse protocol overall — it is a
protocol that sacrifices a handful of structurally-favoured nodes and then
runs the survivors very efficiently.

Per-run FND is bimodal (448, 394, 418, 112, 98 on seeds 0-4), so on two of
five topologies some node is drained almost immediately. Never report GCN's
mean FND without that spread.

**Why this is the expected result, not a bug.** GCN is trained on a
single-round energy-balance objective and has no temporal credit assignment
(`docs/METRICS.md`, and the Q8 rationale in the plan): it cannot represent
"sacrifice this round to extend lifetime." Its `rounds_since_last_CH` input
lets it *see* rotation state, but nothing in its loss rewards using it. DQN,
with the same four input features and γ=0.999, has exactly that temporal
machinery — and posts the most consistent FND of any protocol here
(1404-1530 across five seeds, spread of 126 rounds vs. GCN's 350).

This is the intended clean contrast: **GCN = spatial/structural reasoning,
DQN = temporal/sequential reasoning.** The FND gap between them is the
clearest single measurement of what temporal credit assignment buys.

---

## 31. Timing and memory cannot be measured in the same run

`run_single` originally wrapped the whole run in `tracemalloc.start()` while
measuring `setup_time_ms` inside it. tracemalloc intercepts every allocation,
and its overhead grows as traced blocks accumulate, so the reported
`mean_setup_ms` was a function of how many small objects a protocol allocated
rather than how much work it did.

Diagnosed by timing an identical synthetic NumPy loop inside and outside the
engine: **119 ms before the run, 455 ms then 712 ms during it (growing), 174 ms
after.** SOM's `_train` took 190 ms standalone and 1600 ms inside the engine
for byte-identical work.

Measured inflation, same seed, same 200 rounds, `mean_setup_ms`:

| protocol | honest (ms) | under tracemalloc (ms) | inflation |
|---|---|---|---|
| pegasis | 0.020 | 0.133 | 6.7x |
| leach | 0.607 | 4.130 | 6.8x |
| teen | 0.574 | 4.451 | 7.8x |
| apteen | 0.586 | 3.759 | 6.4x |
| dqn | 0.355 | 1.461 | 4.1x |
| gcn | 0.819 | 2.881 | 3.5x |
| fuzzy_t2 | 3.406 | 19.702 | 5.8x |
| som | 30.314 | 220.483 | 7.3x |
| nsga2 | 69.634 | 259.216 | 3.7x |

**The inflation is non-uniform (3.5x-7.8x), so it distorted the ranking, not
just the scale.** Two concrete inversions:

- **GCN vs. LEACH/TEEN/APTEEN.** GCN's true setup cost is ~35% *higher* than
  LEACH's (0.819 vs 0.607). Under tracemalloc it read ~30% *lower* (2.881 vs
  4.130), and lower than TEEN and APTEEN too. The sign of the comparison flipped.
- **SOM vs. NSGA-II.** Honest ratio 2.30x (69.6 / 30.3). Traced ratio 1.18x.
  tracemalloc made SOM look nearly as expensive as NSGA-II when it is less than
  half the cost.

**Resolution.** `run_single(..., measure_memory=False)` by default: no
tracemalloc, honest timing, `peak_memory_kb = NaN`. With `measure_memory=True`,
tracemalloc runs and `total_runtime_s` / `setup_time_ms` are set to NaN instead.
`run_experiments._one` sets it only for `run_index == 0`, so each protocol gets
one memory sample and `n_runs - 1` clean timing samples. The aggregator's
`pd.to_numeric(errors='coerce')` + `.mean()` skips NaN, so no summing logic
changed. Note `peak_memory_kb_std` is NaN with a single sample.

This changes no simulation result: tracemalloc affects wall-clock only, never
energy, lifetime, or delivery. Every previously reported lifetime and
throughput number stands. Only the `mean_setup_ms` and `total_runtime_s`
columns in `results/checkpoint2/` and `results/checkpoint3/` are invalid, and
those runs predate the fix.

---

## 32. The centralized FND advantage over LEACH is a retry-energy effect, and
the ideal-channel sweep is what proved it

The lossy/ideal sensitivity pair was justified in the plan as a guard against
`Pt` (item A2 of `docs/TRADEOFFS.md`). On the full 30-run sweep it earned its
keep: it caught a conclusion that does not survive the switch.

Paired permutation test on FND against LEACH, 30 paired topologies,
Holm-corrected (`results/analysis/paired_tests_*.csv`):

| protocol | lossy delta | lossy p | ideal delta | ideal p |
|---|---|---|---|---|
| fuzzy_t2 | +417 | <0.001 | +17 | 0.12 (n.s.) |
| dqn | +426 | <0.001 | +22 | 0.12 (n.s.) |
| nsga2 | +827 | <0.001 | +482 | <0.001 |
| pegasis | +542 | <0.001 | +188 | 0.009 |
| som | -87 | 0.0015 | -399 | <0.001 |
| gcn | -710 | <0.001 | -1140 | <0.001 |

Fuzzy T2 and DQN beat LEACH on first-node-death **only when the channel loses
packets.** NSGA-II and PEGASIS keep a real (if reduced) advantage on both.

**Mechanism, measured rather than inferred.** `net.consumed` already breaks
energy out by category, and `retry` is one of them (added for the conservation
identity under ARQ, item 21). Probing one seed over 1100 rounds, with mean
CH-to-BS distance captured from each round's `ClusterAssignment`:

| protocol | retry % of energy | ctrl % of energy | mean CH->BS | total J |
|---|---|---|---|---|
| leach | 6.39 | 12.73 | 101.8 m | 68.02 |
| som | 5.28 | 2.38 | 102.8 m | 55.79 |
| fuzzy_t2 | 3.65 | 2.33 | 85.6 m | 58.09 |
| nsga2 | 3.57 | 2.46 | 94.2 m | 54.46 |
| dqn | 2.31 | 3.95 | 81.1 m | 56.44 |
| gcn | 2.25 | 3.85 | 77.2 m | 55.41 |

`d0 = 87.706 m`. **LEACH's average cluster head sits at 101.8 m, past the
crossover and onto the `d^4` multipath branch; DQN's sits at 81.1 m, inside the
`d^2` free-space branch.** LEACH consequently spends 6.4% of its whole budget on
retransmissions against DQN's 2.3%. Removing channel loss removes that 4-point
penalty, and with it the entire FND gap.

Two things follow, and both belong in the write-up rather than being smoothed
over:

- The defensible claim is **not** "the fuzzy/learned protocols cluster better."
  It is that they keep the CH-to-BS hop inside the free-space regime, which pays
  off strictly in proportion to how lossy that hop is. At a higher `Pt` the
  advantage would shrink further.
- **LEACH's rotation is the better mechanism on its own terms.** It consumes 20%
  more total energy than DQN over the same 1100 rounds and still matches its FND
  on the ideal channel, because the epoch rule rotates CH duty perfectly (every
  node exactly 20 times per epoch, item 30's table) and perfectly even rotation
  is near-optimal for *first* death specifically. Notably SOM, which has the same
  CH-to-BS distance problem as LEACH (102.8 m) without LEACH's rotation
  guarantee, loses to LEACH on FND in both channels.

**The flip is specific to FND — do not overstate it.** Checked before reporting:
on `alive_node_auc` (the censoring-robust whole-trajectory summary) and on
`readings_delivered_total`, EVERY protocol's difference from LEACH is significant
at p < 0.001 in BOTH channels, in the same direction, with similar magnitude:

| vs LEACH | AUC lossy | AUC ideal | readings lossy | readings ideal |
|---|---|---|---|---|
| fuzzy_t2 | +24,793 | +22,120 | +28,822 | +22,365 |
| dqn | +24,966 | +22,538 | +26,872 | +22,546 |
| nsga2 | +33,484 | +31,691 | +33,245 | +32,235 |
| pegasis | +49,226 | +44,496 | +35,564 | +44,184 |

So the accurate claim is: **Fuzzy T2's and DQN's advantage over LEACH in overall
survival and in data delivered is robust to the channel; only their advantage in
FND specifically is not.** That is itself an instance of item A4 in
`docs/TRADEOFFS.md` — FND is a single order statistic and is the most fragile of
the lifetime measures. It is the metric most often reported alone in this
literature, which is exactly why this matters.

Rank stability across the two channels is otherwise high: only 4 of 40
protocol-metric ranks move (`results/analysis/channel_robustness.csv`), and both
moving pairs are near-ties — fuzzy_t2/som on HND, and fuzzy_t2/dqn on readings
delivered (196,139 vs 196,321, a 0.09% margin).
