"""Damping from the ringdown envelope, and a second frequency estimate for free.

Half-power bandwidth is NOT the primary method. The formula is valid for a free
decay (same pole shapes both), but an 8 s Hann window has its own half-power width
of ~1.44/8 = 0.18 Hz, and the true linewidth at 3 Hz / 3% damping is 2*0.03*3 =
0.18 Hz — the same order. Reading it off the windowed spectrum inflates it
systematically for exactly the lightly-damped structures this project measures.
Time-domain envelope fitting has no such contamination.
"""
import numpy as np
from scipy.signal import hilbert
from .. import config


def _analytic(s, fs, freq):
    z = hilbert(np.asarray(s, dtype=float))
    trim = int(round(config.DAMPING_EDGE_TRIM_CYCLES * fs / max(freq, 0.1)))
    trim = max(1, min(trim, len(z) // 4))
    return z[trim:-trim], trim


def envelope_fit(s, fs, freq):
    """Least-squares log-envelope slope -> zeta. Returns (zeta, r2) or (None, r2).

    A generalisation of logarithmic decrement: least squares uses every sample in
    the decay, where the classic 2-point form uses two.
    """
    if freq is None or len(s) < 32:
        return None, 0.0
    z, _ = _analytic(s, fs, freq)
    env = np.abs(z)
    # Fit only the part of the decay that is ABOVE the noise floor. The tail of a
    # ringdown asymptotes to the sensor's own noise, and including it flattens the
    # regression -> a systematically LOW zeta. Measured: fitting to 5% of peak on a
    # true 3.0% signal returned 1.8%. Estimate the floor from the last 10% of the
    # envelope and stay well clear of it.
    floor = float(np.median(env[int(len(env) * 0.9):])) if len(env) > 20 else 0.0
    keep = env > max(env.max() * 0.05, 3.0 * floor)
    if keep.sum() < 16:
        return None, 0.0
    t = np.arange(len(env))[keep] / fs
    y = np.log(env[keep])
    slope, icept = np.polyfit(t, y, 1)
    resid = y - (slope * t + icept)
    ss = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - float(np.sum(resid ** 2)) / ss if ss > 0 else 0.0
    zeta = -slope / (2 * np.pi * freq)
    lo, hi = config.DAMPING_ZETA_BOUNDS
    if r2 < config.DAMPING_R2_MIN or not (lo <= zeta <= hi):
        return None, r2                     # reject, never clip (I1)
    return float(zeta), r2


def ringdown_frequency(s, fs, freq_hint):
    """Independent frequency estimate: instantaneous phase derivative (§6.10).

    Free, because the analytic signal is already computed above. Genuinely
    independent of the FFT peak — time-domain phase vs a frequency-domain maximum —
    so agreement between them is real evidence, not a restatement.
    """
    if freq_hint is None or len(s) < 32:
        return None
    z, _ = _analytic(s, fs, freq_hint)
    env = np.abs(z)
    keep = env > env.max() * 0.20          # early, high-SNR part of the decay only
    inst = np.diff(np.unwrap(np.angle(z))) * fs / (2 * np.pi)
    sel = inst[keep[:-1]]
    if len(sel) < 16:
        return None
    return float(np.median(sel))


def half_power_bandwidth(freqs, mag, f_peak):
    """Kept only as the N=1 uncertainty proxy and a cross-check, never as the
    damping source itself."""
    if f_peak is None:
        return None
    i = int(np.argmin(np.abs(freqs - f_peak)))
    half = mag[i] / np.sqrt(2.0)
    lo = i
    while lo > 0 and mag[lo] > half:
        lo -= 1
    hi = i
    while hi < len(mag) - 1 and mag[hi] > half:
        hi += 1
    return float(freqs[hi] - freqs[lo])


def decay_ratio(s, fs):
    """Early-window band energy over late-window band energy.

    The one thing that separates a stomp ringdown from a burst of real motion: a
    ringdown DECAYS. A noise burst clears prominence (it is a peak) and clears SNR
    (it is louder than the baseline), and for narrowband-filtered noise the
    instantaneous frequency tracks the spectral peak, so it even clears the
    estimator cross-check. None of those gates can see the difference. This one can.

    Safe against real signals by a wide margin: the slowest golden case (1.4 Hz at
    3% damping, tau = 3.8 s) gives ~24; flat noise gives ~1.
    """
    x = np.asarray(s, dtype=float)
    q = max(1, len(x) // 4)
    early = float(np.mean(x[:q] ** 2))
    late = float(np.mean(x[-q:] ** 2))
    return float("inf") if late <= 0 else early / late
