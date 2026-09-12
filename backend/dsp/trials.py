"""Per-location trial history: median, spread, uncertainty, the single-trial cap.

Keyed per location and never mixed: a tap on the expo table must not enter
Founders Hall's history, or both the median and the "three stomps agree" claim are
silently corrupted.
"""
import numpy as np
from .. import config
from .confidence import worst


def median_frequency(freqs):
    """Median of the non-null trials. A failed trial contributes NOTHING — it is
    excluded, never averaged in as a zero."""
    vals = [f for f in freqs if f is not None]
    return (float(np.median(vals)) if vals else None), len(vals)


def spread_level(freqs):
    """Max deviation from the median, as a fraction of it -> a confidence ceiling."""
    vals = [f for f in freqs if f is not None]
    if len(vals) < 2:
        return "good", None
    med = float(np.median(vals))
    if med <= 0:
        return "good", None
    s = float(max(abs(v - med) for v in vals) / med)
    if s > config.SPREAD_POOR:
        return "poor", s
    if s > config.SPREAD_FAIR:
        return "fair", s
    return "good", s


def uncertainty(freqs, half_power_bw):
    """N>=2: the empirical cross-trial stdev — a real measured number.
    N==1: a conservative heuristic off the half-power bandwidth.

    NOT the Cramer-Rao bound: checked against the real numbers (fs=200, N=1600) it
    gives 0.0001-0.002 Hz even at 0-20 dB SNR, three orders of magnitude tighter
    than anything real, because it assumes a stationary tone and this is a decaying
    transient. Reporting it would be precise-looking and dishonest.
    """
    vals = [f for f in freqs if f is not None]
    if len(vals) >= 2:
        return float(np.std(vals, ddof=1))
    if half_power_bw is None:
        return None
    return float(max(config.UNCERTAINTY_FLOOR_HZ, 0.5 * half_power_bw))


def combine(flag_level, freqs):
    """Worst-of three independent levels, including the single-trial cap.

    The cap is a real rule, not an oversight: a single-trial coherence is
    degenerate, so nothing has actually validated a one-stomp reading. Without an
    explicit cap a clean single stomp would reach "good" through a GAP in the
    spread check rather than by passing anything.
    """
    n = len([f for f in freqs if f is not None])
    spread, _ = spread_level(freqs)
    single_cap = "fair" if n <= 1 else "good"
    return worst(flag_level, spread, single_cap)
