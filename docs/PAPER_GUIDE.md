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
rounds and stop being significant. We measured why: LEACH's average cluster head sits 101.8 m from
the base station, past the 87.7 m point where the radio model switches to a much more expensive
distance law, and inside the region where packets start failing and have to be retransmitted. It
burns 6.4% of its energy on retries; the DQN, whose heads average 81.1 m, burns 2.3%. So the real
skill of the newer protocols is keeping that final hop short, and it only pays off in proportion to
how bad the channel is. **This is the paper's most important contribution, and it is a retraction,
not a boast.** (Their advantage in *total network survival* and *readings delivered* is not
conditional — that holds in both channels.)

**3. Learning "over time" is a different skill from learning "about structure".** The DQN and the
GCN see the exact same inputs and differ only in what they are trained to do. The DQN is trained on
a long-term reward and produces the most consistent results in the study (first death at
1472 ± 55 rounds). The GCN optimises a single round at a time and is wildly inconsistent
(335 ± 142 rounds) because it repeatedly re-picks its best-looking node until that node dies. A
neural network is not automatically better; *what you train it on* decides everything.

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

## Part 3 — How to write the paper

### Target

IEEE two-column conference format (IEEEtran), **6–7 pages including references**. That is roughly
5,500–6,000 words of body text once figures, tables and the bibliography take their space. It is
tight. Every paragraph must earn its place.

### The story the paper tells

One sentence: *the standard narrative of steady progress across three generations of WSN
clustering cannot be verified from the published literature because no two protocols were measured
under the same conditions, so we measured them under the same conditions, and the picture is more
complicated than the narrative.*

Everything in the paper should serve that sentence. If a paragraph does not, cut it.

### Section structure and page budget

| # | Section | Budget | Must contain |
|---|---|---|---|
| — | Abstract | 150–200 words | The problem, the method (one harness, 600 runs, paired stats), the four findings, and the channel retraction. The retraction belongs in the abstract — it is the contribution. |
| I | Introduction | ~1 page | The three generations; why published comparisons are not comparable; our fairness-by-construction approach; preview of the four findings; a numbered contributions list; a roadmap sentence. |
| II | System and Radio Model | ~1 page | Field/energy setup, the radio equations, the channel chain, how control traffic is charged, the sensor data process, latency, and the invariants the engine enforces. **Table I** = every parameter. **Fig. 1** = the packet-error curve. |
| III | Protocols | ~1.25 pages | One short paragraph per protocol grouped by generation. **Table II** = the ten configurations vs class, control model, re-clustering cadence, pre-training. Plus the honest subsection on DQN hyperparameters. |
| IV | Experimental Design | ~0.75 page | Paired runs, the two-channel decision rule, the metrics, the timing-measurement artefact, the statistical procedure, the verification gates. |
| V | Results | ~1.75 pages | The four findings, in order, each with numbers and significance. **Table III** + three or four figures. |
| VI | Threats to Validity | ~0.75 page | The control-traffic subsidy, transmit power being bracketed not swept, the pre-training asymmetry, modelling simplifications, scope. |
| VII | Conclusion | ~0.3 page | Synthesis. No new numbers. |
| — | References | ~0.5 page | 25–35 of the 47 in `refs.bib`. |

### Figures — pick four, not fifteen

There are 15 figures in `results/analysis/`. Four fit in 7 pages. Recommended:

1. **The packet-error-vs-distance curve** with the 87.7 m crossover and the 150–158 m base-station
   band marked. This makes Section IV's two-channel decision obvious before the reader reaches it.
2. **Living-nodes-over-time for all ten** (`fig1_alive_nodes.png`). Carries findings 1 and 4 at once.
3. **Paired first-death differences with confidence intervals, lossy and ideal side by side**
   (`fig8_channel_sensitivity.png`). This *is* finding 2 and is the paper's strongest single image.
4. **Head-service concentration, DQN vs GCN.** Carries finding 3.

Latency and computational cost belong in Table III as columns, not as their own plots.

### Writing rules for this paper specifically

**Every number gets its uncertainty and its test.** Not "the fuzzy system improved lifetime" but
"the fuzzy system delayed first node death by 417 rounds (95% CI [X, Y], Holm-corrected p = 0.0004)".
The CI and p-value are already computed in `paired_tests_lossy.csv` — copy them.

**State the assumption where the reader would otherwise be misled, not in a footnote.** Three places
where we deliberately expose a weakness rather than hide it:
- The centralized protocols get their uplink status reports for free (piggybacked on data traffic).
  This is standard in the literature and we adopt it, but it is worth 9–10 percentage points of the
  energy budget, so we quantify it in Section VI rather than letting a reader assume it is nothing.
- Transmit power was fixed, not swept. We ran both endpoints (lossy and ideal), which brackets the
  answer but does not trace the curve between them. Say so.
- The DQN's hyperparameters were revised once after a training divergence. Disclose it, and state
  the stopping rule that was fixed in advance.

**There is no "best protocol" sentence anywhere in this paper, and none can be defended from this
data.** Different protocols win different metrics; the paper's job is to make the trade explicit,
not to crown someone.

**Concise means dense, not vague.** Cut hedging, cut throat-clearing ("It is important to note
that..."), cut any sentence restating the previous one. Do not cut numbers, uncertainties, or
caveats — those are the paper.

**No calibration, ever.** If a result disagrees with a published table, report our result and note
the difference. Never adjust a protocol to match someone else's number.

### If you run out of space

Compress in this order:
1. Section IV-D (the timing-measurement artefact) → three sentences.
2. Protocol descriptions in III → the module docstrings already hold the full specification;
   the paper only needs what differs between them.
3. The fuzzy system's type-reduction detail and the GCN's loss terms → cite and move on.

Do **not** compress: Table I (reproducibility), Section V-C (the retraction), or Section VI.

### Current state of the writing

| Piece | Status |
|---|---|
| `paper/refs.bib` | **Done** — 47 entries on disk. Four carry `% VERIFY` comments to check before camera-ready. |
| Sections I–VII | **Drafted in conversation, not yet written to `.tex` files.** The prose exists; it needs to be committed to `paper/*.tex` with `\cite{}` commands inserted. |
| Abstract | Not written. |
| Tables I, II, III | Not built. Table III should be generated from `headline_lossy.csv`, not hand-typed. |
| Figures | Exist as PNGs; four need selecting and captioning. |

### Before submitting — checklist

- [ ] Every number in the paper traced back to a CSV in `results/analysis/`
- [ ] Every comparison carries a CI and a Holm-corrected p-value
- [ ] Table I matches `wsn_sim/config.py` exactly
- [ ] No number from `results/checkpoint2/` or `checkpoint3/` anywhere
- [ ] The channel retraction appears in the abstract, the introduction, and Section V
- [ ] TEEN/APTEEN lifetime is never quoted without their data yield alongside
- [ ] TEEN/APTEEN lifetime uses `alive_node_auc`, never the censored `lnd`
- [ ] Section VI names the two experiments we did not run (control-traffic ablation, power sweep)
- [ ] The four `% VERIFY` bib entries checked against publisher records
- [ ] Page count is 7 or fewer with references

### The strongest reviewer objection to expect

Section VI ends twice with "this experiment has not been run" — the control-traffic ablation and
the transmit-power sweep. A reviewer may reasonably say that is one unrun experiment too many. If
there is compute available before submission, **run the control-traffic ablation** (charge the
centralized uplink honestly). It retires the single largest confound in the study. The power sweep
only refines a result Section V already establishes at both endpoints.
