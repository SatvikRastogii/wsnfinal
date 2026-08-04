"""Graph Convolutional Network (GCN) cluster-head selection.

Kipf, T. N., & Welling (2017). "Semi-Supervised Classification with Graph
Convolutional Networks." ICLR 2017. (The symmetric-normalized propagation
rule `A_hat = D^(-1/2)(A+I)D^(-1/2)`, `H^(l+1) = act(A_hat H^(l) W^(l))`,
applied here to score cluster-head suitability rather than classify graph
nodes.)

`control_model = "centralized"`: the BS builds the graph, runs the frozen
network, and dictates cluster structure every round (see
`docs/ASSUMPTIONS.md` item 23) -- no node makes an autonomous decision.

Graph and features
---------------------
- Graph over ALIVE nodes only: symmetrized k-nearest-neighbour, k=6 (`A[i,j]
  = 1` if j is among i's 6 nearest alive neighbours OR i is among j's,
  i.e. `A = A_knn | A_knn.T`). `A_hat = D^(-1/2)(A+I)D^(-1/2)`.
- Features X: the SAME 4 features as DQN (`wsn_sim.protocols.dqn.
  state_features` -- residual_energy/e0, dist_to_BS/max_dist_to_BS,
  local_density/n_alive, rounds_since_last_CH/epoch_len), imported and
  reused directly rather than redefined, so the two learned protocols are
  compared on an apples-to-apples INPUT basis and only differ in
  architecture/training signal.

Network (hand-written forward/backward, verified in tests/test_nn.py)
--------------------------------------------------------------------------
Two graph-conv layers, hidden width 16:
    H = ReLU(A_hat @ X @ W0)          W0: (4, 16)
    s = (A_hat @ H @ W1).squeeze(-1)  W1: (16, 1)   -- one score per node
No bias terms (matching the spec's literal layer formulas). Adam (lr 1e-3,
`wsn_sim.nn.Adam`) is used for training.

CH selection: greedy top-k with a minimum separation
---------------------------------------------------------
Nodes are sorted by score `s` descending. Walking that order, a candidate is
ACCEPTED as a CH iff it is at least 15 m from every already-accepted CH;
otherwise it is skipped (not replaced -- the greedy pass never backtracks).
Stops once `k = max(1, round(cfg.p_ch * n_alive))` CHs are accepted OR
candidates are exhausted -- if separation exhausts candidates first, FEWER
than k CHs are accepted (never padded back up to k). Membership is
nearest-accepted-CH, the same convention as every other clustering protocol
here.

TRAINING SIGNAL -- self-supervised energy-balance objective (NOT imitation)
--------------------------------------------------------------------------------
This network is trained against a differentiable proxy for "is this a good
set of cluster heads", not to imitate LEACH (that would make any later
LEACH-vs-GCN comparison vacuous) and not wired into the DQN training loop
in any way (separate script, separate weights file, separate reward/loss
entirely).

SCORE STANDARDIZATION (fixes a scale defect, not a design choice to tune):
raw scores `s` out of a randomly-initialized/lightly-trained network sit at
roughly `+/-0.1`, while the fixed geometry term `d_ij / T` spans `~0..4.7`
(T=30.0). Feeding raw `s` into the membership softmax below therefore gives
the learnable term ~50x less influence than the fixed geometry term, so
gradients through the softmax are negligible and the network has no real
leverage over the loss. To fix this, `s` is standardized to zero mean / unit
variance across alive nodes before it enters ANY softmax in this loss:

    s_norm = (s - mean(s)) / (std(s) + 1e-8)

and a fixed gain `GAIN=3.0` is applied only where `s_norm` competes directly
against the `d_ij / T` geometry term, putting the two on comparable scale
(`~+/-3` vs `~0..4.7`). Concretely: `q = softmax(s_norm)` over alive nodes (a
SOFT cluster-head distribution) and, for every ordered pair (i, j), `M_ij =
softmax_j(GAIN * s_norm_j - d_ij / T)` (node i's soft membership over
candidate heads j -- every node is a candidate head, not just the top-k,
since the loss must stay differentiable through the discrete top-k+
separation selection that only happens at INFERENCE time). Then

    L =   sum_ij M_ij * c_ij            (expected member -> head tx energy)
        + lam1 * sum_j q_j * c_jBS       (expected head -> BS tx energy)
        + lam2 * var_j(soft cluster size)  (load balance, size_j = sum_i M_ij)
        - lam3 * sum_j q_j * e_hat_j       (prefer high-residual-energy heads)

with `lam1=1.0, lam2=0.5, lam3=0.5`. `c_ij` / `c_jBS` are the ENGINE's own
`radio.e_tx` costs (imported from `wsn_sim.radio`, never re-derived),
divided by `e_tx(cfg.data_bits, ref_d, cfg)` at a fixed reference distance
(the larger of the field's max node-node and max node-BS distance) purely
to bring them to O(1) for numerical conditioning -- this is a linear
rescaling of the SAME cost function, not a different one.

Standardization is a monotonic, positive-scale affine transform of `s`
(`std(s)+eps > 0`), so it never changes the ORDER of scores -- inference-time
top-k CH selection (`GCNProtocol.setup_round`, which ranks by raw `s`) is
unaffected and needed no change.

`gcn.energy_balance_loss` returns both `L` and `dL/ds` (hand-derived; see
inline comments for the four term-by-term softmax-gradient identities used,
PLUS the standardization Jacobian that `dL/ds_norm` is chained back through
-- omitting that Jacobian would be a silent gradient bug, since `s` no
longer enters the loss directly anywhere) so the training script chains it
directly into `gcn_backward` -- no autodiff anywhere in this codebase
(torch/scipy are absent by requirement).

What this network can and cannot learn (the intended DQN contrast)
------------------------------------------------------------------------
GCN sees only the CURRENT round's graph and node state; its loss is a
single-step (not discounted, not bootstrapped) energy/balance proxy for
THIS round alone. It is a topology- and energy-aware CH SCORING function
with NO temporal credit assignment: it cannot learn "elect an expensive CH
this round to extend the network's lifetime three rounds from now," because
nothing in its training signal ever looks past the current round. DQN
(`wsn_sim.protocols.dqn`), by contrast, is trained with a discounted
Bellman target specifically so it CAN learn that kind of sacrifice-now-for-
later-payoff tradeoff. This is the deliberate spatial/structural (GCN) vs.
temporal (DQN) contrast the two learned protocols are meant to illustrate.

TRAINING REGIME
-------------------
Trained on run_index 100..129 with RANDOMIZED residual-energy states (not
just the topologies' natural round-0 state -- see `scripts/train_gcn.py`
for why: a GCN trained only ever seeing `energy == e0` for every node could
never learn anything about the residual-energy term of its own loss).
Frozen weights: `models/gcn_weights.npz`. Learning curve:
`results/validation/gcn_learning_curve.csv`. Same missing-weights hard-error
behaviour as DQN (see `_load_frozen_weights` below) -- no silent
random-weight fallback.

`ops_this_round`: kNN graph construction is one node-to-node distance
computation per alive-node pair (`n_alive * (n_alive - 1)`, symmetrized
kNN still requires the full pairwise distance matrix), PLUS one graph
forward pass per layer counted as `n_alive + n_edges` (nodes processed plus
edges propagated over, matching `docs/METRICS.md`'s stated `O((N+E)*H)`
inference complexity -- unlike DQN's per-node-independent forward pass,
a GCN forward pass is fundamentally a single joint computation over the
whole graph, not `n_alive` separable ones), PLUS one distance computation
per greedy-selection candidate-vs-accepted-CH separation check.

Deviations
-----------
- All energy accounting and packet sizing is engine-owned, as with every
  protocol in this simulator; this module only decides cluster structure.
- No bias terms in either graph-conv layer (spec's literal formulas omit
  them); DQN's MLP does have biases. This asymmetry is intentional, not an
  inconsistency -- it mirrors each network's own spec exactly.
"""

import os

import numpy as np

from ..network import BS
from ..nn import relu, relu_grad_mask, softmax
from ..radio import e_tx
from .base import ClusterAssignment, Protocol, Transmission
from .dqn import state_features

K_NEIGHBORS = 6
HIDDEN = 16
N_FEATURES = 4
MIN_CH_SEPARATION_M = 15.0
T_MEMBERSHIP = 30.0
LAM1, LAM2, LAM3 = 1.0, 0.5, 0.5
GAIN = 3.0  # scale-matches standardized scores against d_ij/T (~0..4.7) in the membership softmax

_MODELS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "models"
)
WEIGHTS_PATH = os.path.join(_MODELS_DIR, "gcn_weights.npz")


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------

def build_normalized_adjacency(dist_sub: np.ndarray, k: int = K_NEIGHBORS):
    """dist_sub: (n,n) pairwise distance among alive nodes. Returns
    (A_hat, n_edges) where A_hat is the symmetric-normalized adjacency
    (with self-loops) and n_edges is the number of off-diagonal nonzero
    entries in the symmetrized (pre-self-loop) adjacency, used for ops
    counting.
    """
    n = dist_sub.shape[0]
    if n == 0:
        return np.zeros((0, 0)), 0
    if n == 1:
        return np.ones((1, 1)), 0

    d = dist_sub.copy()
    np.fill_diagonal(d, np.inf)
    kk = min(k, n - 1)
    nn_idx = np.argpartition(d, kk - 1, axis=1)[:, :kk]  # (n, kk) nearest-kk indices per row

    A = np.zeros((n, n), dtype=bool)
    rows = np.repeat(np.arange(n), kk)
    cols = nn_idx.reshape(-1)
    A[rows, cols] = True
    A = A | A.T  # symmetrize
    n_edges = int(A.sum())  # counts each undirected edge twice (i->j and j->i), both real propagation paths

    A_self = A | np.eye(n, dtype=bool)
    deg = A_self.sum(axis=1).astype(float)
    d_inv_sqrt = 1.0 / np.sqrt(deg)
    A_hat = (A_self.astype(float) * d_inv_sqrt[:, None]) * d_inv_sqrt[None, :]
    return A_hat, n_edges


# ---------------------------------------------------------------------------
# Hand-written forward/backward (gradient-checked in tests/test_nn.py).
# ---------------------------------------------------------------------------

def init_params(rng):
    w0 = rng.normal(0.0, np.sqrt(2.0 / N_FEATURES), size=(N_FEATURES, HIDDEN))
    w1 = rng.normal(0.0, np.sqrt(2.0 / HIDDEN), size=(HIDDEN, 1))
    return {"W0": w0, "W1": w1}


def forward(params, A_hat, X):
    """X: (n,4), A_hat: (n,n) -> s: (n,). Returns (s, cache)."""
    xw0 = X @ params["W0"]          # (n,16)
    axw0 = A_hat @ xw0               # (n,16)
    h = relu(axw0)
    hw1 = h @ params["W1"]           # (n,1)
    ahw1 = A_hat @ hw1                # (n,1)
    s = ahw1[:, 0]
    cache = (X, A_hat, xw0, axw0, h, hw1)
    return s, cache


def backward(params, cache, ds):
    """ds: (n,) upstream gradient on the score vector -> grads dict."""
    X, A_hat, xw0, axw0, h, hw1 = cache
    d_ahw1 = ds[:, None]                       # (n,1)
    d_hw1 = A_hat.T @ d_ahw1                   # (n,1)
    dW1 = h.T @ d_hw1                          # (16,1)
    dh = d_hw1 @ params["W1"].T                # (n,16)
    d_axw0 = dh * relu_grad_mask(axw0)         # (n,16)
    d_xw0 = A_hat.T @ d_axw0                   # (n,16)
    dW0 = X.T @ d_xw0                          # (4,16)
    return {"W0": dW0, "W1": dW1}


# ---------------------------------------------------------------------------
# Self-supervised energy-balance loss and its hand-derived gradient w.r.t.
# the score vector s. See module docstring for the term-by-term formula.
# ---------------------------------------------------------------------------

def energy_balance_loss(net, alive_arr, s, e_hat, lam1=LAM1, lam2=LAM2, lam3=LAM3, T=T_MEMBERSHIP, gain=GAIN):
    cfg = net.cfg
    n = len(alive_arr)

    d_ij = net.dist[np.ix_(alive_arr, alive_arr)]
    d_jbs = net.dist_bs[alive_arr]
    ref_d = max(float(net.dist.max()), float(net.dist_bs.max()), 1.0)
    scale = float(e_tx(cfg.data_bits, ref_d, cfg))
    c_ij = e_tx(cfg.data_bits, d_ij, cfg) / scale     # (n,n), O(1)
    c_jbs = e_tx(cfg.data_bits, d_jbs, cfg) / scale   # (n,)

    # --- standardize raw scores (zero mean, unit variance across alive
    # nodes) before ANY softmax below -- see module docstring for why: raw
    # s (~+/-0.1) is ~50x smaller than d_ij/T (~0..4.7), so without this the
    # learnable term has no leverage against the fixed geometry term. `gain`
    # then scale-matches s_norm specifically where it competes against
    # d_ij/T (the membership softmax M); q's softmax has no competing fixed
    # term, so it uses s_norm ungained. ---
    mu = float(s.mean())
    std = float(s.std())          # population std (ddof=0)
    sigma = std + 1e-8            # epsilon guards the s_norm divide only
    s_norm = (s - mu) / sigma     # (n,)
    z = gain * s_norm              # (n,) -- scale-matched against d_ij/T

    q = softmax(s_norm)                   # (n,) -- soft CH distribution
    u = z[None, :] - d_ij / T             # (n,n): row i = candidate scores seen by member i
    M = softmax(u, axis=1)                # (n,n) -- M[i,j] = i's soft membership on head j

    Mc = M * c_ij
    term1 = float(Mc.sum())
    term2 = lam1 * float((q * c_jbs).sum())
    n_vec = M.sum(axis=0)                 # (n,) soft cluster size per candidate head j
    mean_n = float(n_vec.mean())
    var_n = float(np.mean((n_vec - mean_n) ** 2))
    term3 = lam2 * var_n
    term4 = -lam3 * float((q * e_hat).sum())
    L = term1 + term2 + term3 + term4

    # --- dL/ds, term by term (all standard softmax-weighted-sum identities:
    # d(sum_j p_j f_j)/dz_k = p_k*(f_k - sum_j p_j f_j) for p=softmax(z)),
    # computed first w.r.t. z / s_norm (whichever the term actually uses),
    # then chained back through the standardization Jacobian at the end. ---

    # terms 2+4: sum_j q_j * b_j, b = lam1*c_jbs - lam3*e_hat (constant w.r.t. s).
    # q = softmax(s_norm), so this gradient lands directly on s_norm (no gain).
    b = lam1 * c_jbs - lam3 * e_hat
    d24_dsnorm = q * (b - float((q * b).sum()))

    # term1: sum_i sum_j M_ij c_ij, M_i = softmax_j(z_j - d_ij/T) row-wise;
    # z_k enters every row i at column k, so
    # d(term1)/dz_k = sum_i M_ik*(c_ik - <M_i,c_i>)
    #              = colsum(M*c)_k - (M.T @ rowdot)_k,  rowdot_i = sum_j M_ij c_ij
    rowdot = Mc.sum(axis=1)
    colsum_mc = Mc.sum(axis=0)
    d1_dz = colsum_mc - M.T @ rowdot

    # term3: lam2*Var_j(n_j), n_j = colsum(M)_j = sum_i M_ij.
    # dVar/dn_j = (2/n)*(n_j - mean_n) [exact for population variance].
    # dn_j/dz_k = delta(j,k)*n_j - sum_i M_ij*M_ik  (softmax gradient, z_k
    # enters column k of each row i's distribution).
    # Chaining: dVar/dz_k = (2/n)*[n_k*(n_k-mean_n) - (M.T @ w)_k],
    # w_i = sum_j (n_j-mean_n)*M_ij = (M @ (n_vec-mean_n))_i.
    centered = n_vec - mean_n
    w = M @ centered
    dvar_dz = (2.0 / n) * (n_vec * centered - M.T @ w)
    d3_dz = lam2 * dvar_dz

    # z = gain * s_norm, so d(term1+term3)/d(s_norm) = gain * d(term1+term3)/dz.
    dsnorm = gain * (d1_dz + d3_dz) + d24_dsnorm   # dL/d(s_norm), all terms

    # --- chain back through standardization: s_norm_k = (s_k - mu)/sigma.
    # Standard "LayerNorm-style" Jacobian (no learnable scale/bias):
    #   ds_norm_k/ds_m = (delta_km - 1/n)/sigma - s_norm_k*s_norm_m/(n*std)
    # so for upstream gradient g = dL/d(s_norm):
    #   dL/ds_m = (g_m - mean(g))/sigma - s_norm_m * mean(g*s_norm) / std
    # (derived from d(std)/ds_m = (s_m-mu)/(n*std); note the FIRST term uses
    # sigma = std+eps (what s_norm was actually divided by) while the SECOND
    # uses the true std (what its own derivative works out to) -- these are
    # not interchangeable if eps is non-negligible, so both are kept exact.)
    g = dsnorm
    mean_g = float(g.mean())
    mean_g_snorm = float((g * s_norm).mean())
    std_safe = std if std > 1e-12 else 1.0  # s_norm==0 whenever std==0, so this only avoids 0/0
    ds = (g - mean_g) / sigma - (s_norm / std_safe) * mean_g_snorm

    return L, ds


def _load_frozen_weights():
    if not os.path.exists(WEIGHTS_PATH):
        raise FileNotFoundError(
            f"GCN frozen weights not found at {WEIGHTS_PATH!r}. Run "
            f"`python scripts/train_gcn.py` first to train and freeze the "
            f"network before evaluating the 'gcn' protocol. This is a hard "
            f"error, not a silent random-weight fallback: an untrained "
            f"network would still run and produce numbers, but they would "
            f"be meaningless and indistinguishable from a real result."
        )
    data = np.load(WEIGHTS_PATH)
    return {k: np.asarray(data[k], dtype=float) for k in ("W0", "W1")}


class GCNProtocol(Protocol):
    name = "gcn"
    control_model = "centralized"

    def __init__(self):
        self.reclustered_this_round = True
        self._params = _load_frozen_weights()
        self._last_ch_round = {}

    def setup_round(self, net, round_idx: int, rng) -> ClusterAssignment:
        cfg = net.cfg
        alive_arr = np.flatnonzero(net.alive)
        n_alive = len(alive_arr)
        self.reclustered_this_round = True
        if n_alive == 0:
            return ClusterAssignment(ch_ids=[], member_of={})

        dist_sub = net.dist[np.ix_(alive_arr, alive_arr)]
        self.ops_this_round += n_alive * max(0, n_alive - 1)  # kNN pairwise distances
        A_hat, n_edges = build_normalized_adjacency(dist_sub, K_NEIGHBORS)

        X = state_features(net, alive_arr, round_idx, self._last_ch_round)
        s, _ = forward(self._params, A_hat, X)
        self.ops_this_round += 2 * (n_alive + n_edges)  # 2 graph-conv layers, each O(N+E)

        k = max(1, min(n_alive, round(cfg.p_ch * n_alive)))
        order = np.argsort(-s, kind="stable")

        ch_local = []
        for cand in order.tolist():
            if len(ch_local) >= k:
                break
            ok = True
            for chosen in ch_local:
                self.ops_this_round += 1  # separation distance check
                if dist_sub[cand, chosen] < MIN_CH_SEPARATION_M:
                    ok = False
                    break
            if ok:
                ch_local.append(cand)

        ch_local_arr = np.array(ch_local, dtype=int)
        ch_ids = [int(x) for x in alive_arr[ch_local_arr]] if len(ch_local) > 0 else []
        for c in ch_ids:
            self._last_ch_round[c] = round_idx

        member_of = {}
        if ch_ids:
            ch_mask = np.zeros(n_alive, dtype=bool)
            ch_mask[ch_local_arr] = True
            non_ch = alive_arr[~ch_mask]
            if len(non_ch) > 0:
                ch_arr = np.array(ch_ids, dtype=int)
                d = net.dist[np.ix_(non_ch, ch_arr)]
                self.ops_this_round += int(d.size)
                nearest_pos = np.argmin(d, axis=1)
                for n, p in zip(non_ch.tolist(), nearest_pos.tolist()):
                    member_of[int(n)] = int(ch_arr[p])

        return ClusterAssignment(ch_ids=ch_ids, member_of=member_of)

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
