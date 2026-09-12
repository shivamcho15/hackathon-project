"""The only test here that is NOT a closed loop.

Every other test grades this pipeline against conftest.py — a generator written by
the same author as the analyser, so a shared wrong assumption passes silently.
firmware/tools/fake_node.py was written independently by Saahil, and it is harder
in two ways conftest is not:

  * gravity is tilted at a RANDOM azimuth, not a fixed one;
  * every stomp carries a 2.5x vertical impact transient at 18 Hz (tau = 0.08 s),
    which sits inside the 25 Hz bandpass edge. If the gravity projection leaks, it
    reaches the spectrum.

It also uses a decaying broadband burst for --mode noisy, so the decay gate cannot
be what rejects it — prominence has to.
"""
import importlib.util
import random
from pathlib import Path

import pytest

from backend.dsp.analyse import analyse

GEN = Path(__file__).resolve().parents[1] / "firmware" / "tools" / "fake_node.py"
pytestmark = pytest.mark.skipif(not GEN.exists(), reason="fake_node.py not present")

FS, COUNTDOWN_S, DURATION_S = 200.0, 3.0, 12.0
GROUND_GAIN, TOP_GAIN = 0.28, 1.15          # as fake_node's own run() sets them


def _fake_node_module():
    spec = importlib.util.spec_from_file_location("fake_node_gen", GEN)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)               # `websockets` is imported lazily in run()
    return m


def session(freq, mode="stomp", damping=0.03, tilt=25.0, noise=0.02,
            single=False, seed=0, fs=FS, stomp_offset=0.35):
    fn = _fake_node_module()
    random.seed(seed)                        # pin the random azimuth
    nodes = [fn.FakeNode("ground", GROUND_GAIN, freq, damping, tilt, mode, noise)]
    if not single:
        nodes.append(fn.FakeNode("top", TOP_GAIN, freq, damping, tilt, mode, noise))

    n, t0, batches = int((COUNTDOWN_S + DURATION_S) * fs), 1_757_712_345.678, []
    for nd in nodes:
        nd.last_stomp = t0 + COUNTDOWN_S + stomp_offset
        rows = [dict(zip(("ax", "ay", "az"), nd.sample(t0 + i / fs)))
                | {"t": int(round((t0 + i / fs) * 1000)), "node": nd.name}
                for i in range(n)]
        batches += [rows[i:i + 20] for i in range(0, len(rows), 20)]
    times = {"armed_at": int(t0 * 1000),
             "stomp_cue_at": int((t0 + COUNTDOWN_S) * 1000),
             "window_ends_at": int((t0 + COUNTDOWN_S + DURATION_S) * 1000)}
    return batches, times


@pytest.mark.parametrize("f_true", [1.4, 2.5, 3.2, 5.7])
@pytest.mark.parametrize("seed", [0, 1, 2])
def test_recovers_known_frequency_from_the_other_generator(f_true, seed):
    r = analyse(*session(f_true, seed=seed))
    assert r.frequency_hz == pytest.approx(f_true, rel=0.01)
    assert r.confidence in ("good", "fair")


def test_vertical_impact_transient_is_projected_out():
    """The 18 Hz transient is 2.5x the sway amplitude and inside the filter band.
    If it reached the spectrum it would dominate, or at least flag near_ceiling."""
    r = analyse(*session(3.2))
    assert r.frequency_hz == pytest.approx(3.2, rel=0.01)
    assert "near_ceiling" not in r.confidence_flags


@pytest.mark.parametrize("seed", [0, 1, 2, 3])
def test_quiet_and_noisy_never_invent_a_frequency(seed):
    assert analyse(*session(3.2, mode="quiet", seed=seed)).frequency_hz is None
    # Decaying broadband burst: the decay gate CANNOT reject this one.
    assert analyse(*session(3.2, mode="noisy", seed=seed)).frequency_hz is None


def test_amplification_tracks_the_generators_own_gain_ratio():
    r = analyse(*session(3.2))
    assert r.amplification == pytest.approx(TOP_GAIN / GROUND_GAIN, rel=0.15)


def test_ground_only_still_measures_and_says_so():
    r = analyse(*session(3.2, single=True))
    assert r.frequency_hz == pytest.approx(3.2, rel=0.01)
    assert r.channels_used == ["ground"]
    assert "single_node_ground" in r.confidence_flags
    assert r.confidence == "fair"            # capped, per the guard rules


def test_at_the_real_measured_hardware_rate():
    """Hardware holds 199.961 Hz, not 200. Integer-ms timestamps must still derive
    it closely enough that the reported frequency is unaffected."""
    r = analyse(*session(3.2, fs=199.961))
    assert r.fs_hz == pytest.approx(199.961, rel=0.005)
    assert r.frequency_hz == pytest.approx(3.2, rel=0.01)


@pytest.mark.parametrize("offset", [-0.4, 0.0, 2.0, 6.0])
def test_stomp_timing_within_the_window_is_found_automatically(offset):
    """Onset detection finds the real moment: an eager stomper 0.4 s before the cue
    through to someone 6 s late. This is why the protocol does not require precise
    timing from the person stomping."""
    r = analyse(*session(3.2, stomp_offset=offset))
    assert r.frequency_hz == pytest.approx(3.2, rel=0.02)
