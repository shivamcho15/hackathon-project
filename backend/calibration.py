"""Cantilever beam prediction for the validation sweep.

The ratio between two lengths of the SAME ruler is the pass/fail criterion, not the
absolute value: without calipers the thickness estimate carries ~+/-50% on absolute
frequency (h from 0.8 to 1.8 mm swings the 20 cm prediction from ~0.85 to ~2.9 Hz
via h^1.5), but a constant h, E or b error CANCELS EXACTLY in the ratio.
"""
import numpy as np

E_PLASTIC = 3.0e9          # assumed mid-range rigid plastic, genuinely uncertain


def predict(overhang_m, width_m=0.030, thickness_m=0.0012,
            tip_mass_kg=0.050, E=E_PLASTIC):
    I = width_m * thickness_m ** 3 / 12.0
    return float(np.sqrt(3 * E * I / (tip_mass_kg * overhang_m ** 3)) / (2 * np.pi))


def ratio_check(l_long, l_short, f_long, f_short, tol=0.15):
    """Predicted ratio is purely geometric: (L_long/L_short)^1.5."""
    predicted = (l_long / l_short) ** 1.5
    measured = f_short / f_long
    delta = abs(measured - predicted) / predicted
    return {"predicted": round(predicted, 4), "measured": round(measured, 4),
            "delta": round(delta, 4), "pass": delta <= tol}
