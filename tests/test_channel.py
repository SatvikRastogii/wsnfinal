"""PER calibration curve — mandatory hard gate. Plain script (pytest not
installed) -- run via `python tests/test_channel.py`.

Per the coordinator's explicit instruction: if any of assertions (a)/(b)/(c)
fails against the spec's pinned default constants, this script reports the
real numbers and FAILS LOUDLY. It does not loosen the assertions or tweak
pt_dbm/pl_1m_db/etc. to force a pass.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from wsn_sim.config import SimConfig
from wsn_sim.radio import ber, per, snr_db

FAILURES = []


def check_true(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"{status}: {name}")
    if not cond:
        FAILURES.append(name)


def main():
    cfg = SimConfig()
    out_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "results", "validation"
    )
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "per_calibration.csv")

    d = np.arange(1, 201, dtype=float)  # 1..200 m inclusive
    shadow = np.zeros_like(d)

    snr = snr_db(d, shadow, cfg)
    b = ber(d, shadow, cfg)
    per_curve = per(cfg.data_bits, d, shadow, cfg)

    df = pd.DataFrame(
        {
            "distance_m": d,
            "snr_db": snr,
            "ber": b,
            "per_4000bit": per_curve,
        }
    )
    df.to_csv(out_path, index=False)
    print(f"Wrote {out_path} ({len(df)} rows)")

    # (a) monotonic non-decreasing in distance
    diffs = np.diff(per_curve)
    check_true(
        "(a) PER monotonically non-decreasing in distance",
        bool(np.all(diffs >= -1e-12)),
    )

    # (b) PER < 0.01 at d <= 30 m
    mask_close = d <= 30
    max_close_per = float(per_curve[mask_close].max())
    check_true(
        f"(b) PER < 0.01 at d<=30m (max observed = {max_close_per!r})",
        max_close_per < 0.01,
    )

    # (c) 0.0 < PER < 1.0 somewhere in the 100-160 m band
    mask_band = (d >= 100) & (d <= 160)
    band = per_curve[mask_band]
    stressed = bool(np.any((band > 0.0) & (band < 1.0)))
    check_true(
        f"(c) 0 < PER < 1 somewhere in 100-160m band "
        f"(band min={band.min()!r}, max={band.max()!r})",
        stressed,
    )

    # per_enabled=False gives PER == 0 everywhere
    cfg_no_per = SimConfig(per_enabled=False)
    per_curve_disabled = per(cfg_no_per.data_bits, d, shadow, cfg_no_per)
    check_true(
        "per_enabled=False gives PER == 0.0 everywhere",
        bool(np.all(per_curve_disabled == 0.0)),
    )

    # Report the actual curve values at the 9 requested distances.
    report_distances = [10, 30, 50, 75, 100, 125, 150, 160, 200]
    print()
    print("PER calibration curve at requested distances (shadow=0, 4000-bit packet):")
    print(f"{'d (m)':>8} {'SNR (dB)':>12} {'BER':>14} {'PER':>14}")
    for rd in report_distances:
        idx = rd - 1  # d starts at 1
        print(f"{d[idx]:8.1f} {snr[idx]:12.4f} {b[idx]:14.6e} {per_curve[idx]:14.6e}")

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S): {FAILURES}")
        sys.exit(1)
    print("ALL test_channel.py CHECKS PASSED")
    sys.exit(0)


if __name__ == "__main__":
    main()
