"""Raw axes -> one scalar sway signal, robust to any mounting angle.

The landmine this module exists to avoid: NEVER take the instantaneous magnitude
of the horizontal components. For linearly-polarised sway both components are
scaled in-phase copies of one sine, |sin| has zero energy at the true frequency,
and the FFT returns a clean confident peak at exactly 2f. Only a FIXED LINEAR
combination (the PCA projection below) is safe.
"""
import numpy as np


def derive_fs(t_ms):
    """fs from timestamps, never the nominal 200 (I4).

    Median of a K-LAGGED difference, not of adjacent diffs. Adjacent diffs fail on
    this wire format: `t` is integer milliseconds, so at 190 Hz the true 5.263 ms
    spacing lands as 5,6,5,5,5,6... whose median is 5 -> a derived 200 Hz and every
    reported frequency 5% wrong, silently. That is precisely the failure this
    function exists to prevent, so it must not be reintroduced by quantisation.

    Lagging by k spreads the same +/-0.5 ms rounding error over k intervals and
    divides it away, while the median still ignores dropped samples the way a mean
    would not. k=50 at 200 Hz is a 250 ms baseline: quantisation error ~0.2%.
    """
    t = np.asarray(t_ms, dtype=float)
    if len(t) < 2:
        raise ValueError("sensor timestamps are not increasing")
    k = max(1, min(50, len(t) // 4))
    dt = float(np.median(t[k:] - t[:-k])) / k / 1000.0
    if dt <= 0:
        raise ValueError("sensor timestamps are not increasing")
    return 1.0 / dt


def gravity_from_baseline(a_baseline):
    """The baseline mean IS the measured gravity vector. Returns (mean, unit)."""
    m = np.asarray(a_baseline, dtype=float).mean(axis=0)
    n = np.linalg.norm(m)
    if n == 0:
        raise ValueError("degenerate baseline: no gravity vector")
    return m, m / n


def horizontal(a, baseline_mean, g_hat):
    """Remove DC using the BASELINE mean (not the whole buffer, which the stomp
    biases), then project the gravity direction out. What remains is genuine
    horizontal motion whatever angle the sensor is taped at."""
    d = np.asarray(a, dtype=float) - baseline_mean
    return d - np.outer(d @ g_hat, g_hat)


def pca_direction(a_horiz):
    """Dominant sway direction: leading eigenvector of the horizontal covariance.

    Sign is fixed deterministically (largest |component| made positive) so repeated
    runs give an identical signal. Magnitude spectra are sign-invariant anyway, and
    the two-sensor path uses only cross-spectral magnitude, so a flip cannot bias
    any reported number.
    """
    c = np.cov(np.asarray(a_horiz, dtype=float).T)
    w, v = np.linalg.eigh(c)
    d = v[:, int(np.argmax(w))]
    return d if d[int(np.argmax(np.abs(d)))] >= 0 else -d


def project(a_horiz, direction):
    return np.asarray(a_horiz, dtype=float) @ direction
