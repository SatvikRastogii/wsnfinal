# Paper revision notes

What changed between `wsn_research_final (8).pdf` and the LaTeX source now in
`paper/`, and how every number in the new text was verified.

Read this before you paste anything back into Overleaf. Section 2 lists defects
that were **wrong**, not merely rough, and three of them contradicted the
paper's own tables.

---

## 1. What is now in `paper/`

```
paper/
  main.tex                      IEEEtran skeleton, pulls in sections + tables
  refs.bib                      47 entries, all 47 now cited
  sections/
    00_abstract.tex             abstract + index terms
    01_introduction.tex         I.   Introduction
    02_system_model.tex         II.  System Model
    03_protocols.tex            III. Protocols Under Comparison
    04_experimental_design.tex  IV.  Experimental Design
    05_results.tex              V.   Results
    06_threats.tex              VI.  Threats to Validity
    07_conclusion.tex           VII. Conclusion
  tables/                       12 generated tables (unchanged except em dashes)
```

The section structure is the same seven sections the PDF already had. Nothing
was restructured; the content was corrected, completed and rewritten.

Build with `pdflatex main && bibtex main && pdflatex main && pdflatex main`
from inside `paper/`. There is no LaTeX toolchain on this machine, so the
source has **not** been compile-tested. It passes a static check
(`scratchpad/check_paper.py`) for brace balance, every `\ref` resolving to a
`\label`, and every `\cite` key existing in `refs.bib`.

---

## 2. Defects that were wrong, not just rough

### 2.1 Drafting notes were pasted into the manuscript (5 places)

The PDF contains conversational text that was never meant to be in a paper.
All five are gone. For the record, they were:

- End of §I: *"Two things I flag for you rather than decide silently.
  Contribution 3 is the paper's real novelty and I'd argue it should also
  appear in the abstract... say so and I'll add a sentence."*
- End of §II-G: *"Table I in the file lists all parameters with values: n =
  100, field 100 × 100 m..."*
- Immediately after: *"One correction to what I told you last turn..."*, which
  **breaks off mid-sentence** at "their measured control energy is 2.3–4.0".
- After that: *"Fig. 1 should be the PER-vs-distance curve with the d0 line..."*
- End of §III-D: *"Table II in the file lists the ten configurations against
  class, control-traffic model..."*

The substance inside three of them was real and has been folded into the body:
the abstract now states the retraction, §I now discloses the centralized
subsidy up front, and §II-D now says explicitly that centralized protocols
still pay the per-round TDMA schedule.

### 2.2 The mechanism claim contradicted its own table

`tab8_energy_split.tex` (Table IX in the PDF) carries the corrected caption:
packet error is near zero below 120 m, so the **mean** head distance cannot
explain the retry gap; the **tail** can.

Three places in the PDF body still carried the retracted claim, that LEACH's
102 m average head sits "far enough out to be losing packets": the
introduction, §V-C, and the conclusion. All three now state the tail argument.

The honest framing, which the new text uses, is this. The tail share beyond
120 m correlates with retry energy at r = 0.953. The mean distance correlates
at r = 0.927, which is barely worse, because the two are collinear. **The
reason to prefer the tail is not a better fit but that only the tail lies in
the region where packets actually fail.** Do not let a reviewer read the
correlation as the argument; the mechanism is the argument.

PEGASIS is stated as an explicit exclusion rather than dropped quietly: it has
the same 30% tail as LEACH and 1.39% retry, because only its leader faces the
sink. Including it drops r from 0.95 to 0.50.

### 2.3 "Over-serving its busiest node fivefold" (conclusion)

Table XII says 13.6×, and the caption of `tab12_head_rotation.tex` says 13.6.
Verified: GCN busiest node 750 rounds, LEACH 55, ratio 13.64. Corrected.

### 2.4 "The DQN posts the tightest first-death distribution of any protocol"

False, and it contradicted §V-B four paragraphs earlier, which correctly said
NSGA-II has the tightest spread. Over 30 trials:

| protocol | std | min | max | spread |
|---|---|---|---|---|
| NSGA-II | 30.7 | 1806 | 1921 | 115 |
| LEACH | 43.1 | 979 | 1142 | 163 |
| DQN | 54.8 | 1361 | 1580 | 219 |
| GCN | 141.6 | 94 | 482 | 388 |

The PDF's "DQN 1404 to 1530, spread 126" and "GCN spans 350" are **first-five-
seed** figures presented as if they were across all seeds. Both replaced with
the 30-trial figures. The DQN-vs-GCN contrast that §V-D needs still holds and
is now stated on those numbers.

Note also that the direct baseline has the tightest spread of all (std 10.7),
so the new text says "tightest of the nine clustering protocols".

### 2.5 NSGA-II convergence figures matched no artifact

The PDF says round energy improves 0.70%, minimum head energy 3.1%, and
cluster-size balance moves 5.9 → 1.79. These match **neither** committed
version of `results/validation/nsga2_convergence.csv`.

They predate the change that moved convergence logging off round 0. The class
docstring in `wsn_sim/protocols/nsga2.py` explains why round 0 was abandoned:
every node still holds exactly `e0`, so f2 is pinned at −e0 for all 30
generations and carries zero information. Logging now fires at the first
reclustering after round 800 at which residual energy has genuinely diverged.

Read from the shipped artifact:

| quantity | gen 0 | gen 29 | change |
|---|---|---|---|
| best round energy (f1) | 0.039129 | 0.038441 | −1.76% |
| best min head energy (f2) | −0.5878 | −0.6090 | +3.61% |
| best cluster-size spread (f3) | 2.99 | 1.85 | |
| knee cluster-size spread | 9.19 | 5.58 | |

The qualitative finding is unchanged and still worth reporting: convergence is
modest on the energy objectives and substantial only on cluster-size balance.

`docs/STATUS.md` and `docs/TRADEOFFS.md` carried the same stale numbers and
have been updated, with a note so they do not get copied forward again.

### 2.6 Survivorship-bias figures were slightly off

The PDF says the direct baseline's delivery ratio rises from 81.6% over its
first hundred rounds to 99.0% over its last hundred. Recomputed from
`results/lossy/raw/stub/run_*.csv` over all 30 runs: **83.7% → 98.6%**.
Corrected. The point is unaffected.

### 2.7 Mean head distances were off in the inline table

The PDF's §V-C contains a small inline table duplicating Table IX, and it gives
LEACH 101.8 m and GCN 77.2 m against the probe's 102.1 and 77.1. The duplicate
table has been deleted (Table IX covers it) and the two numbers in the prose
now match the artifact.

### 2.8 Two broken cross-references

`(Section ??)` appears twice, in the captions of Tables II and IV. Cause: both
captions say `\ref{sec:validity}`, but Threats to Validity was written as an
unnumbered section, which is why it prints with no roman numeral in the PDF and
cannot be referenced. `main.tex` now uses `\section{Threats to Validity}` with
`\label{sec:validity}`, and the same for the conclusion.

### 2.9 Every figure caption was the literal text "1"

All nine render as "Fig. N. 1". Nine real captions are now written into the
sections, each one saying what the figure shows and what to read from it.

### 2.10 Tables X and XI had no prose

The scale-sweep tables float in the PDF with nothing in the body reading them.
The results section now has §V-G, *Node Count, Field Area, and the Regime
Boundary*, covering all of it.

### 2.11 Stale claims contradicted by the sweep

- §VI-C: *"nothing here supports a claim that either policy transfers to a
  different density, field size, or sink placement."* The sweep measures
  exactly that. Rewritten to say what is now measured and what still is not
  (retrained comparison, non-similar sink placement).
- §VI-E: *"There is no scalability sweep."* There is. Rewritten.

---

## 3. Numbers verified against artifacts

Every number in the new text was read from a file. Spot-check list:

| claim | value | source |
|---|---|---|
| LEACH / direct FND | 1046 / 114 | `headline_lossy.csv` |
| LEACH / direct LND | 2191 / 3202 (46% later) | same |
| Fuzzy, DQN vs LEACH FND, lossy | +416.6, +426.3 @ p_Holm 0.00045 | `paired_tests_lossy.csv` |
| same, ideal | +17.4 @ 0.1195, +21.9 @ 0.1244 | `paired_tests_ideal.csv` |
| Holm floor | 0.00045 (raw 5e-5) | same |
| Fuzzy AUC gain | +24,793 lossy / +22,120 ideal | both |
| PER at 100/120/140/158 m | 2.6e-8 / 1.0e-3 / 0.194 / 0.969 | `per_calibration.csv` |
| SNR span of the waterfall | 14.62 → 11.04 dB = 3.58 dB | same |
| retry % / control % / mean d / tail>120 m | Table IX values | `energy_probe.csv` |
| r(tail, retry), six single-hop | 0.9532 | computed from same |
| r(mean, retry), six single-hop | 0.9274 | computed from same |
| r with PEGASIS included | 0.5035 | computed from same |
| head duty: GCN 750, LEACH 55 | ratio 13.64 | `head_service_counts.csv` |
| GCN distinct heads / never served | 87 / 13 over 1100 rounds | same |
| GCN first five seeds | 448, 394, 418, 112, 98 | `lossy/summary/gcn_summary.csv` |
| GCN bimodality | 8 runs in 94–151, 22 in 284–482 | same |
| nodes inside d0 | 36 of 100 on seed 0; 32.7% expected | probe + 2e7-sample integration |
| NSGA-II ops / setup | 86,348 / 102.89 ms | `headline_lossy.csv` |
| DQN vs fuzzy ops and time | 8210 in 0.52 ms vs 2301 in 5.14 ms | same |
| control packets | LEACH 171,644; TEEN 573,870; centralised 9,657–12,216 | same |
| PEGASIS aggregation ratio | 182,179 readings / 2,272 packets = 80 | same |
| TEEN/APTEEN data yield, reporting rate | 0.109 / 0.121, 0.155 / 0.168 | summaries |
| TEEN AUC vs LEACH | 3.20× | `headline_lossy.csv` |
| LEACH total energy vs DQN | 68.02 J vs 56.44 J = +20.5% | `energy_probe.csv` |
| area vs node count | ×0.88–1.26 vs ×5–7 | `scale_aggregate.csv` |
| LEACH/direct FND ratio at 50×50 | 0.82 / 0.83 / 0.95 | same |
| at 100×100 and 150×150 | 5.4–9.8 and 6.7–16.1 | same |
| DQN vs LEACH at 50×50 | −291 / +10 / +91 | same |
| Fuzzy vs LEACH at 50×50 | −135 / +68 / +112 | same |
| NSGA-II vs LEACH, all nine cells | +394 to +1,177 | same |
| GCN deficit, smallest → largest field | −1,409/−1,591 → −84/−272 | same |
| density range | 22 to 600 nodes/ha, factor 27 | same |
| rank spans (FND) | NSGA-II 1–3, GCN 9–10, TEEN 1→6 | computed from same |
| rank spans (AUC) | ≤4 places except direct (7) | computed from same |
| mean sink distance / % beyond 120 m | 52/0%, 104/33%, 156/75% | analytic + probe |

**One number is not from the headline table and is labelled as such in the
text.** The claim that the GCN's true setup cost is ~35% higher than LEACH's
(0.819 vs 0.607 ms) comes from the diagnostic benchmark recorded in
`docs/ASSUMPTIONS.md`, not from `headline_lossy.csv`, where the same pair reads
0.878 vs 0.817 ms (+7.5%). Different machine, different run. The sign of the
comparison, which is the point being made, is the same in both.

---

## 4. Style pass

- **No em dashes anywhere.** Checked programmatically across all 21 `.tex`
  files. Five table captions also had them and were rewritten (the tables are
  regenerated by `scripts/make_tables.py`, so if you re-run it, re-apply the
  fix or edit the generator).
- Spelling normalized to American forms throughout (56 + 19 replacements),
  matching the generated tables and IEEE house style; the PDF mixed
  "optimisation"/"organizes" mix, which was inconsistent.
- Sentences that ran on through three semicolons were split. Lists that were
  "First... Second... Third..." with no other structure were kept only where
  they are genuinely enumerations.
- The abstract now states the retraction and the scale sweep. Both were missing.

---

## 5. Length

Body text is about 12,300 words. With 12 tables and 9 figures that lands near
16 pages in IEEEtran two-column, roughly where the current PDF sits.

If you need 12 pages, cut in this order. Each item is self-contained.

1. §IV-F Verification, down to three sentences. Point at the repo. (~350 words)
2. §IV-E A Measurement Artifact Worth Reporting, down to a footnote. It is a
   good observation but it is about our harness, not about clustering. (~300)
3. §V-F Cost and Latency, keep Table V and cut the prose to the one point that
   matters, that counted operations and wall-clock disagree in sign. (~250)
4. §II-F Latency, cut to the equation plus the lower-bound caveat. (~150)
5. §VI-D Modelling Simplifications, merge the static-network and sensor-data
   paragraphs. (~200)
6. Drop Fig. 2 (alive nodes) and Fig. 8 (scale density); both duplicate a table.

Do **not** cut, in order of how much a reviewer will miss them: §V-C the
retraction, §V-D the DQN/GCN contrast, §V-G the regime boundary, §VI-A the
control-traffic subsidy.

---

## 6. Still open

- The manuscript has not been compiled. Static checks pass; float placement,
  overfull boxes and page count are unverified.
- The control-traffic ablation is still the largest remaining confound and has
  not been run. It is named as such in §VI-A and in the conclusion.
- Four `refs.bib` entries carry `% VERIFY` comments (Kim CHEF page numbers,
  truncated author lists for Mnih, Harris and Pineau). Check those against the
  originals before submission.
- The author block in `main.tex` reproduces the PDF's, which lists Ashish
  Sharma and Yogesh Sharma as Assistant Professors and the other three as
  students. Confirm the affiliation lines are how you want them.
