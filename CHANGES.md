# CHANGES.md

Review of `wsn_research_final (8).pdf` (13 pages, compiled 09 Sep 2026) against
what an IEEE conference reviewer will actually flag.

Every page reference below is to the compiled PDF. Every section reference is to
the numbered section in that PDF, which matches `paper/sections/*.tex`.

I rendered all 13 pages and read them, rather than working from the text layer,
because the text extraction misreports table alignment. **Tables I, II, III, IV,
V, VI, VII and VIII all render correctly.** If you have been worried about the
tables looking scrambled when you copy text out of the PDF, that is an artifact
of the extractor, not a defect in the paper.

### 0. Read this first: your Overleaf source has drifted from this repo

Two findings only make sense if the `.tex` and `.bib` you compiled from are not
the ones in this repository:

- The reference numbering follows `refs.bib` file order (1.1 below). Compiling
  `paper/main.tex` from this repo does not do that.
- Reference `[27]` prints an author `G. V. Bellemare` that does not exist in this
  repo's `paper/refs.bib`, whose `mnih2015dqn` entry ends `Ostrovski, Georg and
  Hassabis, Demis`.

So the fastest route through most of this list is to **re-sync your Overleaf
project with `paper/` from this repo** rather than patch the two copies
separately. Items marked **[DONE]** below are already fixed in the repo source.

Severity key: **[BLOCK]** a reviewer will raise it, **[FIX]** cheap and clearly
wrong, **[ASK]** a reviewer may probe it, **[OPT]** improves the paper.

---

## 1. Blockers

### 1.1 [BLOCK] References are not numbered in order of first citation

IEEE requires `[1]` to be the first reference cited in the text, `[2]` the
second, and so on. **46 of the 47 references violate this.**

The text cites Akyildiz `[1]`, then Heinzelman, which prints as `[8]`, then
Lindsey as `[10]`, then Manjeshwar as `[11]`, `[12]`, then Younis as `[13]`,
then Abbasi as `[2]`. The bibliography is printing in `refs.bib` file order
instead.

**Where:** the preamble and end matter of whichever `.tex` you compiled from
(not `paper/main.tex` in this repo, which does not have this problem).

**Cause and fix:** this happens when the document contains `\nocite{*}`, or when
the bibliography is a hand-written `thebibliography` block. Delete `\nocite{*}`,
keep

```latex
\bibliographystyle{IEEEtran}
\bibliography{refs}
```

and rerun `pdflatex → bibtex → pdflatex → pdflatex`. BibTeX will renumber in
citation order on its own. The correct first fourteen become:

```
[1] akyildiz2002survey     [8]  deb2002nsga2
[2] heinzelman2000leach    [9]  mendel2002type2
[3] lindsey2002pegasis     [10] karnik2001centroid
[4] manjeshwar2001teen     [11] alsheikh2014ml
[5] manjeshwar2002apteen   [12] kohonen1990som
[6] younis2004heed         [13] mnih2015dqn
[7] abbasi2007clustering   [14] sutton2018rl
```

### 1.2 [BLOCK] [DONE] Fig. 4 is unreadable at the size it is printed

**Where:** page 9, right column, Section V-F.

The source image is 1428 x 549 px and was authored 7.2 inches wide, but it is
placed with `\includegraphics[width=\columnwidth]` in a 3.4-inch column. It
renders about 1.3 inches tall carrying three sub-panels, three sets of axis
labels and a ten-entry legend. In print the legend is illegible.

**Fix:** it was drawn for a two-column span. Change the environment, nothing
else:

```latex
\begin{figure*}[!t]          % was \begin{figure}[!t]
\centering
\includegraphics[width=\textwidth]{figD_scale_fnd.png}   % was \columnwidth
...
\end{figure*}                % was \end{figure}
```

### 1.3 [BLOCK] [DONE] Fig. 2 has the same problem

**Where:** page 7, left column, Section V-B.

1233 x 513 px, authored 7.0 inches wide, placed at column width. It renders
about 1.4 inches tall with ten rotated protocol labels along the x-axis. Same
fix: promote to `figure*` with `width=\textwidth`.

Both figures were generated at 7 inches by `scripts/extra_figures.py`
(`figsize=(7.0, 2.6)` and `(7.2, 2.6)`). They were always meant to span the
page; only the LaTeX environment is wrong.

Page 13 currently ends about one third of the way down, so there is enough slack
to absorb both without adding a page.

### 1.4 [BLOCK] [DONE] The paper promises analytical complexity and never reports it

**Where:** Section IV-D says computational cost is reported in three forms,
"wall-clock setup time, counted algorithmic operations and analytical
complexity, never merged". Section V-E then gives wall-clock and counted
operations only. There is no complexity analysis anywhere in the paper.

This is the kind of internal inconsistency a reviewer notices immediately,
because it is a promise in the methods that the results do not keep.

**Fix, pick one:**

- Drop "and analytical complexity" from Section IV-D (one clause, safest), or
- Add one sentence to Section V-E, for example: *"Analytically, LEACH and the
  reactive protocols are O(N) per round, the fuzzy system and SOM O(kN), PEGASIS
  O(N²) for chain construction, and NSGA-II O(G · P · kN) for G generations of
  population P."* Verify each against the implementation before you state it.

The same paragraph also says timing and memory "are measured in separate runs",
but peak memory is never reported either. It was in the cost table that was cut
for length. Either restore that column or drop the memory clause.

### 1.5 [BLOCK] Page count is wrong for a conference

13 pages with 47 references reads as a journal submission. Most IEEE conferences
cap at 6 pages, or 8 with an over-length charge. If you are targeting a
conference rather than a book chapter or a journal, this needs a hard cut, not
trimming.

**Decide the venue first**, because it changes everything else in this list. If
it is a conference, the realistic path is to cut Sections V-E and V-F and the
whole scale sweep into a follow-up, keeping the channel retraction as the single
contribution.

---

## 2. Figures: what is there, what to add, and exactly where

### Current placement

| | File | Page | Section |
|---|---|---|---|
| Fig. 1 | `figA_per_curve` | 3 | II-C Channel |
| Fig. 2 | `figB_fnd_distribution` | 7 | V-B Lifetime Across the Three Generations |
| Fig. 3 | `figF_head_distance` | 8 | V-C A Conclusion the Channel Sweep Retracts |
| Fig. 4 | `figD_scale_fnd` | 9 | V-F Node Count, Field Area, Regime Boundary |

### Sections that carry argument with no figure

**V-A**, **V-D** and **V-E** have none, and **VI-A** has none. V-A is the
weakest of these, because it states the paper's opening result entirely in prose.

### What to add, in priority order

**(a), (b) and (c) are now applied in the repo source.** The figure list is
now seven, numbering in reading order: Fig. 1 II-C, Fig. 2 V-A, Fig. 3 V-B,
Fig. 4 V-C, Fig. 5 V-D, Fig. 6 V-F, Fig. 7 VI-A.

**(a) `fig1_alive_nodes` into Section V-A.** Highest value. The claim that
clustering redistributes rather than extends lifetime rests on the two survival
curves crossing, and right now the reader has to take that on trust. Paste
immediately after the paragraph ending *"...the two most commonly reported
figures pick opposite ones."*

```latex
\begin{figure}[!t]
\centering
\includegraphics[width=\columnwidth]{fig1_alive_nodes.png}
\caption{Living nodes against round, lossy channel, mean over 30 paired trials.
The direct baseline loses its first node almost immediately and then decays
slowly; the clustered protocols hold a full population far longer and then
collapse. The two shapes cross, which is why no single death point orders these
protocols.}
\label{fig:alive}
\end{figure}
```

Then change that same sentence to end *"...pick opposite ones
(Fig.~\ref{fig:alive})."*

**(b) `figG_head_rotation` into Section V-D.** The DQN-versus-GCN contrast is
the paper's cleanest controlled result and currently has only Table VII. LEACH's
flat line at exactly 55 against the GCN's 750-round spike is the most striking
image in the study. Paste after the paragraph ending *"...at 223 rounds on its
busiest node and a Gini of 0.476."*

```latex
\begin{figure}[!t]
\centering
\includegraphics[width=\columnwidth]{figG_head_rotation.png}
\caption{Rounds served as cluster head per node over 1{,}100 rounds, seed 0,
sorted. LEACH's epoch rule produces a flat line at exactly 55. The GCN
concentrates 750 rounds of head duty on one node while 13 nodes never serve,
which is what its single-round objective is indifferent to.}
\label{fig:rotation}
\end{figure}
```

Note: `figG_head_rotation.png` is 1244 x 434, so it is another wide one. Use
`figure*` with `width=\textwidth`, or accept that it will be short.

**(c) `fig5_control_traffic` into Section VI-A.** The control-traffic subsidy is
named as the largest confound in the paper and has no visual at all. A reviewer
weighing how much to discount your cross-class comparisons would use it. Paste
after *"...most are short-range."*

**(d) `figC_mechanism` into Section V-C**, if space allows. The r = 0.95 scatter
with PEGASIS plotted separately. Section V-C already has two tables and one
figure, so this is the first thing to drop if you are tight.

**(e) `fig6_compute_cost` into Section V-E** and **`figE_scale_density` into
Section V-F**, only if you end up with slack.

All of these already exist under `results/analysis/`. Adding one is a
`figure` block and a caption, not new work.

---

## 3. Correctness and consistency

### 3.1 [FIX] [DONE] Table V prints `0.0004` where the text says `0.00045`

**Where:** Table V, page 8, both `pHolm` columns, against Section V-C which says
*"both at the corrected floor of pHolm = 0.00045"* and Section IV-E which says
*"a corrected floor of pHolm = 0.00045"*.

The table rounds to four decimals and shows `0.0004`. The prose says `0.00045`.
Same number, two renderings, and the table's version is the one that looks
wrong. Reviewers read tables against text.

**Fix:** in `scripts/make_tables.py`, print this column at five decimals, or
switch the table to `< 0.001` and state the exact floor once in the caption.

### 3.2 [FIX] Reference [27] has a corrupted author list

**Where:** page 13.

> V. Mnih, K. Kavukcuoglu, D. Silver, A. A. Rusu, J. Veness, M. G. Bellemare,
> A. Graves, M. Riedmiller, A. K. Fidjeland, G. Ostrovski, **G. V. Bellemare,
> and others**, ...

`G. V. Bellemare` is a duplicated, garbled entry: M. G. Bellemare is already
listed sixth. And `and others` should render as *et al.* The real list continues
S. Petersen, C. Beattie, A. Sadik, and so on.

**Fix:** in `paper/refs.bib`, entry `mnih2015dqn`, replace the author field with
the first six authors followed by `and others`, and let IEEEtran render the
*et al.*

### 3.3 [FIX] Missing comma in the author block

**Where:** page 1, byline.

> Ashish Sharma\*, Yogesh Sharma\* Vansh Tomar†, Satvik Rastogi†, Ansh Rai†

Missing comma after `Yogesh Sharma*`. Small, but it is the first line a reviewer
reads.

### 3.4 [FIX] Literal double hyphen inside Fig. 1

**Where:** page 3, inside the plot, the annotation reads `median node--sink
104 m`. That is a LaTeX-style en dash written into a Matplotlib label, where it
renders as two hyphens. Change to `median node-sink 104 m` in
`scripts/extra_figures.py`.

### 3.5 [FIX] Table II caption points at the wrong granularity

The caption ends *"(Section VI)"*. It should be Section VI-A, which is where the
subsidy is actually quantified.

### 3.6 [ASK] Section V-C claims 18 comparisons with no table to show them

Section V-C states *"all eighteen comparisons against LEACH are significant at
the corrected floor in both channels"*. The table that showed them
(`tab7_paired_robust`) was cut for length. The claim is true and verified, but a
reviewer has to take it on faith while every other statistical claim in the
paper has a table.

**Fix:** if you find space, restore `tab7_paired_robust`. It is still in git
history at commit `34a9b65`.

---

## 4. IEEE conformance

### 4.1 [BLOCK] No repository URL anywhere

The paper says *"All configuration constants, per-round outputs and verification
artifacts are released with the code"* and never says where. For a paper whose
central contribution is reproducibility, this is the first thing a reviewer will
look for and not find.

**Fix:** add a footnote on page 1 or a line in the conclusion with the GitHub URL,
ideally a Zenodo DOI for the archived snapshot.

### 4.2 [FIX] No DOIs in the reference list

None of the 47 entries carry a DOI. Several IEEE venues now require them.
`paper/refs.bib` has `doi = {}` slots ready to fill.

### 4.3 [FIX] Two references still carry `% VERIFY` markers

- `[23]` Kim et al., CHEF (ICACT 2008) has no page numbers.
- `[7]` Pineau et al. lists seven authors then *et al.*, which is unusual; IEEE
  style is either the full list or first author plus *et al.*

Both are marked `% VERIFY` in `paper/refs.bib`. Check them against the originals
before submission.

### 4.4 [OPT] Index Terms are not alphabetical

IEEE convention is alphabetical order. Currently: *Wireless sensor networks,
clustering protocols, network lifetime, energy efficiency, reinforcement
learning, graph neural networks, type-2 fuzzy logic, cluster head selection,
reproducibility.*

### 4.5 [OPT] No copyright or conference identification block

Most IEEE conference templates require the copyright strip on page 1. Add once
you know the venue.

### 4.6 [OPT] Student emails are personal, not institutional

`vanshwar@gmail.com`, `satvikrastogi777@gmail.com`, `raiansh230405@gmail.com`
against `@mait.ac.in` for the faculty authors. Some venues require institutional
addresses.

---

## 5. What a WSN reviewer will probe

### 5.1 [ASK] [DONE] "Why don't your LEACH numbers match Heinzelman's?"

This is the single most likely reviewer question, and the paper's answer is
buried in Section VI-E. The non-calibration policy is a strength, but it reads
as a limitation where it currently sits.

**Fix:** move one sentence of it into Section I, right after *"No protocol is
tuned to reproduce any published number."* Something like: *"Absolute lifetimes
therefore differ from the source papers by construction; what is comparable here
is the ordering under identical conditions, not the magnitudes."*

### 5.2 [ASK] No dedicated Related Work section

The literature is folded into Section I and Section III. A reviewer may ask for a
proper Related Work section with a table of prior evaluation setups: which paper
used which field size, node count, energy budget and channel. That table would
also be direct evidence for the paper's central claim about incomparability,
which is currently asserted rather than shown.

This is the highest-value addition to the paper if you have room.

### 5.3 [ASK] 30 runs, no power analysis

30 paired trials per configuration with a permutation floor of 5 x 10⁻⁵. Defensible,
and the pairing does most of the work, but a statistically minded reviewer may
ask what effect size the design could detect. One sentence would close it.

### 5.4 [ASK] Single sink placement

Every cell of the scale sweep keeps the base station at `(W/2, 1.5W)`. Section
VI-C admits this. A reviewer may still ask for a centre-sink or in-field-sink
comparison, since sink placement is known to dominate WSN lifetime.

### 5.5 [ASK] The control-traffic ablation is named but not run

Section VI-A calls it *"the single most valuable follow-up this codebase
supports. It has not been run."* Honest, and it will still be asked about.
Running it before submission would materially strengthen the paper, because it
converts the largest confound into a measurement.

---

## 6. Ordered plan

If you have a day:

1. Fix the reference numbering (1.1). Hard requirement, ten minutes.
2. Promote Fig. 2 and Fig. 4 to `figure*` (1.2, 1.3). Ten minutes, biggest
   visual gain in the paper.
3. Drop the analytical-complexity and memory clauses from Section IV-D (1.4),
   or add the one sentence that delivers them.
4. Add the repository URL (4.1).
5. Fix Table V's p-value rendering (3.1) and the Mnih reference (3.2).
6. Add `fig1_alive_nodes` to Section V-A (2a).

If you have a week, add on top:

7. Decide the venue and cut to length if it is a conference (1.5).
8. Write the Related Work section with the evaluation-setup table (5.2).
9. Add `figG_head_rotation` and `fig5_control_traffic` (2b, 2c).
10. Run the control-traffic ablation (5.5).
