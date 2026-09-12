"""The single highest-value test in the project.

Exercises the entire chain at once: timestamp-derived fs, baseline gravity
estimation, horizontal projection, onset detection, bandpass, Hann, zero-padded
rFFT, adaptive prominence, the SNR gate, parabolic interpolation. If it passes at
four frequencies on a tilted sensor, the pipeline is fundamentally right. If it
fails, nothing downstream is worth debugging yet.
"""
import pytest
from conftest import synth_session
from backend.dsp.analyse import analyse


@pytest.mark.parametrize("f_true", [1.4, 2.5, 3.2, 5.7])
def test_recovers_known_frequency(f_true):
    batches, times = synth_session(freq=f_true, damping=0.03, tilt_deg=25, noise=0.02)
    r = analyse(batches, times)
    assert r.frequency_hz == pytest.approx(f_true, rel=0.01)
    assert r.confidence in ("good", "fair")
    assert r.period_s == pytest.approx(1 / f_true, rel=0.01)


def test_fs_is_derived_not_assumed():
    # A node running at 190 Hz must be measured at 190, not assumed to be 200 —
    # every reported frequency scales linearly with fs.
    batches, times = synth_session(freq=3.2, fs=190.0)
    r = analyse(batches, times)
    assert r.fs_hz == pytest.approx(190.0, rel=0.01)
    assert r.frequency_hz == pytest.approx(3.2, rel=0.02)


def test_quiet_session_returns_null_never_a_number():
    batches, times = synth_session(mode="quiet")
    r = analyse(batches, times)
    assert r.frequency_hz is None and r.period_s is None
    assert r.frequency_uncertainty_hz is None       # no fabricated +/- either
    assert r.confidence == "poor"
    assert "no_onset" in r.confidence_flags


def test_single_trial_cannot_reach_good():
    # A single-trial coherence is degenerate, so nothing validated this reading.
    batches, times = synth_session(freq=3.2)
    r = analyse(batches, times)
    assert r.trials_used == 1
    assert r.coherence is None                      # not 1.0
    assert r.confidence == "fair"


def test_second_trial_unlocks_coherence_and_good():
    store = []
    r1 = analyse(*synth_session(freq=3.2, seed=0), trial_store=store)
    b2, t2 = synth_session(freq=3.24, seed=10)
    r2 = analyse(b2, t2, history=[r1.frequency_hz], trial_store=store)
    assert r2.trials_used == 2
    assert r2.coherence is not None
    assert r2.location_median_hz is not None
    assert r2.confidence == "good"


def test_two_sensor_amplification_recovers_the_gain_ratio():
    # conftest drives ground at 0.25x top, so transmissibility should be ~4x.
    batches, times = synth_session(freq=3.2, ground_gain=0.25)
    r = analyse(batches, times)
    assert r.channels_used == ["top", "ground"]
    assert r.amplification == pytest.approx(4.0, rel=0.15)


def test_degrades_to_top_only_when_ground_is_absent():
    batches, times = synth_session(freq=3.2, single=True)
    r = analyse(batches, times)
    assert r.frequency_hz == pytest.approx(3.2, rel=0.01)
    assert r.amplification is None and r.coherence is None
