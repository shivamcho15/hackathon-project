"""D1-D11: every ingest path that needs no socket. Hand-built batches, no sleeps."""
import numpy as np
import pytest
from conftest import synth_session
from backend.ingest import validate as V
from backend.state import NodeRegistry
from backend.dsp.analyse import analyse
from backend import config


def rows(n=10, t0=1_757_712_345_678, step=5, node="top"):
    return [{"t": t0 + i * step, "node": node, "ax": 0.0, "ay": 0.0, "az": 9.81}
            for i in range(n)]


def test_D1_duplicates_deduped_first_kept():
    r = rows(5)
    r.append(dict(r[2], ax=99.0))                 # same (node, t), different payload
    t, a, st = V.dedupe_sort(r)
    assert st["duplicates"] == 1 and len(t) == 5
    assert a[2][0] == 0.0                         # the FIRST one survived


def test_D2_out_of_order_sorted_without_error():
    r = rows(6)
    r[1], r[4] = r[4], r[1]
    t, _, st = V.dedupe_sort(r)
    assert list(t) == sorted(t) and st["out_of_order"] > 0


def test_D3_300ms_hole_aborts_with_a_stated_reason():
    t = np.array([0, 5, 10, 310, 315, 320], dtype=float)
    flags, abort = V.gap_flags(V.gap_stats(t))
    assert abort and "300" in abort


def test_D4_40ms_hole_flags_and_demotes_but_keeps_the_result():
    t = np.array(sorted(list(range(0, 1000, 5)) + [1040, 1045, 1050]), dtype=float)
    flags, abort = V.gap_flags(V.gap_stats(t))
    assert abort is None and "sample_gap" in flags


def test_D5_ntp_failure_disables_two_sensor_but_not_the_measurement():
    b, times = synth_session(freq=3.2)
    shift = 1_757_712_345_678 - 500_000        # before 2001 -> relative clock
    for batch in b:
        for s in batch:
            s["t"] -= shift
    times = {k: v - shift for k, v in times.items()}
    r = analyse(b, times)
    assert r.frequency_hz == pytest.approx(3.2, rel=0.02)   # single channel unaffected
    assert "no_clock_sync" in r.confidence_flags
    assert r.amplification is None and r.coherence is None


def test_D6_implausible_sample_rate_is_rejected():
    with pytest.raises(ValueError, match="implausible"):
        V.check_fs(83.0)
    assert V.check_fs(199.961) == 199.961


def test_D7_vertical_clipping_is_informational():
    g = np.array([0.0, 0.0, 1.0])
    a = np.tile([0.1, 0.1, 9.81], (50, 1))
    a[20, 2] = 19.7
    assert V.clipping_flag(a, g) == "clipping_vertical"


def test_D8_horizontal_clipping_demotes():
    g = np.array([0.0, 0.0, 1.0])
    a = np.tile([0.1, 0.1, 9.81], (50, 1))
    a[20, 0] = 19.7                               # rails the X axis, perpendicular to g
    assert V.clipping_flag(a, g) == "clipping"


def test_D9_sensor_rotating_mid_window_is_caught():
    fs = 200.0
    g = np.array([0.0, 0.0, 1.0])
    a = np.tile([0.0, 0.0, 9.81], (int(3 * fs), 1))
    th = np.radians(20)
    a[-int(fs):] = [0.0, 9.81 * np.sin(th), 9.81 * np.cos(th)]
    assert V.moved_flag(a, g, fs) == "moved_during_recording"
    assert V.moved_flag(np.tile([0.0, 0.0, 9.81], (int(3 * fs), 1)), g, fs) is None


def test_D10_two_connections_claiming_one_label_is_a_conflict():
    reg = NodeRegistry()
    reg.hello("conn-a", {"node": "top", "firmware": "stream_node"})
    reg.hello("conn-b", {"node": "top", "firmware": "stream_node"})
    assert reg.state("top") == "conflict"
    assert reg.samples("top", rows(3), conn_id="conn-b") is False   # not a 2nd channel
    # ...but a RECONNECT must not be a conflict, or a node reboot blocks arming
    reg2 = NodeRegistry()
    reg2.hello("conn-a", {"node": "top", "firmware": "stream_node"})
    reg2.release("conn-a")
    reg2.hello("conn-c", {"node": "top", "firmware": "stream_node"})
    assert reg2.state("top") != "conflict"
    assert reg2.nodes["top"]["hellos"] == 2          # counted: the watchdog's signal


def test_D11_ground_vanishing_midwindow_still_yields_a_measurement():
    b, times = synth_session(freq=3.2)
    cut = times["stomp_cue_at"] + 2000
    b = [[s for s in batch if not (s["node"] == "ground" and s["t"] > cut)] for batch in b]
    r = analyse([x for x in b if x], times)
    assert r.frequency_hz == pytest.approx(3.2, rel=0.01)   # the measurement survives
    assert r.channels_used == ["top"]
    assert "ground_lost_midrun" in r.confidence_flags
    assert r.amplification is None


def test_provenance_whitelist_never_defaults_to_hardware():
    reg = NodeRegistry()
    for fw, expect in [("stream_node", "hardware"), ("fake_node", "simulated"),
                       ("replay_node", "replay"), ("weird", "unknown"), (None, "unknown")]:
        reg.hello(f"c-{fw}", {"node": f"n-{fw}", "firmware": fw})
        assert reg.nodes[f"n-{fw}"]["source"] == expect
