# script.md

Speaking script for the Minor Project Second Defense, 10 slides, three speakers
rotating.

**Total: about 10 minutes**, which leaves room for questions. Times are the
target for each slide. If you are running long, the compressible slides are
marked. Do not compress slides 8 and 9.

## Who speaks when

| Slide | Speaker |
|---|---|
| 1. Title | **Vansh** |
| 2. Problem Statement | **Satvik** |
| 3. Abstract | **Ansh** |
| 4. Introduction | **Vansh** |
| 5. Literature Survey | **Satvik** |
| 6. Technology Stack | **Ansh** |
| 7. Architecture | **Vansh** |
| 8. Prototype | **Satvik** |
| 9. Results | **Ansh** |
| 10. References and close | **Vansh** |

Vansh 4 slides, Satvik 3, Ansh 3. Swap freely, but keep the rotation so nobody
speaks twice in a row.

**One rule that matters more than the words:** whoever is not speaking should be
looking at the panel, not at the screen. Three people all staring at the
projector looks like nobody knows the material.

---

## Slide 1. Title — VANSH — 30 seconds

> Good morning. I am Vansh Tomar, with me are Satvik Rastogi and Ansh Rai, and
> we are working under Mr. Ashish Sharma and Mr. Yogesh Sharma.
>
> Our project is a unified performance evaluation of clustering techniques for
> wireless sensor networks.
>
> The short version of what we did: there are about twenty-five years of
> published protocols for this problem, and they have never been compared
> fairly. We built a single simulator that measures nine of them under
> identical conditions, ran about two thousand experiments, and found four
> things. One of those things contradicts a result we ourselves published
> earlier in the project, and we will show you that.
>
> Satvik will start with the problem.

**Handoff:** step back, Satvik steps forward.

---

## Slide 2. Problem Statement — SATVIK — 1 minute

> The problem is not that we lack protocols. We have too many. The problem is
> that nobody can tell which one is better.
>
> *(point at the bullets as you go)*
>
> Every protocol was published with its own results, from its own simulator.
> Different field size, different node count, different packet length,
> different energy budget, different channel. Almost all of them compare
> against LEACH alone, and almost all of them assume a perfect radio that never
> loses a packet.
>
> And the assumptions that actually decide who wins usually are not stated at
> all. For example, whether a centralized protocol is charged for the message
> that reports each node's battery level. That single accounting decision is
> worth about a quarter of the entire energy budget.
>
> *(point at the box on the right)*
>
> So when a paper reports a margin over LEACH, you genuinely cannot tell whether
> that is evidence about the algorithm or evidence about the test harness. Right
> now there is no way to separate them.
>
> Our aim is one benchmark where all three generations run under provably
> identical conditions, with every modelling choice disclosed.
>
> Ansh will summarise what we built.

**If asked "why does that matter?":** because a designer choosing a protocol for
a real deployment today has no reliable basis for the choice.

---

## Slide 3. Abstract — ANSH — 1 minute

> This slide is the whole project in five lines.
>
> Nine clustering protocols, plus a tenth configuration with no clustering at
> all as a control, all running on one engine. That engine owns everything that
> could be cheated: energy accounting, packet sizing, fusion, the channel, and
> the counting of delivered readings. A protocol hands back only a cluster
> structure and nothing else.
>
> The trials are paired. At a given run index, every protocol faces the exact
> same topology, the same signal shadowing, and the same sensor readings. So any
> difference we measure is the protocol, not the luck of the draw.
>
> Nineteen hundred and fifty runs in total.
>
> *(point at the fourth bullet)*
>
> And this is the result I want you to remember. We ran the entire study twice,
> once with a realistic lossy radio and once with a perfect one. Two protocols
> that beat LEACH by more than four hundred rounds in the first case turned out
> to be statistically indistinguishable from it in the second. So we retracted
> our own comparison.
>
> Vansh will take the scope.

---

## Slide 4. Introduction — VANSH — 1 minute

> Three columns here: what we cover, why, and what made it hard.
>
> **Scope.** Ten configurations across three generations on one engine. A
> hundred nodes in a hundred metre square field, sink outside at fifty, one
> fifty. Two channel settings. Nine different deployment scales.
>
> **Motivation.** A designer today cannot get a straight answer from the
> literature, because reported gains are entangled with the harness that
> produced them. And learned protocols are arriving quickly with no common
> yardstick against the heuristics they claim to beat.
>
> **Challenges**, and this is the part we spent the most time on. Fairness has
> to be structural, not something we promise in the write-up. Topology variance
> is larger than the differences between protocols, so a normal unpaired test
> would have wasted almost all of its statistical power. And unspecified
> parameters, transmit power above all, can decide the ranking outright.
>
> *(point at the line at the bottom)*
>
> One standing rule throughout: we never tuned a protocol to reproduce a
> published number. Where our numbers disagree with the original papers, that is
> expected, and it is not an error.
>
> Satvik, the literature.

**Compressible:** if short on time, read only the Challenges column.

---

## Slide 5. Literature Survey — SATVIK — 1 minute 15 seconds

> Twenty-five years of work falls into three generations.
>
> **Generation one is heuristic.** LEACH rotates the cluster head role with a
> probabilistic threshold and an epoch constraint, so every node serves once
> before anyone serves twice. PEGASIS abandons clusters entirely for a chain.
> TEEN and APTEEN keep LEACH's clustering but simply stay silent unless the
> reading changed enough to be worth sending.
>
> **Generation two writes down an objective and searches.** NSGA-II treats head
> selection as a genuine three-objective optimisation. The type-2 fuzzy system
> encodes it as twenty-seven human-readable rules over battery, distance and
> local density.
>
> **Generation three learns the selection function.** A self-organizing map, a
> deep Q-network, and a graph convolutional network.
>
> *(point at the box on the right)*
>
> Now, the gap. The fact that simulation studies are not comparable is itself a
> documented finding: Kurkowski in 2005 and Pawlikowski in 2002 both showed that
> most published network simulation results cannot be reproduced or compared.
> Nobody has applied that lesson to clustering protocols across all three
> generations.
>
> *(point at the line at the bottom)*
>
> Because what none of these papers share is a common simulator, a common
> channel model, a common energy budget, or a stated position on who pays for
> control traffic. Every one of those four decides the ranking.
>
> Ansh, the stack.

---

## Slide 6. Technology Stack — ANSH — 45 seconds

> Deliberately small. Python, NumPy for every numerical path, pandas,
> Matplotlib. Multiprocessing to run about two thousand simulations. pytest plus
> an eighteen-check static audit. LaTeX for the paper, with every table
> generated straight from the result files rather than typed by hand.
>
> *(point at the box at the bottom, slow down here)*
>
> This part is a design decision, not a limitation. No PyTorch, no TensorFlow,
> no SciPy. We wrote the backpropagation for both the deep Q-network and the
> graph network by hand in NumPy, and verified it against central finite
> differences.
>
> The reason is that per-round setup time is one of our reported metrics. If one
> protocol ran on an optimised C++ backend and another on plain Python, that
> column would be measuring the framework, not the algorithm. So everything runs
> on the same substrate.
>
> Vansh will explain how fairness is enforced.

**Expect a question here.** See Q&A below.

---

## Slide 7. Architecture — VANSH — 1 minute 15 seconds

> This is the core of the project, so I will go slowly.
>
> *(point left box)*
>
> The engine owns energy, through one single charging function. It owns packet
> sizing, the fusion charge, the channel and its retries, the TDMA slots, and
> the counting of delivered readings.
>
> *(point right box)*
>
> A protocol returns a set of cluster head identities and a membership map. That
> is all. It never touches energy or liveness.
>
> Four things follow.
>
> **Paired seeding.** Run index i generates the positions, the energies, the
> shadowing matrix and the whole sensor stream. That order depends only on i,
> never on which protocol is running.
>
> **A static audit, eighteen checks**, confirms no protocol implementation ever
> writes to the energy or liveness arrays or picks its own packet sizes.
>
> **Three invariants** the engine will not let a protocol break. Transmissions
> execute in hop-depth order, because plain index ordering breaks causality for
> about half of all head-member pairings and silently corrupts fusion totals. A
> fusing node emits at most one packet. And the engine counts delivered readings
> itself, rather than letting a protocol declare its own, which an earlier
> version allowed and which would have let a protocol inflate its own numbers.
>
> **And conservation is asserted every single run.** Energy in equals energy out
> to within a nanojoule. If that fails, the run refuses to complete.
>
> So fairness here is not a promise we make in the write-up. It is a property of
> the code, and it is verified by audit.
>
> Satvik, where we are.

---

## Slide 8. Prototype — SATVIK — 1 minute 15 seconds

**Do not compress this slide. This is the progress slide.**

> Everything runs end to end today.
>
> All ten configurations are implemented and passing verification. Nineteen
> hundred and fifty runs are complete: six hundred for the headline channel pair
> in eighty minutes on sixteen cores, and thirteen hundred and fifty for the
> scale grid in two hundred and twenty-two minutes on fourteen.
>
> Seven verification gates, all green. Energy conservation. Radio energies hand
> checked on both sides of the crossover distance. An invariant suite. And
> determinism, which means we run every protocol three times per seed and diff
> every per-round field. All nine reproduce exactly.
>
> *(point at the figure)*
>
> This is real output from the simulator. Living nodes against round, averaged
> over thirty paired trials.
>
> The dark blue curve, labelled *stub* in the legend, is our no-clustering
> baseline: every node simply transmits for itself. Watch what it does. It loses
> its first node almost immediately, then decays slowly and steadily. The
> clustered protocols hold a full population much longer, then fall off a cliff
> around round two thousand.
>
> *(trace where blue crosses orange, around round 2,100)*
>
> Notice the blue baseline is still alive after LEACH, in orange, has hit zero.
> The two shapes **cross**. That is not a detail, it is our first result, and
> Ansh will pick it up.

**Handoff line is deliberate.** It sets up slide 9.

> **Warn the panel about the legend before they ask.** It says `stub`, which is
> our internal codename for the no-clustering baseline. Say the word "baseline"
> immediately after you say "stub" and it will not come up again. If someone
> does ask: "it is the direct-transmission control, the configuration with no
> clustering at all."

---

## Slide 9. Results — ANSH — 2 minutes

**The most important slide. Do not rush it.**

> Four findings.
>
> **One.** Clustering does not extend network lifetime so much as redistribute
> it. LEACH reaches first node death at one thousand and forty-six rounds
> against the baseline's one hundred and fourteen. That is a factor of nine.
> But the baseline's *last* node dies at three thousand two hundred, where
> LEACH's dies at two thousand one hundred and ninety-one. So clustering buys a
> much later first death by bringing the last death forward. It is
> redistribution, not extension.
>
> **Two, and this is the one I would like to draw attention to.** On the lossy
> channel the fuzzy system and the deep Q-network beat LEACH by four hundred and
> seventeen and four hundred and twenty-six rounds, both statistically
> significant. We then removed packet loss and ran the identical study again.
> The same two comparisons gave seventeen and twenty-two rounds, and neither was
> significant.
>
> We had committed in advance to reporting only what survived both settings. So
> we are retracting that comparison. It was not a statement about the protocols.
> It was a statement about transmit power.
>
> **Three, the mechanism**, and this is where we were wrong before we measured.
> *(point at the figure)* We expected the clever protocols to win because their
> average cluster head sits closer to the sink. But packet error is essentially
> zero below a hundred and twenty metres, and every protocol's average sits
> below that line. So the average cannot be the cause.
>
> What separates them is the tail. LEACH puts almost thirty percent of its head
> rounds beyond a hundred and twenty metres and spends six point four percent of
> its energy on retransmissions. The Q-network puts five percent out there and
> spends two point three.
>
> **Four.** It is a regime, not a rule. In a fifty by fifty metre field, where no
> link ever reaches the error waterfall, the no-clustering baseline actually
> outlives LEACH. So clustering only pays once the sink is far enough away to be
> worth aggregating for.
>
> Vansh will close.

---

## Slide 10. References and close — VANSH — 30 seconds

> Twelve references here, forty-seven in the manuscript.
>
> To close: the draft paper is complete and every table and figure in it is
> generated directly from the result files, so the paper and the data cannot
> disagree.
>
> What remains before the final defense is the control-traffic ablation, which
> converts our largest remaining confound into a measurement, and a transmit
> power sweep across intermediate values.
>
> Thank you. We are happy to take questions.

---

## Questions to expect, and who answers

Agree these now. Whoever owns a topic answers it, the others stay quiet unless
asked directly. It is fine to say "we have not measured that" — for this project
that is often the *correct* answer and it is consistent with everything else you
have said.

| Likely question | Who | Answer |
|---|---|---|
| "Why not use PyTorch?" | **Ansh** | Setup time per round is a reported metric. Mixing an optimised backend with plain Python would make that column measure the framework instead of the algorithm. We verified our hand-written gradients against finite differences. |
| "Why do your LEACH numbers differ from the original paper?" | **Satvik** | Deliberately. We took the protocol descriptions, the radio model and the parameters from prior work, and discarded their numeric results before implementing. Absolute lifetimes differ by construction; what is comparable is the ordering under identical conditions. |
| "Only 30 runs. Is that enough?" | **Ansh** | The trials are paired, so topology variance cancels out rather than having to be averaged away. The permutation floor at 30 paired samples is 5 x 10⁻⁵, and after Holm correction 0.00045. Our significant results sit at that floor. |
| "Is this realistic? There is no MAC layer." | **Vansh** | No, and we state that. No MAC, no idle listening, no interference, no mobility, and fusion is ideal. Idle listening in particular often dominates real deployments and would compress all our differences. Our claims are about relative ordering under a stated model, not absolute lifetime. |
| "What is the novelty? These protocols already exist." | **Satvik** | The novelty is not a protocol. It is the harness and the discipline. Fairness enforced structurally instead of promised, paired trials with proper correction, and a decision rule fixed in advance that made us retract one of our own results. |
| "Which protocol should I use?" | **Ansh** | It depends on the regime, and that is finding four. If your sink is close, do not cluster at all. If it is far, NSGA-II was rank one in every large-field cell we tested. |
| "Why is the GCN so bad?" | **Ansh** | It is not choosing badly, it is choosing the same good node repeatedly until that node dies. Its busiest node serves 13.6 times as often as LEACH's, and thirteen nodes never serve at all. It can see rotation state in its inputs, but nothing in its single-round loss rewards acting on it. |
| "What is left to do?" | **Vansh** | The control-traffic ablation, a transmit power sweep, and submission. The ablation is the most valuable because it converts our largest confound into a measurement. |
| "Where is the code?" | **Vansh** | On GitHub, with every configuration constant, per-round output and verification artifact released alongside. |

---

## Practical notes for tomorrow

- **Rehearse the handoffs once.** They are where teams look unprepared. Each of
  you ends by naming the next speaker and what they will cover.
- **Slides 8 and 9 are the ones being marked.** A second defense is judged on
  demonstrated progress. Everything before slide 8 is setup.
- **Numbers you must not fumble:** 1,950 runs; 9.2 times; +417 and +426 rounds
  falling to +17 and +22; 29.9% against 5.1%; 13.6 times.
- **If a number is challenged and you are not certain, say so** and offer to
  follow up. Do not invent a figure in front of a panel. Every number on these
  slides comes from a CSV in the repository.
- **Formals, and all three of you present**, per points 1 and 2 of the notice.
- **Carry the signed paper draft.** Point 4 of the notice requires the first
  draft, reviewed and signed by your guide, in front of the panel.
