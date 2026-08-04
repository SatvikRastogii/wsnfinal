"""Mandatory gradient check: hand-written backprop (DQN's MLP, GCN's 2-layer
graph conv) verified against central finite differences on EVERY weight
matrix. This is the single most likely place for a silent bug -- a wrong
gradient still "trains" (loss can still go down), just toward the wrong
place, so a normal training-curve sanity check would not catch it. Plain
script (pytest not installed) -- run via `python tests/test_nn.py`. Prints
PASS/FAIL per check, prints the actual max relative error achieved, and
exits non-zero on any failure.

Method: central finite differences of a SCALAR probe `sum(dY * Y(param))`
against each parameter, compared to the same quantity computed by feeding
the same upstream gradient `dY` into the hand-written `backward()`. This is
the standard, framework-agnostic way to validate a `backward()` function:
it decouples the check from any particular loss, so it validates the
forward/backward PAIR itself rather than one specific loss's gradient.
(The GCN self-supervised loss's OWN gradient, `dL/ds`, is separately
verified against finite differences in an ad hoc check during development;
see wsn_sim/protocols/gcn.py's `energy_balance_loss` docstring -- this file
focuses on the network primitives, which is where a silent bug would most
plausibly hide and propagate into every downstream use.)
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from wsn_sim.protocols import dqn, gcn

FAILURES = []
REL_ERRORS = []


def check_true(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"{status}: {name}")
    if not cond:
        FAILURES.append(name)


def _rel_error(analytic, numeric):
    denom = np.maximum(np.abs(analytic), np.abs(numeric))
    denom = np.where(denom < 1e-8, 1.0, denom)  # avoid inflating error on near-zero entries
    return np.abs(analytic - numeric) / denom


def _grad_check(label, forward_fn, backward_fn, params, extra_fwd_args, dY, eps=1e-5, tol=1e-5):
    """`forward_fn(params, *extra_fwd_args) -> (Y, cache)`,
    `backward_fn(params, cache, dY) -> grads dict`. Checks every key in
    `params` via central finite differences on the scalar probe
    `sum(dY * Y)`.
    """
    Y0, cache = forward_fn(params, *extra_fwd_args)
    grads = backward_fn(params, cache, dY)

    for key, W in params.items():
        analytic = grads[key]
        numeric = np.zeros_like(W, dtype=float)
        it = np.nditer(W, flags=["multi_index"])
        for _ in it:
            idx = it.multi_index
            orig = W[idx]
            W[idx] = orig + eps
            y_plus, _ = forward_fn(params, *extra_fwd_args)
            W[idx] = orig - eps
            y_minus, _ = forward_fn(params, *extra_fwd_args)
            W[idx] = orig
            numeric[idx] = np.sum(dY * (y_plus - y_minus)) / (2 * eps)

        rel = _rel_error(analytic, numeric)
        max_rel = float(rel.max())
        REL_ERRORS.append((f"{label}.{key}", max_rel))
        check_true(
            f"[{label}] d/d{key} matches finite differences (max rel error = {max_rel:.3e} < {tol:.0e})",
            max_rel < tol,
        )


def test_dqn_gradcheck():
    rng = np.random.default_rng(0)
    params = dqn.init_params(rng)
    n = 7
    X = rng.uniform(0.0, 1.0, size=(n, dqn.N_FEATURES))
    dQ = rng.normal(size=(n, dqn.N_ACTIONS))
    _grad_check("dqn", dqn.forward, dqn.backward, params, (X,), dQ)


def test_gcn_gradcheck():
    rng = np.random.default_rng(1)
    params = gcn.init_params(rng)
    n = 9
    # A small, real-looking symmetric-normalized adjacency (ring graph + self loops).
    A = np.zeros((n, n), dtype=bool)
    for i in range(n):
        A[i, (i + 1) % n] = True
        A[i, (i - 1) % n] = True
    A_self = A | np.eye(n, dtype=bool)
    deg = A_self.sum(axis=1).astype(float)
    d_inv_sqrt = 1.0 / np.sqrt(deg)
    A_hat = (A_self.astype(float) * d_inv_sqrt[:, None]) * d_inv_sqrt[None, :]

    X = rng.uniform(0.0, 1.0, size=(n, gcn.N_FEATURES))
    ds = rng.normal(size=n)
    _grad_check("gcn", gcn.forward, gcn.backward, params, (A_hat, X), ds)


def test_gcn_loss_gradient():
    """The loss->score gradient (dL/ds) is hand-derived separately from the
    network backward pass (see gcn.energy_balance_loss); check IT against
    finite differences too, decoupled from the network entirely (s is
    treated as a free vector, not the network's output).
    """
    import sys as _sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from wsn_sim.config import SimConfig
    from wsn_sim.network import Network

    cfg = SimConfig(n_nodes=12)
    net = Network(cfg, run_index=0)
    alive_arr = np.arange(12)
    rng = np.random.default_rng(2)
    s = rng.normal(size=12)
    e_hat = rng.random(12)

    _, ds_analytic = gcn.energy_balance_loss(net, alive_arr, s, e_hat)
    eps = 1e-6
    ds_numeric = np.zeros(12)
    for k in range(12):
        sp = s.copy(); sp[k] += eps
        sm = s.copy(); sm[k] -= eps
        Lp, _ = gcn.energy_balance_loss(net, alive_arr, sp, e_hat)
        Lm, _ = gcn.energy_balance_loss(net, alive_arr, sm, e_hat)
        ds_numeric[k] = (Lp - Lm) / (2 * eps)

    rel = _rel_error(ds_analytic, ds_numeric)
    max_rel = float(rel.max())
    REL_ERRORS.append(("gcn_loss.dL/ds", max_rel))
    check_true(
        f"[gcn_loss] dL/ds matches finite differences (max rel error = {max_rel:.3e} < 1e-5)",
        max_rel < 1e-5,
    )


def main():
    print("=== DQN MLP (4->16->2) gradient check ===")
    test_dqn_gradcheck()
    print()
    print("=== GCN 2-layer graph-conv gradient check ===")
    test_gcn_gradcheck()
    print()
    print("=== GCN self-supervised loss dL/ds gradient check ===")
    test_gcn_loss_gradient()

    print()
    print("=== Summary: max relative error per parameter ===")
    for label, err in REL_ERRORS:
        print(f"  {label}: {err:.3e}")
    overall_max = max(e for _, e in REL_ERRORS) if REL_ERRORS else 0.0
    print(f"\nOverall max relative error across all checks: {overall_max:.3e}")

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S): {FAILURES}")
        sys.exit(1)
    print("ALL test_nn.py CHECKS PASSED")
    sys.exit(0)


if __name__ == "__main__":
    main()
