"""Offline GCN training driver (self-supervised energy-balance objective --
see wsn_sim/protocols/gcn.py for the frozen-eval side and the full loss
derivation).

- Trains on run_index 100..129 (30 "episodes", one per topology), disjoint
  from the evaluation seeds 0..29.
- Each episode uses that run_index's REAL topology (`net.x`, `net.y`,
  `net.dist`, `net.dist_bs` -- static, from `Network.__init__`) but with
  RANDOMIZED residual-energy states: at round 0 every node holds exactly
  `cfg.e0`, and a GCN that only ever saw that degenerate state during
  training could never learn anything about the residual-energy term in
  its own loss (`-lam3 * sum_j q_j * e_hat_j`) or the min-separation/
  energy tradeoff it induces. So for each of `STEPS_PER_EPISODE` gradient
  steps within an episode, every alive node's energy is redrawn
  independently as `Uniform(0.05*e0, e0)` -- a fresh synthetic "mid-life"
  snapshot of the same topology -- and `rounds_since_last_CH` is redrawn
  too (a random subset of nodes gets a random recent "last CH round",
  everyone else is treated as overdue), so the network also sees varied
  values on that feature. `alive` stays all-True (every node is a training
  candidate); this is a deliberate simplification, not a claim that
  randomized-low-energy nodes would actually still be alive in a real run
  -- flagged here rather than silently narrowed.
- This is NOT reinforcement learning and is NOT wired into the DQN loop in
  any way: there is no reward, no replay buffer, no environment rollout.
  Each step is a single forward pass -> `energy_balance_loss` -> hand-
  derived `dL/ds` -> `gcn_backward` -> Adam step, i.e. ordinary supervised-
  style gradient descent on a differentiable, self-supervised objective.
- Writes frozen weights to `models/gcn_weights.npz` and a per-episode
  learning curve to `results/validation/gcn_learning_curve.csv`
  (episode, mean_loss, mean_term1_member_tx, mean_term2_ch_bs_tx,
  mean_term3_balance, mean_term4_energy_pref).
- All randomness in this script comes from its own deterministic
  `np.random.default_rng` stream (seeded from the episode's run_index) --
  an offline training utility, not a protocol exercised inside the
  fairness-critical benchmark harness (see `wsn_sim.engine` module
  docstring). The evaluation-time code path (`GCNProtocol.setup_round`)
  never calls this script or touches its randomness.
"""

import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from wsn_sim.config import SimConfig
from wsn_sim.network import Network
from wsn_sim.nn import Adam
from wsn_sim.protocols.dqn import epoch_len_of, state_features
from wsn_sim.protocols.gcn import (
    K_NEIGHBORS,
    backward,
    build_normalized_adjacency,
    energy_balance_loss,
    forward,
    init_params,
)

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MODELS_DIR = os.path.join(_ROOT, "models")
_WEIGHTS_PATH = os.path.join(_MODELS_DIR, "gcn_weights.npz")
_CURVE_PATH = os.path.join(_ROOT, "results", "validation", "gcn_learning_curve.csv")

TRAIN_RUN_INDICES = list(range(100, 130))  # 30 episodes, disjoint from eval seeds 0..29
STEPS_PER_EPISODE = 200
LR = 1e-3
E_MIN_FRAC = 0.05  # avoid a degenerate all-zero-energy draw


def _term_breakdown(net, alive_arr, s, e_hat):
    """Re-derive the four loss terms separately (unscaled by lam where the
    main function already applies it) purely for the learning-curve CSV --
    duplicates a small amount of energy_balance_loss's math (INCLUDING the
    score standardization + gain -- see wsn_sim/protocols/gcn.py's module
    docstring) rather than threading an extra return-terms flag through the
    hot training path.
    """
    from wsn_sim.protocols.gcn import GAIN, LAM1, LAM2, LAM3, T_MEMBERSHIP
    from wsn_sim.nn import softmax
    from wsn_sim.radio import e_tx

    cfg = net.cfg
    d_ij = net.dist[np.ix_(alive_arr, alive_arr)]
    d_jbs = net.dist_bs[alive_arr]
    ref_d = max(float(net.dist.max()), float(net.dist_bs.max()), 1.0)
    scale = float(e_tx(cfg.data_bits, ref_d, cfg))
    c_ij = e_tx(cfg.data_bits, d_ij, cfg) / scale
    c_jbs = e_tx(cfg.data_bits, d_jbs, cfg) / scale

    mu = float(s.mean())
    std = float(s.std())
    sigma = std + 1e-8
    s_norm = (s - mu) / sigma
    z = GAIN * s_norm

    q = softmax(s_norm)
    u = z[None, :] - d_ij / T_MEMBERSHIP
    M = softmax(u, axis=1)
    n_vec = M.sum(axis=0)
    mean_n = float(n_vec.mean())

    t1 = float((M * c_ij).sum())
    t2 = LAM1 * float((q * c_jbs).sum())
    t3 = LAM2 * float(np.mean((n_vec - mean_n) ** 2))
    t4 = -LAM3 * float((q * e_hat).sum())
    return t1, t2, t3, t4


def train():
    os.makedirs(_MODELS_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(_CURVE_PATH), exist_ok=True)

    cfg = SimConfig()
    init_rng = np.random.default_rng(43)
    params = init_params(init_rng)
    adam = Adam(params, lr=LR)

    curve_rows = []

    for ep_idx, run_index in enumerate(TRAIN_RUN_INDICES):
        net = Network(cfg, run_index)
        n = cfg.n_nodes
        alive_arr = np.arange(n)
        rng = np.random.default_rng(50000 + run_index)

        dist_sub = net.dist  # static, all nodes alive throughout training
        A_hat, _ = build_normalized_adjacency(dist_sub, K_NEIGHBORS)
        epoch_len = epoch_len_of(cfg)

        losses, t1s, t2s, t3s, t4s = [], [], [], [], []

        for step in range(STEPS_PER_EPISODE):
            net.energy = rng.uniform(E_MIN_FRAC * cfg.e0, cfg.e0, size=n)

            last_ch_round = {}
            n_recent = int(rng.integers(0, n // 2 + 1))
            recent_nodes = rng.choice(n, size=n_recent, replace=False)
            for node in recent_nodes.tolist():
                last_ch_round[node] = -int(rng.integers(0, epoch_len))

            X = state_features(net, alive_arr, 0, last_ch_round)
            e_hat = X[:, 0]

            s, cache = forward(params, A_hat, X)
            L, ds = energy_balance_loss(net, alive_arr, s, e_hat)
            grads = backward(params, cache, ds)
            adam.step(params, grads)

            losses.append(L)
            t1, t2, t3, t4 = _term_breakdown(net, alive_arr, s, e_hat)
            t1s.append(t1)
            t2s.append(t2)
            t3s.append(t3)
            t4s.append(t4)

        curve_rows.append({
            "episode": ep_idx,
            "mean_loss": float(np.mean(losses)),
            "mean_term1_member_tx": float(np.mean(t1s)),
            "mean_term2_ch_bs_tx": float(np.mean(t2s)),
            "mean_term3_balance": float(np.mean(t3s)),
            "mean_term4_energy_pref": float(np.mean(t4s)),
        })
        print(f"episode {ep_idx:2d} (run_index={run_index}): mean_loss={np.mean(losses):.6f}")

    np.savez(_WEIGHTS_PATH, **params)
    print(f"\nSaved frozen weights to {_WEIGHTS_PATH}")

    with open(_CURVE_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "episode", "mean_loss", "mean_term1_member_tx", "mean_term2_ch_bs_tx",
            "mean_term3_balance", "mean_term4_energy_pref",
        ])
        writer.writeheader()
        for row in curve_rows:
            writer.writerow(row)
    print(f"Wrote learning curve to {_CURVE_PATH}")


if __name__ == "__main__":
    train()
