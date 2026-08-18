# Area and Node Comparison

The scale study: how the ten protocols behave as node count and field area change. Read this to get
the gist without opening a CSV.

**Status: sweep running.** Design and paper-integration guidance below are final. The Results
section is filled in from `results/scale/scale_aggregate.csv` when the run completes; regenerate
with `python scripts/scale_sweep.py --runs 15 --skip-existing`.

---

## 1. What is being varied

A full 3 x 3 grid, lossy channel only, 15 paired runs per cell — 1,350 runs.

| | 50 x 50 m | 100 x 100 m | 150 x 150 m |
|---|---|---|---|
| **N = 50** | 200 nodes/ha | 50 nodes/ha | 22 nodes/ha |
| **N = 100** | 400 nodes/ha | **100 nodes/ha** (headline) | 44 nodes/ha |
| **N = 150** | 600 nodes/ha | 150 nodes/ha | 67 nodes/ha |

The grid is deliberately full rather than a cross. Node count and area jointly determine *density*,
and only a full grid can tell you which of the three actually drives an effect — cells with the same
density but different absolute size (e.g. 50 nodes in 50x50 at 200/ha vs 200 nodes in 100x100)
separate "more neighbours" from "more ground".

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
> taken deliberately; the mean head-to-sink distance is reported per cell so a reader can separate
> the two effects rather than having to trust that they are separable.

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

Stated in advance so the results are read rather than rationalised:

- **Smaller field should lengthen every lifetime**, because transmit energy falls with d^2 and the
  sink hop shrinks. If a protocol does *not* improve at 50x50, that is interesting.
- **The gap between generations should narrow at 50x50.** The measured skill of the gen-2/gen-3
  protocols is keeping the head-to-sink hop inside free space; when every hop is already inside free
  space there is nothing left to win. This is the same mechanism as the ideal-channel retraction, so
  the 50x50 column is effectively a *second, independent* test of it — which makes it valuable.
- **The gap should widen at 150x150**, for the same reason in reverse.
- **Higher density should help clustering and hurt direct transmission**, since more neighbours means
  more readings fused into each packet.
- **DQN and GCN may degrade away from N=100 / 100x100.** Expected; label as transfer.

## 4. Results

*(Pending sweep completion. Populated from `results/scale/scale_aggregate.csv`.)*

Tables generated by `python scripts/make_tables.py --scale`:
- `paper/tables/tab10_scale_fnd.tex` — first node death across all nine cells
- `paper/tables/tab11_scale_density.tex` — density against LEACH and best-of-G2/G3

Figures generated by `python scripts/extra_figures.py`:
- `results/analysis/figures_paper/figD_scale_fnd.png` — FND vs N, one panel per field size
- `results/analysis/figures_paper/figE_scale_density.png` — FND vs density, log axis

## 5. What to add to the paper, and where

This becomes **Section VIII, "Results: Scale and Density"**, about 1.25 pages, placed after the
mechanism section and before threats to validity. Four things go in it.

**A short design paragraph.** The grid, the 15-run choice, and — non-negotiably — the sentence that
cross-cell comparisons are not paired. One sentence stating that the base station scales with the
field and that this couples area to channel severity. Do not bury this; a reviewer who finds it
themselves will distrust the rest.

**Table X and Figure 8** carry the main result: does the ranking established in Section VI hold as
the deployment changes? Write the answer as a direct statement — "the ordering is stable across all
nine configurations" or "protocol X and Y exchange places below N=100" — not as a tour of the table.

**Table XI and Figure 9** answer the density question: is the effect about neighbours or about
ground covered? This is the part of the section a reader cannot get from any other paper, because
nobody else varies both.

**A transfer paragraph.** How the DQN and GCN behave away from their training configuration, framed
explicitly as out-of-distribution transfer. Cross-reference the pre-training disclosure in the
protocols section and the caveat in threats to validity.

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
