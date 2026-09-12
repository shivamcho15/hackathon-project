"""Closed forms with exact answers, asserted against numpy's own eigensolver.

These are the formulas where a wrong answer is invisible: a building that sways at
5.89 Hz instead of 3.24 Hz looks completely plausible on screen.
"""
import numpy as np
import pytest
from backend import physics_ref as PH, hazard, calibration as CAL

SPEC = dict(sds=1.03, sd1=0.56, t0=0.109, ts=0.546, tl=6)


@pytest.mark.parametrize("n", range(1, 9))
def test_P1_stiffness_tuning_is_exact(n):
    target = 3.24
    k = PH.stiffness_for(target, n)
    f1, _ = PH.mode_shape(PH.stiffness_matrix(k, n))
    assert f1 == pytest.approx(target, rel=1e-9)


def test_P1_trap_2k_on_the_last_diagonal_is_wrong():
    """The obvious assembly loop writes 2k on every diagonal. It looks right and it
    is wrong — the top floor has no floor above it. Documented here so nobody
    'simplifies' stiffness_matrix back into the bug."""
    n, target = 5, 3.24
    k = PH.stiffness_for(target, n)
    K = PH.stiffness_matrix(k, n)
    K_wrong = K.copy()
    K_wrong[n - 1, n - 1] = 2 * k
    f_wrong = np.sqrt(np.linalg.eigvalsh(K_wrong)[0]) / (2 * np.pi)
    assert PH.mode_shape(K)[0] == pytest.approx(target, rel=1e-9)
    assert f_wrong == pytest.approx(5.89, abs=0.01)     # 82% high, silently


def test_P2_magnification_peaks_at_resonance_and_is_always_finite():
    """Replaces the old symplectic-Euler stability test: there is no integrator to
    destabilise, so what matters is that H(r) behaves."""
    zeta, f1 = 0.0325, 3.24
    assert PH.magnification(f1, f1, zeta) == pytest.approx(1 / (2 * zeta), rel=1e-9)
    assert PH.magnification(0.001, f1, zeta) == pytest.approx(1.0, abs=1e-3)
    assert PH.magnification(1000.0, f1, zeta) < 1e-4
    # finite and positive across the whole slider range at the demo configuration
    for f in np.linspace(0.5, 15.0, 300):
        h = PH.magnification(f, f1, zeta)
        assert np.isfinite(h) and h > 0


def test_P3_stiffening_raises_frequency_and_lowers_drift_there():
    n, target = 5, 3.24
    k = PH.stiffness_for(target, n)
    f0, phi0 = PH.mode_shape(PH.stiffness_matrix(k, n))
    crit = PH.critical_floor(phi0)
    f1, phi1 = PH.mode_shape(PH.stiffness_matrix(k, n, retrofit_floor=crit))
    assert f1 > f0
    assert PH.drift_profile(phi1)[crit] < PH.drift_profile(phi0)[crit]


def test_P4_beam_predictions_and_the_ratio_that_actually_validates():
    assert CAL.predict(0.20) == pytest.approx(1.569, abs=0.002)
    assert CAL.predict(0.16) == pytest.approx(2.193, abs=0.002)
    assert CAL.predict(0.12) == pytest.approx(3.376, abs=0.002)
    # The ratio is the pass/fail criterion: a constant h error swings the absolute
    # prediction +/-50% but cancels exactly here.
    assert CAL.predict(0.12) / CAL.predict(0.20) == pytest.approx((20 / 12) ** 1.5, abs=1e-4)
    thick = {"thickness_m": 0.0018}                    # 50% thicker ruler
    assert CAL.predict(0.12, **thick) / CAL.predict(0.20, **thick) == pytest.approx(
        (20 / 12) ** 1.5, abs=1e-4)


def test_P5_hazard_score_all_three_branches():
    assert hazard.compare(1 / 0.05, SPEC)["resonance_score"] == pytest.approx(0.675, abs=1e-3)
    assert hazard.compare(1 / 0.309, SPEC)["resonance_score"] == pytest.approx(1.000, abs=1e-3)
    assert hazard.compare(1 / 2.0, SPEC)["resonance_score"] == pytest.approx(0.272, abs=1e-3)
    assert hazard.compare(1 / 0.309, SPEC)["band"] == "red"
    assert hazard.compare(1 / 2.0, SPEC)["band"] == "green"


def test_P5_founders_hall_lands_on_the_plateau():
    c = hazard.compare(3.24, SPEC, "founders_hall", "4215 E Stevens Way NE")
    assert c["measured_period_s"] == pytest.approx(0.309, abs=1e-3)
    assert c["plateau_t0_s"] <= c["measured_period_s"] <= c["plateau_ts_s"]
    assert c["band"] == "red"
