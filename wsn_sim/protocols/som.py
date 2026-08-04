"""Kohonen Self-Organizing Map (SOM) cluster-head selection.

Kohonen, T. (1982). "Self-Organized Formation of Topologically Correct
Feature Maps." Biological Cybernetics, 43(1), 59-69. Kohonen, T. (1990).
"The Self-Organizing Map." Proceedings of the IEEE, 78(9), 1464-1480.

`control_model = "centralized"`: the BS trains the map over globally known
node state and dictates cluster structure (see `docs/ASSUMPTIONS.md` item
23) -- no node makes an autonomous CH decision.

Map and retrain cadence
------------------------
- `U = max(1, min(n_alive, round(cfg.p_ch * n_alive)))` map units, arranged on a 1-D
  CHAIN neighbourhood topology (unit `i`'s neighbours are `i-1`/`i+1`; the
  neighbourhood function below is evaluated on `|i - j|`, the chain
  distance, not a 2-D grid distance).
- The map is RETRAINED from scratch every `cfg.ga_interval` rounds -- the
  SAME re-clustering cadence as NSGA-II (`protocols/nsga2.py`) and Fuzzy-T2
  (`protocols/fuzzy_t2.py`), so all three centralized, periodically
  re-clustering protocols are compared on equal footing (same knob, same
  carry-forward semantics between reclusterings). Between reclusterings the
  last assignment is reused, dropping dead CHs (members rejoin their
  nearest surviving CH, or become self-heads if none survive) -- identical
  logic to NSGA-II/Fuzzy-T2's `_carry_forward`.

Input features (per alive node, each normalized to [0, 1])
-------------------------------------------------------------
- x: `net.x[i] / cfg.field_w`
- y: `net.y[i] / cfg.field_h`
- residual energy: `net.energy[i] / net.initial_energy[i]`, clipped to
  [0, 1] -- normalized against the node's own starting energy, same
  convention as Fuzzy-T2's E input (still means "fraction of my own budget
  left" under heterogeneity).

Training (batch-per-iteration Kohonen update)
------------------------------------------------
100 iterations. Learning rate decays geometrically 0.5 -> 0.01 and the
Gaussian neighbourhood radius decays geometrically `U/2 -> 0.5` across the
100 iterations (`radius_t = radius_0 * (radius_end/radius_0) ** (t/99)`,
same shape for the learning rate). Weights are `U x 3`, initialized from
`rng` (the Generator passed into `setup_round` -- never a private RNG) via
`rng.random((U, 3))`, which lands directly in the same [0,1) range as the
normalized input features.

Each iteration:
  1. Compute EVERY alive node's distance to EVERY map unit's weight vector
     (an `n_alive x U` computation -- this is the counted "op", see below)
     and take each node's best-matching unit (BMU) under the CURRENT
     weights.
  2. Visit the `n_alive` nodes in an `rng`-drawn random order and apply the
     classic online Kohonen update to every unit using that node's
     (already-computed) BMU:
         W[u] += lr_t * h(u, bmu_i) * (x_i - W[u])
         h(u, bmu_i) = exp(-(u - bmu_i)^2 / (2 * radius_t^2))
     `lr_t`/`radius_t` are held fixed for the whole iteration and decayed
     between iterations (not per node). This is a standard sequential
     Kohonen sweep, one "epoch" per iteration, with the BMU snapshot from
     step 1 shared across every node's update within that iteration (a
     deliberate simplification -- units the sweep has already moved this
     iteration are not immediately re-queried -- documented under
     Deviations below).

`ops_this_round` counts exactly `n_alive * U` per training iteration (step
1's distance computation), matching `docs/METRICS.md`'s stated SOM
complexity `O(N*U*I)`, PLUS one more `n_alive * U` pass after training to
compute the FINAL BMU assignment used for clustering, plus one distance
computation per node for its distance-to-group-centroid term in CH scoring
(see below).

Cluster-head selection
------------------------
Every alive node maps to its BMU (final weights, after training). Empty
BMU groups (no node's BMU) contribute NO cluster head -- never
force-elected. Within each non-empty BMU group, the CH is the node
maximizing

    0.5 * normalized_residual_energy + 0.5 * (1 - normalized_distance_to_group_centroid)

where `normalized_residual_energy` is the node's own (already [0,1]-clipped)
energy feature, `group_centroid` is the mean (x, y) position of the group's
members, and `normalized_distance_to_group_centroid` is that node's
Euclidean distance to the centroid divided by the group's OWN maximum
member-to-centroid distance (0.0 for a singleton group, since max distance
there is 0 and every member -- the one member -- is exactly at distance 0
from itself... a one-node group's centroid IS that node).

Deviations from a textbook Kohonen SOM
-----------------------------------------
- All energy accounting and packet sizing is engine-owned, as with every
  protocol in this simulator; this module only decides cluster structure.
- The textbook algorithm updates weights strictly sequentially (each node's
  BMU is recomputed against the just-updated weights before the next node
  is processed). This implementation snapshots BMUs once per iteration
  (step 1 above) and applies all `n_alive` updates against that snapshot,
  which is the standard "batch-within-iteration" relaxation of online SOM
  training -- it keeps the ops-counting formula in `docs/METRICS.md`
  (`O(N*U*I)`, not `O(N*U*I) + O(N*U*N)`) exact, and converges to
  effectively the same map at this scale (U on the order of a handful of
  units, 100 iterations).
- The paper's original neighbourhood topology is typically a 2-D grid; a
  1-D chain is used here per this build's spec (also keeps the "which unit
  is a neighbour" relation a single scalar index difference, matching
  PEGASIS's own chain-topology convention elsewhere in this simulator).
"""

import numpy as np

from ..network import BS
from .base import ClusterAssignment, Protocol, Transmission

N_ITERS = 100
LR_START, LR_END = 0.5, 0.01
RADIUS_END = 0.5


class SOMProtocol(Protocol):
    name = "som"
    control_model = "centralized"

    def __init__(self):
        self.reclustered_this_round = False
        self._assignment = ClusterAssignment(ch_ids=[], member_of={})
        self._has_clustered = False

    # ------------------------------------------------------------------
    # Features
    # ------------------------------------------------------------------
    @staticmethod
    def _features(net, alive_arr):
        cfg = net.cfg
        x = net.x[alive_arr] / cfg.field_w
        y = net.y[alive_arr] / cfg.field_h
        e = np.clip(net.energy[alive_arr] / net.initial_energy[alive_arr], 0.0, 1.0)
        return np.stack([x, y, e], axis=1)

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------
    def _train(self, X, U, rng):
        n_alive = X.shape[0]
        W = rng.random((U, 3))
        unit_pos = np.arange(U, dtype=float)

        radius_start = max(U / 2.0, RADIUS_END)
        for t in range(N_ITERS):
            frac = t / (N_ITERS - 1) if N_ITERS > 1 else 1.0
            lr_t = LR_START * (LR_END / LR_START) ** frac
            radius_t = radius_start * (RADIUS_END / radius_start) ** frac

            d2 = ((X[:, None, :] - W[None, :, :]) ** 2).sum(axis=2)  # (n_alive, U)
            self.ops_this_round += n_alive * U
            bmu_all = np.argmin(d2, axis=1)

            order = rng.permutation(n_alive)
            for i in order:
                bmu = bmu_all[i]
                h = np.exp(-((unit_pos - bmu) ** 2) / (2.0 * radius_t ** 2))
                W += lr_t * h[:, None] * (X[i] - W)

        return W

    # ------------------------------------------------------------------
    # Clustering
    # ------------------------------------------------------------------
    def _recluster(self, net, rng):
        alive_arr = np.flatnonzero(net.alive)
        n_alive = len(alive_arr)
        cfg = net.cfg
        U = max(1, min(n_alive, round(cfg.p_ch * n_alive)))

        X = self._features(net, alive_arr)
        W = self._train(X, U, rng)

        # Final BMU assignment against the trained map.
        d2 = ((X[:, None, :] - W[None, :, :]) ** 2).sum(axis=2)
        self.ops_this_round += n_alive * U
        bmu = np.argmin(d2, axis=1)

        xy = np.stack([net.x[alive_arr], net.y[alive_arr]], axis=1)
        e_norm = X[:, 2]

        ch_ids = []
        member_of = {}
        for u in range(U):
            group_mask = bmu == u
            if not np.any(group_mask):
                continue  # empty BMU group: no forced CH
            group_nodes = alive_arr[group_mask]
            group_xy = xy[group_mask]
            group_e = e_norm[group_mask]

            centroid = group_xy.mean(axis=0)
            dist_to_centroid = np.sqrt(((group_xy - centroid) ** 2).sum(axis=1))
            self.ops_this_round += len(group_nodes)  # one dist-to-centroid comp per member
            max_d = dist_to_centroid.max()
            norm_dist = dist_to_centroid / max_d if max_d > 0.0 else np.zeros_like(dist_to_centroid)

            score = 0.5 * group_e + 0.5 * (1.0 - norm_dist)
            ch = int(group_nodes[int(np.argmax(score))])
            ch_ids.append(ch)
            for n in group_nodes.tolist():
                if n != ch:
                    member_of[int(n)] = ch

        return ClusterAssignment(ch_ids=ch_ids, member_of=member_of)

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
            assignment = self._recluster(net, rng)
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
