"""ASCE 7-22 two-period spectrum and the resonance score.

Evaluate the closed form at exactly the period needed — zero interpolation error.
Interpolating between two array points on a 1/T decay segment would introduce real
error, so "which interpolation method?" has a clean answer: there isn't one.

Use the TWO-period spectrum only. The real response carries six; the multi-period
curve is a genuinely different shape with no single plateau value to divide by, and
the MCEr / vertical pairs are different hazard levels and a different axis entirely.
"""
from . import config


def sa(period_s, sds, sd1, t0, ts, tl=6.0):
    T = float(period_s)
    if T < t0:
        return sds * (0.4 + 0.6 * T / t0)      # linear ramp
    if T <= ts:
        return sds                             # plateau — the spectrum's maximum
    if T <= tl:
        return sd1 / T                         # decay
    return sd1 * tl / (T * T)                  # long-period tail


def band(score):
    if score < config.BAND_GREEN_MAX:
        return "green"
    if score < config.BAND_AMBER_MAX:
        return "amber"
    return "red"


def compare(frequency_hz, spectrum, measurement_location=None, site_address=None,
            location_matches_site=True):
    """The measurement-to-site join. Computed HERE and nowhere else — both Verdict
    and the stiffness screen need it, and computing it twice guarantees drift.

    resonance_score is NOT a safety score. It is the ratio of spectral acceleration
    at the measured period to the spectrum's plateau: a statement about how hard
    this ground shakes at this period, not about whether the building stands up.
    """
    if not frequency_hz or not spectrum:
        return None
    T = 1.0 / frequency_hz
    s = spectrum
    val = sa(T, s["sds"], s["sd1"], s["t0"], s["ts"], s.get("tl", 6.0))
    score = val / s["sds"]
    return {
        "measured_period_s": round(T, 5),
        "sa_at_period_g": round(val, 5),
        "resonance_score": round(score, 5),
        "band": band(score),
        "plateau_t0_s": s["t0"],
        "plateau_ts_s": s["ts"],
        "measurement_location": measurement_location,
        "site_address": site_address,
        "location_matches_site": location_matches_site,
    }
