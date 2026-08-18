"""NSGA-II (Non-dominated Sorting Genetic Algorithm II) cluster-head
selection.

Deb, K., Pratap, A., Agarwal, S., & Meyarivan, T. (2002). "A Fast and
Elitist Multiobjective Genetic Algorithm: NSGA-II." IEEE Transactions on
Evolutionary Computation, 6(2), 182-197.

This is the real algorithm -- fast non-dominated sort, crowding distance,
binary tournament selection, elitist (mu+lambda) environmental survival --
not a weighted-sum GA standing in for it.

What is implemented here
-------------------------
- `control_model = "centralized"`: the BS runs the whole GA over globally
  known node state and dictates cluster structure; no node makes its own
  CH-election decision (see `docs/ASSUMPTIONS.md` item 23).
- Decision variable: an integer vector of `k = max(1, round(cfg.p_ch *
  n_alive))` DISTINCT alive node indices (the chosen CHs). Fixed
  cardinality by construction, so no repair operator is ever needed.
- Genetic operators, all randomness drawn from the `rng` passed into
  `setup_round` (never a private RNG):
    * Mutation: swap one CH for a uniformly random alive non-CH node.
    * Crossover: uniform crossover over the k index slots; any duplicate
      node that results is replaced by a uniformly random alive node not
      already in the child (always resolvable: a universe of >= k alive
      nodes always has exactly enough spare nodes to fill however many
      duplicate slots a fixed-cardinality uniform crossover can produce).
    * Binary tournament selection on (rank, crowding distance), the
      standard NSGA-II comparator.
    * Environmental selection: parents (mu) + offspring (lambda) are
      merged, non-dominated sorted, and the next generation is filled
      front-by-front, using crowding distance to break the final
      partially-included front -- the standard elitist (mu+lambda) rule.
- THREE objectives, all minimized, computed with the ENGINE's own radio
  functions (`radio.e_tx`, `radio.e_agg`) so the GA optimizes exactly the
  cost model the engine will later charge for real, never a re-derived
  approximation of it:
    f1 = total energy of one round under this assignment: every non-CH
         alive node's tx energy to its nearest candidate CH, plus each
         CH's aggregation energy on the bits it would receive, plus each
         CH's tx energy to the BS.
    f2 = -(minimum residual energy among the selected CHs) -- minimizing
         this maximizes the worst-off CH's remaining energy.
    f3 = population standard deviation of cluster membership COUNTS
         (deliberately size-based, not intra-cluster distance variance --
         distance is already the dominant term inside f1, and a second,
         strongly correlated distance-based objective would collapse the
         Pareto front instead of giving the GA a genuinely independent
         third axis).
- Final selection off the Pareto front: KNEE POINT -- each objective is
  normalized to [0,1] across the CURRENT front, and the individual with
  minimum Euclidean distance to the ideal point (0,0,0) is chosen.
  Deterministic, no hand-tuned scalarization weights.
- Between reclusterings (every `cfg.ga_interval` rounds -- shared knob with
  Fuzzy-T2, see `config.py`), the last assignment is reused, DROPPING dead
  CHs: members of a dead CH rejoin their nearest surviving CH; if no CH
  survives at all, they become self-heads (direct-to-BS) for that round.
- `ops_this_round` counts every fitness evaluation (once per individual
  evaluated, initial population + every generation's offspring) and every
  node-to-candidate-CH distance comparison inside that evaluation's
  nearest-CH membership assignment -- see `protocols/base.py` for why only
  these two things count as "ops."
- GA convergence logging (`results/validation/nsga2_convergence.csv`,
  `self.convergence_log`): logged the first time this protocol reclusters at
  `run_index == 0` with `round_idx` inside `[self._conv_round_min,
  self._conv_round_max]` (defaults 800/1200) AND the alive population's
  residual energy has genuinely diverged (`std(energy[alive]) >
  self._conv_energy_std_threshold`, default 1e-3 J). Round 0 is deliberately
  NOT used: every node still holds exactly `cfg.e0` at round 0, so f2 (the
  negated minimum CH residual energy) is pinned at -e0 for all 30
  generations and carries zero information -- logging there proves nothing
  about the search. If no reclustering round inside the window has
  diverged enough by `_conv_round_max`, the window is extended one
  reclustering interval at a time until it has (energy divergence is a
  property of the run, not something to force onto a fixed round). Each
  generation logs BOTH the knee-point objective triple and the
  best-in-population value of each objective evaluated independently
  (columns: generation, knee_f1, knee_f2, knee_f3, best_f1, best_f2,
  best_f3) -- the knee point trades objectives against each other, so its
  own trajectory can look flat/non-monotonic even while the population's
  best per-objective values are improving, and conflating the two would
  hide that.

Deviations from a "textbook" NSGA-II write-up
----------------------------------------------
- Mutation is applied to each offspring with fixed probability 0.2 (a
  standard-order-of-magnitude choice, not tuned to this benchmark) after
  crossover, rather than as a separate operator producing its own
  offspring -- this is the common "crossover then maybe mutate" GA
  offspring-generation loop, not a deviation from NSGA-II's selection/
  survival machinery itself (which is what actually defines NSGA-II).
- f1/f2/f3 are a MODEL of the round's cost the GA optimizes against, not
  the actual per-round charge -- the real charge (computed later by
  `engine.py`) additionally depends on channel-loss draws the GA cannot
  see when it runs (retries, drops). Using the engine's own `e_tx`/`e_agg`
  functions for the model keeps it consistent with the real cost formula;
  only the channel-randomness component is necessarily absent from a
  fitness function evaluated before that randomness is drawn.
"""

import csv
import os

import numpy as np

from ..radio import e_agg, e_tx
from .base import ClusterAssignment, Protocol, Transmission
from ..network import BS

_RESULTS_VALIDATION_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "results", "validation",
)


class NSGA2Protocol(Protocol):
    name = "nsga2"
    control_model = "centralized"

    MUTATION_PROB = 0.2

    def __init__(self, conv_round_min=800, conv_round_max=1200, conv_energy_std_threshold=1e-3):
        self.reclustered_this_round = False
        self._assignment = ClusterAssignment(ch_ids=[], member_of={})
        self._has_clustered = False
        self._convergence_logged = False
        self.convergence_log = []
        self._convergence_round = None
        # See docstring "GA convergence logging" -- a fixed round window is
        # tried first, then extended (never shrunk) until energies have
        # genuinely diverged. Instance attrs (not module constants) so
        # tests can shrink the window for a fast smoke check.
        self._conv_round_min = conv_round_min
        self._conv_round_max = conv_round_max
        self._conv_energy_std_threshold = conv_energy_std_threshold

    # ------------------------------------------------------------------
    # Fitness
    # ------------------------------------------------------------------
    def _evaluate(self, net, alive_arr, individual):
        cfg = net.cfg
        ch_arr = np.asarray(individual, dtype=int)
        k = len(ch_arr)
        non_ch = alive_arr[~np.isin(alive_arr, ch_arr)]

        self.ops_this_round += 1  # one fitness evaluation

        if len(non_ch) > 0:
            d = net.dist[np.ix_(non_ch, ch_arr)]  # (n_non_ch, k)
            self.ops_this_round += int(d.size)  # one distance comp per (node, CH) pair
            nearest_pos = np.argmin(d, axis=1)
            nearest_d = d[np.arange(len(non_ch)), nearest_pos]
            member_tx_energy = float(np.sum(e_tx(cfg.data_bits, nearest_d, cfg)))
            sizes = np.bincount(nearest_pos, minlength=k)
        else:
            member_tx_energy = 0.0
            nearest_pos = np.empty(0, dtype=int)
            sizes = np.zeros(k, dtype=int)

        agg_energy = float(np.sum(e_agg(sizes * cfg.data_bits, cfg)))
        ch_tx_energy = float(np.sum(e_tx(cfg.data_bits, net.dist_bs[ch_arr], cfg)))

        f1 = member_tx_energy + agg_energy + ch_tx_energy
        f2 = -float(net.energy[ch_arr].min())
        f3 = float(np.std(sizes)) if k > 0 else 0.0

        # member_of is NOT built here (that dict-comprehension cost is paid
        # ~1240 times per reclustering for individuals that are discarded);
        # only `non_ch`/`nearest_pos` are kept so the WINNING individual's
        # membership can be reconstructed once, after the GA finishes.
        return (f1, f2, f3), non_ch, nearest_pos

    # ------------------------------------------------------------------
    # Genetic operators
    # ------------------------------------------------------------------
    @staticmethod
    def _random_individual(alive_idx, k, rng):
        return np.asarray(rng.choice(alive_idx, size=k, replace=False), dtype=int)

    @staticmethod
    def _mutate(individual, alive_idx, rng):
        child = individual.copy()
        current_set = set(child.tolist())
        candidates = [n for n in alive_idx if n not in current_set]
        if candidates:
            pos = int(rng.integers(0, len(child)))
            new_node = candidates[int(rng.integers(0, len(candidates)))]
            child[pos] = new_node
        return child

    @staticmethod
    def _crossover(parent_a, parent_b, alive_idx, rng):
        k = len(parent_a)
        mask = rng.random(k) < 0.5
        child = np.where(mask, parent_a, parent_b).astype(int)

        seen = set()
        dup_positions = []
        for i in range(k):
            v = int(child[i])
            if v in seen:
                dup_positions.append(i)
            else:
                seen.add(v)
        if dup_positions:
            pool = [n for n in alive_idx if n not in seen]
            rng.shuffle(pool)
            for i, pos in enumerate(dup_positions):
                child[pos] = pool[i]
                seen.add(pool[i])
        return child

    # ------------------------------------------------------------------
    # NSGA-II machinery: non-dominated sort, crowding distance, tournament
    # ------------------------------------------------------------------
    @staticmethod
    def _dominates(a, b):
        return all(x <= y for x, y in zip(a, b)) and any(x < y for x, y in zip(a, b))

    @staticmethod
    def _fast_nondominated_sort(objectives):
        """Standard fast non-dominated sort. Vectorized with numpy (the
        pairwise domination test is computed for all O(n^2) pairs at once)
        rather than a pure-Python double loop calling `_dominates` --
        purely a performance fix (profiled as the dominant per-generation
        cost with pop_size=40), the sort semantics are unchanged.
        """
        n = len(objectives)
        if n == 0:
            return []
        obj = np.asarray(objectives, dtype=float)
        all_le = np.all(obj[:, None, :] <= obj[None, :, :], axis=2)
        any_lt = np.any(obj[:, None, :] < obj[None, :, :], axis=2)
        dom_matrix = all_le & any_lt  # dom_matrix[p, q] == True iff p dominates q
        np.fill_diagonal(dom_matrix, False)

        dom_count = dom_matrix.sum(axis=0).tolist()  # how many individuals dominate q
        dominated_by = [np.flatnonzero(dom_matrix[p]).tolist() for p in range(n)]

        fronts = [[p for p in range(n) if dom_count[p] == 0]]
        i = 0
        while fronts[i]:
            next_front = []
            for p in fronts[i]:
                for q in dominated_by[p]:
                    dom_count[q] -= 1
                    if dom_count[q] == 0:
                        next_front.append(q)
            i += 1
            fronts.append(next_front)
        fronts.pop()
        return fronts

    @staticmethod
    def _crowding_distance(objectives, front):
        m = len(front)
        distances = {idx: 0.0 for idx in front}
        if m == 0:
            return distances
        n_obj = len(objectives[0])
        for obj_idx in range(n_obj):
            front_sorted = sorted(front, key=lambda i: objectives[i][obj_idx])
            distances[front_sorted[0]] = float("inf")
            distances[front_sorted[-1]] = float("inf")
            obj_min = objectives[front_sorted[0]][obj_idx]
            obj_max = objectives[front_sorted[-1]][obj_idx]
            span = obj_max - obj_min
            if span <= 0:
                continue
            for j in range(1, m - 1):
                prev_obj = objectives[front_sorted[j - 1]][obj_idx]
                next_obj = objectives[front_sorted[j + 1]][obj_idx]
                distances[front_sorted[j]] += (next_obj - prev_obj) / span
        return distances

    @staticmethod
    def _tournament_select(indices, ranks, crowd, rng):
        i, j = rng.integers(0, len(indices), size=2)
        a, b = indices[int(i)], indices[int(j)]
        if ranks[a] != ranks[b]:
            return a if ranks[a] < ranks[b] else b
        ca, cb = crowd.get(a, 0.0), crowd.get(b, 0.0)
        if ca != cb:
            return a if ca > cb else b
        return a

    @staticmethod
    def _knee_point(objectives, front):
        arr = np.array([objectives[i] for i in front], dtype=float)
        mins = arr.min(axis=0)
        maxs = arr.max(axis=0)
        span = np.where(maxs > mins, maxs - mins, 1.0)
        norm = (arr - mins) / span
        dist = np.sqrt((norm ** 2).sum(axis=1))
        return front[int(np.argmin(dist))]

    def _should_log_convergence(self, net, round_idx) -> bool:
        """See the class docstring's "GA convergence logging" section.

        Round 0 is deliberately excluded (every node holds exactly cfg.e0,
        so f2 is pinned at -e0 and carries zero information). Logging
        instead fires the first reclustering round at or after
        `self._conv_round_min` where the ALIVE population's residual
        energy has genuinely diverged -- there is no upper cutoff, so a
        slow-to-diverge run still gets a real, information-bearing log
        rather than a forced one.
        """
        if self._convergence_logged or net.run_index != 0:
            return False
        if round_idx < self._conv_round_min:
            return False
        alive_energy = net.energy[net.alive]
        if alive_energy.size < 2:
            return False
        return bool(np.std(alive_energy) > self._conv_energy_std_threshold)

    # ------------------------------------------------------------------
    # GA driver
    # ------------------------------------------------------------------
    def _run_ga(self, net, round_idx, rng):
        cfg = net.cfg
        alive_arr = np.flatnonzero(net.alive)
        alive_idx = alive_arr.tolist()
        n_alive = len(alive_idx)
        k = max(1, min(n_alive, round(cfg.p_ch * n_alive)))

        pop = [self._random_individual(alive_idx, k, rng) for _ in range(cfg.pop_size)]
        evals = [self._evaluate(net, alive_arr, ind) for ind in pop]
        objectives = [e[0] for e in evals]

        log_this_run = self._should_log_convergence(net, round_idx)
        convergence_rows = []

        for gen in range(cfg.generations):
            fronts = self._fast_nondominated_sort(objectives)
            ranks = {}
            crowd = {}
            for f_idx, front in enumerate(fronts):
                for idx in front:
                    ranks[idx] = f_idx
                crowd.update(self._crowding_distance(objectives, front))

            pop_indices = list(range(len(pop)))
            offspring = []
            while len(offspring) < cfg.pop_size:
                pa = self._tournament_select(pop_indices, ranks, crowd, rng)
                pb = self._tournament_select(pop_indices, ranks, crowd, rng)
                child = self._crossover(pop[pa], pop[pb], alive_idx, rng)
                if rng.random() < self.MUTATION_PROB:
                    child = self._mutate(child, alive_idx, rng)
                offspring.append(child)

            offspring_evals = [self._evaluate(net, alive_arr, ind) for ind in offspring]
            offspring_objectives = [e[0] for e in offspring_evals]

            combined_pop = pop + offspring
            combined_evals = evals + offspring_evals
            combined_objectives = objectives + offspring_objectives

            combined_fronts = self._fast_nondominated_sort(combined_objectives)
            new_idx = []
            for front in combined_fronts:
                if len(new_idx) + len(front) <= cfg.pop_size:
                    new_idx.extend(front)
                else:
                    remaining = cfg.pop_size - len(new_idx)
                    cd = self._crowding_distance(combined_objectives, front)
                    front_sorted = sorted(front, key=lambda i: -cd.get(i, 0.0))
                    new_idx.extend(front_sorted[:remaining])
                    break

            pop = [combined_pop[i] for i in new_idx]
            evals = [combined_evals[i] for i in new_idx]
            objectives = [combined_objectives[i] for i in new_idx]

            if log_this_run:
                cur_fronts = self._fast_nondominated_sort(objectives)
                knee_idx = self._knee_point(objectives, cur_fronts[0])
                knee_f1, knee_f2, knee_f3 = objectives[knee_idx]
                obj_arr = np.array(objectives, dtype=float)
                best_f1, best_f2, best_f3 = obj_arr.min(axis=0).tolist()
                convergence_rows.append({
                    "generation": gen,
                    "knee_f1": knee_f1, "knee_f2": knee_f2, "knee_f3": knee_f3,
                    "best_f1": best_f1, "best_f2": best_f2, "best_f3": best_f3,
                })

        fronts = self._fast_nondominated_sort(objectives)
        knee_idx = self._knee_point(objectives, fronts[0])

        if log_this_run:
            self._write_convergence_log(convergence_rows)
            self._convergence_logged = True
            self._convergence_round = round_idx
            self.convergence_log = convergence_rows

        best_individual = pop[knee_idx]
        _, non_ch, nearest_pos = evals[knee_idx]
        member_of = {
            int(n): int(best_individual[p]) for n, p in zip(non_ch.tolist(), nearest_pos.tolist())
        }
        ch_ids = [int(c) for c in best_individual]
        return ClusterAssignment(ch_ids=ch_ids, member_of=member_of)

    @staticmethod
    def _write_convergence_log(rows):
        # This write is a side effect of running the protocol at all, and it
        # targets a fixed path. Any sweep that runs NSGA-II under a NON-headline
        # configuration (different N, field size, or BS placement) would
        # therefore overwrite the production-scale validation artifact with one
        # the paper never intended to cite. scripts/scale_sweep.py sets this
        # variable for exactly that reason; regenerate the real artifact with
        # scripts/generate_nsga2_convergence.py.
        if os.environ.get("WSN_SUPPRESS_VALIDATION_WRITE"):
            return
        os.makedirs(_RESULTS_VALIDATION_DIR, exist_ok=True)
        path = os.path.join(_RESULTS_VALIDATION_DIR, "nsga2_convergence.csv")
        fieldnames = ["generation", "knee_f1", "knee_f2", "knee_f3", "best_f1", "best_f2", "best_f3"]
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)

    # ------------------------------------------------------------------
    # Carry-forward between reclustering rounds
    # ------------------------------------------------------------------
    def _carry_forward(self, net):
        prev = self._assignment
        alive = net.alive
        surviving_chs = [c for c in prev.ch_ids if alive[c]]
        member_of = {}
        if surviving_chs:
            ch_arr = np.array(surviving_chs, dtype=int)
            for m, c in prev.member_of.items():
                if not alive[m]:
                    continue
                if alive[c]:
                    member_of[m] = c
                else:
                    dists = net.dist[m, ch_arr]
                    nearest = int(ch_arr[int(np.argmin(dists))])
                    member_of[m] = nearest
        return ClusterAssignment(ch_ids=surviving_chs, member_of=member_of)

    # ------------------------------------------------------------------
    # Protocol interface
    # ------------------------------------------------------------------
    def setup_round(self, net, round_idx: int, rng) -> ClusterAssignment:
        cfg = net.cfg
        if not self._has_clustered or round_idx % cfg.ga_interval == 0:
            assignment = self._run_ga(net, round_idx, rng)
            self.reclustered_this_round = True
            self._has_clustered = True
        else:
            assignment = self._carry_forward(net)
            self.reclustered_this_round = False
        self._assignment = assignment
        return assignment

    def route(self, net, assignment: ClusterAssignment, round_idx: int) -> list:
        members_by_ch = {}
        for m, c in assignment.member_of.items():
            members_by_ch.setdefault(c, []).append(m)

        transmissions = []
        for ch in assignment.ch_ids:
            members = sorted(m for m in members_by_ch.get(ch, []) if net.alive[m])
            for slot, m in enumerate(members):
                transmissions.append(
                    Transmission(src=m, dst=ch, kind="data", slot_index=slot, hop_depth=1, originates=True)
                )
            if net.alive[ch]:
                transmissions.append(
                    Transmission(
                        src=ch, dst=BS, kind="data", slot_index=len(members),
                        hop_depth=2, originates=True,
                    )
                )

        assigned_or_ch = set(assignment.ch_ids) | set(assignment.member_of.keys())
        alive_idx = np.flatnonzero(net.alive)
        for n in alive_idx:
            n = int(n)
            if n in assigned_or_ch:
                continue
            transmissions.append(
                Transmission(src=n, dst=BS, kind="data", slot_index=0, hop_depth=1, originates=True)
            )

        return transmissions
