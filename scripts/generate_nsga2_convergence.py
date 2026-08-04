"""Regenerate results/validation/nsga2_convergence.csv at production scale
(default SimConfig: n_nodes=100, lossy channel) on run_index 0.

Runs the real engine round loop (same `_run_round` the benchmark uses) but
stops as soon as NSGA2Protocol has logged its convergence CSV -- no need to
simulate the network all the way to LND just to produce this one artifact.
See wsn_sim/protocols/nsga2.py ("GA convergence logging" in the class
docstring) for exactly when that fires: the first reclustering round at or
after round 800 where the alive population's residual energy has genuinely
diverged (std > 1e-3 J). Safety cap at round 3000 in case divergence is
somehow slower than expected on this particular topology.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from wsn_sim.config import SimConfig
from wsn_sim.engine import _derive_seed, _run_round
from wsn_sim.network import Network
from wsn_sim.protocols.nsga2 import NSGA2Protocol

SAFETY_CAP = 3000


def main():
    cfg = SimConfig()  # production defaults: n_nodes=100, lossy channel, p_ch=0.05
    run_index = 0
    net = Network(cfg, run_index)
    protocol = NSGA2Protocol()  # default window: round [800, 1200], std threshold 1e-3

    proto_rng = np.random.default_rng(_derive_seed(run_index, protocol.name))
    channel_rng = np.random.default_rng(_derive_seed(run_index, protocol.name, "channel"))
    all_latencies = []

    for round_idx in range(SAFETY_CAP):
        if not net.alive.any():
            print(f"WARNING: network died at round {round_idx} before convergence logged")
            break
        _run_round(net, protocol, cfg, round_idx, proto_rng, channel_rng, all_latencies)
        if protocol._convergence_logged:
            alive_energy = net.energy[net.alive]
            print(f"Convergence logged at round {round_idx}")
            print(f"  alive_nodes = {int(net.alive.sum())}")
            print(f"  residual energy: min={alive_energy.min():.6f} max={alive_energy.max():.6f} "
                  f"std={alive_energy.std():.6f} J")
            break
    else:
        print(f"WARNING: convergence never logged within {SAFETY_CAP} rounds")
        return

    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "results", "validation", "nsga2_convergence.csv")
    print(f"Wrote {path}")

    log = protocol.convergence_log
    knee_f1_0, knee_f1_n = log[0]["knee_f1"], log[-1]["knee_f1"]
    best_f1_0, best_f1_n = log[0]["best_f1"], log[-1]["best_f1"]
    knee_f2_0, knee_f2_n = log[0]["knee_f2"], log[-1]["knee_f2"]
    best_f2_0, best_f2_n = log[0]["best_f2"], log[-1]["best_f2"]
    print(f"  knee_f1: {knee_f1_0:.6f} -> {knee_f1_n:.6f} "
          f"({(knee_f1_0 - knee_f1_n) / knee_f1_0 * 100:.2f}% improvement)")
    print(f"  best_f1: {best_f1_0:.6f} -> {best_f1_n:.6f} "
          f"({(best_f1_0 - best_f1_n) / best_f1_0 * 100:.2f}% improvement)")
    print(f"  knee_f2: {knee_f2_0:.6f} -> {knee_f2_n:.6f}")
    print(f"  best_f2: {best_f2_0:.6f} -> {best_f2_n:.6f}")


if __name__ == "__main__":
    main()
