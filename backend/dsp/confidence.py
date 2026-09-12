"""Flags and the worst-of combination rule.

Nothing here ever changes WHICH frequency is reported (I10). Every check only
demotes confidence and appends a human-readable flag, so the reported number is
always "the global max that cleared prominence and SNR", full stop.
"""
import numpy as np
from .. import config

LEVELS = ("poor", "fair", "good")
NO_DEMOTE = {"clipping_vertical"}          # informational: that energy is projected out


def demote(level, steps=1):
    return LEVELS[max(0, LEVELS.index(level) - steps)]


def worst(*levels):
    return LEVELS[min(LEVELS.index(l) for l in levels if l)]


def frequency_flags(peak, candidates, median_mag, snr_db, f_check, band, n_floors=None):
    """The frequency-domain checks. `peak` is the accepted candidate."""
    flags = []
    if peak["prominence"] < config.PROMINENCE_MULT * median_mag:
        flags.append("low_prominence")
    if snr_db is not None and snr_db < config.SNR_MIN_DB:
        flags.append("low_snr")

    # A real fundamental can hide under a stronger harmonic, so the partner search
    # uses a RELAXED bar. Flag only — never swap to the lower peak.
    f = peak["f"]
    for c in candidates:
        # The partner must be a real competing peak. Against a spectrum zero-padded
        # to 8192 bins there is almost always SOME relaxed-bar bump near f/2 or f/3
        # by chance, so a bare prominence bar false-positives on nearly every peak.
        # A genuinely hidden fundamental is the clear SECOND peak, comparable in
        # magnitude to the first. Measured on a clean 5.7 Hz ringdown, this
        # spectrum's own transient/noise floor sits at 18-28% of the peak, and one
        # of those bumps landed near f/2 by chance -> a false positive at any bar
        # below that. 40% is above the floor and far below a real competing mode.
        if c is peak or c["f"] >= f or c["mag"] < config.HARMONIC_MIN_RATIO * peak["mag"]:
            continue
        for k in (2, 3):
            if abs(f - k * c["f"]) <= config.HARMONIC_TOLERANCE * f:
                flags.append("possible_harmonic")
                break
        if "possible_harmonic" in flags:
            break

    # A filter's rolloff is not a wall: slab-mode energy can leak in just under the
    # ceiling, and a true low-rise sway mode is far more plausibly 1-8 Hz.
    if f >= band[1] - config.NEAR_CEILING_HZ:
        flags.append("near_ceiling")

    if n_floors:
        expected = 1.0 / (0.1 * n_floors)
        if max(f / expected, expected / f) > config.PLAUSIBILITY_FACTOR:
            closer = [c for c in candidates if c is not peak and
                      abs(c["f"] - expected) < abs(f - expected)]
            if closer:
                flags.append("plausibility_mismatch")

    if f_check is not None and f > 0:
        if abs(f_check - f) / f > config.ESTIMATOR_AGREEMENT:
            flags.append("estimator_disagreement")
    return flags


def level_from_flags(flags):
    level = "good"
    for fl in flags:
        if fl not in NO_DEMOTE:
            level = demote(level)
    return level
