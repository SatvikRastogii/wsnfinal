# generalexp.md

The whole project, explained from the very beginning.

Every section starts with the simplest possible version, then adds the real
technical detail underneath. If you only read the **In plain words** boxes you
will still understand the entire project. If you read everything you will be
able to answer a panel.

---

## 1. The one-paragraph version

Little battery-powered sensors get scattered in a field. They have to send what
they measure back to one computer far away. Sending far costs a lot of battery,
so the sensors take turns: one collects everyone's readings and sends one big
message instead of everyone shouting separately. Lots of clever people have
invented lots of ways to decide *who takes the turn*. But every inventor tested
their idea on their own computer with their own settings, so nobody actually
knows which one is best. We rebuilt all of them inside one fair testing machine
and measured them properly. We found some surprising things, including one
result of our own that we had to take back.

---

## 2. What is a wireless sensor network?

> **In plain words.** Imagine you throw a hundred tiny weather thermometers
> across a big playground. Each one has a small battery and a tiny walkie-talkie.
> Every few seconds each one says "it is 23 degrees here". A computer sits
> outside the playground and writes all of it down. Nobody is ever going to walk
> around and change a hundred batteries. So when a thermometer's battery runs
> out, it is dead forever.

**Technically.** A WSN is a set of low-power nodes with a radio, a sensor and a
non-replaceable battery, reporting to a base station (also called the sink). In
our study: **100 nodes**, placed uniformly at random in a **100 x 100 m** field,
each starting with **1 joule**. The sink sits outside the field at **(50, 150)**,
so node-to-sink distances run from **50 m to 158 m**. Nodes never move and only
ever fail by running out of energy.

### Why the battery is the whole story

> **In plain words.** Talking is expensive. Thinking is cheap. And shouting to
> someone far away is *much* more expensive than whispering to someone close.
> If you shout twice as far, it does not cost twice as much. It can cost
> **sixteen** times as much.

**Technically.** We use the first-order radio model of Heinzelman et al.
Transmitting *k* bits over distance *d* costs

```
E = k·E_elec + k·ε_fs·d²      when d <  d0     (free-space, "whisper")
E = k·E_elec + k·ε_mp·d⁴      when d >= d0     (multipath, "shout")
```

with `E_elec = 50 nJ/bit`, `ε_fs = 10 pJ/bit/m²`, `ε_mp = 0.0013 pJ/bit/m⁴`.

The crossover is `d0 = sqrt(ε_fs / ε_mp) = 87.7 m`. Below it, cost grows with
distance **squared**. Above it, with distance to the **fourth power**. That is
the "sixteen times" above: doubling distance past the crossover multiplies cost
by 2⁴.

**This one number, 87.7 m, is the hinge of the entire project.** Our sink is 50
to 158 m away, so some nodes are on the cheap side of it and some on the
expensive side. If the sink were very close, or very far, nothing interesting
would happen.

---

## 3. What is clustering, and why does it exist?

> **In plain words.** Imagine the whole class has to hand homework to a teacher
> in another building. If all forty children walk over separately, everyone gets
> tired. Instead, one child is picked as monitor. Everyone hands their sheet to
> the monitor, who is standing right there, so that costs almost nothing. The
> monitor staples all forty sheets into one bundle and makes the one long walk.
>
> That saves the whole class a lot of walking. But it is very tiring for the
> monitor. So you must pick a **different monitor every day**, or the same poor
> child collapses.
>
> **The entire field of research is about one question: who should be monitor
> today?**

**Technically.** Members transmit short-range to their cluster head; the head
performs data fusion and pays the single expensive long-range transmission to
the sink. Because head duty is expensive, the role must rotate. Every clustering
protocol is a different rule for choosing this round's heads. In our study every
protocol targets the same nominal head count, `k = max(1, round(p·N_alive))`
with `p = 0.05`, so roughly five heads out of a hundred living nodes.

---

## 4. The three generations of answers

> **In plain words.** Over twenty-five years, people answered "who should be
> monitor?" in three increasingly clever ways. First with simple rules. Then by
> writing down exactly what a good monitor looks like and searching for the best
> one. Then by letting a computer *learn* what a good monitor looks like.

| Gen. | Idea | Protocols we implemented |
|---|---|---|
| **G1** heuristic | A simple rule, usually random with a fairness constraint | LEACH, PEGASIS, TEEN, APTEEN |
| **G2** optimization | Write down an objective, then search for the best answer | NSGA-II, Type-2 Fuzzy |
| **G3** learned | Let a neural network learn the selection function | SOM, DQN, GCN |

Plus a tenth configuration, **Direct**, where there is no clustering at all and
every node just shouts to the sink itself. That is the control.

### What each one actually does

- **LEACH.** Each node flips a weighted coin. A node that has already been head
  this "epoch" is not allowed to be head again until everyone else has had a
  turn. Every 20 rounds the slate wipes clean.
  *In plain words: take turns fairly, but pick randomly within the turn.*

- **PEGASIS.** No clusters at all. Build a chain from the farthest node inward,
  each node passing data to its nearest neighbour, fusing at every step, until
  one leader sends the single message to the sink.
  *In plain words: a bucket brigade instead of a monitor.*

- **TEEN / APTEEN.** Same clustering as LEACH, but a node **stays silent** unless
  the temperature actually changed a lot. APTEEN adds "and speak at least once
  every 50 rounds anyway".
  *In plain words: only speak up if something interesting happened.*

- **NSGA-II.** A genetic algorithm. Try many candidate sets of heads, keep the
  good ones, mix them, repeat. It balances three goals at once: low round energy,
  no head with a nearly-flat battery, and evenly-sized clusters.
  *In plain words: breed better answers, like breeding better roses.*

- **Type-2 Fuzzy.** A rule table written in almost-English: *if battery is HIGH
  and distance is NEAR and neighbours are MANY, then this node is a GREAT
  candidate.* 27 rules, with an extra layer that handles "we are not even sure
  where HIGH begins".
  *In plain words: a checklist a human could read.*

- **SOM.** A Kohonen self-organizing map finds natural clumps of nodes; the node
  closest to each clump centre becomes head.
  *In plain words: find the natural groups, pick whoever is in the middle.*

- **DQN.** A small neural network trained with reinforcement learning. It looks
  at four numbers per node and predicts *how good the future will be* if this
  node is head now. Crucially it is trained to care about the future, not just
  this round.
  *In plain words: it learned from playing the game many times.*

- **GCN.** A graph neural network. Same four inputs as the DQN, but it reasons
  over who is near whom, and it is only ever rewarded for **this** round.
  *In plain words: same eyes as the DQN, but no memory of consequences.*

**The DQN and the GCN are deliberately built as a matched pair.** They get the
identical four features, the GCN literally imports the DQN's feature function.
The only difference is that the DQN has temporal credit assignment and the GCN
does not. So any gap between them measures exactly one thing.

---

## 5. The problem we are actually solving

> **In plain words.** Suppose Ali says he ran 100 m in 12 seconds, and Bilal says
> he ran it in 11 seconds. Bilal is faster, right? Not necessarily. Ali ran uphill
> in sand. Bilal ran downhill with the wind. **You cannot compare times from
> different tracks.**
>
> Every one of those nine protocols was tested on a different track. Different
> field size, different number of sensors, different battery, different radio,
> different amount of interference. So when a paper says "we beat LEACH by 40%",
> nobody can tell whether the protocol is good or whether the track was friendly.

**Technically.** Published clustering results are not comparable because the
evaluation harness varies between papers and the decisive assumptions are
usually unstated. Three assumptions in particular can flip a ranking:

1. **Is a centralized protocol charged for its uplink?** Centralized protocols
   need the sink to know every node's battery level. If you charge for sending
   that, it costs about a quarter of the whole energy budget. Most papers do not
   charge for it and do not say so.
2. **Is data fusion free?** If one head can squash 20 messages into one at no
   cost, chain protocols like PEGASIS look amazing.
3. **Which death do you report?** First node death, half, or last? They give
   different winners. The author picks.

The literature already knows this is a problem in network simulation generally
(Kurkowski 2005, Pawlikowski 2002). Nobody had applied that lesson across all
three generations of clustering. **That gap is our project.**

---

## 6. What we built

> **In plain words.** We built one fair racetrack and made all ten runners race
> on it, on the same day, in the same weather, wearing the same shoes.

**Technically.** A single simulation engine in Python where:

- **The engine owns everything that could be cheated.** Energy accounting
  through one charging function, packet sizing, the fusion charge, the channel
  and its retries, the TDMA schedule, and the counting of delivered readings.
- **A protocol returns only two things**: which nodes are heads, and who belongs
  to whom. Nothing else. It cannot touch energy or liveness.
- **A static audit of the source code (18 checks) proves it.** No protocol
  implementation writes to the energy or liveness arrays, calls the charging
  function, or chooses its own packet sizes.

> **In plain words about why that matters.** In most papers, fairness is a
> promise the author makes. In ours it is a property of the code: a protocol
> *cannot* cheat because it is never handed the pencil.

### Paired trials

> **In plain words.** Instead of testing each runner on a different day, we test
> all ten on the exact same field, in the exact same wind, with the exact same
> everything. So any difference is the runner, not the day.

**Technically.** Run index *i* seeds one random stream that generates, in a fixed
order, the node positions, the initial energies, the full per-link shadowing
matrix, and the entire sensed-value stream for all rounds. That order depends
only on *i*, never on which protocol is running. So at index *i* all ten
configurations face a byte-identical world.

This matters statistically: topology variance is larger than the differences
between protocols. An unpaired test would spend all its power fighting that
noise. Pairing removes it by construction.

### How big

| | Runs |
|---|---|
| Headline: 10 protocols x 30 trials x 2 channel settings | **600** |
| Scale sweep: 10 protocols x 15 trials x 9 deployment cells | **1,350** |
| **Total** | **1,950** |

80 minutes on 16 cores for the first, 222 minutes on 14 for the second.

---

## 7. The channel: why packets get lost

> **In plain words.** If you whisper to someone across a room they hear you. If
> you whisper across a football pitch they hear nothing. And it is not a slow
> fade. There is a distance where it goes from "perfectly fine" to "hopeless"
> almost immediately. It is a cliff, not a slope.

**Technically.** We derive packet loss from a link budget rather than assuming a
constant. Log-distance path loss with per-link log-normal shadowing gives an
SNR; non-coherent BFSK gives a bit error rate; that gives packet error rate for
a 4,000-bit packet.

The resulting curve is a **waterfall**:

| Distance | Packet error rate |
|---|---|
| 100 m | 0.000000026 |
| 120 m | 0.001 |
| 140 m | 0.19 |
| 158 m | 0.97 |

Effectively zero out to about **120 m**, then it collapses. The whole transition
spans about 3.6 dB of SNR and 40 m of distance.

**Remember this number too: 120 m.** It is the second hinge of the project.

Failed packets are retried up to twice. Each retry pays full transmit and
receive energy, which is what makes a lossy channel cost **joules**, not just
packets. Retry energy is booked to its own category so we can measure it rather
than infer it.

---

## 8. What we found

### Finding 1: Clustering does not extend life, it moves it around

> **In plain words.** Everyone says clustering makes the network live longer.
> That is only half true. Clustering makes the **first** sensor die much later,
> but it makes the **last** sensor die *sooner*. It is like taking money from the
> rich kids to help the poor kids: nobody is very poor, but nobody is very rich
> either.

**Technically.**

| | First node death | Last node death |
|---|---|---|
| No clustering (Direct) | 114 rounds | 3,202 rounds |
| LEACH | 1,046 rounds | 2,191 rounds |

LEACH improves first death by **9.2 times**, and the baseline outlasts LEACH on
last death by **46%**.

**Why?** Geometry. With the sink at 150 m and the crossover at 87.7 m, **36 of
the 100 nodes** (in the seed-0 topology) are close enough to whisper. Under
direct transmission those lucky nodes are never asked to carry anyone else's
traffic, so they live a very long time. Under rotation they are made to
subsidise the expensive far-away nodes.

**Consequence:** any paper reporting a single lifetime number is picking a
winner by choosing which number to report. We report four: first, half, last,
and the area under the alive-node curve.

### Finding 2: We had to take back one of our own results

> **In plain words.** We found that the two clever modern protocols beat the old
> one. Then we tested again with a perfect radio that never loses anything, and
> the advantage completely disappeared. So the clever protocols were not better
> at clustering. They were better at **avoiding a bad radio**. We had promised
> ourselves before we started that we would report whatever survived both tests,
> so we reported that our own result did not survive.

**Technically.** We fixed this decision rule before reading any results:

> A conclusion that holds in both channel configurations is a statement about
> the protocol. A conclusion that changes between them is a statement about
> transmit power.

| Protocol vs LEACH, first node death | Lossy channel | Ideal channel |
|---|---|---|
| Type-2 Fuzzy | **+417 rounds**, p = 0.00045 | +17 rounds, p = 0.119 (not significant) |
| DQN | **+426 rounds**, p = 0.00045 | +22 rounds, p = 0.124 (not significant) |

Transmit power is a parameter the original papers never fix. Choosing it to
make your metric look good would be exactly the calibration we forbade
ourselves. So we ran both endpoints.

**What survives:** on area under the alive-node curve and on readings delivered,
all 18 comparisons hold at the corrected floor in **both** channels. Only the
first-death advantage is conditional.

### Finding 3: The reason is the tail, not the average

> **In plain words.** We thought the clever protocols won because their monitor
> stood *closer* to the teacher on average. We measured it, and that turned out
> to be the wrong explanation. Everyone's average was inside the safe zone. What
> actually mattered was how often a monitor stood *very* far out, past the cliff.
> LEACH did that about a third of the time. The clever ones almost never did.

**Technically.** Packet error is essentially zero below 120 m, and **every**
protocol's mean head-to-sink distance is below 120 m. So the mean cannot be
causal: a protocol whose heads all sat at the mean would retry essentially never.

| | Mean head distance | Share of head-rounds beyond 120 m | Retry energy |
|---|---|---|---|
| LEACH | 102.1 m | **29.9%** | **6.39%** |
| DQN | 81.1 m | **5.1%** | **2.31%** |

Across the six single-hop protocols, the tail share predicts retry energy at
**r = 0.95**. The mean correlates almost as well, at r = 0.93, because the two
are collinear. **The reason to prefer the tail is not a better fit; it is that
only the tail lies in the region where packets actually fail.**

**PEGASIS is the exception that fixes the scope.** It has the same 30% tail as
LEACH but only 1.39% retry energy, because in a chain only one node faces the
sink per round. Including it drops the correlation from 0.95 to 0.50. So the
claim is specific to single-hop clustered protocols. We state this rather than
quietly dropping the inconvenient protocol.

### Finding 4: Memory of consequences is what separates the two learned models

> **In plain words.** We built two neural networks with exactly the same eyes.
> One of them remembers that using a node today means it is worn out tomorrow.
> The other only thinks about today. The one that only thinks about today keeps
> picking the same excellent node over and over until that node dies. It is not
> choosing badly. It is choosing the *same good thing* too many times.

**Technically.** Over 1,100 rounds on seed 0:

| | Busiest node served | Median node | Never served | Gini |
|---|---|---|---|---|
| LEACH | 55 rounds | 55 | 0 | 0.001 |
| DQN | 223 rounds | 38 | 16 | 0.476 |
| GCN | **750 rounds** | 16 | **13** | **0.700** |

The GCN's busiest node serves **13.6 times** as often as LEACH's. LEACH's 55 is
exact, not approximate: its epoch rule elects every node exactly once per 20
rounds.

The cost is a first node death 3.1 times earlier than LEACH's. The GCN can *see*
rotation state in its fourth input feature. What it lacks is any term in its loss
that rewards deferring cost. **This is the paper's cleanest controlled contrast**,
because the two models differ in exactly one thing.

### Finding 5: It is a regime, not a rule

> **In plain words.** We then asked: does any of this depend on how big the field
> is, or how many sensors there are? It turns out the number of sensors barely
> matters. What matters is **how far away the teacher is**. And in a small field
> where the teacher is close, clustering is not just useless, it is actively
> worse than everyone shouting for themselves.

**Technically.** A 3x3 sweep: node counts {50, 100, 150} x field sides
{50, 100, 150} m, 15 paired runs per cell, 1,350 runs.

- **Area beats node count about five to one.** Tripling node count changes first
  death by a factor of 0.88 to 1.26. Tripling the field side changes it by 5 to 7.
- **Density is not the driver.** Density spans a factor of 27 across the grid and
  explains almost none of the variation. Two cells at nearly equal density (50
  and 44 nodes per hectare) differ by up to 5.5 times, because one has its sink
  104 m away and the other 156 m.
- **Clustering is harmful when the sink is close.** At 50 x 50 m, LEACH's first
  node death relative to no clustering at all is 0.82, 0.83 and 0.95. The
  no-clustering baseline **outlives LEACH in all three cells.**
- **The retraction reproduces independently.** At 50 x 50 m the DQN's advantage
  over LEACH collapses to +10 rounds, and to -291 at N = 50. Same boundary as
  Finding 2, reached by moving the sink instead of by removing packet loss.
- **The untrained fuzzy system is the control that makes this safe.** It has no
  training at all, so its collapse cannot be a transfer failure. Since the DQN
  behaves identically, the DQN's collapse is the environment too.

**Two of our five pre-registered expectations were wrong and we report both.** We
expected the generational gap to widen at 150 x 150 m; it narrows. We expected
density to matter; it does not.

---

## 9. The statistics, in plain words

> **In plain words.** If you flip a coin ten times and get seven heads, is the
> coin bent? Maybe, or maybe you were lucky. Statistics is how you tell the
> difference. We used a method that makes almost no assumptions: we take our real
> measurements, randomly flip the signs of some of them thousands of times, and
> ask how often pure chance produces something as extreme as what we actually
> saw.

**Technically.**

- **Sign-flip permutation test**, 20,000 random sign vectors, on the vector of 30
  paired per-topology differences. Assumes only exchangeability, not normality,
  which matters because several difference distributions are visibly skewed and
  the GCN's is bimodal.
- **Paired bootstrap**, 20,000 resamples, for confidence intervals.
- **Holm-Bonferroni correction** across the nine comparisons within each metric
  and channel, because making nine comparisons means nine chances to get lucky.
- The uncorrected floor at 30 paired samples is 5 x 10⁻⁵; the corrected floor is
  **p = 0.00045**.
- Validated against exhaustive enumeration on a reduced sample: exact p = 0.00391
  against our sampled 0.00420.

---

## 10. How we know the simulator is not lying

> **In plain words.** Before we believed a single number, we made the program
> prove it was not cheating. The most important check: at the end of every single
> run, add up all the energy that ever left a battery, and add up all the energy
> that was ever spent on anything. If those two numbers are not the same, stop and
> refuse to continue.

**Technically.** Seven gates, all passing:

1. **Energy conservation** asserted every run to 10⁻⁹ J.
2. **Radio energies** hand-checked on both sides of the crossover.
3. **Invariant suite:** energy never negative, dead nodes never transmit, living
   count monotone, death points ordered, delivery ratios in range.
4. **Determinism:** every protocol run three times per seed, all per-round fields
   diffed. All nine reproduce exactly.
5. **Static audit,** 18 checks on the protocol source.
6. **Independent recomputation** of one protocol's summary row, diffed at 10⁻⁹.
7. **Packet-error curve** published as an artifact and asserted non-decreasing
   and strictly between 0 and 1 somewhere in the band of sink distances. Without
   this the channel would be a binary range switch and the lossy results would
   carry no information.

Plus: the centre cell of the scale sweep reproduces the first 15 runs of the
headline study **exactly**, which proves the two harnesses are the same simulator.

---

## 11. What we are honest about

A good paper states what could make it wrong. Ours does, ordered by how much
each could move a conclusion.

1. **The control-traffic subsidy.** Centralized protocols are not charged for
   the uplink that tells the sink each node's battery level. Measured, LEACH
   spends 12.73% of its energy on control traffic against 2.33% to 3.95% for the
   centralized five. So every cross-class comparison carries a **9 to 10
   percentage point** subsidy. Our strongest results are within-class, so they
   are unaffected, but the reader must know.
2. **Transmit power is bracketed, not swept.** Two endpoints do not trace a
   continuum.
3. **The learned models arrive pre-trained** and the other seven do not.
4. **The model is minimal:** no idle listening, no MAC layer, no interference, no
   mobility, ideal fusion, no hardware testbed.
5. **No protocol was tuned to reproduce a published number.** Only the protocol
   descriptions, the radio model and the parameters were taken from prior work.
   Disagreement with published tables is expected, not an error.

---

## 12. Words you may be asked to define

| Word | Plain meaning |
|---|---|
| **Node** | One little sensor with a battery and a radio |
| **Sink / base station** | The computer that collects everything |
| **Cluster head** | The "monitor" for this round |
| **Round** | One cycle: everyone senses, heads collect, heads report |
| **FND / HND / LND** | First / half / last node death, measured in rounds |
| **AUC** | Area under the alive-node curve: total node-rounds of life |
| **Data yield** | Readings that arrived, divided by readings taken |
| **d0 (87.7 m)** | Where transmission cost switches from d² to d⁴ |
| **Packet error waterfall** | The cliff near 120 m where links stop working |
| **Shadowing** | Random signal blocking from obstacles, fixed per link |
| **ARQ** | Automatic retry when a packet is lost. We allow 2 retries |
| **Paired trial** | Same world, different protocol, so the world cancels out |
| **Holm correction** | Making the bar higher because you made many comparisons |
| **Gini coefficient** | 0 = perfectly even sharing, 1 = one node does everything |
| **Censored** | The network never fully died before the 7,000-round cap |
| **Out-of-distribution** | Tested somewhere it was never trained |
