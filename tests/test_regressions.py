"""Bugs that were actually made. A test is what keeps each of them fixed.

R4, R6 and R7 (wrong building, USGS field-name drift, DNR layer confusion) are
asserted in test_fixtures.py against the committed raw payloads.
"""
import numpy as np
import pytest
from conftest import synth_session, synth_signal
from backend.dsp import project as P, spectrum as S
from backend.dsp.analyse import analyse
from backend import hazard


def test_R1_linear_projection_not_magnitude():
    """THE landmine. |sin| has zero energy at the true frequency: its Fourier
    series is DC plus EVEN harmonics. The wrong path gives a clean, confident,
    beautiful peak at exactly 2f, and nothing about the output looks broken."""
    t_ms, a = synth_signal(freq=3.2, tilt_deg=25, noise=0.005, seed=3)
    fs = P.derive_fs(t_ms)
    base = slice(0, int(3.0 * fs))
    mean, g_hat = P.gravity_from_baseline(a[base])
    h = P.horizontal(a, mean, g_hat)[int(3.4 * fs):int(3.4 * fs) + 1600]
    hw = S.bandpass(h, fs)

    right = P.project(hw, P.pca_direction(hw))
    f1, m1 = S.amp_spectrum(right, fs)
    peak_right = f1[np.argmax(np.where((f1 > 0.5) & (f1 < 15), m1, 0))]

    wrong = np.linalg.norm(hw, axis=1)          # the instantaneous magnitude
    f2, m2 = S.amp_spectrum(wrong - wrong.mean(), fs)
    peak_wrong = f2[np.argmax(np.where((f2 > 0.5) & (f2 < 15), m2, 0))]

    assert peak_right == pytest.approx(3.2, rel=0.01)
    assert peak_wrong == pytest.approx(6.4, rel=0.02)    # the bug, reproduced
    assert abs(peak_right - 6.4) > 1.0                   # and NOT what we report


def test_R2_noise_burst_produces_no_frequency():
    """Real motion, no resonance. A noise burst can clear a bare prominence bar,
    so this is what proves the gates are load-bearing rather than decorative."""
    for seed in range(6):
        r = analyse(*synth_session(mode="noisy", seed=seed))
        assert r.frequency_hz is None, f"seed {seed} invented {r.frequency_hz} Hz"
        assert r.confidence == "poor"


def test_R3_zero_median_dt_is_a_named_error_not_zerodivision():
    """Real failure: 15 ms Windows scheduler granularity against a 5 ms target made
    a dozen samples share one millisecond."""
    with pytest.raises(ValueError, match="not increasing"):
        P.derive_fs([1757712345678] * 40)


def test_R5_resonance_score_has_no_universal_lower_bound():
    """An earlier draft claimed Sa/sds is bounded in [0.4, 1.0]. True only up to
    ts; the decay region keeps falling. Checked against the real spectrum."""
    s = dict(sds=1.03, sd1=0.56, t0=0.109, ts=0.546, tl=6)
    score = hazard.compare(0.5, s)["resonance_score"]     # T = 2.0 s
    assert score == pytest.approx(0.27, abs=0.01)
    assert score < 0.4


def test_clipping_vertical_is_informational_but_horizontal_demotes():
    b, t = synth_session(freq=3.2, tilt_deg=5, seed=1)
    for batch in b:
        for s in batch:
            if s["node"] == "top":
                s["az"] = 19.7                        # rail the near-vertical axis
    r = analyse(b, t)
    assert "clipping_vertical" in r.confidence_flags
    assert "clipping" not in r.confidence_flags
