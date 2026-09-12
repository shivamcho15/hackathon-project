"""Filtering, the FFT, and peak location. Single channel, division-free (I3)."""
import numpy as np
from scipy.signal import butter, filtfilt, find_peaks
from .. import config


def bandpass(x, fs):
    """4th-order Butterworth, zero-phase. Zero-phase matters: the damping estimate
    reads the decay envelope's shape, and a causal filter would smear it."""
    ny = fs / 2.0
    hi = min(config.BANDPASS_HIGH_HZ / ny, 0.99)
    b, a = butter(config.BANDPASS_ORDER, [config.BANDPASS_LOW_HZ / ny, hi], btype="band")
    x = np.asarray(x, dtype=float)
    pad = min(len(x) - 1, 3 * max(len(b), len(a)))
    return filtfilt(b, a, x, padlen=pad) if x.ndim == 1 else np.apply_along_axis(
        lambda c: filtfilt(b, a, c, padlen=pad), 0, x)


def amp_spectrum(x, fs, nfft=None):
    """Hann-windowed, zero-padded amplitude spectrum in physical units.

    Normalised by the window's coherent gain, so spectra computed from segments of
    DIFFERENT length (the 8 s analysis window vs the 3 s baseline) are directly
    comparable — which is exactly what the SNR gate needs.
    """
    x = np.asarray(x, dtype=float)
    nfft = nfft or config.ZERO_PAD_N
    w = np.hanning(len(x))
    X = np.fft.rfft(x * w, nfft)
    return np.fft.rfftfreq(nfft, 1.0 / fs), 2.0 * np.abs(X) / w.sum()


def _parabolic(freqs, mag, i):
    """Sub-bin refinement on the log-magnitude across the 3 bins at the peak."""
    if i <= 0 or i >= len(mag) - 1:
        return float(freqs[i])
    y0, y1, y2 = np.log(np.maximum(mag[i - 1:i + 2], 1e-30))
    den = y0 - 2 * y1 + y2
    d = 0.0 if den == 0 else 0.5 * (y0 - y2) / den
    return float(freqs[i] + np.clip(d, -0.5, 0.5) * (freqs[1] - freqs[0]))


def find_candidates(freqs, mag, band):
    """Every prominence-qualified peak in band, strongest first.

    Adaptive threshold: prominence >= 3x the in-band MEDIAN. Adaptive because raw
    magnitude scales with stomp strength and sensor gain, so a fixed absolute bar
    would be too strict for a soft stomp and too loose for a hard one.
    """
    lo, hi = band
    sel = (freqs >= lo) & (freqs <= hi)
    fb, mb = freqs[sel], mag[sel]
    if not len(mb):
        return [], 0.0
    med = float(np.median(mb))
    idx, props = find_peaks(mb, prominence=config.PROMINENCE_MULT * med)
    relaxed, _ = find_peaks(mb, prominence=config.PROMINENCE_MULT_RELAXED * med)
    out = [{"f": _parabolic(fb, mb, int(i)), "mag": float(mb[i]),
            "prominence": float(p), "qualified": True}
           for i, p in zip(idx, props["prominences"])]
    out += [{"f": _parabolic(fb, mb, int(i)), "mag": float(mb[i]),
             "prominence": 0.0, "qualified": False}
            for i in relaxed if i not in set(idx)]
    out.sort(key=lambda d: -d["mag"])
    return out, med


def spectrum_points(freqs, mag, band, step=4):
    lo, hi = band
    sel = (freqs >= lo) & (freqs <= hi)
    return [{"f": round(float(f), 4), "mag": float(m)}
            for f, m in zip(freqs[sel][::step], mag[sel][::step])]
