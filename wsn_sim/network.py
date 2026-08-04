"""Node population, topology, sensed-data process, and energy accounting.

Everything in this module that a protocol touches (`x`, `y`, `dist`,
`dist_bs`, `shadow`, `shadow_bs`, `sensed`, `alive`, `energy`, `per_data`,
`per_ctrl`, `per_data_bs`, `per_ctrl_bs`) is READ-ONLY from a protocol's
point of view. Protocols must never call `Network.spend` or mutate any
array on this object directly -- only `wsn_sim.engine` does that. This is
documented rather than enforced with a proxy/wrapper class, per the "no
speculative abstraction" constraint on this build.

`per_data[i, j]` / `per_ctrl[i, j]` / `per_data_bs[i]` / `per_ctrl_bs[i]` are
precomputed packet-error-rate lookup tables (see `Network.__init__`): PER is
static given (bits, distance, per-link shadowing), all fixed once the
topology is built, so the engine looks these up instead of recomputing
`radio.per()` per packet per attempt per round.

`e_tx_data[i, j]` / `e_tx_ctrl[i, j]` / `e_tx_data_bs[i]` / `e_tx_ctrl_bs[i]`
are precomputed transmit-energy lookup tables, mirroring the PER tables
exactly and for the same reason: `radio.e_tx(bits, d, cfg)` depends only on
(bits, distance), both fixed once the topology is built (bits is always one
of the two fixed `cfg` constants; distance is static since nodes are
static), so it is precomputed once here instead of being recomputed --
`np.asarray`/`np.where`-wrapped -- for every packet, every attempt, every
round. `e_rx_data` / `e_rx_ctrl` are the two possible receive-energy values,
cached as plain Python floats for the same reason. See docs/ASSUMPTIONS.md
for the exactness proof and before/after timing this replacement was held
to (mirroring the PER-table precomputation in item 18).
"""

import numpy as np

from .config import SimConfig
from .radio import e_rx, e_tx, per

# Sentinel destination index meaning "the base station". The BS is not a
# node and has no entry in any of the per-node arrays below.
BS = -1

# Energy-accounting categories tracked by Network.spend / Network.consumed.
CATEGORIES = ("data_tx", "data_rx", "ctrl_tx", "ctrl_rx", "agg", "retry")


class Network:
    """A single simulated topology + its shared random processes.

    Construction consumes ONE numpy Generator stream, seeded by the run
    index alone (`np.random.default_rng(run_index)`), in this fixed order:
        1. x positions, y positions
        2. initial energy (only consumes extra draws if het_enabled)
        3. shadowing matrix (node-node), then shadowing to BS
        4. sensed OU-process values for every round up front

    Because this order depends only on `run_index` -- never on which
    protocol is being benchmarked -- every protocol sees a byte-identical
    topology, shadowing, and sensed-data stream for a given run_index. This
    is the fairness backbone of the whole simulator: protocols cannot see a
    different world just by being a different protocol.
    """

    def __init__(self, cfg: SimConfig, run_index: int):
        self.cfg = cfg
        self.run_index = run_index
        rng = np.random.default_rng(run_index)
        n = cfg.n_nodes

        self.x = rng.uniform(0.0, cfg.field_w, size=n)
        self.y = rng.uniform(0.0, cfg.field_h, size=n)

        self.energy = self._init_energy(cfg, rng, n)
        self.initial_energy = self.energy.copy()

        self.alive = np.ones(n, dtype=bool)
        # Reserved for protocol bookkeeping conveniences; the engine derives
        # num_ch / membership purely from each round's ClusterAssignment, so
        # this array carries no required semantics in step 1.
        self.role = np.zeros(n, dtype=int)

        dx = self.x[:, None] - self.x[None, :]
        dy = self.y[:, None] - self.y[None, :]
        self.dist = np.sqrt(dx ** 2 + dy ** 2)
        self.dist_bs = np.sqrt((self.x - cfg.bs_x) ** 2 + (self.y - cfg.bs_y) ** 2)

        # Per-link shadowing: drawn ONCE here (static, since nodes are
        # static), symmetric, zero diagonal. Drawing the full n x n matrix
        # and folding the lower triangle onto the upper is simpler than
        # scattering n*(n-1)/2 draws into a triangular index and "wastes"
        # half the draws, which is an acceptable trade for a one-shot,
        # once-per-topology cost. See docs/ASSUMPTIONS.md.
        raw = rng.normal(0.0, cfg.shadow_sigma_db, size=(n, n))
        lower = np.tril(raw, -1)
        self.shadow = lower + lower.T
        self.shadow_bs = rng.normal(0.0, cfg.shadow_sigma_db, size=n)

        # PER is STATIC: it depends only on (bits, distance, per-link
        # shadowing), and all three are already fixed at this point (bits is
        # one of two fixed cfg constants; distance/shadowing are the arrays
        # just built above). Precomputing the full lookup tables ONCE here
        # -- rather than calling radio.per() again for every packet, every
        # attempt, every round in engine._run_round -- is a pure cache: same
        # numbers, just computed once instead of thousands of times. This
        # does NOT consume any rng draws, so it cannot perturb the fairness
        # backbone documented above (every protocol still sees the same
        # topology/shadowing/sensed streams for a given run_index). See
        # docs/ASSUMPTIONS.md for the before/after timing and the
        # bit-identical verification this replacement was held to.
        self.per_data = per(cfg.data_bits, self.dist, self.shadow, cfg)
        self.per_ctrl = per(cfg.ctrl_bits, self.dist, self.shadow, cfg)
        self.per_data_bs = per(cfg.data_bits, self.dist_bs, self.shadow_bs, cfg)
        self.per_ctrl_bs = per(cfg.ctrl_bits, self.dist_bs, self.shadow_bs, cfg)

        # e_tx is STATIC for exactly the same reason PER is static above:
        # `radio.e_tx(bits, d, cfg)` depends only on `bits` (one of two fixed
        # cfg constants) and `d` (the static distance arrays just built
        # above). Precomputing these four tables ONCE here -- rather than
        # calling `e_tx()` again for every packet, every attempt, every round
        # in engine._run_round, which was profiled at ~46% of remaining
        # per-round time (see docs/ASSUMPTIONS.md item 18's "remaining
        # hotspot" note) -- is a pure cache: same numbers, computed once
        # instead of thousands of times. Consumes no rng draws, so this
        # cannot perturb the fairness-critical seeding order documented
        # above. e_rx does not depend on distance at all, so it is cached as
        # two plain floats rather than a table.
        self.e_tx_data = e_tx(cfg.data_bits, self.dist, cfg)
        self.e_tx_ctrl = e_tx(cfg.ctrl_bits, self.dist, cfg)
        self.e_tx_data_bs = e_tx(cfg.data_bits, self.dist_bs, cfg)
        self.e_tx_ctrl_bs = e_tx(cfg.ctrl_bits, self.dist_bs, cfg)
        self.e_rx_data = float(e_rx(cfg.data_bits, cfg))
        self.e_rx_ctrl = float(e_rx(cfg.ctrl_bits, cfg))

        # The one remaining dynamic-but-degenerate e_tx case: a zero-member
        # CH's ADV broadcast, priced at electronics-only cost (d=0.0) because
        # there is no real farthest-member distance to charge against yet
        # (see engine._charge_control_traffic and docs/ASSUMPTIONS.md item
        # 6). Not indexable by node pair (there is no "other node" at d=0),
        # so it is cached as a single scalar constant rather than a table.
        self.e_tx_ctrl_zero = float(e_tx(cfg.ctrl_bits, 0.0, cfg))

        # Sensed Ornstein-Uhlenbeck process, precomputed for every round so
        # every protocol reads the exact same sensor stream. Shape
        # (max_rounds, n_nodes).
        self.sensed = np.empty((cfg.max_rounds, n), dtype=float)
        self.sensed[0] = rng.normal(cfg.sense_mu, cfg.sense_init_sd, size=n)
        for r in range(1, cfg.max_rounds):
            prev = self.sensed[r - 1]
            self.sensed[r] = (
                prev
                + cfg.sense_theta * (cfg.sense_mu - prev)
                + rng.normal(0.0, cfg.sense_sigma, size=n)
            )

        self.consumed = {k: 0.0 for k in CATEGORIES}

    @staticmethod
    def _init_energy(cfg: SimConfig, rng: np.random.Generator, n: int) -> np.ndarray:
        if not cfg.het_enabled:
            return np.full(n, cfg.e0, dtype=float)
        energy = np.full(n, cfg.e0, dtype=float)
        n_super = int(round(n * cfg.frac_super))
        n_adv = int(round(n * cfg.frac_adv))
        order = rng.permutation(n)
        super_idx = order[:n_super]
        adv_idx = order[n_super:n_super + n_adv]
        energy[adv_idx] = cfg.e0 * (1.0 + cfg.alpha)
        energy[super_idx] = cfg.e0 * (1.0 + cfg.beta)
        return energy

    def spend(self, node_idx: int, joules: float, category: str) -> bool:
        """The single choke point for ALL energy accounting.

        Partial-energy rule: if `joules` exceeds the node's residual energy,
        the node spends everything it has left, is marked dead, and this
        returns False (caller must treat the packet as lost). Otherwise the
        exact amount is subtracted and this returns True. Energy never goes
        negative, and this makes
            total_consumed_across_categories == total_initial_energy
        exactly at LND, so the conservation check in test_engine.py can
        assert with a tight tolerance.

        A dead node passed here (alive[node_idx] is already False) always
        returns False and spends/charges nothing further -- dead nodes must
        never transmit or receive, and must never be double-charged.
        """
        if not self.alive[node_idx]:
            return False
        residual = self.energy[node_idx]
        if joules > residual:
            self.consumed[category] += residual
            self.energy[node_idx] = 0.0
            self.alive[node_idx] = False
            return False
        self.energy[node_idx] = residual - joules
        self.consumed[category] += joules
        return True

    def total_consumed(self) -> float:
        return float(sum(self.consumed.values()))
