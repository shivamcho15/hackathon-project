"""The orchestrator: wire-format batches in, one analysis result out.

Chain: derive fs -> baseline gravity -> project gravity out -> onset -> crop ->
bandpass -> PCA -> Hann -> zero-pad -> rFFT -> prominence + SNR -> parabolic.
The two-sensor math is a SEPARATE branch evaluated at the frequency found here.
"""
from dataclasses import dataclass, field, asdict
import numpy as np

from .. import config
from . import project as P, onset as O, spectrum as S, damping as D, two_sensor as TS
from . import confidence as C, trials as T
from ..ingest import validate as V


@dataclass
class Result:
    frequency_hz: float = None
    frequency_uncertainty_hz: float = None
    frequency_check_hz: float = None
    location_median_hz: float = None
    period_s: float = None
    damping_ratio: float = None
    amplification: float = None
    channels_used: list = field(default_factory=list)
    coherence: float = None
    trials_used: int = 1
    spectrum: list = field(default_factory=list)
    confidence: str = "poor"
    confidence_flags: list = field(default_factory=list)
    source: str = "unknown"
    fs_hz: float = None
    # Calibration only — echoed back so the row is self-contained and the Validation
    # screen can match a run to the overhang it was recorded at.
    predicted_frequency_hz: float = None
    beam_overhang_m: float = None
    beam_width_m: float = None
    beam_thickness_m: float = None
    beam_tip_mass_kg: float = None
    abort_reason: str = None
    dict = asdict


def _group(batches):
    by = {}
    for b in batches:
        for s in b:
            by.setdefault(s["node"], []).append(s)
    out, stats = {}, {}
    for node, rows in by.items():
        t, a, st = V.dedupe_sort(rows)
        out[node], stats[node] = (t, a), st
    return out, stats


def _prep(t_ms, a, times, fs):
    """Baseline gravity, horizontal projection, and the envelope used for onset."""
    base = t_ms < times["stomp_cue_at"]
    if base.sum() < 10:
        raise ValueError("baseline segment too short")
    mean, g_hat = P.gravity_from_baseline(a[base])
    h = P.horizontal(a, mean, g_hat)
    return h, g_hat, base, O.rms_envelope(np.linalg.norm(h, axis=1), fs)


def analyse(batches, times, mode="building", structural_type=None,
            n_floors=None, source="unknown", history=None, trial_store=None):
    structural_type = structural_type or config.STRUCTURAL_TYPE_DEFAULT
    band = (config.SEARCH_HZ_CALIBRATION if mode == "calibration"
            else config.SEARCH_HZ_BUILDING)
    history = list(history or [])
    r = Result(source=source)

    chans, ingest_stats = _group(batches)
    if not chans:
        r.confidence_flags = ["no_data"]
        return r

    fs = V.check_fs(P.derive_fs(next(iter(chans.values()))[0]))
    r.fs_hz = round(fs, 3)

    # Two clocks on different epochs cannot be aligned, so the two-sensor path is
    # disabled for the session. Single-channel analysis is completely unaffected.
    no_clock = any(V.clock_mode(t) == "relative" for t, _ in chans.values())

    prepped, flags = {}, []
    for node, st in ingest_stats.items():
        flags += V.timestamp_flags(st)
    for node, (t_ms, a) in chans.items():
        _, g0 = P.gravity_from_baseline(a[t_ms < times["stomp_cue_at"]])
        cf = V.clipping_flag(a, g0)
        if cf:
            flags.append(cf)
        prepped[node] = (t_ms, a) + _prep(t_ms, a, times, fs)

    # Onset on the COMBINED envelope, so both channels crop to the same window.
    # Per-sensor onset would not guarantee time-aligned segments.
    ref = max(prepped, key=lambda n: prepped[n][5].max())
    t_ms_ref, _a, _h, _g, base_mask, env = prepped[ref]
    search_from = int(np.searchsorted(
        t_ms_ref, times["stomp_cue_at"] - config.ONSET_SLACK_S * 1000))
    onset, _ = O.find_onset(env, base_mask, search_from)

    if onset is None:
        r.confidence, r.confidence_flags = "poor", flags + ["no_onset"]
        return r

    start, stop, truncated = O.analysis_window(len(t_ms_ref), onset, fs)
    if truncated:
        flags.append("short_window")

    gaps = V.gap_stats(t_ms_ref[start:stop])
    gflags, abort = V.gap_flags(gaps)
    if abort:
        r.confidence, r.confidence_flags = "poor", flags + ["sample_gap", "aborted"]
        r.abort_reason = abort
        return r
    flags += gflags

    mv = V.moved_flag(prepped[ref][1][start:stop], prepped[ref][3], fs)
    if mv:
        flags.append(mv)

    # Per-channel scalar sway signal over the shared window.
    sig, base_spec, cplx = {}, {}, {}
    for node, (t_ms, a, h, g_hat, bmask, _e) in prepped.items():
        hw = S.bandpass(h[start:stop], fs)
        d = P.pca_direction(hw)
        sig[node] = (t_ms[start:stop], P.project(hw, d))
        hb = S.bandpass(h[bmask], fs)
        base_spec[node] = S.amp_spectrum(P.project(hb, d), fs)

    top = "top" if "top" in sig else next(iter(sig))
    t_top, s_top = sig[top]
    freqs, mag = S.amp_spectrum(s_top, fs)

    cands, med = S.find_candidates(freqs, mag, band)
    qualified = [c for c in cands if c["qualified"]]
    r.spectrum = S.spectrum_points(freqs, mag, band)

    if not qualified:
        r.confidence, r.confidence_flags = "poor", flags + ["no_peak"]
        return r

    peak = qualified[0]
    bf, bm = base_spec[top]
    i = int(np.argmin(np.abs(bf - peak["f"])))
    snr_db = (20 * np.log10(peak["mag"] / bm[i])) if bm[i] > 0 else 99.0
    if snr_db < config.SNR_MIN_DB:
        r.confidence = "poor"
        r.confidence_flags = flags + ["low_snr", "no_peak"]
        return r

    f_check = D.ringdown_frequency(s_top, fs, peak["f"])

    if D.decay_ratio(s_top, fs) < config.DECAY_RATIO_MIN:
        r.confidence = "poor"
        r.confidence_flags = flags + ["no_decay"]
        return r

    r.frequency_hz = round(peak["f"], 4)
    r.frequency_check_hz = None if f_check is None else round(f_check, 4)
    r.period_s = round(1.0 / peak["f"], 5)
    r.channels_used = [top]

    zeta, _r2 = D.envelope_fit(s_top, fs, peak["f"])
    r.damping_ratio = None if zeta is None else round(zeta, 5)
    hpbw = D.half_power_bandwidth(freqs, mag, peak["f"])

    # A ground channel that stops partway through is not a usable second channel:
    # degrade to top-only and say so, rather than analysing a lopsided pair.
    if "ground" in sig and top != "ground":
        cover = len(sig["ground"][0]) / max(len(sig[top][0]), 1)
        if cover < 0.7:
            del sig["ground"]
            flags.append("ground_lost_midrun")
    if no_clock and "ground" in sig:
        del sig["ground"]
        flags.append("no_clock_sync")

    # Two-sensor branch. It never located the frequency; it only evaluates at it.
    if "ground" in sig and top != "ground":
        t_g, s_g = sig["ground"]
        grid, a_t, a_g = TS.resample_pair(t_top, s_top, t_g, s_g, fs)
        if grid is not None:
            w = np.hanning(len(a_t))
            Xt = np.fft.rfft(a_t * w, config.ZERO_PAD_N) * 2 / w.sum()
            Xg = np.fft.rfft(a_g * w, config.ZERO_PAD_N) * 2 / w.sum()
            store = list(trial_store) if trial_store else []
            store.append((Xt, Xg, freqs))
            store = store[-config.TRIAL_HISTORY_MAX:]
            if trial_store is not None:
                trial_store[:] = store
            gb = base_spec["ground"][1]
            amp, coh, tsf = TS.amplification(
                store, peak["f"], float(gb[i]), structural_type)
            r.amplification = None if amp is None else round(amp, 3)
            r.coherence = None if coh is None else round(coh, 4)
            flags += tsf
            r.channels_used = [top, "ground"]
    elif top == "ground":
        flags.append("single_node_ground")

    fflags = C.frequency_flags(peak, cands, med, snr_db, f_check, band, n_floors)
    r.confidence_flags = sorted(set(flags + fflags))

    all_freqs = history + [r.frequency_hz]
    r.location_median_hz, n = T.median_frequency(all_freqs)
    r.trials_used = max(1, n)
    if r.trials_used == 1:
        r.location_median_hz = None          # the median IS frequency_hz; no duplicate
    r.frequency_uncertainty_hz = T.uncertainty(all_freqs, hpbw)
    if r.frequency_uncertainty_hz is not None:
        r.frequency_uncertainty_hz = round(r.frequency_uncertainty_hz, 4)

    level = C.level_from_flags(r.confidence_flags)
    if top == "ground":
        level = C.worst(level, "fair")
    r.confidence = T.combine(level, all_freqs)
    return r
