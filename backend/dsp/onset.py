"""Find the stomp inside the buffer, and crop to the analysis window."""
import numpy as np
from .. import config


def rms_envelope(x, fs, window_s=None):
    w = max(2, int(round((window_s or config.ENVELOPE_WINDOW_S) * fs)))
    p = np.convolve(np.asarray(x, dtype=float) ** 2, np.ones(w) / w, mode="same")
    return np.sqrt(p)


def find_onset(env, baseline_slice, search_from, mult=None):
    """First point where the envelope exceeds `mult` x the baseline RMS.

    The baseline is the countdown segment — guaranteed quiet, because the protocol
    puts a 3 s mechanical-settle window before the cue. Returns None if nobody
    stomped, which is a real outcome and not an error (§6.9 case 1).
    """
    mult = config.ONSET_THRESHOLD_MULT if mult is None else mult
    base = float(np.mean(env[baseline_slice]))
    if base <= 0:
        return None, 0.0
    thr = mult * base
    idx = np.flatnonzero(env[search_from:] > thr)
    return (int(idx[0]) + search_from if len(idx) else None), base


def analysis_window(n, onset_idx, fs):
    """8 s starting 0.1 s before onset, clipped to what exists.

    Returns (start, stop, truncated). `truncated` means a late stomp left less
    than the 3 s minimum after onset — use what there is and demote, rather than
    failing outright.
    """
    start = max(0, onset_idx - int(round(config.ONSET_LEAD_S * fs)))
    stop = min(n, start + int(round(config.ANALYSIS_WINDOW_S * fs)))
    return start, stop, (stop - onset_idx) < int(round(config.MIN_POST_ONSET_S * fs))
