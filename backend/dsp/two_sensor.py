"""Transmissibility, coherence and amplification — evaluated AT a frequency found
elsewhere, never proposing one of its own (I3).

What this computes is a TRANSMISSIBILITY (response/response), not a transfer
function (response/force): there is no measured input-force channel, only two
acceleration responses. Say "transmissibility" to an engineer judge.
"""
import numpy as np
from .. import config


def resample_pair(t_top, s_top, t_ground, s_ground, fs):
    """Onto one uniform grid by linear interpolation. Two independently-clocked
    nodes drift, so never assume they lined up because both claim 200 Hz."""
    lo, hi = max(t_top[0], t_ground[0]), min(t_top[-1], t_ground[-1])
    if hi <= lo:
        return None, None, None
    grid = np.arange(lo, hi, 1000.0 / fs)
    return grid, np.interp(grid, t_top, s_top), np.interp(grid, t_ground, s_ground)


def amplification(trials, f_peak, ground_baseline_amp, structural_type):
    """Ensemble transmissibility at f_peak, gated three ways.

    `trials` is a list of (X_top, X_ground, freqs) complex spectra, most recent last.
    Returns (amplification, coherence, flags).
    """
    flags = []
    if not trials or f_peak is None:
        return None, None, flags

    freqs = trials[0][2]
    i = int(np.argmin(np.abs(freqs - f_peak)))
    Xt = np.array([t[0][i] for t in trials])
    Xg = np.array([t[1][i] for t in trials])

    Sxx = float(np.mean(np.abs(Xg) ** 2))
    Sxy = complex(np.mean(Xt * np.conj(Xg)))

    # Gate 1 — SNR. A "just barely non-zero" denominator can still be pure noise,
    # and no amount of regularization makes that meaningful.
    ground_amp = float(np.mean(np.abs(Xg)))
    if ground_baseline_amp and ground_amp > 0:
        snr_db = 20 * np.log10(ground_amp / ground_baseline_amp)
        if snr_db < config.GROUND_SNR_MIN_DB:
            flags.append("low_ground_snr")
            return None, None, flags

    # Gate 2 — coherence, but only where it means anything. A single-trial coherence
    # is IDENTICALLY 1.0 as a mathematical fact, so it is skipped, not reported.
    coh = None
    if len(trials) >= 2:
        Syy = float(np.mean(np.abs(Xt) ** 2))
        coh = float(abs(Sxy) ** 2 / (Sxx * Syy)) if Sxx > 0 and Syy > 0 else 0.0
        if coh < config.COHERENCE_MIN:
            flags.append("low_coherence")
            return None, coh, flags

    # Water-level regularization: the denominator can never fall below one
    # noise-floor's worth, so a near-zero Sxx cannot produce an unbounded ratio.
    eps = config.WATER_LEVEL_K * (ground_baseline_amp ** 2 if ground_baseline_amp else 0.0)
    amp = float(abs(Sxy) / (Sxx + eps)) if (Sxx + eps) > 0 else None

    # Gate 3 — physical ceiling from Q = 1/(2*zeta) for the selected structural type.
    ceil = config.AMPLIFICATION_CEILING.get(structural_type, 50.0)
    if amp is not None and amp > ceil:
        flags.append("amplification_implausible")
        amp = ceil
    return amp, coh, flags
