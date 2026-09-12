"""PROTOCOL rules as pure functions."""
import pytest
from backend.dsp import trials as T


def test_T1_agreeing_trials_take_no_penalty():
    f = [3.19, 3.24, 3.31]
    med, n = T.median_frequency(f)
    assert med == pytest.approx(3.24) and n == 3
    level, spread = T.spread_level(f)
    assert spread == pytest.approx(0.0216, abs=1e-3) and level == "good"


def test_T2_failed_trials_are_excluded_never_averaged_as_zero():
    med, n = T.median_frequency([3.19, None, 3.31])
    assert med == pytest.approx(3.25) and n == 2


def test_T3_moderate_spread_caps_at_fair():
    assert T.spread_level([3.0, 3.3, 3.6])[0] == "fair"


def test_T4_wide_spread_caps_at_poor():
    assert T.spread_level([2.5, 3.2, 4.1])[0] == "poor"


def test_T5_final_confidence_is_worst_of_not_averaged():
    assert T.combine("good", [2.5, 3.2, 4.1]) == "poor"
    assert T.combine("poor", [3.19, 3.24, 3.31]) == "poor"


def test_T6_single_trial_caps_at_fair():
    assert T.combine("good", [3.24]) == "fair"
    assert T.combine("good", [3.19, 3.24]) == "good"


def test_uncertainty_prefers_measured_spread_over_the_heuristic():
    multi = T.uncertainty([3.19, 3.24, 3.31], half_power_bw=0.5)
    assert multi == pytest.approx(0.0603, abs=1e-3)        # the real stdev
    single = T.uncertainty([3.24], half_power_bw=0.5)
    assert single == pytest.approx(0.25)                   # 0.5 * bandwidth
    assert T.uncertainty([3.24], half_power_bw=0.01) == 0.03   # the hard floor
    assert T.uncertainty([None], half_power_bw=None) is None
