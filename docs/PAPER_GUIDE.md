# Paper Guide — read this before writing or reviewing anything

Plain-language explanation of what this project is, what lives where in the repository, and how
the paper should be written. Written for a colleague who has not touched the code.

If you only read one paragraph: **we built one simulator, ran nine WSN clustering protocols inside
it under provably identical conditions, and measured what actually differs between them. The paper
reports those measurements, states every assumption that could have bent them, and retracts one
finding that did not survive a sensitivity check.**

---

## Part 1 — What the project is, in simple terms

### The problem we are solving

A wireless sensor network is a field of small battery-powered nodes that sense something and send
it to a base station. Sending directly to a far-away base station drains batteries fast, so
protocols group nodes into *clusters*: one node per cluster becomes the *cluster head*, collects
its neighbours' readings, fuses them, and sends one packet onward. Which node becomes the head, and
how often that rotates, is what every protocol in this study argues about.

Over twenty-five years, three generations of ideas appeared:

| Generation | Idea | Protocols here |
|---|---|---|
| One (1999–2002) | Simple rules of thumb. Rotate the head randomly; or chain nodes together; or only report when the reading changes. | LEACH, PEGASIS, TEEN, APTEEN |
| Two (2000s) | Write down what "good" means as a maths objective, then search for it. | NSGA-II (multi-objective genetic algorithm), Type-2 Fuzzy logic |
| Three (2015+) | Do not write the rule; learn it from data. | SOM, DQN (reinforcement learning), GCN (graph neural network) |

**The trouble with the literature:** every one of these protocols was published with numbers
showing it beating the previous one — but each was measured in a *different* simulator, with
different field sizes, different radio constants, different packet sizes, different assumptions
about what control traffic costs. Those numbers cannot be compared with each other. The graph you
often see, showing steady improvement across the generations, is stitched together from
incompatible experiments.

### What we did about it

We built one simulation engine and ran all nine inside it, plus a tenth "no clustering at all"
baseline for reference. The important design decision is this:

> **The engine owns everything a protocol could cheat on. A protocol is only allowed to answer one
> question: "who are the cluster heads this round, and who reports to whom?" Everything else —
> energy accounting, packet sizes, the radio, the channel, fusion cost, counting delivered
> readings — is done by the engine, identically, for all ten.**

That means fairness is not something we *promise*; it is something the code structure makes
impossible to violate. A script (`scripts/fairness_audit.py`) checks this automatically by parsing
the source code and confirming no protocol ever touches the energy arrays.

On top of that, run number *i* generates the same node positions, the same radio conditions, and
the same sensor readings for *every* protocol. So protocol A and protocol B at run 7 faced the
literally identical world, and the difference between them is a *paired* observation — which is
what lets us do proper statistics instead of eyeballing averages.

### The setup being simulated

100 nodes scattered at random in a 100 m x 100 m field. Base station outside the field at
(50, 150), so it is 150–158 m away from the far side. Each node starts with 1 Joule. Data packets
are 4000 bits, control packets 200 bits. The simulation runs up to 7000 rounds, or until every
node is dead. 30 runs per protocol, and the whole thing is run twice — once with a realistic lossy
radio channel, once with a perfect channel — giving 600 runs total (80 minutes on 14 cores).

### What we found (the four things the paper claims)

**1. Clustering does not extend life; it redistributes it.** LEACH delays the *first* node death by
9.2x compared to no clustering (1046 rounds vs 114), but the *last* node dies about 32% *earlier*
(2191 vs 3202). The reason is geometric: 36 of the 100 nodes sit within 87.7 m of the base station
and could reach it on the cheap short-range radio law, so clustering makes them pay for distant
neighbours instead of helping them. Whether
clustering "wins" depends entirely on which lifetime number you quote — and the two most commonly
quoted numbers rank the protocols in opposite directions.

**2. The advantage of the modern protocols is partly an artefact of the channel — and we say so.**
Under the lossy channel, the fuzzy system and the DQN beat LEACH on first-node-death by 417 and 426
rounds, statistically significant. Switch to a perfect channel and those gaps collapse to 17 and 22
rounds and stop being significant. We measured why. LEACH picks cluster heads without caring how far
they are from the base station, so **30% of its head-rounds are spent by a node more than 120 m
away**, which is where packets start failing badly and have to be retransmitted. The DQN puts 0.2%
of its head-rounds out there. LEACH burns 6.4% of its energy on retries; the DQN burns 2.3%. (Note
it is the *tail* that does this, not the average — both protocols' average head distance, 102 m and
81 m, sits below the failure region.) So the real skill of the newer protocols is keeping that final
hop short, and it only pays off in proportion to how bad the channel is. **This is the paper's most important contribution, and it is a retraction,
not a boast.** (Their advantage in *total network survival* and *readings delivered* is not
conditional — that holds in both channels.)

**3. Learning "over time" is a different skill from learning "about structure".** The DQN and the
GCN see the exact same inputs and differ only in what they are trained to do. The DQN is trained on
a long-term reward and produces the most consistent results in the study (first death at
1472 ± 55 rounds). The GCN optimises a single round at a time and is wildly inconsistent
(335 ± 142 rounds) because it repeatedly re-picks its best-looking node until that node dies — we
measured this: over 1100 rounds its busiest node served as head **750 times**, against LEACH's
55. A neural network is not automatically better; *what you train it on* decides everything.

**4. Reactive protocols buy life by not sending data, and the price must be quoted.** TEEN and
APTEEN only report when a reading crosses a threshold. They survive past the 7000-round cap in
every single run, with more than 3x LEACH's total node-alive time. But they deliver only 11–12% of
the readings taken, against about 90% for the others. That is a real trade, not a free win, and any
paper reporting their lifetime without their data yield is misleading the reader.

### The one rule that governs the whole project

**We never tuned anything to match a published number.** The source paper this study started from
had numeric results we discarded entirely; we took only its protocol descriptions, its radio model,
and its simulation parameters. Where our results disagree with published tables, that is the
expected outcome, not a bug. This is written into `docs/STATUS.md` as a locked decision and should
never be re-litigated.

---

## Part 2 — What is in the repository

```
wsnkhechu/
├── wsn_sim/              THE ENGINE — the thing that must be trusted
│   ├── config.py         Every physical constant in one frozen dataclass. Nothing else
│   │                     anywhere defines a constant. Start here to understand parameters.
│   ├── radio.py          Energy per transmit/receive, path loss, BER, packet error rate.
│   ├── network.py        Node positions, energy, the sensor data process, and `spend()` —
│   │                     the SINGLE place energy is ever deducted. The fairness backbone.
│   ├── engine.py         Runs a round: collects the protocol's cluster plan, moves packets,
│   │                     charges energy, retries lost packets, counts deliveries.
│   ├── metrics.py        Turns per-round records into the summary numbers we report.
│   ├── nn.py             Tiny hand-written neural net layers (NumPy, no PyTorch).
│   └── protocols/        THE NINE PROTOCOLS + a baseline. Each returns a cluster
│       ├── stub.py       "no clustering" baseline — every node talks straight to the BS
│       ├── leach.py      pegasis.py  teen.py  apteen.py        (generation one)
│       ├── nsga2.py      fuzzy_t2.py                            (generation two)
│       ├── som.py        dqn.py      gcn.py                     (generation three)
│       └── base.py       the interface every protocol implements
│
├── run_experiments.py    Runs the full sweep (10 protocols x 30 runs x 2 channels).
├── analyze.py            Turns raw results into tables, statistics and figures.
│
├── scripts/
│   ├── train_dqn.py      Offline pre-training for the DQN (seeds 100–129, then frozen)
│   ├── train_gcn.py      Offline pre-training for the GCN
│   ├── fairness_audit.py 18 automated checks that no protocol can cheat
│   ├── check_determinism.py  Runs everything twice and diffs — proves reproducibility
│   └── generate_nsga2_convergence.py
│
├── models/               The frozen trained weights (dqn_weights.npz, gcn_weights.npz)
│
├── tests/                7 test files. All pass. test_engine.py is the big one (540 lines)
│                         and includes the energy-conservation proof.
│
├── results/
│   ├── lossy/            THE HEADLINE RESULTS (realistic channel)
│   ├── ideal/            THE SENSITIVITY CHECK (perfect channel)
│   │   └── each contains raw/ (per-round CSVs), summary/ (per-run), aggregate.csv
│   ├── analysis/         ← EVERYTHING THE PAPER QUOTES COMES FROM HERE
│   │   ├── REPORT.md              readable summary of all tables and tests
│   │   ├── headline_lossy.csv     the main results table
│   │   ├── headline_ideal.csv     same under the perfect channel
│   │   ├── paired_tests_*.csv     statistical comparisons with corrected p-values
│   │   ├── channel_robustness.csv which rankings change between the two channels
│   │   ├── figures_lossy/fig1–7   figures_ideal/fig1–7   fig8_channel_sensitivity.png
│   ├── validation/       per_calibration.csv (the channel's error curve), learning curves
│   ├── checkpoint2/, checkpoint3/   OLD 5-run scratch results. DO NOT CITE THESE.
│   └── README.md         what every column in every CSV means
│
├── docs/
│   ├── STATUS.md         Read first after any break. Locked decisions, what passed.
│   ├── ASSUMPTIONS.md    1060 lines. Every assumption, numbered, with its reason.
│   ├── TRADEOFFS.md      430 lines. The paper-facing limitations document —
│   │                     Section VI of the paper is essentially a compression of this.
│   ├── METRICS.md        What each metric means and why it is defined that way.
│   └── PAPER_GUIDE.md    ← this file
│
└── paper/
    └── refs.bib          47 references, grouped by the section that cites them.
```

### Where each part of the paper gets its facts

| Paper section | Source in the repo |
|---|---|
| System model, Table I (parameters) | `wsn_sim/config.py` — copy the values, do not retype from memory |
| Radio equations | `wsn_sim/radio.py` |
| Channel error curve (Fig. 1) | `results/validation/per_calibration.csv` |
| Protocol descriptions | the docstring at the top of each file in `wsn_sim/protocols/` |
| DQN/GCN training details | `scripts/train_dqn.py`, `scripts/train_gcn.py` |
| Results, Table III | `results/analysis/headline_lossy.csv` |
| All p-values and confidence intervals | `results/analysis/paired_tests_lossy.csv` and `_ideal.csv` |
| The channel retraction | `results/analysis/channel_robustness.csv` + `fig8` |
| Threats to validity | `docs/TRADEOFFS.md` |

**Rule: never type a number into the paper from memory or from an old draft. Open the CSV.**

---

## Part 3 — How to write the paper (12 pages)

### Target

IEEE two-column format (IEEEtran), **12 pages including references**. That is roughly 10,000–11,000
words of body text once figures, tables and the bibliography take their space — nearly double the
6–7 page version, which changes the writing job qualitatively, not just quantitatively.

**What the extra five pages are for.** They are not for padding the same argument. They buy four
things a short paper cannot carry:

1. **A real related-work section.** At 7 pages the literature had to be compressed into the
   introduction. At 12 it becomes Section II, where each generation's assumptions can be stated and
   the incomparability argument can be *demonstrated* with a table of published evaluation setups
   rather than asserted in a sentence.
2. **Protocol descriptions a reader could reimplement from.** At 7 pages we cited and gestured. At
   12, each protocol gets its objective function, its decision rule, and its complexity written out.
3. **Mechanism, not just outcome.** The retraction in Section VII is far more convincing when the
   energy split, the head-distance distribution and the head-rotation pattern are all shown. That
   evidence exists (`scripts/energy_probe.py`) and it did not fit before.
4. **The scale sweep.** Nine node-count/area configurations is a section, not a paragraph.

**What must not expand.** Threats to validity stays proportionally the same size; it does not become
apologetic. The conclusion stays short. Resist the temptation to restate results in the conclusion
because there is room — there is never room for that.

### The story the paper tells

Unchanged from the short version, and it must stay the spine: *the standard narrative of steady
progress across three generations of WSN clustering cannot be verified from the published
literature because no two protocols were measured under the same conditions, so we measured them
under the same conditions, and the picture is more complicated than the narrative.*

The extra pages let us add a second thread underneath it: *where a protocol puts its cluster heads
relative to the radio's crossover distance and the channel's error waterfall explains most of what
separates these ten configurations, and that is a geometric fact rather than an algorithmic one.*

### Section structure and page budget

| # | Section | Pages | Contents |
|---|---|---|---|
| — | Abstract | — | Problem, method (one harness, 600 headline runs + 1,350 scale runs, paired stats), the four findings, the channel-conditional retraction. |
| I | Introduction | 1.25 | The three generations; why published comparisons are not comparable; fairness by construction; the four findings previewed; numbered contributions; roadmap. |
| II | Related Work | 1.25 | Generation by generation, with **Table A** (published evaluation setups side by side) as the evidence for the incomparability claim. Ends by positioning this study. |
| III | System and Radio Model | 1.25 | Field/energy, radio equations, the channel chain, control-traffic accounting, sensed data, latency, engine-enforced invariants. **Table I**, **Fig. A**. |
| IV | Protocols Under Comparison | 2.0 | Four subsections by generation, each protocol with its rule and complexity. **Table II**. Includes the DQN hyperparameter disclosure. |
| V | Experimental Design | 1.0 | Paired runs, the two-channel decision rule, the metric definitions, the timing artefact, the statistical procedure, the verification gates. |
| VI | Results: The Common Environment | 2.0 | Findings 1–4 at N=100, 100×100. **Tables III, IV, V**, **Figs. B, 1, 4**. |
| VII | Results: Mechanism | 1.0 | Why the differences exist. **Tables VI, VII, VIII**, **Figs. F, G**. This is the section the short paper could not afford and it is the most persuasive one. |
| VIII | Results: Scale and Density | 1.25 | The 3×3 sweep. **Tables X, XI**, **Figs. D, E**. |
| IX | Threats to Validity | 0.75 | Unchanged in scope from the short version. |
| X | Conclusion | 0.4 | Synthesis, no new numbers. |
| — | References | 0.85 | 35–45 of the 47 in `refs.bib`. |

Splitting results into three sections (VI outcome, VII mechanism, VIII scale) is the single most
useful structural change the extra pages allow. A reader can accept VI, be convinced by VII, and
check the generality in VIII.

### Tables — twelve, all generated, none hand-typed

Run `python scripts/make_tables.py --scale`. Output lands in `paper/tables/*.tex`, one complete
float per file, ready for `\input{}`. The preamble needs `\usepackage{booktabs}`.

| File | Table | Section | What it carries |
|---|---|---|---|
| `tab1_parameters.tex` | I | III | Every simulation constant, read live from `config.py`. Reproducibility depends on this one. |
| `tab2_taxonomy.tex` | II | IV | The ten configurations: generation, head-selection rule, control model, re-clustering cadence, offline training. |
| `tab3_lifetime.tex` | III | VI | FND, HND, LND, AUC with censoring flagged. |
| `tab4_delivery.tex` | IV | VI | Packets at BS, readings delivered, PDR, data yield. |
| `tab5_cost.tex` | V | VI | Latency, p95, control packets, ops/round, setup ms, peak memory. |
| `tab6_paired_fnd.tex` | VI | VII | **The retraction.** ΔFND vs LEACH with CIs and Holm-corrected p, lossy and ideal side by side. |
| `tab7_paired_robust.tex` | VII | VII | AUC and readings vs LEACH in both channels — the conclusions that survive. |
| `tab8_energy_split.tex` | VIII | VII | Retry %, control %, and head-to-sink distance **including the tail** (p90, share beyond 120 m). |
| `tab12_head_rotation.tex` | IX | VII | Head-duty concentration: busiest node, median, nodes that never served, Gini. |
| `tab9_robustness.tex` | X | VII | Every rank that moves between channels (4 of 40). |
| `tab10_scale_fnd.tex` | XI | VIII | FND across all nine node/area cells. |
| `tab11_scale_density.tex` | XII | VIII | Density in nodes/ha against LEACH and best-of-G2/G3 lifetime. |

Twelve generated tables is more than a 12-page paper can carry comfortably. If you need to cut one,
cut Table IX (robustness) and fold its single sentence — "four of forty ranks move, all single-place
swaps" — into the Section VII text.

**Table A (related-work setups) is the one table you must build by hand**, because it summarises
other people's papers, not our data: columns for protocol, year, N, field size, BS placement, energy
model, channel model, and runs reported. Filling it in is what makes the incomparability argument
evidence instead of opinion. Expect most cells in "channel model" to read "none" and most in "runs
reported" to read "1" or "unstated" — that *is* the argument.

### Figures — nine, and what each one is for

Existing set from `analyze.py` in `results/analysis/figures_lossy/`, plus new ones from
`python scripts/extra_figures.py` in `results/analysis/figures_paper/`.

| Figure | File | Section | Why it earns space |
|---|---|---|---|
| Fig. 1 | `figA_per_curve.png` | III | Packet error against distance, with d₀ = 87.7 m, the measured median node-to-sink distance (104 m), the interquartile band (81–128 m), and where LEACH and DQN actually put their heads. Makes the whole two-channel design decision obvious before the reader reaches it. |
| Fig. 2 | `figures_lossy/fig1_alive_nodes.png` | VI | Living nodes over time, all ten. Carries findings 1 and 4 at once. |
| Fig. 3 | `figB_fnd_distribution.png` | VI | All 30 first-death values per protocol, not a mean ± std bar. Shows GCN's bimodality and DQN's tightness directly, and reveals PEGASIS as the widest-spread protocol in the study. |
| Fig. 4 | `figures_lossy/fig4_lifetime_vs_delivery.png` | VI | The lifetime/delivery trade. This is where TEEN and APTEEN's data yield is priced. |
| Fig. 5 | `fig8_channel_sensitivity.png` | VII | FND and delivery across both channels. **This is the retraction in one image** and is the paper's strongest single figure. |
| Fig. 6 | `figF_head_distance.png` | VII | Box plots of every head-to-sink distance per protocol, overlaid on the error curve. The honest mechanism figure — see the correction note below. |
| Fig. 7 | `figG_head_rotation.png` | VII | Rounds served as head per node, ranked. LEACH's epoch is perfectly flat; the learned protocols are not. |
| Fig. 8 | `figD_scale_fnd.png` | VIII | FND against N, one panel per field size. |
| Fig. 9 | `figE_scale_density.png` | VIII | FND against node density on a log axis, collapsing the 3×3 grid onto its underlying variable. |

Held back: `fig2_lifetime_points`, `fig3_energy`, `fig5_control_traffic`, `fig6_compute_cost`,
`fig7_pdr_survivorship`, and the entire `figures_ideal/` set. Their content is in Tables III–V and
Fig. 5. If a reviewer asks for them, they go in a supplement.

### A correction that changes what Section VII may claim

An early version of Fig. 1 shaded 150–158 m as "the sink hop". **That is the far-corner distance,
not the typical one.** Measured over 30 topologies, node-to-sink distance runs 50–158 m with a
median of 104 m and an interquartile range of 81–128 m. Packet error is essentially zero below
120 m, 0.19 at 140 m and 0.70 at 150 m.

This matters because it changes the mechanism claim. Both LEACH's mean head distance (102 m) and
DQN's (81 m) sit *below* the waterfall, so **the mean cannot explain the retry-energy gap.** The
tail can, and does. Measured at 300 rounds on seed 0:

| | LEACH | DQN |
|---|---|---|
| mean head-to-sink | 102.2 m | 73.9 m |
| 90th percentile | 143.5 m | 95.2 m |
| head-rounds beyond 120 m | **30.0%** | **0.2%** |
| retry energy share | 6.66% | 2.22% |

So the correct sentence for Section VII is: *LEACH places nearly a third of its head-rounds beyond
120 m, where the packet error rate climbs steeply, while the DQN places almost none there; the
retry-energy gap follows from that tail, not from the difference in means.* Do not write "LEACH's
average head sits inside the error region" — it does not.

The full probe (seed 0, 1100 rounds, `results/analysis/energy_probe.csv`) makes this quantitative
across all seven protocols. Share of head-rounds beyond 120 m against retry energy share, excluding
PEGASIS: **Pearson r = 0.95, Spearman ρ = 0.89**. The tail predicts the retry cost.

| | LEACH | SOM | NSGA-II | Fuzzy T2 | DQN | GCN |
|---|---|---|---|---|---|---|
| mean head-to-sink (m) | 102.1 | 102.8 | 94.2 | 85.6 | 81.1 | 77.1 |
| 90th percentile (m) | 143.5 | 136.4 | 127.5 | 122.1 | 111.2 | 104.6 |
| head-rounds beyond 120 m | 29.9% | 31.1% | 17.7% | 11.5% | 5.1% | 3.2% |
| retry energy share | 6.39% | 5.28% | 3.57% | 3.65% | 2.31% | 2.25% |

**PEGASIS must be excluded from that correlation, and the paper should say why.** Its leader rotates
uniformly, so 30% of its leader-rounds are beyond 120 m — identical to LEACH — yet it spends only
1.39% on retries, because almost all of its traffic is short chain hops and only the leader ever
faces the sink. The tail statistic predicts retry cost *within single-hop protocols*; it is not a
general law, and presenting it as one would be exactly the kind of overreach this paper is arguing
against.

### A second finding the mechanism probe turned up

**LEACH's head rotation is perfectly even and the learned protocols' is not.** Over 1100 rounds:

| | busiest node (rounds as head) | nodes that never served | median | Gini |
|---|---|---|---|---|
| LEACH | 55 | 0 | 55.0 | 0.001 |
| PEGASIS | 11 | 0 | 11.0 | 0.000 |
| NSGA-II | 95 | 0 | 60.0 | 0.207 |
| Fuzzy T2 | 360 | 4 | 40.0 | 0.416 |
| DQN | 223 | 16 | 38.0 | 0.476 |
| GCN | **750** | 13 | 16.5 | **0.700** |

LEACH's 55 is not approximately even, it is exactly even: the epoch mechanism makes every node head
exactly once per 20 rounds, so 1100/20 = 55 for all 100 nodes. GCN's busiest node served 750 of 1100
rounds — **13.6 times LEACH's busiest** — which is the direct cause of its 335-round first node
death. It is not that GCN chooses badly; it chooses the same good node over and over until that node
dies.

This is worth a paragraph in Section VII because it complicates the ranking honestly. The DQN wins
first-node-death while distributing head duty far less evenly than LEACH, so it is buying lifetime
by *choosing well*, not by *sharing fairly* — and a deployment that cares about node-level wear, or
about which specific nodes fail first, would weigh those two strategies differently. It also gives
the generation-three contrast a second dimension: DQN and GCN differ not only in consistency but in
how concentrated their head duty is (Gini 0.48 vs 0.70).

### Writing rules for this paper specifically

**Every number gets its uncertainty and its test.** Not "the fuzzy system improved lifetime" but
"the fuzzy system delayed first node death by 417 rounds (95% CI [+393, +440], Holm-corrected
p < 0.0001)". Those values are already in `paired_tests_lossy.csv` and already rendered in
`tab6_paired_fnd.tex` — copy from the table, never retype.

**State the assumption where the reader would otherwise be misled, not in a footnote.** Three places
where we deliberately expose a weakness:
- Centralized protocols get their uplink status reports free (piggybacked on data traffic). Standard
  in the literature, adopted here, worth 9–10 percentage points of the energy budget — quantified in
  Section IX rather than left for a reader to discover.
- Transmit power was fixed, not swept. Both endpoints were run, which brackets the answer without
  tracing the curve between them.
- The DQN's hyperparameters were revised once after a training divergence. Disclose it with the
  pre-registered stopping rule attached.

**With twelve pages there is room to show the reader the negative results, so show them.** SOM is
worse than LEACH on first node death (−87 rounds, p = 0.0015). GCN is much worse (−710). Do not
bury these in a table; a generation-three protocol losing to a 1999 heuristic is informative about
what learning does and does not buy, and a paper that reports it is more credible than one that
does not.

**There is no "best protocol" sentence anywhere, and none can be defended from this data.**
Different protocols win different metrics; the job is to make the trade explicit.

**Concise still applies.** Twelve pages is a budget, not a licence. Cut hedging, throat-clearing,
and any sentence restating the previous one. Do not cut numbers, uncertainties, or caveats.

**No calibration, ever.** If a result disagrees with a published table, report ours and note the
difference.

### If you run out of space at 12 pages

Compress in this order:
1. Section V-D (the timing-measurement artefact) → three sentences.
2. Section IV protocol descriptions → the module docstrings hold the full specification; the paper
   needs only what differs between them.
3. Fig. 4 → its content is recoverable from Table IV.
4. Section VIII → the density figure alone can carry it, with the tables moved to a supplement.

Do **not** compress: Table I, Section VII (mechanism), the retraction, or Section IX.

### Current state of the writing

| Piece | Status |
|---|---|
| `paper/refs.bib` | **Done** — 47 entries. Four carry `% VERIFY` comments to check before camera-ready. |
| `paper/tables/*.tex` | **Done** — nine generated from the CSVs; two more after the scale sweep finishes. |
| `results/analysis/figures_paper/` | **Done** — Figs. A, B, F, G generated; D and E after the sweep. |
| Sections I, III, IV, V, VI, IX, X | **Drafted in conversation at 6–7 page length**, not yet written to `.tex`. Need expanding to the budget above and committing to files with `\cite{}` inserted. |
| Section II (Related Work) | **Not written** — new at 12 pages. Needs Table A built by hand from the cited papers. |
| Section VII (Mechanism) | **Not written** — new at 12 pages. Data exists in `results/analysis/energy_probe.csv`. |
| Section VIII (Scale) | **Not written** — see `docs/AREA_AND_NODE_COMPARISON.md`. |
| Abstract | Not written. |

### Before submitting — checklist

- [ ] Every number traced to a CSV in `results/analysis/` or a generated table
- [ ] Every comparison carries a CI and a Holm-corrected p-value
- [ ] Table I regenerated after any config change (`python scripts/make_tables.py --scale`)
- [ ] No number from `results/checkpoint2/` or `checkpoint3/` anywhere
- [ ] The channel retraction appears in the abstract, the introduction, and Section VII
- [ ] Section VII says "tail", not "mean", when explaining the retry gap
- [ ] TEEN/APTEEN lifetime never quoted without their data yield alongside
- [ ] TEEN/APTEEN lifetime uses `alive_node_auc`, never the censored `lnd`
- [ ] Section VIII states that cross-cell comparisons are not paired and are not tested as if they were
- [ ] Section IX names the two experiments not run (control-traffic ablation, power sweep)
- [ ] The four `% VERIFY` bib entries checked against publisher records
- [ ] Page count is 12 or fewer with references

### The strongest reviewer objection to expect

Section IX ends twice with "this experiment has not been run" — the control-traffic ablation and the
transmit-power sweep. At 12 pages a reviewer has more reason to expect them, not less, because the
space objection no longer applies. If there is compute before submission, **run the control-traffic
ablation**; it retires the largest confound in the study. The power sweep only refines a result
already established at both endpoints.
