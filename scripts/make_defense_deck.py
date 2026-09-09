"""Generate the Minor Project Second Defense deck (12 slides, 16:9).

Content follows the notice dated 3.9.2026: title, problem statement, abstract,
introduction (scope/motivation/challenges), literature survey, technology stack,
architecture, prototype, references. One results slide uses the tenth allowance,
because a second defense is judged on progress.

Every number on the slides is read from the study's own artifacts under
results/ and matches paper/sections/. Nothing here is rounded differently from
the manuscript.

    python scripts/make_defense_deck.py
"""

import os
import sys

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN
from pptx.util import Emu, Inches, Pt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIGS_PAPER = os.path.join(ROOT, "results", "analysis", "figures_paper")
FIGS_LOSSY = os.path.join(ROOT, "results", "analysis", "figures_lossy")
OUT = os.path.join(ROOT, "Minor_Project_Second_Defense.pptx")

W, H = 13.333, 7.5

NAVY = RGBColor(0x1B, 0x33, 0x5F)
INK = RGBColor(0x2B, 0x2B, 0x2B)
GREY = RGBColor(0x66, 0x6B, 0x73)
TEAL = RGBColor(0x0F, 0x77, 0x73)
RUST = RGBColor(0xA8, 0x3A, 0x1E)
RULE = RGBColor(0xD8, 0xDD, 0xE3)
WASH = RGBColor(0xF4, 0xF6, 0xF8)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)

FONT = "Calibri"


# ---------------------------------------------------------------- primitives

def textbox(slide, x, y, w, h):
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = box.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    return tf


def para(tf, first=False):
    return tf.paragraphs[0] if first else tf.add_paragraph()


def write(p, text, size=18, color=INK, bold=False, italic=False, space=6,
          line=1.15, align=PP_ALIGN.LEFT):
    p.alignment = align
    p.space_after = Pt(space)
    p.line_spacing = line
    r = p.add_run()
    r.text = text
    r.font.name = FONT
    r.font.size = Pt(size)
    r.font.bold = bold
    r.font.italic = italic
    r.font.color.rgb = color
    return p


def rect(slide, x, y, w, h, fill, line=None):
    s = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y),
                               Inches(w), Inches(h))
    s.fill.solid()
    s.fill.fore_color.rgb = fill
    if line is None:
        s.line.fill.background()
    else:
        s.line.color.rgb = line
        s.line.width = Pt(0.75)
    s.shadow.inherit = False
    return s


def blank(prs):
    return prs.slides.add_slide(prs.slide_layouts[6])


def header(slide, title, kicker=None, n=None):
    """Standard slide head: thin navy rule, kicker, title, slide number."""
    rect(slide, 0.62, 0.52, 1.15, 0.055, TEAL)
    y = 0.72
    if kicker:
        tf = textbox(slide, 0.62, y, 11.0, 0.3)
        write(para(tf, True), kicker.upper(), size=12, color=TEAL, bold=True,
              space=0)
        y += 0.36
    tf = textbox(slide, 0.62, y, 12.1, 0.75)
    write(para(tf, True), title, size=30, color=NAVY, bold=True, space=0)
    if n is not None:
        tf = textbox(slide, 12.1, 6.85, 0.65, 0.3)
        write(para(tf, True), str(n), size=11, color=GREY, align=PP_ALIGN.RIGHT,
              space=0)


def bullets(tf, items, size=17, gap=9, bullet_color=TEAL):
    """items: list of str, or (lead, rest) to bold the lead-in."""
    for i, it in enumerate(items):
        p = para(tf, i == 0)
        p.space_after = Pt(gap)
        p.line_spacing = 1.18
        b = p.add_run()
        b.text = "▪  "
        b.font.name = FONT
        b.font.size = Pt(size)
        b.font.color.rgb = bullet_color
        if isinstance(it, tuple):
            lead, rest = it
            r = p.add_run()
            r.text = lead
            r.font.name = FONT
            r.font.size = Pt(size)
            r.font.bold = True
            r.font.color.rgb = NAVY
            r2 = p.add_run()
            r2.text = rest
            r2.font.name = FONT
            r2.font.size = Pt(size)
            r2.font.color.rgb = INK
        else:
            r = p.add_run()
            r.text = it
            r.font.name = FONT
            r.font.size = Pt(size)
            r.font.color.rgb = INK


def picture_fit(slide, path, x, y, w, h):
    """Place a picture inside an (x, y, w, h) box, preserving aspect ratio."""
    from PIL import Image
    iw, ih = Image.open(path).size
    scale = min(w / (iw / 96), h / (ih / 96))
    pw, ph = (iw / 96) * scale, (ih / 96) * scale
    return slide.shapes.add_picture(path, Inches(x + (w - pw) / 2),
                                    Inches(y + (h - ph) / 2),
                                    width=Inches(pw), height=Inches(ph))


def caption(slide, x, y, w, text):
    tf = textbox(slide, x, y, w, 0.5)
    write(para(tf, True), text, size=11, color=GREY, italic=True, space=0,
          align=PP_ALIGN.CENTER)


# -------------------------------------------------------------------- slides

def slide_title(prs):
    s = blank(prs)
    rect(s, 0, 0, W, H, NAVY)
    rect(s, 0, 0, 0.28, H, TEAL)

    tf = textbox(s, 1.15, 0.95, 11.0, 0.4)
    write(para(tf, True), "MAHARAJA AGRASEN INSTITUTE OF TECHNOLOGY", size=15,
          color=RGBColor(0x9F, 0xC3, 0xC1), bold=True, space=3)
    write(para(tf), "Department of Computer Science and Engineering", size=13,
          color=RGBColor(0x9F, 0xC3, 0xC1), space=0)

    tf = textbox(s, 1.15, 2.05, 11.0, 2.2)
    write(para(tf, True),
          "Evolution and Unified Performance Evaluation of Clustering "
          "Techniques in Heterogeneous Wireless Sensor Networks",
          size=36, color=WHITE, bold=True, space=0, line=1.12)

    rect(s, 1.15, 4.45, 1.5, 0.05, TEAL)

    tf = textbox(s, 1.15, 4.85, 5.4, 1.5)
    write(para(tf, True), "Presented by", size=12,
          color=RGBColor(0x9F, 0xC3, 0xC1), bold=True, space=5)
    write(para(tf), "Vansh Tomar", size=17, color=WHITE, space=2)
    write(para(tf), "Satvik Rastogi", size=17, color=WHITE, space=2)
    write(para(tf), "Ansh Rai", size=17, color=WHITE, space=0)

    tf = textbox(s, 7.0, 4.85, 5.2, 1.5)
    write(para(tf, True), "Under the guidance of", size=12,
          color=RGBColor(0x9F, 0xC3, 0xC1), bold=True, space=5)
    write(para(tf), "Ashish Sharma", size=17, color=WHITE, space=2)
    write(para(tf), "Yogesh Sharma", size=17, color=WHITE, space=2)
    write(para(tf), "Assistant Professors, Dept. of CSE", size=12,
          color=RGBColor(0xB9, 0xC4, 0xD2), space=0)

    tf = textbox(s, 1.15, 6.55, 11.0, 0.4)
    write(para(tf, True), "Minor Project  |  Second Defense  |  September 2026",
          size=13, color=RGBColor(0x9F, 0xC3, 0xC1), bold=True, space=0)


def slide_problem(prs):
    s = blank(prs)
    header(s, "The comparison everyone makes does not actually hold",
           "Problem Statement", 2)

    tf = textbox(s, 0.62, 2.0, 7.2, 4.2)
    bullets(tf, [
        ("Twenty-five years of protocols, three generations. ",
         "Heuristics, then explicit optimization, then learned selection."),
        ("Each was measured on its own simulator. ",
         "Field size, node count, packet length, energy budget and channel all "
         "differ between papers."),
        ("Almost always against LEACH alone, ",
         "and almost always on a channel with no packet loss."),
        ("The assumptions that decide the winner go unstated. ",
         "Whether a centralized protocol pays for its uplink is worth a quarter "
         "of the entire energy budget."),
        ("Which death point you report can reverse a ranking, ",
         "and the author picks which one to publish."),
    ], size=16, gap=13)

    rect(s, 8.15, 2.0, 4.55, 3.15, WASH, RULE)
    tf = textbox(s, 8.45, 2.3, 3.95, 2.6)
    write(para(tf, True), "So the question we ask", size=13, color=TEAL,
          bold=True, space=10)
    write(para(tf),
          "When a paper reports a margin over LEACH, is that evidence about "
          "the algorithm, or evidence about the harness it was measured in?",
          size=16, color=INK, space=10, line=1.2)
    write(para(tf),
          "Right now there is no way to tell them apart.",
          size=16, color=RUST, bold=True, space=0, line=1.2)

    tf = textbox(s, 0.62, 6.25, 12.1, 0.7)
    write(para(tf, True),
          "Aim:  build one benchmark in which all three generations run under "
          "provably identical physical conditions, with every modeling choice "
          "disclosed.",
          size=16, color=NAVY, bold=True, space=0, line=1.15)


def slide_abstract(prs):
    s = blank(prs)
    header(s, "What we built and what it found", "Abstract", 3)

    tf = textbox(s, 0.62, 1.95, 12.1, 4.6)
    bullets(tf, [
        ("Nine clustering protocols plus a no-clustering baseline ",
         "run on a single engine that owns energy accounting, packet sizing, "
         "fusion, the channel and the counting of delivered readings. A "
         "protocol returns only a cluster structure."),
        ("Trials are paired. ",
         "At a given run index every protocol sees the same topology, the same "
         "per-link shadowing and the same sensor readings, so differences are "
         "tested with sign-flip permutation, paired bootstrap intervals and "
         "Holm correction."),
        ("1,950 runs in total: ",
         "600 across two channel configurations, and 1,350 across a grid of "
         "three node counts by three field areas."),
        ("Bracketing transmit power retracts one of our own comparisons. ",
         "The fuzzy and deep Q-network advantage over LEACH is +417 and +426 "
         "rounds with packet loss, and falls to +17 and +22 rounds, no longer "
         "significant, once loss is removed."),
        ("The scale sweep finds the same boundary from the other side. ",
         "Distance to the sink sets the regime, not node density, and in a "
         "50 x 50 m field clustering is worse than no clustering at all."),
    ], size=16, gap=15)


def slide_intro(prs):
    s = blank(prs)
    header(s, "Scope, motivation and the hard parts", "Introduction", 4)

    cols = [
        ("SCOPE", TEAL, [
            "10 configurations, 3 generations, 1 engine",
            "100 nodes in 100 x 100 m, sink at (50, 150)",
            "Two channels: with and without packet loss",
            "Nine deployment scales, 50 to 150 m fields",
            "Homogeneous, static nodes; failure by energy only",
        ]),
        ("MOTIVATION", NAVY, [
            "A designer choosing a protocol today cannot get a straight "
            "answer out of the literature",
            "Reported gains are entangled with the harness that produced them",
            "Learned protocols are arriving fast, with no common yardstick "
            "against the heuristics they claim to beat",
        ]),
        ("CHALLENGES", RUST, [
            "Fairness has to be structural, not promised in prose",
            "Topology variance is larger than the differences between "
            "protocols, so unpaired tests waste their power",
            "Unspecified parameters, transmit power above all, can decide "
            "the ranking outright",
            "Accounting choices are worth more than the algorithms",
        ]),
    ]
    x = 0.62
    for name, colour, items in cols:
        rect(s, x, 1.95, 3.86, 0.05, colour)
        tf = textbox(s, x, 2.2, 3.86, 0.35)
        write(para(tf, True), name, size=13, color=colour, bold=True, space=0)
        tf = textbox(s, x, 2.75, 3.86, 3.6)
        bullets(tf, items, size=14, gap=11, bullet_color=colour)
        x += 4.13

    tf = textbox(s, 0.62, 6.55, 12.1, 0.5)
    write(para(tf, True),
          "Standing rule: no protocol is tuned to reproduce a published "
          "number. Disagreement with the source tables is expected, not an "
          "error.",
          size=14, color=GREY, italic=True, space=0)


def slide_litsurvey(prs):
    s = blank(prs)
    header(s, "Three generations of answers to one question",
           "Literature Survey", 5)

    rows = [
        ("Gen.", "Protocol", "How it picks the cluster head", "Ref."),
        ("G1", "LEACH", "Probabilistic threshold with an epoch constraint",
         "Heinzelman 2000"),
        ("G1", "PEGASIS", "No clusters; greedy nearest-neighbor chain",
         "Lindsey 2002"),
        ("G1", "TEEN / APTEEN", "LEACH clustering; suppress by sensed-value "
         "threshold", "Manjeshwar 2001, 2002"),
        ("G2", "NSGA-II", "Multi-objective search, three objectives, knee point",
         "Deb 2002"),
        ("G2", "Type-2 Fuzzy", "27-rule interval type-2 base, Karnik-Mendel "
         "reduction", "Mendel 2002"),
        ("G3", "SOM", "Kohonen map over position and residual energy",
         "Kohonen 1990"),
        ("G3", "DQN", "Learned Q-value ranking, temporal credit assignment",
         "Mnih 2015"),
        ("G3", "GCN", "Learned graph scoring over a 6-NN graph", "Kipf 2017"),
    ]
    left, top, width = 0.62, 1.95, 8.1
    tbl = s.shapes.add_table(len(rows), 4, Inches(left), Inches(top),
                             Inches(width), Inches(3.4)).table
    for w, c in zip((0.6, 1.75, 4.05, 1.7), range(4)):
        tbl.columns[c].width = Inches(w)
    for i, row in enumerate(rows):
        tbl.rows[i].height = Inches(0.34)
        for j, val in enumerate(row):
            cell = tbl.cell(i, j)
            cell.text = val
            cell.margin_left = Inches(0.07)
            cell.margin_top = Inches(0.02)
            cell.margin_bottom = Inches(0.02)
            cell.fill.solid()
            cell.fill.fore_color.rgb = NAVY if i == 0 else (
                WASH if i % 2 else WHITE)
            p = cell.text_frame.paragraphs[0]
            p.line_spacing = 1.0
            for r in p.runs:
                r.font.name = FONT
                r.font.size = Pt(12 if i else 12)
                r.font.bold = i == 0
                r.font.color.rgb = WHITE if i == 0 else INK

    rect(s, 9.05, 1.95, 3.67, 3.4, WASH, RULE)
    tf = textbox(s, 9.32, 2.2, 3.15, 2.95)
    write(para(tf, True), "THE GAP WE FOUND", size=12, color=RUST, bold=True,
          space=10)
    write(para(tf),
          "The comparability problem is itself a documented finding in network "
          "simulation.",
          size=14, color=INK, space=9, line=1.2)
    write(para(tf),
          "Kurkowski (2005) and Pawlikowski (2002) show that most published "
          "simulation studies cannot be reproduced or compared.",
          size=14, color=INK, space=9, line=1.2)
    write(para(tf),
          "Nobody has applied that lesson to clustering protocols across all "
          "three generations. That is our gap.",
          size=14, color=RUST, bold=True, space=0, line=1.2)

    tf = textbox(s, 0.62, 5.6, 12.1, 1.0)
    write(para(tf, True),
          "What none of them share: a common simulator, a common channel "
          "model, a common energy budget, or a stated position on who pays for "
          "control traffic. Every one of those four decides the ranking.",
          size=15, color=NAVY, space=0, line=1.2)


def slide_stack(prs):
    s = blank(prs)
    header(s, "Deliberately small, and that is the point", "Technology Stack", 6)

    groups = [
        ("Core", TEAL, [
            "Python 3.11",
            "NumPy for every numerical path",
            "pandas for aggregation",
            "Matplotlib for all figures",
        ]),
        ("Scale and testing", NAVY, [
            "multiprocessing, 14 to 16 workers",
            "pytest, plus 18 static audit checks",
            "Deterministic seeding by keyed hash",
        ]),
        ("Writing", RUST, [
            "LaTeX with IEEEtran",
            "Tables generated from CSVs, never typed",
            "Git for the full history",
        ]),
    ]
    x = 0.62
    for name, colour, items in groups:
        rect(s, x, 1.95, 3.86, 2.35, WASH, RULE)
        rect(s, x, 1.95, 3.86, 0.05, colour)
        tf = textbox(s, x + 0.28, 2.2, 3.3, 0.3)
        write(para(tf, True), name.upper(), size=12, color=colour, bold=True,
              space=0)
        tf = textbox(s, x + 0.28, 2.62, 3.3, 1.6)
        bullets(tf, items, size=14, gap=8, bullet_color=colour)
        x += 4.13

    rect(s, 0.62, 4.55, 12.1, 2.15, RGBColor(0xFB, 0xF3, 0xEE),
         RGBColor(0xE6, 0xCC, 0xBE))
    tf = textbox(s, 1.0, 4.8, 11.3, 1.85)
    write(para(tf, True), "WHAT WE LEFT OUT ON PURPOSE", size=12, color=RUST,
          bold=True, space=9)
    write(para(tf),
          "No PyTorch, no TensorFlow, no SciPy. The backpropagation for both "
          "the deep Q-network and the graph network is hand-written NumPy, "
          "verified against central finite differences.",
          size=16, color=INK, space=7, line=1.18)
    write(para(tf),
          "Per-round setup time is one of our reported metrics. If one "
          "protocol ran on an optimized C++ backend and another on plain "
          "Python, that column would measure the framework, not the algorithm.",
          size=16, color=INK, space=0, line=1.18)


def slide_architecture(prs):
    s = blank(prs)
    header(s, "Fairness is enforced by the code, not promised in the write-up",
           "Architecture", 7)

    rect(s, 0.62, 1.9, 5.85, 2.05, RGBColor(0xEF, 0xF5, 0xF5),
         RGBColor(0xC3, 0xD9, 0xD8))
    tf = textbox(s, 0.95, 2.1, 5.2, 1.75)
    write(para(tf, True), "THE ENGINE OWNS", size=12, color=TEAL, bold=True,
          space=8)
    write(para(tf),
          "Energy, through one charging function  •  packet sizing  "
          "•  the fusion charge  •  the channel and its ARQ retries  "
          "•  TDMA slots and latency  •  counting delivered readings",
          size=15, color=INK, space=0, line=1.2)

    rect(s, 6.87, 1.9, 5.85, 2.05, WASH, RULE)
    tf = textbox(s, 7.2, 2.1, 5.2, 1.75)
    write(para(tf, True), "A PROTOCOL RETURNS", size=12, color=NAVY, bold=True,
          space=8)
    write(para(tf),
          "A set of cluster head identities, and a membership map.",
          size=15, color=INK, space=8, line=1.2)
    write(para(tf), "Nothing else. It cannot touch energy or liveness.",
          size=15, color=RUST, bold=True, space=0, line=1.2)

    tf = textbox(s, 0.62, 4.2, 12.1, 2.4)
    bullets(tf, [
        ("Paired seeding. ",
         "Run index i generates the positions, the initial energies, the "
         "per-link shadowing matrix and the full sensor stream. That order "
         "depends only on i, never on which protocol is running."),
        ("A static audit, 18 checks. ",
         "Confirms no protocol implementation writes to the energy or liveness "
         "arrays, calls the charging function, or picks its own packet sizes."),
        ("Three invariants the engine will not let a protocol break. ",
         "Transmissions execute in hop-depth order, a fusing node emits at most "
         "one packet, and the engine counts delivered readings itself rather "
         "than letting a protocol declare its own."),
        ("Conservation, asserted every run. ",
         "Energy in equals energy out to 1e-9 J. That single assertion is the "
         "primary correctness check on the whole simulator."),
    ], size=15, gap=11)


def slide_prototype(prs):
    s = blank(prs)
    header(s, "The simulator runs end to end today", "Prototype", 8)

    tf = textbox(s, 0.62, 1.95, 6.0, 4.4)
    bullets(tf, [
        ("All 10 configurations implemented ",
         "and passing verification."),
        ("1,950 runs complete. ",
         "600 for the headline channel pair in 80 minutes on 16 cores, 1,350 "
         "for the scale grid in 222 minutes on 14."),
        ("Seven verification gates, all green. ",
         "Energy conservation, hand-checked radio energies either side of the "
         "crossover, an invariant suite, determinism, the static audit, an "
         "independent recomputation, and the packet-error curve."),
        ("Reproducible exactly. ",
         "Three repeats per seed diff to zero on every per-round field for all "
         "nine protocols."),
        ("Outputs. ",
         "Per-round CSVs for every run, 14 figures, and every LaTeX table in "
         "the paper generated straight from those CSVs rather than typed by "
         "hand."),
    ], size=15, gap=11)

    picture_fit(s, os.path.join(FIGS_LOSSY, "fig1_alive_nodes.png"),
                6.95, 1.95, 5.8, 4.05)
    caption(s, 6.95, 6.05, 5.8,
            "Living nodes against round, lossy channel, averaged over 30 "
            "paired trials. The baseline and the clustered protocols cross, "
            "which is why we report four lifetime measures rather than one.")


def slide_results_headline(prs):
    s = blank(prs)
    header(s, "What we found, and the one thing we take back",
           "Results I: Lifetime and the Channel", 9)

    tf = textbox(s, 0.62, 1.9, 7.05, 4.6)
    bullets(tf, [
        ("Clustering redistributes lifetime, it does not extend it. ",
         "LEACH reaches first node death at 1,046 rounds against the "
         "baseline's 114, a factor of 9.2. But its last node dies at 2,191 "
         "against the baseline's 3,202, so the baseline outlasts it by 46%."),
        ("We retract one of our own comparisons. ",
         "The fuzzy system and the deep Q-network beat LEACH by 417 and 426 "
         "rounds under packet loss, at the corrected floor. Remove the loss "
         "and the same comparisons give 17 and 22 rounds, no longer "
         "significant."),
        ("The cause is the tail, not the average. ",
         "Packet error is near zero below 120 m and every protocol's mean head "
         "distance sits below that, so the mean cannot be it. LEACH puts 29.9% "
         "of its head-rounds beyond 120 m and spends 6.39% of its budget "
         "retransmitting; the Q-network puts 5.1% out there and spends 2.31%."),
        ("What survives both channels. ",
         "Area under the alive-node curve and readings delivered: all 18 "
         "comparisons hold at the corrected floor either way."),
    ], size=15, gap=12)

    picture_fit(s, os.path.join(FIGS_PAPER, "figF_head_distance.png"),
                7.95, 2.0, 4.8, 3.55)
    caption(s, 7.95, 5.6, 4.8,
            "Head-to-sink distance per protocol, drawn over the packet-error "
            "curve. Every mean sits in the flat region; only the tails reach "
            "the waterfall.")

    rect(s, 7.95, 6.25, 4.8, 0.72, RGBColor(0xFB, 0xF3, 0xEE),
         RGBColor(0xE6, 0xCC, 0xBE))
    tf = textbox(s, 8.2, 6.42, 4.35, 0.5)
    write(para(tf, True),
          "Across the six single-hop protocols, tail share predicts retry "
          "energy at r = 0.95.",
          size=13, color=RUST, bold=True, space=0, line=1.15)


def slide_results_scale(prs):
    s = blank(prs)
    header(s, "The same boundary, found from a completely different direction",
           "Results II: Scale", 10)

    left = [
        ("1,350 more runs. ",
         "Three node counts by three field areas, 15 paired runs per cell, "
         "with the learned policies frozen at their 100-node weights."),
        ("Area beats node count about five to one. ",
         "Tripling the nodes moves first death by 0.88 to 1.26 times. "
         "Tripling the field side moves it by 5 to 7."),
    ]
    right = [
        ("Distance to the sink is the variable, not density. ",
         "Density spans a factor of 27 and explains almost none of it."),
        ("Clustering is harmful when the sink is close. ",
         "At 50 x 50 m the no-clustering baseline outlives LEACH in all three "
         "cells, so the retraction reproduces without touching the channel."),
    ]
    for x, items in ((0.62, left), (6.95, right)):
        tf = textbox(s, x, 1.9, 5.78, 1.9)
        bullets(tf, items, size=14, gap=9)

    picture_fit(s, os.path.join(FIGS_PAPER, "figD_scale_fnd.png"),
                2.35, 3.72, 8.6, 3.3)
    caption(s, 2.35, 6.98, 8.6,
            "First node death across the nine cells, log scale, colour by "
            "generation. Field size shifts everything by an order of "
            "magnitude; node count barely moves it. Two of our five "
            "pre-registered expectations were wrong, and we report both.")


def slide_conclusion(prs):
    s = blank(prs)
    header(s, "What holds, what we are not claiming, and what is left",
           "Conclusion and Remaining Work", 11)

    cols = [
        ("WHAT HOLDS", TEAL, [
            "Fairness is structural: the engine owns energy, the protocol "
            "returns only a cluster structure",
            "Every conclusion is tested paired, corrected across the family",
            "The channel retraction and the DQN/GCN contrast are both "
            "within-class, so the accounting subsidy does not touch them",
        ]),
        ("WHAT WE ARE NOT CLAIMING", RUST, [
            "Centralized protocols are not charged for their uplink. That is "
            "worth 9 to 10 points of the energy budget",
            "Transmit power is bracketed at two endpoints, not swept",
            "No MAC layer, no idle listening, no mobility, no hardware "
            "testbed",
        ]),
        ("WHAT REMAINS", NAVY, [
            "The control-traffic ablation, which converts our largest "
            "confound into a measurement",
            "A three-point or four-point transmit-power sweep",
            "Paper submission: draft complete at 13 pages, figures and tables "
            "generated from the data",
        ]),
    ]
    x = 0.62
    for name, colour, items in cols:
        rect(s, x, 1.95, 3.86, 0.05, colour)
        tf = textbox(s, x, 2.2, 3.86, 0.35)
        write(para(tf, True), name, size=13, color=colour, bold=True, space=0)
        tf = textbox(s, x, 2.75, 3.86, 3.5)
        bullets(tf, items, size=14, gap=11, bullet_color=colour)
        x += 4.13

    rect(s, 0.62, 6.1, 12.1, 0.75, WASH, RULE)
    tf = textbox(s, 0.95, 6.3, 11.5, 0.5)
    write(para(tf, True),
          "The methodological point generalizes: running a study at both "
          "endpoints of an unspecified parameter, and committing in advance to "
          "report only what survives both, retracted a comparison that either "
          "endpoint alone would have supported.",
          size=14, color=NAVY, bold=True, space=0, line=1.15)


def slide_references(prs):
    s = blank(prs)
    header(s, "References", None, 12)

    refs_l = [
        "[1] W. R. Heinzelman, A. Chandrakasan and H. Balakrishnan, "
        "“Energy-Efficient Communication Protocol for Wireless Microsensor "
        "Networks,” Proc. HICSS, 2000.",
        "[2] S. Lindsey and C. S. Raghavendra, “PEGASIS: Power-Efficient "
        "Gathering in Sensor Information Systems,” Proc. IEEE Aerospace "
        "Conf., 2002.",
        "[3] A. Manjeshwar and D. P. Agrawal, “TEEN: A Routing Protocol for "
        "Enhanced Efficiency in Wireless Sensor Networks,” Proc. IPDPS "
        "Workshops, 2001.",
        "[4] K. Deb, A. Pratap, S. Agarwal and T. Meyarivan, “A Fast and "
        "Elitist Multiobjective Genetic Algorithm: NSGA-II,” IEEE Trans. "
        "Evol. Comput., vol. 6, no. 2, 2002.",
        "[5] J. M. Mendel and R. I. B. John, “Type-2 Fuzzy Sets Made "
        "Simple,” IEEE Trans. Fuzzy Syst., vol. 10, no. 2, 2002.",
        "[6] T. Kohonen, “The Self-Organizing Map,” Proc. IEEE, vol. "
        "78, no. 9, 1990.",
    ]
    refs_r = [
        "[7] V. Mnih et al., “Human-Level Control Through Deep "
        "Reinforcement Learning,” Nature, vol. 518, 2015.",
        "[8] T. N. Kipf and M. Welling, “Semi-Supervised Classification "
        "with Graph Convolutional Networks,” Proc. ICLR, 2017.",
        "[9] S. Kurkowski, T. Camp and M. Colagrosso, “MANET Simulation "
        "Studies: The Incredibles,” ACM SIGMOBILE MC2R, vol. 9, no. 4, "
        "2005.",
        "[10] K. Pawlikowski, H.-D. J. Jeong and J.-S. R. Lee, “On "
        "Credibility of Simulation Studies of Telecommunication Networks,” "
        "IEEE Commun. Mag., vol. 40, no. 1, 2002.",
        "[11] T. S. Rappaport, Wireless Communications: Principles and "
        "Practice, 2nd ed. Prentice Hall, 2002.",
        "[12] S. Holm, “A Simple Sequentially Rejective Multiple Test "
        "Procedure,” Scand. J. Statist., vol. 6, no. 2, 1979.",
    ]
    for x, refs in ((0.62, refs_l), (6.87, refs_r)):
        tf = textbox(s, x, 1.85, 5.85, 4.5)
        for i, r in enumerate(refs):
            write(para(tf, i == 0), r, size=12, color=INK, space=11, line=1.15)

    rect(s, 0.62, 6.1, 12.1, 0.6, WASH, RULE)
    tf = textbox(s, 0.95, 6.26, 11.4, 0.4)
    write(para(tf, True),
          "The manuscript cites 47 references in full. Configuration constants, "
          "per-round outputs and verification artifacts are released with the "
          "code.",
          size=13, color=GREY, italic=True, space=0)


# ----------------------------------------------------------------------- main

def main():
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(W), Inches(H)

    for fn in (slide_title, slide_problem, slide_abstract, slide_intro,
               slide_litsurvey, slide_stack, slide_architecture,
               slide_prototype, slide_results_headline,
               slide_results_scale, slide_conclusion, slide_references):
        fn(prs)

    prs.save(OUT)
    print(f"wrote {OUT}  ({len(prs.slides.__iter__.__self__._sldIdLst)} slides)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
