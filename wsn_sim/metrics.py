"""Metric definitions and CSV writing.

This module is pure with respect to the simulation: it derives every
summary statistic from the per-round records (plus the raw per-packet
latency list and final Network state) that engine.py already produced. It
never spends energy or runs a round itself.
"""

import math

import numpy as np
import pandas as pd

PER_ROUND_COLUMNS = [
    "round",
    "alive_nodes",
    "num_ch",
    "total_residual_energy",
    "mean_residual_energy_all",
    "mean_residual_energy_alive",
    "packets_sent",
    "packets_received_bs",
    "readings_attempted",
    "readings_delivered",
    "control_packets",
    "energy_consumed_round",
    "mean_latency_ms",
    "setup_time_ms",
    "ops_count",
]

SUMMARY_COLUMNS = [
    "run_id",
    "seed",
    "protocol",
    "fnd",
    "hnd",
    "lnd",
    "lnd_censored",
    "throughput_total",
    "readings_attempted_total",
    "readings_delivered_total",
    "pdr_percent",
    "reporting_rate",
    "data_yield",
    "mean_residual_energy_final",
    "mean_latency_ms",
    "p95_latency_ms",
    "alive_node_auc",
    "total_control_packets",
    "mean_setup_ms",
    "total_runtime_s",
    "peak_memory_kb",
    "ops_per_round",
]


def compute_fnd_hnd_lnd(per_round_records: list, n_nodes: int):
    """FND/HND/LND at the per-round `alive_nodes` granularity.

    FND: first recorded round whose alive_nodes < n_nodes (a death has
         occurred by the end of that round -- we cannot see sub-round death
         instants, only end-of-round alive counts).
    HND: first recorded round where cumulative deaths >= ceil(n_nodes/2).
    LND: first recorded round where alive_nodes == 0. If the run never
         reaches that (round cap hit first), LND is reported as the last
         executed round index and lnd_censored=True.
    FND/HND are None if that event never occurs within the recorded rounds
    (e.g. a short smoke run that ends before half the nodes die).
    """
    half = math.ceil(n_nodes / 2)
    fnd = None
    hnd = None
    lnd = None
    lnd_censored = True
    for rec in per_round_records:
        if fnd is None and rec["alive_nodes"] < n_nodes:
            fnd = rec["round"]
        if hnd is None and (n_nodes - rec["alive_nodes"]) >= half:
            hnd = rec["round"]
        if rec["alive_nodes"] == 0:
            lnd = rec["round"]
            lnd_censored = False
            break
    if lnd is None:
        lnd = per_round_records[-1]["round"] if per_round_records else 0
        lnd_censored = True
    return fnd, hnd, lnd, lnd_censored


def build_summary(
    per_round_records: list,
    all_latencies: list,
    net,
    cfg,
    run_index: int,
    protocol_name: str,
    total_runtime_s: float,
    peak_memory_bytes: int,
) -> dict:
    n_nodes = cfg.n_nodes
    fnd, hnd, lnd, lnd_censored = compute_fnd_hnd_lnd(per_round_records, n_nodes)

    packets_sent_total = sum(r["packets_sent"] for r in per_round_records)
    packets_received_bs_total = sum(r["packets_received_bs"] for r in per_round_records)
    readings_attempted_total = sum(r["readings_attempted"] for r in per_round_records)
    readings_delivered_total = sum(r["readings_delivered"] for r in per_round_records)
    total_control_packets = sum(r["control_packets"] for r in per_round_records)
    alive_node_auc = sum(r["alive_nodes"] for r in per_round_records)
    n_rounds_executed = len(per_round_records)

    # pdr_percent: READING-based, not packet-based (see docs/ASSUMPTIONS.md).
    # A packet-based ratio (packets_received_bs_total / packets_sent_total)
    # measures aggregation depth, not delivery: once a CH folds N source
    # readings into 1 BS packet, that ratio collapses toward 1/N regardless
    # of whether every single reading actually arrived. The reading-based
    # ratio below is comparable across protocols with wildly different
    # aggregation depth (LEACH vs. PEGASIS vs. no-clustering), because both
    # numerator and denominator are counted in the same units (readings),
    # not packets. Suppression (TEEN/APTEEN below-threshold) is NOT loss --
    # a suppressed reading was never injected, so it never enters
    # readings_attempted either; see readings_attempted's definition in
    # engine.py (`_run_round`).
    pdr_percent = (
        readings_delivered_total / readings_attempted_total * 100.0
        if readings_attempted_total > 0
        else 0.0
    )

    # reporting_rate: how often sources actually attempted a send, per
    # alive-node-round (alive_node_auc = sum of alive_nodes across rounds).
    reporting_rate = packets_sent_total / alive_node_auc if alive_node_auc > 0 else 0.0

    # data_yield: readings delivered at BS vs. total readings TAKEN. One
    # sensor reading is taken by every alive node every round regardless of
    # whether it is transmitted or suppressed, so "total readings taken" ==
    # alive_node_auc (see docs/ASSUMPTIONS.md).
    data_yield = readings_delivered_total / alive_node_auc if alive_node_auc > 0 else 0.0

    mean_residual_energy_final = (
        per_round_records[-1]["mean_residual_energy_all"] if per_round_records else 0.0
    )

    mean_latency_ms = float(np.mean(all_latencies)) if all_latencies else 0.0
    p95_latency_ms = float(np.percentile(all_latencies, 95)) if all_latencies else 0.0

    mean_setup_ms = (
        float(np.mean([r["setup_time_ms"] for r in per_round_records])) if per_round_records else 0.0
    )

    # ops_per_round: mean COUNTED algorithmic workload (distance
    # computations, fitness/objective evaluations, neural forward passes --
    # see Protocol.ops_this_round in protocols/base.py) per executed round.
    # This replaces an earlier, incorrect definition based on packets_sent
    # (traffic volume, not computational cost) -- see docs/ASSUMPTIONS.md.
    ops_per_round = (
        float(np.mean([r["ops_count"] for r in per_round_records])) if n_rounds_executed > 0 else 0.0
    )

    return {
        "run_id": run_index,
        "seed": run_index,
        "protocol": protocol_name,
        "fnd": fnd,
        "hnd": hnd,
        "lnd": lnd,
        "lnd_censored": lnd_censored,
        "throughput_total": packets_received_bs_total,
        "readings_attempted_total": readings_attempted_total,
        "readings_delivered_total": readings_delivered_total,
        "pdr_percent": pdr_percent,
        "reporting_rate": reporting_rate,
        "data_yield": data_yield,
        "mean_residual_energy_final": mean_residual_energy_final,
        "mean_latency_ms": mean_latency_ms,
        "p95_latency_ms": p95_latency_ms,
        "alive_node_auc": alive_node_auc,
        "total_control_packets": total_control_packets,
        "mean_setup_ms": mean_setup_ms,
        "total_runtime_s": total_runtime_s,
        "peak_memory_kb": peak_memory_bytes / 1024.0,
        "ops_per_round": ops_per_round,
    }


def write_per_round_csv(per_round_records: list, path: str) -> None:
    df = pd.DataFrame(per_round_records, columns=PER_ROUND_COLUMNS)
    df.to_csv(path, index=False)


def write_summary_csv(summary_records: list, path: str) -> None:
    df = pd.DataFrame(summary_records, columns=SUMMARY_COLUMNS)
    df.to_csv(path, index=False)
