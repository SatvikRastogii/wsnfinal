"""Simulation configuration.

A single frozen dataclass holds every tunable constant used anywhere in the
engine. Nothing outside this file defines a physical/energy/timing constant.
"""

from dataclasses import dataclass
from functools import cached_property
import math


@dataclass(frozen=True)
class SimConfig:
    # topology / population
    n_nodes: int = 100
    field_w: float = 100.0
    field_h: float = 100.0
    bs_x: float = 50.0
    bs_y: float = 150.0
    e0: float = 1.0

    # packet sizing
    data_bits: int = 4000
    ctrl_bits: int = 200

    # first-order radio energy model
    e_elec: float = 50e-9
    eps_fs: float = 10e-12
    eps_mp: float = 0.0013e-12
    e_da: float = 5e-9

    # protocol-agnostic knobs
    p_ch: float = 0.05
    max_rounds: int = 7000
    n_runs: int = 30

    # heterogeneity — present but disabled by default (do not hard-code homogeneity)
    het_enabled: bool = False
    frac_adv: float = 0.0
    frac_super: float = 0.0
    alpha: float = 1.0
    beta: float = 2.0

    # channel (lossy by default)
    per_enabled: bool = True
    pt_dbm: float = 12.0
    pl_1m_db: float = 40.0
    path_loss_n: float = 3.0
    shadow_sigma_db: float = 4.0
    noise_floor_dbm: float = -105.0
    max_retx: int = 2

    # sensed data (Ornstein-Uhlenbeck)
    sense_mu: float = 50.0
    sense_theta: float = 0.05
    sense_sigma: float = 2.0
    sense_init_sd: float = 10.0

    # TEEN/APTEEN thresholds
    ht: float = 55.0
    st: float = 1.0
    tc: int = 50

    # centralized-protocol knobs (NSGA-II, Fuzzy-T2)
    pop_size: int = 40
    generations: int = 30
    ga_interval: int = 5
    density_radius: float = 25.0

    # latency
    bitrate_bps: float = 250000.0
    guard_ms: float = 4.0
    proc_ms: float = 1.0

    # d0/tx_time_ms/slot_ms are pure functions of other (frozen, immutable)
    # fields, so each is computed at most ONCE per SimConfig instance and
    # cached in __dict__ by functools.cached_property -- rather than
    # recomputed on every access, which showed up as a real (if minor) line
    # item when profiling the round loop: these get read tens of thousands
    # of times per run (once per delivered packet for slot_ms/tx_time_ms,
    # and inside radio.e_tx for d0), and a plain @property recomputes the
    # sqrt/division/property-chain from scratch every single time.
    # cached_property stores the value directly in instance.__dict__ on
    # first access, which bypasses the frozen dataclass's __setattr__
    # override (it never calls setattr), so this is safe on a frozen
    # dataclass. See docs/ASSUMPTIONS.md item 18 (Defect 4) for the profile
    # that first flagged this as a hotspot.
    @cached_property
    def d0(self) -> float:
        """Crossover distance between the free-space and multipath radio models."""
        return math.sqrt(self.eps_fs / self.eps_mp)

    @cached_property
    def tx_time_ms(self) -> float:
        """Time to transmit one data packet, in milliseconds."""
        return self.data_bits / self.bitrate_bps * 1000.0

    @cached_property
    def slot_ms(self) -> float:
        """TDMA slot length: transmit time plus a fixed guard interval."""
        return self.tx_time_ms + self.guard_ms


def smoke_config() -> SimConfig:
    """A small, fast configuration for smoke-testing the engine."""
    return SimConfig(n_nodes=20, max_rounds=200, n_runs=2)
