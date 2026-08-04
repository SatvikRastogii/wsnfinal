# Results layout and column reference

```
results/
  raw/<protocol>/run_<NN>.csv    per-round time series, one file per (protocol, run)
  summary/<protocol>_summary.csv one row per run, scalar metrics
  aggregate.csv                  one row per protocol, mean and std of every scalar
  validation/                    calibration and convergence artifacts
  analysis/                      paper-ready tables, stats and figures (analyze.py)
```

`analysis/` is produced by `python analyze.py` after the sweep:

| File | Contents |
|---|---|
| `REPORT.md` | Headline tables, the paired-test table, the aggregate verification result and the channel-robustness summary, in one readable document. |
| `headline_<channel>.csv` | Mean, sample std, min and max of every headline metric per protocol, with `class` (distributed / chain / centralized / baseline) and `n_censored`. |
| `paired_tests_<channel>.csv` | Every protocol against the baseline on 8 metrics: mean difference, 95% paired-bootstrap CI, raw p and Holm-corrected p. |
| `channel_robustness.csv` | Each protocol's rank on a metric under lossy vs ideal, and the shift between them. |
| `figures_<channel>/fig1..7` | Survival curves, the three lifetime points, energy depletion, lifetime-vs-delivery, control traffic, compute cost, PDR-vs-survival. |
| `fig8_channel_sensitivity.png` | FND and delivery side by side across both channels. |

**Why paired statistics rather than mean ± std.** Run index `i` fixes the topology, the
per-link shadowing and the sensed-value stream for *every* protocol, so protocol A and
protocol B at run `i` faced the identical world and their difference is a paired
observation. The test is a two-sided sign-flip permutation test on the mean paired
difference (20 000 resamples, fixed seed) with a paired-bootstrap 95% CI, Holm-corrected
across each table's family of comparisons. No scipy dependency, no normality assumption,
and validated against exact enumeration of all 2^10 sign assignments on a synthetic case.

A censored `lnd` breaks both the test and the CI, so lifetime comparisons for TEEN and
APTEEN should use `alive_node_auc`, which censoring does not affect.

When both channel configurations are run (`--channel both`), the tree is duplicated under
`results/lossy/` and `results/ideal/`. The lossy run is the headline; the ideal run is the
sensitivity check. See `docs/METRICS.md` for why both exist.

All files are CSV. Column names are lowercase snake_case. No pickles.

## `raw/<protocol>/run_<NN>.csv` — per-round time series

| Column | Unit | Meaning |
|---|---|---|
| `round` | index | 0-based round number. |
| `alive_nodes` | count | Nodes with energy remaining at end of round. Monotonically non-increasing. |
| `num_ch` | count | Cluster heads elected this round. 0 is legal (all nodes self-head). N/A for chain protocols. |
| `total_residual_energy` | J | Sum of residual energy across all nodes. |
| `mean_residual_energy_all` | J | Mean over all `N` nodes, dead nodes counted as zero. |
| `mean_residual_energy_alive` | J | Mean over living nodes only. Can rise as depleted nodes die. |
| `packets_sent` | count | Data transmissions attempted by living nodes (a retried packet counts once). |
| `packets_received_bs` | count | Data packets that reached the base station. |
| `readings_attempted` | count | Original sensor readings injected into the network. Excludes readings a protocol deliberately suppressed. |
| `readings_delivered` | count | Original readings represented in packets that reached the base station. |
| `control_packets` | count | Control messages sent this round (ADV, JOIN, SCHEDULE, chain token, BS broadcast). |
| `energy_consumed_round` | J | Total energy spent this round across every category. |
| `mean_latency_ms` | ms | Mean end-to-end latency of packets delivered to the BS this round. |
| `setup_time_ms` | ms | Wall-clock time inside `setup_round` only. Not reproducible across runs. |
| `ops_count` | count | Protocol-counted algorithmic operations this round (distance computations, fitness evaluations, neural forward passes). |

## `summary/<protocol>_summary.csv` — one row per run

| Column | Unit | Meaning |
|---|---|---|
| `run_id`, `seed` | index | Run index. The seed equals the run index and drives topology, shadowing and sensed values. |
| `protocol` | name | Protocol identifier. |
| `fnd`, `hnd`, `lnd` | round | First, half and last node death. Empty if never reached within the cap. |
| `lnd_censored` | bool | True when the round cap was hit before all nodes died. **`lnd` is then a lower bound, not a measurement.** |
| `throughput_total` | packets | Cumulative data packets received at the BS. Aggregation-sensitive — see below. |
| `readings_delivered_total` | readings | Cumulative original readings delivered. **The cross-protocol-comparable throughput measure.** |
| `readings_attempted_total` | readings | Cumulative readings injected into the network. |
| `pdr_percent` | % | `readings_delivered / readings_attempted × 100`. Suppression is not counted as loss. |
| `reporting_rate` | ratio | Data packets sent by sources ÷ alive-node-rounds. How chatty the protocol is. |
| `data_yield` | ratio | Readings delivered ÷ all readings taken. Suppression **is** counted against this. |
| `mean_residual_energy_final` | J | Mean residual energy over all `N` nodes at the final round. |
| `mean_latency_ms`, `p95_latency_ms` | ms | Per-packet latency over the whole run. |
| `alive_node_auc` | node·rounds | Area under the alive-node curve. Robust single lifetime summary, unaffected by censoring. |
| `total_control_packets` | count | Control messages over the whole run. |
| `mean_setup_ms` | ms | Mean wall-clock per round inside `setup_round`. |
| `total_runtime_s` | s | Wall-clock for the whole run. |
| `peak_memory_kb` | KiB | Peak traced allocation via `tracemalloc`. |
| `ops_per_round` | count | Mean counted algorithmic operations per round. |

`mean_setup_ms`, `total_runtime_s` and `peak_memory_kb` are genuine measurements but are **not
reproducible** across runs; determinism checks exclude them. Every other column is bit-reproducible
given the same seed.

**Timing and memory are measured in different runs, so they are never both present in one row.**
Run 0 of each protocol measures `peak_memory_kb` and leaves `mean_setup_ms` / `total_runtime_s`
empty; runs 1+ do the reverse. This is not a convenience — `tracemalloc` inflated setup time by
3.5x-7.8x depending on how many small objects a protocol allocated, which was enough to invert the
GCN-vs-LEACH and SOM-vs-NSGA-II comparisons. See `docs/ASSUMPTIONS.md` item 31 for the measured
table. In `aggregate.csv`, the means simply skip the empty cells, so `peak_memory_kb_mean` comes
from 1 sample (its `_std` is therefore empty) and the timing means from `n_runs - 1`.

## `aggregate.csv` — one row per protocol

`protocol`, then `<metric>_mean` and `<metric>_std` for every scalar above (sample std, ddof=1),
plus `n_censored_runs` — the number of runs whose `lnd` hit the cap. **Never read `lnd_mean` without
`n_censored_runs`**: if any run censored, the mean is a lower bound.

## `validation/`

- `per_calibration.csv` — packet error rate vs distance (`distance_m`, `snr_db`, `ber`,
  `per_4000bit`). Published so the channel's behaviour is auditable rather than buried in a config
  constant. The transmit power determines where the error waterfall sits, and therefore how hard
  single-hop protocols are penalized; see `docs/ASSUMPTIONS.md`.
- `nsga2_convergence.csv` — knee-point objective values per GA generation.

## Reading these numbers safely

Three traps, documented at greater length in `docs/METRICS.md`:

1. **Throughput in packets is not comparable across protocols.** One PEGASIS round delivers a single
   fused packet; one LEACH round delivers about five. Use `readings_delivered_total`.
2. **PDR is survivorship-biased.** Distant nodes lose the most packets and die first, so a protocol
   that burns out its far nodes early posts a *better* PDR. Always read it against `alive_nodes`.
3. **FND and LND can rank protocols in opposite directions.** Clustering equalizes energy
   consumption, which buys a much later first death at the cost of an earlier last death. Report all
   three lifetime points rather than leading with one.
