"""Hand-computed radio-model checks. Plain script (pytest not installed) --
run via `python tests/test_radio.py`. Prints PASS/FAIL per check and exits
non-zero on any failure.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wsn_sim.config import SimConfig
from wsn_sim.radio import e_agg, e_rx, e_tx

FAILURES = []


def check(name, actual, expected, rtol=1e-12, atol=0.0):
    ok = abs(actual - expected) <= (atol + rtol * abs(expected))
    status = "PASS" if ok else "FAIL"
    print(f"{status}: {name}  actual={actual!r} expected={expected!r}")
    if not ok:
        FAILURES.append(name)


def check_true(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"{status}: {name}")
    if not cond:
        FAILURES.append(name)


def main():
    cfg = SimConfig()

    # e_tx(4000, 50.0) == 3.0e-4 J  (d < d0: 4000*50e-9 + 4000*10e-12*2500)
    check("e_tx(4000, 50.0) == 3.0e-4 J", e_tx(4000, 50.0, cfg), 3.0e-4)

    # e_tx(4000, 100.0) == 7.2e-4 J (d >= d0: 4000*50e-9 + 4000*1.3e-15*1e8)
    check("e_tx(4000, 100.0) == 7.2e-4 J", e_tx(4000, 100.0, cfg), 7.2e-4)

    # e_rx(4000) == 2.0e-4 J
    check("e_rx(4000) == 2.0e-4 J", e_rx(4000, cfg), 2.0e-4)

    # e_agg(4000) == 2.0e-5 J
    check("e_agg(4000) == 2.0e-5 J", e_agg(4000, cfg), 2.0e-5)

    # d0 ~ 87.7 m
    check_true(f"87.0 < d0 < 88.5 (d0={cfg.d0!r})", 87.0 < cfg.d0 < 88.5)

    # tx_time_ms / slot_ms sanity (from the config spec)
    check("tx_time_ms == 16.0 ms", cfg.tx_time_ms, 16.0)
    check("slot_ms == 20.0 ms", cfg.slot_ms, 20.0)

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S): {FAILURES}")
        sys.exit(1)
    print("ALL test_radio.py CHECKS PASSED")
    sys.exit(0)


if __name__ == "__main__":
    main()
