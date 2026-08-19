# Area and Node Comparison

The scale study: how the ten protocols behave as node count and field area change. Read this to get
the gist without opening a CSV.

**Status: complete.** 1,350 runs, 3.7 hours on 14 cores. Source data is
`results/scale/scale_aggregate.csv`; regenerate with
`python scripts/scale_sweep.py --runs 15 --skip-existing`.

---

## 1. What is being varied

A full 3 x 3 grid, lossy channel only, 15 paired runs per cell — 1,350 runs.

| | 50 x 50 m | 100 x 100 m | 150 x 150 m |
|---|---|---|---|
| **N = 50** | 200 nodes/ha | 50 nodes/ha | 22 nodes/ha |
| **N = 100** | 400 nodes/ha | **100 nodes/ha** (headline) | 44 nodes/ha |
| **N = 150** | 600 nodes/ha | 150 nodes/ha | 67 nodes/ha |

The grid is deliberately full rather than a cross. Node count and area jointly determine *density*,
and only a full grid can vary each independently and see which one an effect follows.

One honest caveat about the grid as built: **no two cells share the same density exactly.** The
closest pair is 50 nodes/ha (N=50, 100x100) against 44 nodes/ha (N=100, 150x150), and that pair does
the disambiguating work in Section 4.1. A grid designed specifically to hold density constant would
have needed cells like N=225 at 150x150; that was not run. The conclusion still holds comfortably,
because the effect sizes along the two axes differ by roughly a factor of five, but it rests on a
near-match rather than an exact one.

Everything else is unchanged from the headline study: E0 = 1 J, 4000-bit data packets, 200-bit
control packets, p = 0.05, 7000-round cap, same radio constants, same thresholds.

## 2. Four decisions, and what each one costs

**Base station scales with the field: BS = (W/2, 1.5W).** So 50x50 puts the sink at (25, 75),
100x100 at (50, 150) — identical to the headline study — and 150x150 at (75, 225). The deployment
stays geometrically self-similar.

> **This is a known confound and must be stated in the paper.** The packet-error waterfall sits at a
> *fixed* distance (error is ~0 below 120 m, 0.19 at 140 m, 0.70 at 150 m), so scaling the sink with
> the field also scales channel severity. At 50x50 every link is below d0 = 87.7 m and essentially
> lossless; at 150x150 the far corner is 239 m and effectively unreachable. The area axis therefore
> measures *area and channel severity together*, not area alone.
>
> The alternative — holding the sink a fixed 50 m outside the field — would have held channel
> severity closer to constant but broken geometric similarity. Neither choice is free. This one was
> taken deliberately, and the coupling is quantified rather than hand-waved: mean node-to-sink
> distance is 52 / 104 / 156 m at the three field sizes, and the share of nodes past the 120 m error
> threshold is 0% / 33% / 75%. Those figures are printed in the note under Table X so a reader can
> attribute the area effect themselves.

**`density_radius` scales with the field (0.25 x W): 12.5 / 25 / 37.5 m.** This is the "local
neighbourhood" feature that NSGA-II, the fuzzy system, SOM, DQN and GCN all read. Held fixed at
25 m it would cover 78% of a 50x50 field and 9% of a 150x150 one, so the feature would quietly
change meaning across the sweep and confound exactly the five protocols that use it. It lives in
`SimConfig` and is read identically by every protocol, so scaling it is a shared environment choice,
not per-protocol tuning.

**DQN and GCN use their frozen N=100 / 100x100 weights everywhere. No retraining.** This measures
out-of-distribution transfer, which is precisely the claim `docs/TRADEOFFS.md` declines to make
("nothing here supports a claim that the policy transfers to different densities, field sizes, or BS
placements"). The sweep converts that caveat into a measurement. If they degrade away from their
training configuration, that is a finding about learned protocols, not a bug — but it must be
labelled as transfer failure and not as "the DQN is bad at 150 nodes".

**15 runs per cell, not 30.** The paired sign-flip permutation test still works (2^15 = 32,768 sign
assignments, so the p floor is about 3e-5), and it halves a run that is already measured in hours.
Cross-cell comparisons are **not** paired — a different N means a different number of nodes to seed,
so run *i* at N=50 and run *i* at N=150 are different worlds — and must never be tested as if they
were. Only within-cell comparisons are paired.

## 3. What to expect, and what would be surprising

Stated in advance so the results are read rather than rationalised. Outcomes added after the fact:

| Prediction | Outcome |
|---|---|
| Smaller field lengthens every lifetime, because transmit energy falls with d^2. | **Confirmed**, and larger than expected: tripling the field side costs a factor of 5-7. |
| The gap between generations narrows at 50x50, because the gen-2/gen-3 skill is keeping the sink hop inside free space and there is nothing to win when every hop already is. A second, independent test of the ideal-channel retraction. | **Confirmed, strongly.** DQN's advantage over LEACH falls from +444 to +10 rounds; fuzzy T2's from +419 to +68. At N=50 both go negative. |
| The gap widens at 150x150, for the same reason in reverse. | **Wrong.** It narrows there too (DQN +257, fuzzy +91). Past a point the sink hop is bad for everyone and head placement cannot rescue it. The gap is largest in the *middle*, at 100x100. |
| Higher density helps clustering and hurts direct transmission. | **Wrong / negligible.** Density is nearly irrelevant next to field size (factor 0.88-1.26 against 5-7). |
| DQN and GCN may degrade away from N=100 / 100x100. | **Not observed.** Neither collapses; GCN's deficit actually shrinks as the field grows. |

Two of five predictions were wrong. Both wrong ones are reported above rather than quietly dropped,
and the non-monotonic gap in row 3 is the more interesting result of the two.

## 4. Results

Complete: 1,350 runs in 3.7 hours on 14 cores. Source `results/scale/scale_aggregate.csv`.

**Correctness check first.** The centre cell (N=100, 100x100) is byte-identical to runs 0-14 of the
headline study for all ten protocols, on both FND and AUC. The sweep pipeline reproduces the main
experiment exactly.

### 4.1 Area dominates node count by roughly five to one

Geometric mean over all ten protocols of the change in first node death:

| Change | Effect on FND |
|---|---|
| Triple the node count (50 -> 150), field fixed | x0.88 to x1.26 |
| Triple the field side (50 -> 150 m), N fixed | **x0.14 to x0.21** (a 5-7x reduction) |

Node count barely matters. Field size decides almost everything. And it is not density doing the
work: ordered by density, the results do not trend with it. The two cells closest in density
(50 vs 44 nodes/ha) differ by 1.7x for NSGA-II, 2.1x for LEACH and 5.5x for direct transmission,
because one has the sink 104 m away and the other 156 m.

Mean node-to-sink distance is 52 / 104 / 156 m at the three field sizes, and the share of nodes
beyond the 120 m error threshold is **0% / 33% / 75%**. That last row is the whole story of this
sweep.

### 4.2 Clustering is actively harmful at 50x50 m

LEACH's first node death, relative to no clustering at all:

| | N=50 | N=100 | N=150 |
|---|---|---|---|
| 50x50 m | **x0.82** | **x0.83** | **x0.95** |
| 100x100 m | x5.36 | x9.27 | x9.78 |
| 150x150 m | x6.68 | x14.06 | x16.13 |

At 50x50 the direct baseline outlives LEACH in every cell, on AUC as well as FND. With the sink
75 m away every node is inside the free-space branch and can reach it cheaply, so clustering
contributes overhead and nothing else. This generalises the paper's first finding from a statement
about *some nodes* into a statement about *a whole operating regime*: clustering does not extend
lifetime, it trades near-sink nodes against far ones, and when there are no far ones the trade is
pure loss.

### 4.3 The channel retraction reproduces, by a completely different route

Advantage over LEACH in first node death, N=100:

| Protocol | 50x50 | 100x100 | 150x150 |
|---|---|---|---|
| NSGA-II | +556 | +838 | +749 |
| PEGASIS | +497 | +576 | +512 |
| DQN | **+10** | +444 | +257 |
| Fuzzy T2 | **+68** | +419 | +91 |
| SOM | -337 | -70 | +39 |
| GCN | -1409 | -664 | -145 |

The fuzzy system and the DQN — the two protocols whose advantage vanished on the ideal channel —
lose that advantage again at 50x50, where no link reaches the error waterfall. At N=50 they are
outright **worse** than LEACH (-135 and -291). This is the same mechanism confirmed independently:
their measurable skill is keeping the sink hop short, and where every hop is already short there is
nothing to win.

**The fuzzy system is the control that makes this attribution safe.** It has no training of any
kind, so its collapse at 50x50 cannot be transfer failure — it must be the environment. Since the
DQN behaves the same way, the DQN's collapse is the environment too, not a consequence of being
evaluated away from its training configuration.

### 4.4 Ranking stability: partial, and the exceptions are informative

Spearman correlation of the FND ranking against the centre cell ranges 0.58 to 1.00. Rank span
across the nine cells:

| Stable (span <= 3) | Unstable (span 5-7) |
|---|---|
| NSGA-II (1-3), GCN (9-10), LEACH (6-8), PEGASIS (2-5), Fuzzy T2 (4-7) | Direct (4-10), DQN (2-8), SOM (3-9), TEEN/APTEEN (1-6) |

Three movements are worth a sentence each in the paper:

- **NSGA-II is the only protocol that beats LEACH in all nine cells** (+394 to +1177) and it takes
  rank 1 in every 150x150 cell. It is the most scale-robust protocol in the study.
- **DQN's standing improves monotonically as the deployment gets harder** — rank 8 at 50x50/N=50,
  rank 2 at 150x150/N=150. It is the protocol whose value depends most on the problem being difficult.
- **TEEN and APTEEN reverse.** Rank 1-2 at 50x50 and 100x100, but rank 4-6 at 150x150, where NSGA-II
  and PEGASIS overtake them. Reactive reporting stops being enough once the sink hop is expensive.

On **AUC** the ranking is far more stable (span 0-4 for every protocol except the direct baseline's
7), which is consistent with the headline study: FND is the fragile metric, survival area is not.

### 4.5 Transfer of the learned protocols

DQN and GCN ran everywhere on weights frozen at N=100 / 100x100. Neither collapses away from that
configuration, and GCN's deficit against LEACH actually *shrinks* as the field grows (-1409 at
50x50, -145 at 150x150). There is no evidence here of catastrophic out-of-distribution failure —
which is a mildly positive result for learned clustering, and one the paper is entitled to state
because it pre-registered the opposite expectation in Section 3.

GCN is nonetheless worse than LEACH in all nine cells, so the transfer result should be phrased as
"it fails to generalise no *worse* than it already performs", not as a success.

### 4.6 Generated artifacts

Tables (`python scripts/make_tables.py --scale`):
- `paper/tables/tab10_scale_fnd.tex` — first node death across all nine cells, with the sink-distance
  note quantifying the area/channel-severity coupling
- `paper/tables/tab11_scale_density.tex` — cells ordered by density, showing they do not trend with it

Figures (`python scripts/extra_figures.py`):
- `results/analysis/figures_paper/figD_scale_fnd.png` — FND vs N, one panel per field size, log axis
- `results/analysis/figures_paper/figE_scale_density.png` — FND vs density, log axis

**TEEN and APTEEN are censored in all nine cells (15/15 runs each).** Their LND is unusable
everywhere in this sweep; use FND or AUC.

## 5. What to add to the paper, and where

This becomes **Section VIII, "Results: Scale and Density"**, about 1.25 pages, placed after the
mechanism section and before threats to validity. Four things go in it.

**A short design paragraph.** The grid, the 15-run choice, and — non-negotiably — the sentence that
cross-cell comparisons are not paired. One sentence stating that the base station scales with the
field and that this couples area to channel severity. Do not bury this; a reviewer who finds it
themselves will distrust the rest.

**Table X and Figure 8** carry the ranking result. The honest statement is *partial* stability:
NSGA-II, GCN, LEACH, PEGASIS and Fuzzy T2 hold their positions across all nine cells; the direct
baseline, DQN, SOM, TEEN and APTEEN move by five or more places. Name the three movements in
Section 4.4 explicitly rather than describing the table.

**Table XI and Figure 9** answer the density question, and the answer is clean: it is neither
neighbours nor ground, it is **distance to the sink**. Tripling node count moves lifetime by under
26%; tripling field side moves it by a factor of 5-7. This is the part of the section no other paper
can offer, because nobody else varies both axes.

**The two results that most strengthen the paper go here, not in the scale section's margins:**

- *Clustering is harmful at 50x50* (Section 4.2). The no-clustering baseline outlives LEACH in all
  three cells at that field size. This turns the paper's opening finding from a statement about some
  nodes into a statement about an operating regime, and it deserves a cross-reference back to
  Section VI.
- *The channel retraction reproduces at 50x50* (Section 4.3), via a completely different route from
  the ideal-channel comparison. Two independent confirmations of the same mechanism is much stronger
  than one, and the untrained fuzzy system acts as the control that rules out transfer failure as
  the explanation. Cross-reference Section VII.

**A transfer paragraph.** Neither learned protocol collapses away from its training configuration —
report this plainly, including that Section 3 predicted the opposite. GCN remains worse than LEACH
in all nine cells, so phrase it as "generalises no worse than it already performs", not as success.

**Two other sections need a sentence added:**

- **Threats to validity** — the scope paragraph currently reads "one scale, one budget, one traffic
  model". Change "one scale" to state that scale was varied across nine configurations while energy
  budget, traffic model and transmit power were not. It strengthens the paper and it is now true.
- **Introduction** — the contributions list gains one item: the scale study. Keep it to one clause.

**One sentence to delete:** anything in the earlier drafts describing a scale sweep as future work.

## 6. One defect this sweep exposed, and the fix

`NSGA2Protocol` writes `results/validation/nsga2_convergence.csv` as a **side effect** of its first
reclustering on run 0, to a fixed path. That artifact is supposed to document the headline
configuration, so the first sweep run silently overwrote it with a 50-node / 50x50 curve — a
validation artifact quietly replaced by one from a configuration the paper never intended to cite.

Fixed by having the write honour `WSN_SUPPRESS_VALIDATION_WRITE`, which `scripts/scale_sweep.py`
sets before any worker spawns. **The first sweep was launched before the fix existed, so
`results/validation/nsga2_convergence.csv` must be restored once it completes** —
`git checkout results/validation/nsga2_convergence.csv`, or regenerate properly with
`python scripts/generate_nsga2_convergence.py`.

Worth knowing generally: any protocol that writes to a fixed path is unsafe under a parameter
sweep. NSGA-II was the only one.

## 7. Honest limitations of this sweep

- Area and channel severity are coupled by the BS placement policy (Section 2). Mean head-to-sink
  distance per cell is the tool for separating them; it is not a substitute for having varied them
  independently.
- 15 runs per cell, half the headline study's power. Small effects that are real may not reach
  significance here.
- Lossy channel only. The ideal-channel sensitivity pair was not repeated across the grid.
- Frozen learned weights everywhere, so gen-3 results away from the centre cell measure transfer,
  not capability.
- `p = 0.05` throughout, giving 3 heads at N=50 and 8 at N=150. Whether the optimal head fraction
  itself varies with scale is a separate question this sweep does not ask.
