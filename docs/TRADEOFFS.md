# Tradeoffs and threats to validity — for the paper's Methods and Limitations sections

Everything here is a choice that a reviewer could reasonably challenge, or a modelling
simplification that bounds what the results can be claimed to show. Each entry states **what was
assumed**, **why**, and **what it could change**. Nothing in this file is hypothetical hedging —
every item corresponds to a decision actually made in the code, cross-referenced to
`ASSUMPTIONS.md`.

Order is by how much each could move a conclusion, most first.

---

## A. Threats to validity — these could change the ranking

### A1. The centralized protocols' control-traffic subsidy (the largest single confound)

**Assumption.** NSGA-II, Fuzzy T2, SOM, DQN and GCN are base-station-computed. Their *uplink* node
state (residual energy, position-derived features) is treated as piggybacked on data packets the
network is already sending, and charged nothing. Only the *downlink* assignment broadcast is
charged. LEACH/TEEN/APTEEN pay a full distributed ADV → JOIN-REQ → SCHEDULE handshake every round.

**Why.** A separate 200-bit status report per node per round, at a >100 m node-to-BS distance, falls
on the `d⁴` multipath branch: `200·e_elec + 200·eps_mp·100⁴ ≈ 3.6×10⁻⁵ J/node/round`. Over the
7000-round cap that is ≈0.25 J — **about 25% of the entire 1 J energy budget**, spent purely on
reporting overhead unrelated to whether the clustering decision is any good. This is the standard
assumption in the centralized-LEACH literature.

**What it could change.** Nearly everything in the cross-class comparison. Measured over the full
30-run sweep, the centralized five send ~10k control packets per run; LEACH sends ~172k and
TEEN/APTEEN ~574k/~554k — a **17× to 57× gap that comes from the accounting model, not from
cluster-head selection quality.**

In energy terms, which is what actually matters, the subsidy is worth about **9–10 percentage points
of the total budget**: LEACH spends 12.73% of everything it consumes on control traffic, against
2.33% for Fuzzy T2, 2.46% for NSGA-II, 2.38% for SOM, 3.95% for DQN and 3.85% for GCN. A claim like
"NSGA-II extends FND by 80% over LEACH" therefore conflates two effects and should not be made
unqualified.

**How to handle it in the paper.** Two options, and I recommend doing both:
1. State the caveat explicitly wherever a centralized protocol is compared to a distributed one.
2. Lead the analysis with the **within-class** comparisons, which are clean:
   - centralized vs centralized: NSGA-II vs Fuzzy T2 vs SOM vs DQN vs GCN
   - distributed vs distributed: LEACH vs TEEN vs APTEEN
   - PEGASIS is its own class (chain) and compares cleanly to neither.

An ablation that charges the uplink honestly would settle it, and is the single most valuable
follow-up experiment this codebase could run. Not currently run.

### A2. Transmit power `Pt` decides the single-hop-vs-multi-hop verdict

**Assumption.** `Pt = 12 dBm`, path-loss exponent `n = 3.0`, shadowing `σ = 4 dB`, noise floor
−105 dBm, non-coherent BFSK, ARQ with 2 retries.

**Why.** The source paper specifies no link budget at all. These are conventional 802.15.4 / 2.4 GHz
values.

**What it could change.** The base station sits at (50, 150), i.e. 150–158 m from far-field nodes —
right at the edge of realistic 802.15.4 range, which is exactly where the PER waterfall lives.
**Choosing `Pt` is choosing how hard single-hop protocols get punished.** Raise it and LEACH's
CH→BS hop becomes reliable; lower it and PEGASIS's short chain hops win by default. Because
`PER = 1−(1−BER)^4000` with an exponential BER, the transition from ~0 to ~1 spans only ~12 dB —
a cliff, not a gradient. The log-normal shadowing term is what smears it into something usable.

**Mitigation actually implemented.** (a) A PER-vs-distance calibration curve is published as
`results/validation/per_calibration.csv` so the cliff's location is auditable rather than buried in
a constant. (b) The whole experiment is run as a sensitivity pair — lossy (headline) and ideal
(`per_enabled=False`). **The rule for the paper: any conclusion that survives both channel
configurations is about the protocol; any conclusion that flips between them is about `Pt`.**

**What the sensitivity pair actually caught — this is a headline result, not a caveat.** Applying
that rule to the 30-run sweep, one conclusion flips, and it is a load-bearing one:

| FND vs LEACH | lossy channel | ideal channel |
|---|---|---|
| Fuzzy T2 | **+417** rounds, p < 0.001 | +17 rounds, p = 0.12 (**not significant**) |
| DQN | **+426** rounds, p < 0.001 | +22 rounds, p = 0.12 (**not significant**) |
| NSGA-II | +827 rounds, p < 0.001 | +482 rounds, p < 0.001 (holds) |
| PEGASIS | +542 rounds, p < 0.001 | +188 rounds, p = 0.009 (holds) |

Fuzzy T2's and DQN's first-node-death advantage over LEACH **exists only on the lossy channel.**
Remove packet loss and they are statistically indistinguishable from LEACH.

**The mechanism, measured directly rather than inferred** (single seed, 1100 rounds, energy split by
the engine's own accounting categories):

| protocol | retry energy | control energy | mean CH→BS distance | total consumed |
|---|---|---|---|---|
| LEACH | **6.39%** | 12.73% | **101.8 m** | 68.02 J |
| SOM | 5.28% | 2.38% | 102.8 m | 55.79 J |
| Fuzzy T2 | 3.65% | 2.33% | 85.6 m | 58.09 J |
| NSGA-II | 3.57% | 2.46% | 94.2 m | 54.46 J |
| DQN | **2.31%** | 3.95% | **81.1 m** | 56.44 J |
| GCN | 2.25% | 3.85% | 77.2 m | 55.41 J |

The crossover distance is `d0 ≈ 87.7 m`. **LEACH's average cluster head sits at 101.8 m — past the
crossover, on the `d⁴` multipath branch and far enough out to be losing packets — while DQN's sits
at 81.1 m, inside the `d²` free-space branch.** LEACH therefore spends 6.4% of its entire energy
budget on ARQ retransmissions against DQN's 2.3%. That gap is the whole of the FND advantage: delete
it by making the channel lossless and the advantage disappears.

So the honest claim is narrower and more interesting than "the learned/fuzzy protocols cluster
better": **their measurable skill is keeping the cluster-head-to-BS hop inside the free-space
regime, which pays off only in proportion to how lossy that hop is.** LEACH's compensating strength
is visible in the same table — it burns 20% more total energy than DQN yet matches its FND on the
ideal channel, because its epoch mechanism rotates cluster-head duty perfectly (every node exactly
20 times per epoch), and perfectly even rotation is close to optimal for *first* death specifically.

**The flip is FND-specific, and saying otherwise would overstate it.** On `alive_node_auc` and on
`readings_delivered_total`, every protocol's difference from LEACH is significant at p < 0.001 in
*both* channels, same direction, similar magnitude (Fuzzy T2 AUC +24,793 lossy / +22,120 ideal; DQN
+24,966 / +22,538). The correct statement is therefore: **Fuzzy T2's and DQN's advantage over LEACH
in overall survival and in data delivered is robust to the channel; only their advantage in FND
specifically is not.** That is A4 (below) in action — FND is a single order statistic and the most
fragile of the lifetime measures, and it is the one this literature most often reports alone.

### A3. DQN and GCN are pre-trained; the other seven protocols are not

**Assumption.** Both learned protocols are trained on seeds 100–129, frozen, and evaluated on seeds
0–29 (DQN additionally validated on held-out seeds 130–134).

**Why.** This measures the only claim anyone would actually make for a learned protocol in the
field — a policy trained offline, deployed to unseen topologies — and it genuinely tests
generalization, since the evaluation topologies are unseen.

**What it could change.** Three distinct caveats, all of which belong in the paper:
- DQN's and GCN's reported `mean_setup_ms` and `ops_per_round` are **inference only**. Training cost
  is real, is paid once, and is reported separately. It must not be read as free.
- The seven non-learned protocols get **no equivalent offline preparation**. This is a fair
  comparison of a *deployed* system and is *not* an apples-to-apples algorithmic comparison.
- Generalization is demonstrated only across topologies from the *same distribution* (uniform
  random, N=100, 100×100 m field, BS at (50,150)). **Nothing here supports a claim of transfer** to
  other densities, field sizes, or BS placements.

### A4. FND and LND rank protocols in opposite directions

**Finding, not an assumption.** Clustering equalizes energy consumption: it buys a much later first
death at the cost of an earlier last death. Measured directly — LEACH reaches FND at ~1040 rounds
vs ~112 for direct-to-BS (a ~9× improvement), but LEACH's LND is *earlier* (~2158 vs ~3271). The
mechanism is geometric: 36 of the 100 nodes lie within `d0 ≈ 87.7 m` of the BS and are individually
cheap to run, so under direct transmission they outlive any node under LEACH's rotation.

**What it could change.** Any single-number "lifetime" claim. **Report all three lifetime points
plus `alive_node_auc`.** Leading with one silently picks a winner. GCN is the extreme case: its FND
(294) is 3.5× *worse* than LEACH's while its HND (1843) and LND (3251) are both *better*.

### A5. PDR is survivorship-biased

**Finding, not an assumption.** Distant nodes lose the most packets and die first, so a protocol
that burns out its far nodes early posts a *better* PDR. Measured: direct-to-BS PDR rises from 81.6%
over the first 100 rounds to 99.0% over the last 100. This is why direct transmission (96.9%)
appears to beat LEACH (87.3%) on the lossy channel while being far worse in every other respect.

**What it could change.** Any standalone PDR table. **Never report PDR without the alive-node
curve beside it.**

### A6. Packet-count throughput measures aggregation ratio, not delivery

**Finding.** One PEGASIS round delivers a single fused packet to the BS; one LEACH round delivers
about five. On a packets-at-BS basis PEGASIS looks ~5× worse while actually delivering *more*
readings. Both bases are recorded: `throughput_total` (packets) and `readings_delivered_total`
(original sensor readings). **Only the second is cross-protocol comparable.** The first is reported
because the spec asked for it, and should be labelled as an aggregation-ratio indicator.

The same defect once affected PDR, which is why PDR is now reading-based: the old packet-based
formula measured 10% on a *zero-loss* channel purely because 10 source packets became 1 aggregated
packet (`ASSUMPTIONS.md` item 15).

### A7. TEEN and APTEEN censor at the round cap

**Finding.** Both hit the 7000-round cap in every run without reaching LND. Their `lnd` is therefore
a **lower bound, not a measurement**, flagged per-run by `lnd_censored` and per-protocol by
`n_censored_runs`.

**What it could change.** Any mean that averages a censored value silently understates it. Either
report `n_censored_runs` alongside every `lnd_mean`, or use `alive_node_auc` (unaffected by
censoring) as the lifetime summary for these two. Their low `data_yield` (~0.11–0.12 vs ~0.89 for
the proactive protocols) is the honest counterweight: they survive by not reporting.

### A8. GCN's mean FND is bimodal and should never be reported alone

**Finding.** Per-run FND on seeds 0–4: 448, 394, 418, 112, 98. On two of five topologies some node
drains almost immediately. Mechanism, measured over a real 400-round run: GCN uses 79 distinct
cluster heads out of 100, with the busiest node serving 106 of 2000 CH slots against a uniform share
of 20 — roughly 5× over-service. LEACH's epoch mechanism rotates perfectly by construction (100
distinct nodes, exactly 20 slots each).

**Why it happens, stated as a result rather than a defect.** GCN is trained on a single-round
energy-balance objective with no temporal credit assignment — it cannot represent "sacrifice this
round to extend lifetime." Its `rounds_since_last_CH` input lets it *see* rotation state but nothing
in its loss rewards using it. DQN, with the same four features and γ=0.999, has exactly that
machinery and posts the tightest FND of any protocol (1404–1530, spread 126 rounds vs GCN's 350).

**This is the paper's cleanest single measurement of what temporal credit assignment buys**, and it
is worth framing as such: **GCN = spatial/structural reasoning, DQN = temporal/sequential
reasoning.**

---

## B. Modelling simplifications — standard, but must be stated

### B1. Radio and energy

- **First-order radio model only.** `E_tx = k·E_elec + k·ε_fs·d²` (d < d0) or `k·E_elec + k·ε_mp·d⁴`
  (d ≥ d0); `E_rx = k·E_elec`; `E_agg = k·E_DA`. This is the Heinzelman model and is standard, but
  it means **no idle-listening energy, no sleep/wake transition energy, no radio startup cost, and
  no processor energy**. In real deployments idle listening frequently dominates the energy budget,
  which would compress the differences between all nine protocols.
- **No battery nonlinearity.** Energy is a linear reservoir; no rate-capacity effect, no recovery
  effect, no voltage cutoff.
- **Death-during-transmission rule:** a node with insufficient energy spends what remains, dies, and
  the packet is lost. The alternative (refuse and strand energy) would break the clean conservation
  identity `initial − residual = tx + rx + ctrl + agg + retry`, asserted every run to 10⁻⁹ J.

### B2. Aggregation is ideal

A cluster head that fuses any number of member packets emits **one 4000-bit packet**, regardless of
how many readings it represents. Fusion is therefore lossless and free in bits, charged only
`E_DA = 5 nJ/bit` on bits received. Real fusion has a compression ratio below 1 and may lose
information. This assumption **systematically favours high-fan-in protocols**, PEGASIS most of all
(a 100-node chain collapses to one packet). The engine enforces the rule symmetrically — a
receiving-and-forwarding node may emit at most one data packet and cannot opt out of the `E_DA`
charge — so no protocol can exploit it more than the structure of its own topology allows.

### B3. No MAC layer, no interference, no collisions

TDMA is assumed perfectly scheduled and collision-free. There is no CSMA backoff, no hidden
terminal, no inter-cluster interference, no capture effect. Packet loss comes *only* from the
distance-dependent PER model. Adding interference would penalize dense-cluster protocols relative to
the chain, and would make the number of simultaneously-active cluster heads matter — a dimension
this study cannot see.

### B4. Latency is analytic, not queueing

```
latency = slot_index × slot_ms + hop_depth × (tx_time_ms + proc_ms)
slot_ms = 4000 bits / 250 kbps + 4 ms guard = 20.0 ms
```
No queueing delay, no retransmission delay (ARQ costs energy but not modelled time), no MAC
contention. A cluster head's own packet carries `slot_index = len(members)` because it can only
forward after every member's slot elapses — this is what makes cluster latency scale with cluster
size. PEGASIS uses `slot_index = 0` and accumulates through `hop_depth`. The resulting ordering
(LEACH ≈ TEEN < centralized ≪ PEGASIS) is structurally correct but the absolute milliseconds are
lower bounds.

### B5. Static everything

Nodes never move, never fail except by energy depletion, and are deployed once uniformly at random.
Per-link log-normal shadowing is consequently drawn **once per topology and held fixed** — re-drawing
per packet would model fast fading, which averages out and would contribute nothing. There is no
mobility, no node addition, no environmental change over the 7000 rounds.

### B6. CH→BS is single-hop for eight of nine protocols

Matching each protocol's original paper. PEGASIS is the sole multi-hop contrast. Adding CH→BS
relaying would change the results substantially — and would also flatten the latency metric, since
`hop_depth` would stop being a constant 2 for eight of nine.

### B7. Sensed data is a mean-reverting (Ornstein–Uhlenbeck) process

`v(r) = v(r−1) + θ(μ − v(r−1)) + N(0, σ²)`, θ=0.05, μ=50, σ=2.0, stationary ≈ N(50, 6.4²).

**A pure random walk was rejected deliberately**: over 7000 rounds it drifts σ√7000 ≈ 167 units and
pegs against any clip bound, which would make TEEN's entire behaviour an artifact of clipping.
TEEN/APTEEN thresholds (HT=55 ≈ +0.78σ, ST=1.0, TC=50) are set against this stationary distribution,
**not tuned to produce a particular result**. The reactive protocols' results are conditional on
this data model; a bursty or spatially-correlated field would change them markedly, and no real
sensor trace was used.

### B8. Cluster count: same target, protocol-specific realization

Every clustering protocol targets `k = max(1, round(p·N_alive))`, recomputed from the *alive* count.
The realized count is left alone: LEACH's stays stochastic and is never clamped (forcing it would be
implementing a different algorithm), PEGASIS has no `k`, and the centralized five select exactly
`k`. Zero-CH rounds are a legitimate unforced outcome for LEACH.

**Consequence to state:** part of every observed difference is attributable to realized cluster
count rather than to selection logic. Fixing the *target* isolates the question the nine protocols
actually differ on — *given you may pick about five heads, which five?*

---

## C. Measurement and methodology caveats

### C1. Three separate notions of computational cost, never merged

1. **Measured** — `mean_setup_ms`, `total_runtime_s`, `peak_memory_kb`.
2. **Counted** — `ops_per_round`: every node-pair distance computation, every fitness/objective
   evaluation, every neural forward pass. Counted over both `setup_round` and `route`. Protocols
   count *logical* work, so an algorithm that must compare each node against each head pays that
   cost conceptually even though the engine precomputes the distance matrix.
3. **Analytical** — Big-O per protocol (`METRICS.md`).

**Wall-clock reflects implementation quality as much as algorithm design.** Counted ops are the more
honest comparison; analytical complexity is the most honest of all. Report all three; never combine
them into a single "cost" number.

### C2. All nine protocols run on the same numerical substrate — this is a fairness requirement

NumPy with hand-written backprop, no PyTorch. At these model sizes (a 4→16→1 MLP, a 2-layer GCN with
16 hidden units) PyTorch's ~50 µs per-call overhead would dominate and make DQN and GCN look
artificially slow against NumPy-implemented competitors. **Since `mean_setup_ms` is a reported
metric, mixing frameworks would corrupt a reported result.** The cost of this choice is no autograd
— gradients are hand-derived and verified against central finite differences in `tests/test_nn.py`.

### C3. Timing and memory are measured in *different runs* — and here is why that matters

`tracemalloc` intercepts every allocation and its overhead grows as traced blocks accumulate.
Measuring memory and time in the same run inflated `mean_setup_ms` by **3.5×–7.8× depending on how
many small objects a protocol allocated** — SOM's Kohonen sweep allocates ~40k NumPy temporaries per
recluster and was hit hardest; vectorized LEACH and PEGASIS barely at all.

**The inflation was non-uniform, so it distorted the ranking, not just the scale.** Two measured
inversions:
- GCN's true setup cost is ~35% *higher* than LEACH's (0.819 vs 0.607 ms). Under tracemalloc it read
  ~30% *lower* (2.881 vs 4.130 ms), and below TEEN and APTEEN too. **The sign flipped.**
- SOM vs NSGA-II: honest ratio 2.30× (69.6 / 30.3 ms); traced ratio 1.18×.

Resolution: run 0 of each protocol measures memory and reports NaN timing; runs 1+ do the reverse.
So `peak_memory_kb_mean` comes from **one sample** (its std is undefined) and timing means from
`n_runs − 1`. Simulation results are unaffected — tracemalloc changes wall-clock only, never energy,
lifetime, or delivery.

**Worth a sentence in the paper's methods section.** It is a general and under-reported hazard: any
comparative study that profiles memory and time simultaneously is silently ranking protocols by
allocation count.

### C4. Fairness is enforced structurally, not by convention

The engine owns everything a protocol could otherwise cheat on: energy accounting (a single
`Network.spend` choke point), packet sizing, aggregation charging, channel and ARQ, and reading
accounting. Protocols decide only cluster structure and route shape. Verified by grep that no
protocol touches `net.energy`, `net.alive`, or `net.spend`.

Two engine-enforced invariants worth mentioning as methodology:
- Transmissions execute sorted by `(hop_depth, src)`, **not** ascending node index. Plain index order
  breaks causality whenever a forwarding node's index is below one of its senders' — about half of
  all cluster/member pairings on a random topology — silently corrupting aggregation totals. A
  runtime check raises if a forward executes while inbound packets are still pending.
- A node that receives data may emit at most one outgoing data packet and pays `E_DA` on all bits
  received. The engine raises if a protocol violates this.

Two earlier fairness defects were found and fixed, and are worth a line in the paper because they
are easy to repeat: `payload_readings` was originally protocol-declared (a protocol could inflate
its own delivery numbers — now engine-computed from a boolean `originates`), and `ops_per_round`
originally measured traffic volume rather than algorithmic work (which would have made the
NSGA-II-vs-LEACH computational comparison meaningless).

### C5. Paired topologies, and what is *not* shared across protocols

Run index `i` seeds topology, per-link shadowing, and the sensed-value stream, so **all nine
protocols see byte-identical physical conditions at a given run index**. Protocol randomness comes
from a separate blake2b-derived stream (never Python's `hash()`, which is salted per process).

The one thing deliberately *not* shared: the per-packet channel coin-flips. Different protocols make
different numbers of draws per round, so there is no meaningful sense in which two protocols could
see "the same channel realization" packet-by-packet. The fairness-critical piece is the **static
per-link shadowing**, which *is* identical. These are different claims — "the physical channel
geometry is fair" versus "the exact sequence of coin flips is fair" — and only the first needs to
hold.

### C6. Statistics

30 paired runs per protocol per channel configuration. Reported as mean and sample std (ddof=1).
Because topologies are paired across protocols, **paired tests (Wilcoxon signed-rank, or a paired
t-test on FND) are available and are stronger than the unpaired comparison the std alone implies.**
Currently the pipeline reports mean ± std only; adding paired significance tests and confidence
intervals is a cheap and worthwhile addition before submission. Note that a censored `lnd` violates
the assumptions of both tests — use `alive_node_auc` for TEEN/APTEEN.

### C7. Results are deliberately not calibrated to the source paper

Only the protocol descriptions, radio model, and simulation parameters were taken from it; its
numeric results were discarded. **Nothing has been tuned to reproduce a published number.**
Disagreement with the source tables is expected and is not evidence of an error here. This should be
stated plainly rather than buried — it is a methodological strength, but only if declared.

Relatedly, a **pre-registered stopping rule** was applied to DQN: after the divergence fix, the
result was recorded as final regardless of outcome, with no further reward/architecture/feature/
hyperparameter changes attempted. It beat random CH rotation on 5/5 held-out seeds (mean FND 1487.6
vs 1176.2, +26.5%). Stating the pre-commitment is what makes that number credible.

---

## D. What this study cannot claim

State these as explicit scope limits rather than letting a reader infer them:

1. **One network scale.** N=100, 100×100 m field, BS at (50,150), `p=0.05`. No scalability sweep.
   Nothing here shows how the ranking behaves at N=50 or N=500, and several protocols have
   complexity that is superlinear in N (NSGA-II, PEGASIS rebuild, SOM).
2. **One energy budget.** `E0 = 1.0 J`, homogeneous. Heterogeneity fields exist in the config but are
   disabled, so no advanced/super-node results.
3. **One traffic model.** Every alive node senses every round. No event-driven traffic, no duty
   cycling, no query workload (APTEEN's query mechanism is explicitly out of scope — only its
   reporting-frequency half is modelled).
4. **No real-world validation.** No testbed, no hardware, no measured traces. Every number is
   simulation output under the assumptions above.
5. **Learned protocols are not shown to transfer** beyond the training distribution (see A3).
6. **NSGA-II converges only modestly** — this is a finding, not a failure: population-best round
   energy improves 0.70%, minimum CH energy 3.1%, and only cluster-size balance moves substantially
   (5.9 → 1.79). With 5 heads drawn from 100 candidates, random initialization already lands near
   good. Worth reporting as a statement about the landscape, and it also means NSGA-II's advantage
   here should not be attributed to the sophistication of the search.
7. **The fuzzy rule base is authored, not learned.** The 27 rules are generated by
   `score = 2·E + (2−D) + Dn`, monotone in every input by construction. Monotonicity is what makes it
   defensible, but the double weight on residual energy is a designer's choice, not a derived one.

---

## E. Suggested one-paragraph limitations statement

> Results are simulation-only under a first-order radio model with no idle-listening, MAC-contention,
> or interference costs, on a single network scale (N=100, 100×100 m, BS at (50,150), E0=1 J) with an
> ideal-fusion aggregation assumption. Centralized protocols are modelled with piggybacked uplink
> state, so their measured control-traffic advantage over distributed protocols reflects that
> accounting choice as much as clustering quality; within-class comparisons are the reliable ones.
> The learned protocols (DQN, GCN) are pre-trained offline and evaluated on unseen topologies drawn
> from the same distribution, so their reported per-round cost is inference-only and their
> generalization is untested beyond that distribution. The single-hop-versus-multi-hop ranking is
> sensitive to transmit power, a parameter the reference specification does not fix; every experiment
> is therefore repeated on an ideal (lossless) channel, and only conclusions stable across both
> configurations are claimed. Lifetime is reported at three points (FND, HND, LND) plus area under
> the alive-node curve, because clustering trades a later first death for an earlier last death and
> no single point summarizes it; reactive protocols censor at the round cap and their LND is a lower
> bound.
