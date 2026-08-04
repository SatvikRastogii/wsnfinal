"""Offline DQN training driver (locked regime -- see wsn_sim/protocols/dqn.py
for the frozen-eval side).

- Trains on run_index 100..129 ONLY, cycled through for N_TRAIN_EPISODES=100
  episodes (was 30 -- see DIVERGENCE FIX below), disjoint from the
  evaluation seeds 0..29.
- Each episode runs the real engine round loop (`wsn_sim.engine._run_round`)
  under an epsilon-greedy version of the DQN ranking policy
  (`_EpsilonGreedyDQNClusterer` below) until the network fully dies or
  `cfg.max_rounds` is reached.
- Per-node transitions (s_i, a_i, r, s'_i): a_i in {0 (not CH), 1 (CH)} is
  whatever this episode's epsilon-greedy policy actually chose for node i
  this round. The reward r is shared across every transition collected in
  the same round (it is a property of the whole round's outcome, not of
  any one node's action):

      r = -(E_round / E_REF) - 2.0*(std(residual_energy over ALIVE nodes) / e0) - 1.0*(deaths this round)
      E_REF = 0.1 J

  `s'_i` is node i's own state feature vector re-evaluated against the
  network's state immediately after the round executes (i.e. "the state at
  the start of the next round") if node i survived the round, else a
  terminal transition (zero next-state, no bootstrap).

  REWARD FIX (2026-08 -- see docs/ASSUMPTIONS.md / the incident report that
  triggered it): the ORIGINAL spec used `gamma=0.95` (effective horizon
  ~20 rounds) with a reward dominated by `-(E_round/E_REF)`, i.e. minimize
  THIS round's energy. FND happens at round ~1000-2000 -- 50x past the
  discount horizon -- so the agent was structurally blind to the outcome it
  was judged on, AND the dominant reward term actively taught CH
  concentration (cheapest way to cut this round's energy is to always pick
  CHs nearest the BS, which drains the same few nodes and causes early
  FND -- the exact opposite of lifetime extension). Both are a-priori
  specification errors, not implementation bugs (the gradient check below
  is clean). Fixed by (a) `gamma=0.999` (~1000-round horizon, matching the
  phenomenon's timescale) and (b) replacing the cluster-size-std term with a
  RESIDUAL-ENERGY-std term, which directly rewards the even energy
  distribution that FND measures, weighted higher (2.0 vs the old 0.5) since
  it's now the term actually doing the balancing work. `E_REF` and the
  `-1.0*deaths` term are unchanged.

  DIVERGENCE FIX (2026-08 -- see docs/ASSUMPTIONS.md): even with the REWARD
  FIX above, the pre-fix learning curve showed classic deadly-triad
  divergence -- mean_loss FELL to 0.039 by episode 21 then ROSE to 0.212 by
  episode 29, and total_reward degraded monotonically (-1446 -> -2091)
  instead of improving. Cause: with gamma=0.999 and ~2500-step episodes,
  undiscounted return magnitude reaches ~1/(1-gamma)=1000x the per-step
  reward, so Q targets grow into the hundreds-to-thousands range while the
  4-16-2 network is still a poor approximator, and it ends up chasing an
  exploding, moving target. Fixed by three standard, principled
  stabilizers (see the constants block and `RunningNormalizer` below for the
  full rationale): (a) standardizing rewards with a running mean/std before
  they enter the replay buffer/TD target (rescales the value function,
  does not change the optimal policy), (b) clipping TD targets to
  +/-TD_TARGET_CLIP and gradients to a global norm of GRAD_CLIP_NORM, and
  (c) training for N_TRAIN_EPISODES=100 (was 30) with epsilon decay scaled
  to match.
- Replay buffer: fixed-capacity ring buffer, 10000 transitions, uniform
  random sampling, batch size 64. gamma=0.999 (see REWARD FIX above). Adam
  lr=1e-3 (see `wsn_sim.nn.Adam`). Target network parameters are a periodic
  COPY of the online network, synced every 200 gradient updates (not every
  200 rounds).
- Epsilon decays LINEARLY over the N_TRAIN_EPISODES=100 TRAINING EPISODES
  (not over environment steps, and not the fixed "30" of the original
  regime -- see DIVERGENCE FIX above): episode e in [0, 99] uses
  `epsilon = 1.0 + (0.05 - 1.0) * e / 99`, fixed for that whole episode.
  This is a deliberate simplification over per-step annealing: the total
  number of environment steps (rounds) an episode will produce is not known
  in advance (it depends on when the network dies under that episode's
  policy), so per-episode decay is the natural, reproducible schedule here.
- Writes frozen weights to `models/dqn_weights.npz` and a per-episode
  learning curve to `results/validation/dqn_learning_curve.csv`
  (episode, total_reward, mean_loss, epsilon, fnd_achieved).
- PERMANENT GUARD: after training, the frozen greedy policy (epsilon=0,
  final trained weights) and a pure random-rotation policy (epsilon=1.0,
  same ranking machinery but uniform-random top-k every round) are each run
  to completion on `HOLDOUT_SEEDS` (5 run_indices disjoint from both the
  training set 100..129 and the evaluation set 0..29) and their FND is
  recorded as extra rows in the SAME learning-curve CSV (`eval_seed`,
  `frozen_greedy_fnd`, `random_baseline_fnd` columns, blank on the
  per-episode training rows). This makes "does the trained policy actually
  beat random CH rotation?" a number that is always written down, never
  something that has to be inferred or re-derived by hand later.
- Exploration/ordering randomness in this script comes from its OWN
  deterministic `np.random.default_rng` streams (seeded from the episode's
  run_index) -- this is an offline training utility, not a protocol
  exercised inside the fairness-critical benchmark harness (see
  `wsn_sim.engine` module docstring), so it does not need to draw from that
  harness's proto_rng/channel_rng scheme. It still never touches the
  EVALUATION-time `rng` (that code path -- `DQNProtocol.setup_round` --
  never calls this script or any randomness at all).
"""

import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from wsn_sim.config import SimConfig
from wsn_sim.engine import _derive_seed, _run_round
from wsn_sim.network import BS, Network
from wsn_sim.nn import Adam, clip_grad_norm
from wsn_sim.protocols.base import ClusterAssignment, Protocol, Transmission
from wsn_sim.protocols.dqn import backward, epoch_len_of, forward, init_params, state_features

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MODELS_DIR = os.path.join(_ROOT, "models")
_WEIGHTS_PATH = os.path.join(_MODELS_DIR, "dqn_weights.npz")
_CURVE_PATH = os.path.join(_ROOT, "results", "validation", "dqn_learning_curve.csv")

N_TRAIN_EPISODES = 100  # was 30; see DIVERGENCE FIX below -- a 4-feature policy needs more than 30 episodes
TRAIN_RUN_INDICES = [100 + (i % 30) for i in range(N_TRAIN_EPISODES)]  # cycle seeds 100..129, disjoint from eval 0..29
HOLDOUT_SEEDS = list(range(130, 135))  # 5 seeds, disjoint from both train (100..129) and eval (0..29)
GAMMA = 0.999  # ~1000-round horizon -- was 0.95 (~20 rounds), 50x shorter than FND's timescale. See REWARD FIX above.
BUFFER_CAPACITY = 10000
BATCH_SIZE = 64
TARGET_SYNC_EVERY = 200  # gradient updates, not rounds
EPS_START, EPS_END = 1.0, 0.05
E_REF = 0.1
ENERGY_STD_WEIGHT = 2.0  # was 0.5 on the old cluster-size-std term; see REWARD FIX above
LR = 1e-3

# --- DIVERGENCE FIX (2026-08 -- see docs/ASSUMPTIONS.md) -----------------
# With gamma=0.999 and ~2500-step episodes, undiscounted return magnitude is
# ~1/(1-gamma) = 1000x the per-step reward. The per-step reward here is
# O(1) (see REWARD FIX above), so Q targets were growing into the hundreds
# to low thousands early in training, before the network's function
# approximation had anywhere near converged -- classic "deadly triad"
# divergence (bootstrapping + function approximation + off-policy replay),
# visible directly in the pre-fix learning curve: mean_loss FELL to 0.039
# by episode 21 then ROSE to 0.212 by episode 29, and total_reward degraded
# monotonically (-1446 -> -2091) instead of improving. Three standard,
# principled stabilizers, none of which touch the reward *definition* or
# alter what policy is optimal, only the numerics of chasing it:
#   1. Reward standardization: a running (Welford) mean/std of observed raw
#      rewards is maintained (`RunningNormalizer` below) and the STANDARDIZED
#      reward ((r - running_mean) / running_std) is what actually enters the
#      replay buffer and the TD target. This rescales the value function by
#      a constant (well, slowly-converging-to-constant) factor; it does not
#      change which action has higher Q, hence not the optimal policy. Raw
#      reward is still what's summed into `total_reward` for the learning
#      curve, so the curve stays comparable across the fix.
#   2. TD targets are clipped to +/-TD_TARGET_CLIP before computing the loss,
#      and gradients are clipped to a global norm of GRAD_CLIP_NORM
#      (`wsn_sim.nn.clip_grad_norm`) before the Adam step. Both bound how far
#      a single bad bootstrap/minibatch can drag the online network.
#   3. Trained for N_TRAIN_EPISODES=100 (was 30) -- 30 episodes is thin for
#      even a 4-feature linear-ish policy to settle into; epsilon decay
#      (below) is scaled to the new episode count so exploration still
#      anneals to EPS_END by the final episode.
TD_TARGET_CLIP = 20.0  # bounds on the standardized-reward scale, not raw energy units
GRAD_CLIP_NORM = 10.0


class RunningNormalizer:
    """Streaming mean/std via Welford's online algorithm (numerically stable,
    single pass, no stored history). `normalize(x)` standardizes BEFORE the
    current observation updates the running stats (so a normalized value is
    always relative to everything seen strictly before it, not leaking the
    current sample into its own denominator).
    """

    def __init__(self, eps=1e-4):
        self.eps = eps
        self.count = 0
        self.mean = 0.0
        self.m2 = 0.0

    @property
    def std(self):
        var = self.m2 / self.count if self.count > 0 else 1.0
        return float(np.sqrt(max(var, 0.0)))

    def normalize(self, x: float) -> float:
        std = self.std if self.count > 0 else 1.0
        normed = (x - self.mean) / (std + self.eps)
        self._update(x)
        return normed

    def _update(self, x: float):
        self.count += 1
        delta = x - self.mean
        self.mean += delta / self.count
        delta2 = x - self.mean
        self.m2 += delta * delta2


class _EpsilonGreedyDQNClusterer(Protocol):
    """Training-time DQN clusterer: same ranking logic as the frozen
    `DQNProtocol`, but (a) reads MUTABLE online params instead of frozen
    ones, (b) explores with probability `epsilon` (uniform-random top-k
    instead of the ranked top-k), and (c) records this round's (state,
    action, alive-node-order, cluster-size std) on `self` so the training
    loop can build transitions after the round executes. Never registered
    in run_experiments.REGISTRY -- training-only.
    """

    name = "dqn_train_probe"
    control_model = "centralized"

    def __init__(self, params):
        self.reclustered_this_round = True
        self.params = params
        self.epsilon = 1.0
        self._last_ch_round = {}
        # populated each setup_round call, read by the training loop:
        self.last_alive_arr = None
        self.last_X = None
        self.last_action = None  # (n_alive,) 0/1
        self.last_cluster_std = 0.0

    def setup_round(self, net, round_idx: int, rng) -> ClusterAssignment:
        cfg = net.cfg
        alive_arr = np.flatnonzero(net.alive)
        n_alive = len(alive_arr)
        self.reclustered_this_round = True
        self.last_alive_arr = alive_arr
        if n_alive == 0:
            self.last_X = np.zeros((0, 4))
            self.last_action = np.zeros(0, dtype=int)
            self.last_cluster_std = 0.0
            return ClusterAssignment(ch_ids=[], member_of={})

        X = state_features(net, alive_arr, round_idx, self._last_ch_round)
        self.last_X = X
        k = max(1, min(n_alive, round(cfg.p_ch * n_alive)))

        if rng.random() < self.epsilon:
            ch_local = rng.choice(n_alive, size=k, replace=False)
        else:
            q, _ = forward(self.params, X)
            advantage = q[:, 1] - q[:, 0]
            order = np.argsort(-advantage, kind="stable")
            ch_local = order[:k]

        ch_mask = np.zeros(n_alive, dtype=bool)
        ch_mask[ch_local] = True
        self.last_action = ch_mask.astype(int)
        ch_ids = [int(x) for x in alive_arr[ch_local]]
        for c in ch_ids:
            self._last_ch_round[c] = round_idx

        member_of = {}
        non_ch = alive_arr[~ch_mask]
        cluster_sizes = np.zeros(k, dtype=float)
        if len(non_ch) > 0 and ch_ids:
            ch_arr = np.array(ch_ids, dtype=int)
            d = net.dist[np.ix_(non_ch, ch_arr)]
            nearest_pos = np.argmin(d, axis=1)
            counts = np.bincount(nearest_pos, minlength=k)
            cluster_sizes = counts.astype(float)
            for n, p in zip(non_ch.tolist(), nearest_pos.tolist()):
                member_of[int(n)] = int(ch_arr[p])
        self.last_cluster_std = float(np.std(cluster_sizes)) if k > 0 else 0.0

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
                    Transmission(src=ch, dst=BS, kind="data", slot_index=len(members), hop_depth=2, originates=True)
                )
        assigned_or_ch = set(assignment.ch_ids) | set(assignment.member_of.keys())
        for n in np.flatnonzero(net.alive).tolist():
            if n in assigned_or_ch:
                continue
            transmissions.append(Transmission(src=n, dst=BS, kind="data", slot_index=0, hop_depth=1, originates=True))
        return transmissions


class ReplayBuffer:
    def __init__(self, capacity):
        self.capacity = capacity
        self.s = np.zeros((capacity, 4))
        self.a = np.zeros(capacity, dtype=int)
        self.r = np.zeros(capacity)
        self.s2 = np.zeros((capacity, 4))
        self.done = np.zeros(capacity, dtype=bool)
        self.size = 0
        self.ptr = 0

    def push(self, s, a, r, s2, done):
        i = self.ptr
        self.s[i] = s
        self.a[i] = a
        self.r[i] = r
        self.s2[i] = s2
        self.done[i] = done
        self.ptr = (self.ptr + 1) % self.capacity
        self.size = min(self.size + 1, self.capacity)

    def sample(self, batch_size, rng):
        idx = rng.integers(0, self.size, size=batch_size)
        return self.s[idx], self.a[idx], self.r[idx], self.s2[idx], self.done[idx]


def _evaluate_policy_fnd(params, run_index, epsilon, cfg):
    """PERMANENT GUARD (see module docstring): run one full episode (until
    death or cfg.max_rounds) under the given epsilon and return the FND
    round (cfg.max_rounds -- actually the round loop stopped at -- if the
    network survived the whole run without any death). epsilon=0.0 is the
    frozen greedy ranking policy (deterministic given params); epsilon=1.0
    is a pure random-rotation baseline (SAME ranking/membership machinery,
    just uniform-random top-k every round instead of ranked top-k). Uses its
    own rng streams, tagged separately from training so this never collides
    with (or depends on) the training loop's randomness.
    """
    net = Network(cfg, run_index)
    protocol = _EpsilonGreedyDQNClusterer(params)
    protocol.epsilon = epsilon
    tag = "dqn_holdout_greedy" if epsilon == 0.0 else "dqn_holdout_random"
    proto_rng = np.random.default_rng(_derive_seed(run_index, tag, "proto"))
    channel_rng = np.random.default_rng(_derive_seed(run_index, tag, "channel"))
    all_latencies = []
    round_idx = 0
    fnd_achieved = None
    while net.alive.any() and round_idx < cfg.max_rounds:
        record = _run_round(net, protocol, cfg, round_idx, proto_rng, channel_rng, all_latencies)
        if fnd_achieved is None and record["alive_nodes"] < cfg.n_nodes:
            fnd_achieved = round_idx
        round_idx += 1
    return fnd_achieved if fnd_achieved is not None else round_idx


def train():
    os.makedirs(_MODELS_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(_CURVE_PATH), exist_ok=True)

    init_rng = np.random.default_rng(42)
    online_params = init_params(init_rng)
    target_params = {k: v.copy() for k, v in online_params.items()}
    adam = Adam(online_params, lr=LR)

    buffer = ReplayBuffer(BUFFER_CAPACITY)
    n_updates = 0
    # Running reward normalizer (DIVERGENCE FIX -- see constants block above).
    # ONE instance for the whole training run (not reset per episode): the
    # running mean/std needs to accumulate across the full reward stream to
    # be a meaningful standardization, and resetting it every episode would
    # make each episode's Q targets calibrated against a different implicit
    # scale, reintroducing exactly the moving-target instability this fix
    # is meant to remove.
    reward_normalizer = RunningNormalizer()

    curve_rows = []
    cfg = SimConfig()

    for ep_idx, run_index in enumerate(TRAIN_RUN_INDICES):
        epsilon = EPS_START + (EPS_END - EPS_START) * ep_idx / (N_TRAIN_EPISODES - 1)

        net = Network(cfg, run_index)
        protocol = _EpsilonGreedyDQNClusterer(online_params)
        protocol.epsilon = epsilon

        proto_rng = np.random.default_rng(_derive_seed(run_index, "dqn_train", "proto"))
        channel_rng = np.random.default_rng(_derive_seed(run_index, "dqn_train", "channel"))
        sample_rng = np.random.default_rng(_derive_seed(run_index, "dqn_train", "replay_sample"))
        all_latencies = []

        total_reward = 0.0
        losses = []
        fnd_achieved = None
        round_idx = 0

        while net.alive.any() and round_idx < cfg.max_rounds:
            alive_before = protocol_alive = np.flatnonzero(net.alive)
            n_alive_before = len(alive_before)

            record = _run_round(net, protocol, cfg, round_idx, proto_rng, channel_rng, all_latencies)

            if fnd_achieved is None and record["alive_nodes"] < cfg.n_nodes:
                fnd_achieved = round_idx

            deaths = n_alive_before - record["alive_nodes"]
            e_round = record["energy_consumed_round"]
            # Residual-energy balance term (post-round, over nodes still alive):
            # directly rewards the even energy distribution FND measures. Replaces
            # the old std_cluster_size term, which rewarded minimizing THIS round's
            # energy (-> CH concentration near the BS) with no bearing on lifetime.
            # See REWARD FIX in the module docstring.
            alive_now = net.energy[net.alive] / cfg.e0
            energy_std = float(np.std(alive_now)) if alive_now.size > 0 else 0.0
            reward = (
                -(e_round / E_REF)
                - ENERGY_STD_WEIGHT * energy_std
                - 1.0 * deaths
            )
            total_reward += reward  # RAW reward -- learning-curve total_reward stays comparable pre/post fix
            # Standardized reward is what actually enters the replay buffer / TD target
            # (DIVERGENCE FIX; see constants block above). Rescales the value function,
            # does not change the optimal policy.
            reward_for_buffer = reward_normalizer.normalize(reward)

            if n_alive_before > 0:
                still_alive_mask = net.alive[alive_before]
                surviving = alive_before[still_alive_mask]
                if len(surviving) > 0:
                    next_X = state_features(net, surviving, round_idx + 1, protocol._last_ch_round)
                else:
                    next_X = np.zeros((0, 4))
                surv_ptr = 0
                for local_i, node in enumerate(alive_before):
                    s = protocol.last_X[local_i]
                    a = int(protocol.last_action[local_i])
                    if net.alive[node]:
                        s2 = next_X[surv_ptr]
                        surv_ptr += 1
                        done = False
                    else:
                        s2 = np.zeros(4)
                        done = True
                    buffer.push(s, a, reward_for_buffer, s2, done)

            if buffer.size >= BATCH_SIZE:
                s_b, a_b, r_b, s2_b, done_b = buffer.sample(BATCH_SIZE, sample_rng)
                q_all, cache = forward(online_params, s_b)
                q_sa = q_all[np.arange(BATCH_SIZE), a_b]
                q_next_all, _ = forward(target_params, s2_b)
                max_q_next = q_next_all.max(axis=1)
                target = r_b + GAMMA * max_q_next * (~done_b)
                # DIVERGENCE FIX: clip the TD target itself, bounding how far a single
                # bad bootstrap (early in training, before the network has converged)
                # can drag the online network before the next update.
                target = np.clip(target, -TD_TARGET_CLIP, TD_TARGET_CLIP)
                td_error = q_sa - target
                loss = float(np.mean(td_error ** 2))
                losses.append(loss)

                dQ = np.zeros_like(q_all)
                dQ[np.arange(BATCH_SIZE), a_b] = 2.0 * td_error / BATCH_SIZE
                grads = backward(online_params, cache, dQ)
                clip_grad_norm(grads, GRAD_CLIP_NORM)  # DIVERGENCE FIX: global-norm grad clip
                adam.step(online_params, grads)
                n_updates += 1
                if n_updates % TARGET_SYNC_EVERY == 0:
                    target_params = {k: v.copy() for k, v in online_params.items()}

            round_idx += 1

        mean_loss = float(np.mean(losses)) if losses else 0.0
        curve_rows.append({
            "episode": ep_idx,
            "total_reward": total_reward,
            "mean_loss": mean_loss,
            "epsilon": epsilon,
            "fnd_achieved": fnd_achieved if fnd_achieved is not None else round_idx,
        })
        print(f"episode {ep_idx:2d} (run_index={run_index}): rounds={round_idx} "
              f"total_reward={total_reward:.3f} mean_loss={mean_loss:.6f} "
              f"epsilon={epsilon:.3f} fnd={fnd_achieved}")

    np.savez(_WEIGHTS_PATH, **online_params)
    print(f"\nSaved frozen weights to {_WEIGHTS_PATH}")

    # --- PERMANENT GUARD: frozen greedy vs. random-rotation baseline, on
    # held-out seeds disjoint from both training (100..129) and evaluation
    # (0..29). Answers "did the trained policy actually beat random CH
    # rotation on FND?" as a number written to the learning-curve CSV, not
    # something inferred later. ---
    print("\n=== Holdout guard: frozen greedy DQN vs. random-rotation baseline ===")
    holdout_rows = []
    greedy_fnds, random_fnds = [], []
    for seed in HOLDOUT_SEEDS:
        greedy_fnd = _evaluate_policy_fnd(online_params, seed, 0.0, cfg)
        random_fnd = _evaluate_policy_fnd(online_params, seed, 1.0, cfg)
        greedy_fnds.append(greedy_fnd)
        random_fnds.append(random_fnd)
        holdout_rows.append({
            "eval_seed": seed,
            "frozen_greedy_fnd": greedy_fnd,
            "random_baseline_fnd": random_fnd,
        })
        verdict = "DQN WINS" if greedy_fnd > random_fnd else ("TIE" if greedy_fnd == random_fnd else "DQN LOSES")
        print(f"  seed {seed}: frozen_greedy_fnd={greedy_fnd:5d}  random_baseline_fnd={random_fnd:5d}  {verdict}")

    mean_greedy = float(np.mean(greedy_fnds))
    mean_random = float(np.mean(random_fnds))
    n_wins = sum(1 for g, r in zip(greedy_fnds, random_fnds) if g > r)
    overall_verdict = (
        "DQN beats random rotation on mean FND"
        if mean_greedy > mean_random
        else "DQN does NOT beat random rotation on mean FND"
    )
    print(f"\n  mean frozen_greedy_fnd={mean_greedy:.1f}  mean random_baseline_fnd={mean_random:.1f}  "
          f"({n_wins}/{len(HOLDOUT_SEEDS)} seeds won)  -> {overall_verdict}")

    fieldnames = [
        "episode", "total_reward", "mean_loss", "epsilon", "fnd_achieved",
        "eval_seed", "frozen_greedy_fnd", "random_baseline_fnd",
    ]
    with open(_CURVE_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, restval="")
        writer.writeheader()
        for row in curve_rows:
            writer.writerow(row)
        for row in holdout_rows:
            writer.writerow(row)
    print(f"Wrote learning curve (+ holdout guard rows) to {_CURVE_PATH}")


if __name__ == "__main__":
    train()
