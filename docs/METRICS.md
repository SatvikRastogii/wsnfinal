# Metric definitions

Every metric below is computed in `wsn_sim/metrics.py` from the per-round records the engine
produces. Ambiguous metrics are how comparative studies go wrong, so each definition is pinned down
here and in code, and the known interpretation traps are stated rather than left for the reader to
fall into.

## Lifetime

| Metric | Definition |
|---|---|
| `fnd` | Round index of the first node death. |
| `hnd` | Round index at which cumulative deaths first reach `ceil(N/2)`. |
| `lnd` | Round index at which all nodes are dead. If the `max_rounds` cap is reached first, `lnd` records the cap and `lnd_censored = True`. |

Granularity is end-of-round: the engine records `alive_nodes` per round, so a death is attributed to
the round in which it is first observed, not to a sub-round instant.

**Censoring.** A censored `lnd` is a lower bound, not a measurement. Never average it into a mean
without reporting `n_censored_runs` alongside. Reactive protocols (TEEN especially) are expected to
censor at the 7000-round cap — that is a real property of suppression, not a simulation failure.

**FND and LND can rank protocols differently, and neither is "the" lifetime.** Measured directly in
this simulator: LEACH reaches FND at ~1040 rounds versus ~112 for direct-to-BS transmission (a ~9×
improvement), but LEACH's LND is *earlier* (~2158 vs ~3271). The cause is geometric, not a defect:
36 of the 100 nodes lie within `d0` of the base station and are individually cheap to operate, so
under direct transmission they survive far longer than any node does under LEACH, which rotates the
expensive cluster-head role through the whole population. Clustering equalizes consumption, which
buys a much later first death at the cost of an earlier last death. Report all three points; leading
with only one silently picks a winner.

## Delivery

| Metric | Definition |
|---|---|
| `throughput_total` | Cumulative **data packets** received at the BS. |
| `readings_delivered_total` | Cumulative **original sensor readings** represented in packets received at the BS. |
| `pdr_percent` | `readings_delivered / readings_attempted × 100`. |
| `reporting_rate` | Data packets sent by sources ÷ alive-node-rounds. How chatty the protocol is. |
| `data_yield` | Readings delivered at the BS ÷ all readings **taken** (`alive_node_auc`). |

**Throughput must be read on the readings basis for cross-protocol comparison.** One PEGASIS round
delivers a single fused packet to the BS; one LEACH round delivers about five. The packet count is
measuring aggregation ratio, not delivery, so `throughput_total` alone would make PEGASIS look ~5×
worse while it may be delivering more readings per joule. `readings_delivered_total` is the
comparable number.

**PDR is reading-based for the same reason, and this was a correction.** The original packet-based
definition (BS packets ÷ source packets) measured 10% on a channel with *zero* packet loss, because
10 source packets legitimately became 1 aggregated packet. It would have reported ~5% for LEACH and
~1% for PEGASIS and read as a protocol difference when it was purely aggregation depth.

**`pdr_percent` vs `data_yield` — the denominators differ deliberately.** PDR's denominator is
readings *injected into the network*, so a reading a protocol deliberately suppresses (TEEN/APTEEN
below threshold) never enters it: suppression is correct behaviour, not loss. `data_yield`'s
denominator is all readings *taken*, so suppression does count against it. PDR answers "of what you
tried to send, how much arrived"; `data_yield` answers "how much of the sensed world reached the
BS". TEEN should score well on the first and poorly on the second, and that contrast is the point.

**PDR is survivorship-biased — do not read it without the alive-node curve.** Measured: direct-to-BS
PDR rises from 81.6% over the first 100 rounds to 99.0% over the last 100, because the distant nodes
that lose packets die first and the survivors are all near the base station. A protocol that burns
out its far nodes early therefore posts a *better* PDR. This is why direct transmission (96.9%)
appears to beat LEACH (87.3%) on the lossy channel despite being far worse in every other respect:
LEACH keeps electing distant cluster heads for the whole run and keeps paying for it.

## Energy

| Metric | Definition |
|---|---|
| `total_residual_energy` | Sum of residual energy over all nodes, per round. |
| `mean_residual_energy_all` | Mean over all `N` nodes, counting dead nodes as zero. |
| `mean_residual_energy_alive` | Mean over living nodes only. |

Both means are reported because they tell different stories: the all-nodes mean falls monotonically
toward zero and tracks total network depletion, while the alive-only mean can *rise* as the most
depleted nodes die out, which is a survivorship effect and not a recovery.

**Conservation is asserted every run**: `initial_total − final_residual` equals the sum of accounted
consumption across all categories (`data_tx`, `data_rx`, `ctrl_tx`, `ctrl_rx`, `agg`, `retry`) to
within 1e-9 J. The `retry` category exists because ARQ retransmissions are real energy; omitting it
would silently break the identity.

## Latency

Per delivered data packet, in milliseconds:

```
latency = slot_index × slot_ms + hop_depth × (tx_time_ms + proc_ms)
slot_ms = tx_time_ms + guard_ms = 4000 bits / 250 kbps + 4 ms = 20.0 ms
```

Derived from bitrate rather than hardcoded, so it stays consistent with the packet size. Reported as
`mean_latency_ms` and `p95_latency_ms`.

A cluster head's outgoing packet carries `slot_index = len(members)`, because it can only forward
after every member's TDMA slot has elapsed. This is what makes cluster latency scale with cluster
size; setting it to zero would make clustered protocols look artificially fast. PEGASIS instead uses
`slot_index = 0` and accumulates latency through `hop_depth`, since its cost is sequential fusion
along the chain rather than slot waiting.

## Alive nodes

`alive_nodes` per round, plus `alive_node_auc` (the summed area under the curve) as a single scalar.
The AUC is the most robust single lifetime summary available here, since unlike LND it is unaffected
by censoring and unlike FND it reflects the whole survival trajectory.

## Computational cost — three separate things, never merged

1. **Measured.** `mean_setup_ms` (wall-clock inside `setup_round` only), `total_runtime_s`, and
   `peak_memory_kb` via `tracemalloc`.
2. **Counted.** `ops_per_round` — the mean per round of a protocol-incremented counter covering
   every node-pair distance computation, every fitness/objective evaluation, and every neural
   forward pass. Counted over both `setup_round` and `route`. Protocols count *logical* algorithmic
   work, not physical numpy calls: the engine precomputes a distance matrix, but an algorithm that
   must compare each node against each cluster head still pays that cost conceptually, and it is the
   algorithmic cost the metric exists to compare.
3. **Analytical.** Big-O per protocol, below.

**Wall-clock reflects implementation quality as much as algorithm design.** The counted operations
are the more honest comparison, and the analytical complexity is the most honest of all. All three
are reported separately and never combined into a single "cost" figure.

Note also that all nine protocols run on the same numerical substrate (NumPy, no PyTorch). This is
partly a fairness requirement rather than a convenience: at these model sizes PyTorch's per-call
overhead would dominate, making DQN and GCN look artificially slow against NumPy-implemented
competitors, and `mean_setup_ms` is a reported metric.

### Analytical complexity per round

`N` = live nodes, `k` = cluster heads (≈ `p·N`), `P` = GA population, `G` = generations,
`H` = hidden width, `E` = graph edges.

| Protocol | Time | Space | Justification |
|---|---|---|---|
| LEACH | `O(N·k)` | `O(N)` | One coin flip per node, then each non-head compares against every head to find the nearest. |
| PEGASIS | `O(N²)` on rebuild, `O(N)` otherwise | `O(N)` | Greedy nearest-neighbour chain construction scans remaining nodes at each of `N` steps; rebuilt only on death. |
| TEEN | `O(N·k)` | `O(N)` | LEACH's clustering plus an O(1) threshold test per node. |
| APTEEN | `O(N·k)` | `O(N)` | TEEN plus an O(1) count-time check per node. |
| NSGA-II | `O(P·G·N + P²·G·M)` amortized over `K` rounds | `O(P·N)` | Each of `P·G` fitness evaluations costs `O(N)` to assign members and sum energy; non-dominated sort is `O(P²·M)` per generation for `M`=3 objectives. |
| Fuzzy T2 | `O(N·R + N·log N)` | `O(N)` | 27 rule firings plus Karnik–Mendel iteration per node, then a top-`k` selection. KM iteration count is bounded and treated as constant. |
| SOM | `O(N·U·I)` | `O(U)` | `I` training iterations, each presenting `N` nodes against `U` map units. |
| DQN | `O(N·H)` inference | `O(H)` | One forward pass of a small MLP per node, then top-`k`. Training cost is excluded — see below. |
| GCN | `O((N + E)·H)` inference | `O(N·H + E)` | Sparse propagation over the k-NN graph, two layers. |

**DQN and GCN report inference cost only.** Both are pre-trained on seeds 100–129, frozen, and
evaluated on seeds 0–29, so their `mean_setup_ms` and `ops_per_round` exclude training entirely. The
one-off training cost is reported separately and must not be read as free. The eight non-learned
protocols receive no equivalent offline preparation, so this is a fair measure of a *deployed*
policy but not an apples-to-apples algorithmic comparison. Generalization is tested only across
topologies from the same distribution (uniform random, N=100, same field and BS placement); nothing
here supports a claim of transfer to other densities or geometries.
