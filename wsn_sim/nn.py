"""Hand-written NumPy neural-network primitives shared by the DQN
(`wsn_sim/protocols/dqn.py`) and GCN (`wsn_sim/protocols/gcn.py`) protocols
and their offline training scripts (`scripts/train_dqn.py`,
`scripts/train_gcn.py`).

No autodiff library is installed or used anywhere in this simulator
(torch/scipy are absent by requirement) -- every forward pass here has a
hand-derived backward pass next to it, and both are checked against central
finite differences in `tests/test_nn.py`.
"""

import numpy as np


def relu(x):
    return np.maximum(0.0, x)


def relu_grad_mask(x):
    """d(relu(x))/dx, as a 0/1 mask. relu is non-differentiable at x==0;
    the subgradient 0 is used there, the conventional choice.
    """
    return (x > 0.0).astype(x.dtype)


def softmax(x, axis=-1):
    """Numerically stable softmax."""
    z = x - np.max(x, axis=axis, keepdims=True)
    ez = np.exp(z)
    return ez / np.sum(ez, axis=axis, keepdims=True)


class Adam:
    """Adam optimizer (Kingma & Ba, 2015) over a dict of named parameters.

    One instance per fixed parameter dict (shapes are captured at
    construction time via `params`). `step(params, grads)` mutates `params`
    in place.
    """

    def __init__(self, params: dict, lr=1e-3, beta1=0.9, beta2=0.999, eps=1e-8):
        self.lr = lr
        self.beta1 = beta1
        self.beta2 = beta2
        self.eps = eps
        self.m = {k: np.zeros_like(v, dtype=float) for k, v in params.items()}
        self.v = {k: np.zeros_like(v, dtype=float) for k, v in params.items()}
        self.t = 0

    def step(self, params: dict, grads: dict):
        self.t += 1
        for k in params:
            g = grads[k]
            self.m[k] = self.beta1 * self.m[k] + (1.0 - self.beta1) * g
            self.v[k] = self.beta2 * self.v[k] + (1.0 - self.beta2) * (g * g)
            m_hat = self.m[k] / (1.0 - self.beta1 ** self.t)
            v_hat = self.v[k] / (1.0 - self.beta2 ** self.t)
            params[k] = params[k] - self.lr * m_hat / (np.sqrt(v_hat) + self.eps)


def clip_grad_norm(grads: dict, max_norm: float) -> float:
    """In-place global-norm gradient clipping across ALL arrays in `grads`
    (treated as one flat vector, standard practice -- clipping each array
    independently would let a single huge-gradient parameter escape
    unclipped while still distorting the relative direction of the update).
    Returns the pre-clip global norm (for logging). No-op (norm unchanged)
    if the global norm is already <= max_norm.
    """
    total_sq = 0.0
    for g in grads.values():
        total_sq += float(np.sum(g * g))
    total_norm = float(np.sqrt(total_sq))
    if total_norm > max_norm and total_norm > 0.0:
        scale = max_norm / total_norm
        for k in grads:
            grads[k] = grads[k] * scale
    return total_norm
