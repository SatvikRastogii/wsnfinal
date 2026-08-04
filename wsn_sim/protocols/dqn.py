"""Deep Q-Network (DQN) cluster-head selection.

Mnih, V., Kavukcuoglu, K., Silver, D., et al. (2015). "Human-level control
through deep reinforcement learning." Nature, 518(7540), 529-533.
(Experience replay + a periodically-synced target network, the two ideas
this module borrows; applied here to WSN cluster-head selection rather
than Atari.)

`control_model = "centralized"`: the BS runs the frozen network over
globally known node state and dictates cluster structure every round (see
`docs/ASSUMPTIONS.md` item 23) -- no node makes an autonomous decision.

State (per alive node, 4 features, each normalized to roughly [0, 1])
--------------------------------------------------------------------------
  residual_energy / cfg.e0
  dist_to_BS / max(net.dist_bs)          (static, all-node denominator)
  local_density / n_alive                (alive neighbours within
                                           cfg.density_radius, excluding
                                           self, normalized by n_alive --
                                           NOT n_alive-1, per spec)
  rounds_since_last_CH / epoch_len       (epoch_len = round(1/cfg.p_ch),
                                           the same epoch-length convention
                                           LEACH uses; a node that has
                                           never been a CH is treated as
                                           already `epoch_len` rounds
                                           overdue, i.e. this feature
                                           starts at 1.0)

Network: hand-written MLP, 4 -> 16 (ReLU) -> 2 (Q[not_CH], Q[CH]). Forward
and backward passes are implemented by hand in this module (`forward` /
`backward` below) and verified against central finite differences in
`tests/test_nn.py` (max relative error must be < 1e-5 on every weight
matrix). Adam (lr 1e-3, from `wsn_sim.nn.Adam`) is used for training.

RANKING, not independent per-node binary actions
----------------------------------------------------
At evaluation time this module does NOT let every node act on its own
argmax(Q) independently -- doing so would let epsilon-free greedy Q-values
elect a wildly different number of cluster heads round to round (anywhere
from 0 to n_alive), which is both physically silly (there is no reason
cluster COUNT should be this unstable round to round for a fixed p_ch) and
would have made TRAINING itself unstable (the reward function below is
defined in terms of `std_cluster_size / n_alive`, which presupposes a
roughly fixed cluster count -- training against a free-running count would
fight its own reward signal). Instead, every alive node's advantage
`Q[CH] - Q[not_CH]` is computed, nodes are RANKED by advantage, and the top
`k = max(1, round(cfg.p_ch * n_alive))` become CHs. This makes the network
a learned SCORING/ranking function, not a set of independent RL agents each
free to choose their own action -- documented here explicitly because it is
a real, deliberate narrowing of "the DQN paradigm," not an oversight.
Membership is nearest-CH, same convention as every other clustering
protocol in this simulator.

TRAINING REGIME (locked -- see scripts/train_dqn.py for the full driver)
-----------------------------------------------------------------------------
Pre-trained OFFLINE on run_index 100..129 (30 episodes, disjoint from the
evaluation seeds 0..29 -- evaluation topologies are genuinely unseen),
frozen, and loaded here read-only. `scripts/train_dqn.py` writes
`models/dqn_weights.npz`; `results/validation/dqn_learning_curve.csv` logs
(episode, total_reward, mean_loss, epsilon, fnd_achieved). See that script's
docstring for the reward, replay buffer, target-network, and epsilon-decay
details. Reproduced here only insofar as the frozen weights and the
inference-time state/ranking logic depend on it.

At evaluation:
- Frozen weights are loaded from `models/dqn_weights.npz` once, in
  `__init__`. Missing weights raise `FileNotFoundError` immediately with an
  explicit instruction to run the training script first -- an untrained
  (random-weight) network would silently look like a working protocol and
  produce meaningless comparisons, so this is a hard error, not a fallback.
- NO training happens here, weights are never mutated, and the `rng`
  argument to `setup_round` is never touched (evaluation is a pure,
  deterministic function of network state given frozen weights).
- The assignment is recomputed EVERY round (unlike NSGA-II/Fuzzy-T2/SOM's
  `cfg.ga_interval` gating): a frozen forward pass is cheap inference, not
  an expensive search, so there is no computational reason to cache it, and
  caching would need the same dead-CH carry-forward machinery those other
  three protocols need for no benefit here.

`ops_this_round` counts one forward pass per alive node (the whole-network
batched matrix multiply is one call, but it evaluates `n_alive` independent
node decisions, so `docs/METRICS.md`'s stated inference complexity
`O(N*H)` is counted as `n_alive` ops, mirroring how NSGA-II counts one op
per individual evaluated even though each evaluation is itself vectorized)
plus the density-radius and nearest-CH-membership distance computations
(same convention as Fuzzy-T2/NSGA-II).

Deviations
-----------
- All energy accounting and packet sizing is engine-owned, as with every
  protocol in this simulator; this module only decides cluster structure.
- The paper's DQN targets a discrete-action-per-timestep control problem
  with a single agent; here every alive node is scored each round by the
  SAME shared network (parameter sharing across nodes, not one network per
  node), which is what makes both training and generalizing across
  different `n_alive` values tractable at all.
"""

import os

import numpy as np

from ..network import BS
from ..nn import Adam, relu, relu_grad_mask
from .base import ClusterAssignment, Protocol, Transmission

HIDDEN = 16
N_FEATURES = 4
N_ACTIONS = 2

_MODELS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "models"
)
WEIGHTS_PATH = os.path.join(_MODELS_DIR, "dqn_weights.npz")


# ---------------------------------------------------------------------------
# Hand-written forward/backward (shared by the protocol and the training
# script; gradient-checked in tests/test_nn.py).
# ---------------------------------------------------------------------------

def init_params(rng):
    """He-initialized weights, drawn from `rng` (caller decides which
    stream -- eval never calls this at all; training uses its own rng).
    """
    w1 = rng.normal(0.0, np.sqrt(2.0 / N_FEATURES), size=(N_FEATURES, HIDDEN))
    b1 = np.zeros(HIDDEN)
    w2 = rng.normal(0.0, np.sqrt(2.0 / HIDDEN), size=(HIDDEN, N_ACTIONS))
    b2 = np.zeros(N_ACTIONS)
    return {"W1": w1, "b1": b1, "W2": w2, "b2": b2}


def forward(params, X):
    """X: (N, 4) -> Q: (N, 2). Returns (Q, cache) for backward()."""
    z1 = X @ params["W1"] + params["b1"]
    h1 = relu(z1)
    q = h1 @ params["W2"] + params["b2"]
    cache = (X, z1, h1)
    return q, cache


def backward(params, cache, dQ):
    """dQ: (N, 2) upstream gradient -> grads dict matching `params`."""
    X, z1, h1 = cache
    dW2 = h1.T @ dQ
    db2 = dQ.sum(axis=0)
    dh1 = dQ @ params["W2"].T
    dz1 = dh1 * relu_grad_mask(z1)
    dW1 = X.T @ dz1
    db1 = dz1.sum(axis=0)
    return {"W1": dW1, "b1": db1, "W2": dW2, "b2": db2}


# ---------------------------------------------------------------------------
# State features (shared by the protocol and scripts/train_dqn.py).
# ---------------------------------------------------------------------------

def epoch_len_of(cfg) -> int:
    return max(1, round(1.0 / cfg.p_ch))


def state_features(net, alive_arr, round_idx, last_ch_round: dict, ops_sink=None):
    """Returns (n_alive, 4) feature matrix for the given alive-node index
    array, in the order documented in the module docstring. If `ops_sink`
    is a list with one int element, `ops_sink[0]` is incremented by the
    number of distance computations performed (density-radius check) --
    used so both the protocol and the training script can route this into
    `ops_this_round` consistently without duplicating the density logic.
    """
    cfg = net.cfg
    n_alive = len(alive_arr)
    e_feat = net.energy[alive_arr] / cfg.e0

    max_d = float(net.dist_bs.max())
    max_d = max_d if max_d > 0.0 else 1.0
    d_feat = net.dist_bs[alive_arr] / max_d

    sub = net.dist[np.ix_(alive_arr, alive_arr)]
    within = sub <= cfg.density_radius
    np.fill_diagonal(within, False)
    if ops_sink is not None:
        ops_sink[0] += int(sub.size)
    density = within.sum(axis=1)
    dens_feat = density / max(1, n_alive)

    epoch_len = epoch_len_of(cfg)
    rsc = np.array(
        [round_idx - last_ch_round.get(int(n), round_idx - epoch_len) for n in alive_arr],
        dtype=float,
    )
    rsc_feat = rsc / epoch_len

    return np.stack([e_feat, d_feat, dens_feat, rsc_feat], axis=1)


def _load_frozen_weights():
    if not os.path.exists(WEIGHTS_PATH):
        raise FileNotFoundError(
            f"DQN frozen weights not found at {WEIGHTS_PATH!r}. Run "
            f"`python scripts/train_dqn.py` first to train and freeze the "
            f"network before evaluating the 'dqn' protocol. This is a hard "
            f"error, not a silent random-weight fallback: an untrained "
            f"network would still run and produce numbers, but they would "
            f"be meaningless and indistinguishable from a real result."
        )
    data = np.load(WEIGHTS_PATH)
    return {k: np.asarray(data[k], dtype=float) for k in ("W1", "b1", "W2", "b2")}


class DQNProtocol(Protocol):
    name = "dqn"
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

        ops_sink = [0]
        X = state_features(net, alive_arr, round_idx, self._last_ch_round, ops_sink)
        q, _ = forward(self._params, X)
        self.ops_this_round += n_alive  # one forward pass per alive node
        self.ops_this_round += ops_sink[0]

        advantage = q[:, 1] - q[:, 0]
        k = max(1, min(n_alive, round(cfg.p_ch * n_alive)))
        order = np.argsort(-advantage, kind="stable")
        ch_local = order[:k]
        ch_mask = np.zeros(n_alive, dtype=bool)
        ch_mask[ch_local] = True
        ch_ids = [int(x) for x in alive_arr[ch_local]]
        for c in ch_ids:
            self._last_ch_round[c] = round_idx

        member_of = {}
        non_ch = alive_arr[~ch_mask]
        if len(non_ch) > 0 and ch_ids:
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
