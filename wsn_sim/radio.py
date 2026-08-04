"""First-order radio energy model and lossy-channel math.

All energy accounting and packet-error math for the whole simulator lives
here. Protocols never compute energy or PER themselves.
"""

import numpy as np

from .config import SimConfig


def _scalar_or_array(value, like):
    """Return a plain float if `like` was a scalar, else the array unchanged."""
    if np.ndim(like) == 0:
        return float(value)
    return value


def e_tx(bits: float, d, cfg: SimConfig):
    """Energy to transmit `bits` a distance `d` (first-order radio model).

    d < d0  -> free-space model (d^2 loss)
    d >= d0 -> multipath model (d^4 loss)
    """
    d_arr = np.asarray(d, dtype=float)
    short = bits * cfg.e_elec + bits * cfg.eps_fs * d_arr ** 2
    long_ = bits * cfg.e_elec + bits * cfg.eps_mp * d_arr ** 4
    result = np.where(d_arr < cfg.d0, short, long_)
    return _scalar_or_array(result, d)


def e_rx(bits: float, cfg: SimConfig) -> float:
    """Energy to receive `bits`."""
    return bits * cfg.e_elec


def e_agg(bits: float, cfg: SimConfig) -> float:
    """Energy to aggregate/fuse `bits` worth of received data before forwarding."""
    return bits * cfg.e_da


def path_loss_db(d, shadow_db, cfg: SimConfig):
    """Log-distance path loss in dB, with per-link shadowing added.

    Distance is clamped to >= 1.0 m before the log to avoid log(0)/negative
    path loss at very short range.
    """
    d_arr = np.clip(np.asarray(d, dtype=float), 1.0, None)
    result = cfg.pl_1m_db + 10.0 * cfg.path_loss_n * np.log10(d_arr) + shadow_db
    return _scalar_or_array(result, d)


def snr_db(d, shadow_db, cfg: SimConfig):
    """Receiver SNR in dB."""
    pl = path_loss_db(d, shadow_db, cfg)
    pr_dbm = cfg.pt_dbm - np.asarray(pl, dtype=float)
    result = pr_dbm - cfg.noise_floor_dbm
    return _scalar_or_array(result, d)


def ber(d, shadow_db, cfg: SimConfig):
    """Bit error rate for non-coherent BFSK: BER = 0.5*exp(-SNR_lin/2).

    SNR_lin is clipped to a large-but-safe ceiling before exponentiation so
    that extreme close-range SNR values can never trigger an overflow
    warning in `np.exp`/`np.power` (exp(-large/2) underflows harmlessly to
    0.0 in float64, which is the physically correct answer: BER -> 0 at very
    high SNR).
    """
    snr = snr_db(d, shadow_db, cfg)
    snr_lin = np.power(10.0, np.asarray(snr, dtype=float) / 10.0)
    snr_lin = np.clip(snr_lin, 0.0, 1e6)
    result = 0.5 * np.exp(-snr_lin / 2.0)
    return _scalar_or_array(result, d)


def per(bits: float, d, shadow_db, cfg: SimConfig):
    """Packet error rate for a `bits`-bit packet: PER = 1 - (1-BER)**bits.

    Computed via the numerically stable form PER = -expm1(bits*log1p(-BER))
    rather than the naive `1 - (1-BER)**bits`, which loses precision (and can
    warn) when BER is extremely small and `bits` is large.
    """
    if not cfg.per_enabled:
        if np.ndim(d) == 0:
            return 0.0
        return np.zeros_like(np.asarray(d, dtype=float))
    b = ber(d, shadow_db, cfg)
    b_arr = np.clip(np.asarray(b, dtype=float), 0.0, 0.5)
    result = -np.expm1(bits * np.log1p(-b_arr))
    return _scalar_or_array(result, d)
