# Project status — read this first after a context reset

Unified benchmark of nine WSN clustering protocols in one shared simulator, 30 paired runs each.
The source paper's numbers are discarded; only its protocol descriptions, radio model and simulation
parameters were used. **Nothing has been tuned to reproduce a published number, and nothing should
be.** Fairness by construction is the top constraint, above performance and elegance.

## State: ALL STEPS COMPLETE. Full sweep run, analyzed, and gated.

600 runs done in 80 minutes on 14 cores: 10 protocols (9 + a direct-to-BS baseline) x 30 runs
x 2 channel configurations, 300 per channel. Results in `results/{lossy,ideal}/`, analysis and
15 figures in `results/analysis/`.

`results/checkpoint2/` and `checkpoint3/` are superseded 5-run scratch results kept only for
provenance. Their `mean_setup_ms` / `total_runtime_s` columns predate the tracemalloc fix and
are invalid (item 31); their lifetime and delivery numbers are fine but the 30-run sweep
replaces them. Do not cite them.

Every gate passes, each with independently confirmed exit codes:

```
test_radio  test_channel  test_engine  test_leach
test_protocols  test_nn  test_learned_protocols        all EXIT=0

scripts/check_determinism.py     9/9 protocols reproduce exactly (3 runs x 400 rounds)
scripts/fairness_audit.py        18/18 checks pass
analyze.py                       aggregate.csv verification PASS on both channels
```

The fairness audit parses the AST rather than grepping source text. Text matching produced
four false positives, every one a docstring *documenting* the constraint it was supposed to
detect ("This protocol never calls `net.spend`", "torch/scipy are absent by requirement"),
and it could not distinguish a read of `net.energy` — which a clustering decision legitimately
needs — from a write, which is the thing actually forbidden.

## Locked decisions (do not re-litigate)

| Topic | Decision |
|---|---|
| Channel | Distance-dependent packet error, **enabled by default**. Log-distance path loss + per-link log-normal shadowing (static, drawn once — nodes don't move) → non-coherent BFSK BER → PER. ARQ with 2 retries. |
| DQN regime | Pre-train on seeds 100–129, freeze, evaluate on 0–29. Held-out sanity seeds 130–134. |
| Cluster count | Same nominal target `k = round(p·N_alive)`; realized count is protocol-specific. LEACH's stays stochastic and is never clamped. |
| Throughput | Report **both** packets-at-BS and readings-delivered. |
| PDR | **Reading-based**, not packet-based. Denominator is readings *injected* (suppression is not loss). |
| Control traffic | 200 bits. Three models: `distributed` (LEACH/TEEN/APTEEN), `chain` (PEGASIS), `centralized` (the other five). |
| Centralized uplink | Node state piggybacks on existing data traffic, charged nothing. Only the downlink assignment broadcast is charged. |
| Neural stack | NumPy with hand-written backprop. No torch — partly a *fairness* requirement, since `mean_setup_ms` is a reported metric and torch's per-call overhead would dominate at these model sizes. |

## Architecture

Engine owns everything that could be cheated: energy accounting (single `Network.spend` choke
point), packet sizing, aggregation charging, channel/ARQ, reading accounting. Protocols decide only
cluster structure and route shape. Verified by grep that no protocol touches `net.energy`,
`net.alive`, or `net.spend`.

Two engine-enforced invariants worth knowing:
- Transmissions execute sorted by `(hop_depth, src)`, **not** plain ascending node index. Plain index
  order breaks causality whenever a forwarding node's index is below one of its senders' (about half
  of all clusters on a random topology), silently corrupting aggregation totals. A runtime check
  raises if a forward executes while inbound packets to it are still pending.
- A node that receives data may emit at most one outgoing data packet, and pays `e_agg` on total
  bits received. The engine raises if a protocol violates this.

## Bugs found and fixed (all were spec errors, not coding errors)

1. **PDR was meaningless under aggregation.** Packet-based PDR measured 10% on a channel with *zero*
   loss, because 10 source packets legitimately become 1 aggregated packet. Would have reported ~5%
   for LEACH and ~1% for PEGASIS and read as a protocol difference. Now reading-based.
2. **`payload_readings` was protocol-declared**, so a protocol could inflate its own delivery
   numbers. Engine computes it now; protocols only declare the boolean `originates`.
3. **`ops_per_round` measured traffic volume**, not algorithmic work — would have made the
   NSGA-II-vs-LEACH computational comparison meaningless.
4. **DQN reward was anti-correlated with lifetime.** γ=0.95 gave a ~20-round horizon for a
   phenomenon occurring at round 1000–2000, and the dominant reward term rewarded minimizing
   *instantaneous* energy, which provably teaches concentrating cluster heads near the BS. Fixed to
   γ=0.999 with a residual-energy-balance reward, plus reward standardization and TD/gradient
   clipping (both load-bearing; neither alone is stable).
5. **GCN loss had no learnable leverage** — geometry term spanned ~0–4.7 while initialized scores
   spanned ~±0.1. Fixed by standardizing scores with a gain of 3.0.
6. **`tracemalloc` was corrupting the reported timing metrics.** `run_single` wrapped the whole run
   in `tracemalloc.start()` while `setup_time_ms` was measured *inside* it. tracemalloc intercepts
   every allocation and its overhead grows as traced blocks accumulate, so protocols that allocate
   many small NumPy temporaries in Python loops (SOM's Kohonen sweep: ~40k allocations per
   recluster; NSGA-II's GA) were penalized far harder than vectorized ones (LEACH, PEGASIS).
   Diagnosed by running an identical synthetic loop inside and outside the engine: 119 ms before,
   455 ms then 712 ms during (growing), 174 ms after. SOM's `_train` measured 190 ms standalone and
   1600 ms inside the engine for byte-identical work. **`mean_setup_ms` was measuring allocation
   count under tracemalloc, not algorithmic cost** — and the inflation is non-uniform, so it
   distorted the cross-protocol ranking, not just the scale. Fixed: timing and memory are now
   measured in separate runs (`run_single(..., measure_memory=...)`); only run 0 measures memory,
   and the unmeasured field is NaN (the aggregator skips NaN). Simulation results are unaffected —
   tracemalloc changes wall-clock only, never energy or lifetime. It also makes the sweep far
   cheaper: SOM drops from ~344 to ~36 ms/round.

Performance: 45 → 11 ms/round by precomputing static per-link PER and transmit-energy tables,
verified bit-identical against a 300-round baseline.

## Final results (30 runs, N=100, lossy channel — the headline)

Mean ± sample std. Full tables including the ideal channel in `results/analysis/REPORT.md`.

| | FND | HND | LND | cens. | alive AUC | readings | PDR % | yield |
|---|---|---|---|---|---|---|---|---|
| TEEN | 2208 ± 164 | 5601 ± 189 | ≥6999 | 30/30 | 535398 | 58551 | 90.8 | 0.109 |
| APTEEN | 2144 ± 139 | 5367 ± 161 | ≥6999 | 30/30 | 518432 | 62579 | 90.8 | 0.121 |
| NSGA-II | 1873 ± 31 | 1965 ± 23 | 2697 | 0 | 200616 | 179860 | 89.6 | 0.896 |
| PEGASIS | 1588 ± 331 | 2199 ± 9 | 2630 | 0 | 216358 | **182179** | 84.2 | 0.842 |
| DQN | 1472 ± 55 | 1920 ± 31 | 2325 | 0 | 192098 | 173487 | 90.3 | 0.903 |
| Fuzzy T2 | 1462 ± 50 | 2006 ± 28 | 2109 | 0 | 191925 | 175438 | **91.4** | 0.914 |
| LEACH | 1046 ± 43 | 1679 ± 25 | 2191 | 0 | 167132 | 146616 | 87.7 | 0.877 |
| SOM | 959 ± 127 | 1998 ± 32 | 2874 | 0 | 196801 | 175822 | 89.3 | 0.893 |
| GCN | 335 ± 142 | 1824 ± 70 | 3185 | 0 | 180214 | 162782 | 90.3 | 0.903 |
| *(stub: direct-to-BS)* | 114 ± 11 | 1144 ± 183 | 3202 | 0 | 131995 | 128075 | 96.9 | 0.970 |

Four results worth knowing before reading further:

- **The headline finding is a conclusion that does NOT survive the channel switch.** Fuzzy T2
  (+417) and DQN (+426) beat LEACH on FND on the lossy channel at p < 0.001, and on the ideal
  channel both collapse to +17/+22 at p = 0.12 — **not significant**. NSGA-II (+827 → +482) and
  PEGASIS (+542 → +188) hold on both. Measured mechanism: LEACH's average CH sits at 101.8 m,
  past the `d0 = 87.7 m` crossover, and burns 6.4% of its budget on ARQ retries against DQN's
  2.3% at 81.1 m. **The flip is FND-specific** — on `alive_node_auc` and readings delivered,
  every protocol's gap to LEACH is significant in both channels. See `ASSUMPTIONS.md` item 32.
- **LEACH's rotation is the better mechanism on its own terms.** It consumes 20% more energy than
  DQN over 1100 rounds and still ties its FND on the ideal channel, because the epoch rule rotates
  CH duty perfectly. SOM has LEACH's CH-distance problem (102.8 m) *without* its rotation guarantee
  and loses to LEACH on FND in both channels.
- **DQN posts the most consistent FND of any protocol** (± 55 over 30 runs), matching its held-out
  validation (1488) almost exactly — the frozen policy generalizes.
- **GCN's FND (335 ± 142) is its only weak metric.** Its HND and LND both *beat* LEACH. It
  concentrates CH duty ~5x on structurally-favoured nodes (79 distinct CHs vs LEACH's 100; busiest
  serves 106 slots vs a uniform 20). The std is 42% of the mean — never report it without the
  spread. This is the predicted consequence of a single-round training objective with no temporal
  credit assignment, and the cleanest measurement of what DQN's γ=0.999 buys. `ASSUMPTIONS.md` 30.

Rank stability across channels is otherwise high: only 4 of 40 protocol-metric ranks move, and both
moving pairs are near-ties (`results/analysis/channel_robustness.csv`).

## Open items for the write-up

- **The centralized control-model confound.** Centralized protocols send ~10k control packets;
  LEACH sends ~173k. That 17× gap comes from the piggyback assumption, not from cluster-head
  selection quality. So "NSGA-II beats LEACH by 80% on FND" conflates two effects. The clean
  within-class comparison is NSGA-II vs Fuzzy T2 (both centralized). Either state the caveat or
  revisit the assumption; charging real status reports would cost ~25% of the energy budget.
- **FND and LND rank protocols in opposite directions.** Clustering equalizes consumption: much
  later first death, earlier last death. Report all three lifetime points.
- **PDR is survivorship-biased.** Distant nodes lose packets and die first, so burning out far nodes
  early *improves* PDR. Never report it without the alive-node curve.
- **NSGA-II converges only modestly** (population-best round energy improves 0.70%, minimum CH
  energy 3.1%; only cluster-size balance moves substantially, 5.9 → 1.79). Real finding about the
  landscape: with 5 heads from 100 candidates, random initialization already lands near-good.
- **TEEN/APTEEN censor at the 7000-round cap** in all runs. `lnd` is a lower bound there; never
  average it without reporting `n_censored_runs`.

## Reproducing everything

```
python run_experiments.py --runs 30 --channel both --jobs 14   # the sweep (80 min, measured)
python analyze.py --results results --baseline leach           # tables, stats, 15 figures
python scripts/check_determinism.py --runs 3 --rounds 400      # determinism gate
python scripts/fairness_audit.py                               # 18-check fairness table
```

matplotlib is required for `analyze.py` only, never for the simulation itself.

The lossy run is the headline and the ideal run is the sensitivity check: **any conclusion that
survives both channel configurations is about the protocol; any conclusion that flips between them
is about transmit power**, which the paper never specifies. That rule is now operationalized —
`analyze.py` emits `channel_robustness.csv` listing every rank that moves.

## Remaining work, if the paper wants it

1. **The control-traffic ablation.** Charge centralized uplink state honestly (a 200-bit status
   report per node per round) and re-run. This is the single most valuable follow-up: it would
   convert the largest caveat in `TRADEOFFS.md` (A1, worth ~9–10 percentage points of the energy
   budget) from a disclosure into a measurement. Not run.
2. **A `Pt` sweep.** The lossy/ideal pair brackets the extremes but does not trace the curve
   between them. Since `Pt` is what decides the single-hop-vs-multi-hop verdict, 3–4 values would
   turn A2 from a caveat into a result.
3. **A scale sweep** (N = 50 / 100 / 200). Several protocols are superlinear in N.

See `docs/TRADEOFFS.md` (everything the paper must disclose, ordered by how much it could move a
conclusion), `docs/ASSUMPTIONS.md` (every assumption with its reason), `docs/METRICS.md`
(definitions, Big-O, interpretation traps) and `results/README.md` (every column and unit).
