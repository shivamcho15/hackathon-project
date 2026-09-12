"""Load a serial-capture log as a measurement, at boot, with no socket.

`firmware/recordings/` holds two 240 s captures — the Founders Hall ground and top
floor measurements. Provenance comes from each file's own "firmware" field in its
hello line, mapped through the ordinary whitelist in config.py; nothing here
special-cases it. See `firmware/recordings/README.md` for what's currently checked
in vs. pending.
"""
import json
import re
from pathlib import Path

import numpy as np

from . import config
from .dsp import project as P, onset as O
from .dsp.analyse import analyse

RECORDINGS = config.BASE_DIR.parent / "firmware" / "recordings"
DATA_RE = re.compile(r"^\[DATA\]\s*(\[.*\])\s*$")
HELLO_RE = re.compile(r"^\[HELLO\]\s*(\{.*\})\s*$")


def parse_log(path: Path):
    """Serial capture -> (samples, hello). Ignores [BOOT]/[WIFI]/[NTP]/[HEALTH]."""
    samples, hello = [], None
    for line in path.read_text(errors="replace").splitlines():
        m = DATA_RE.match(line)
        if m:
            try:
                samples.extend(json.loads(m.group(1)))
            except json.JSONDecodeError:
                continue                      # a torn serial line is not fatal
            continue
        h = HELLO_RE.match(line)
        if h and hello is None:
            try:
                hello = json.loads(h.group(1))
            except json.JSONDecodeError:
                pass
    return samples, hello


def _event_strength(samples, n=4000):
    """Peak-to-baseline envelope ratio — how clearly this channel was excited."""
    a = np.array([[s["ax"], s["ay"], s["az"]] for s in samples], dtype=float)
    if len(a) < n:
        return 0.0
    mean, g_hat = P.gravity_from_baseline(a[:600])
    env = O.rms_envelope(np.linalg.norm(P.horizontal(a, mean, g_hat), axis=1), 200.0)
    base = float(np.median(env[:600]))
    return float(env.max() / base) if base > 0 else 0.0


def _best_window(samples, fs, countdown_s, duration_s):
    """Pick the window containing the strongest excitation in the recording.

    A 240 s capture holds several stomps; a measurement is one window. Rather than
    guess an offset, run the same RMS envelope the pipeline uses and centre on the
    largest event, leaving a full countdown of quiet in front of it for the baseline.
    """
    t = np.array([s["t"] for s in samples], dtype=float)
    a = np.array([[s["ax"], s["ay"], s["az"]] for s in samples], dtype=float)
    lead = int(countdown_s * fs)
    if len(a) < lead * 3:
        return t[0], t[-1]
    mean, g_hat = P.gravity_from_baseline(a[:lead])
    env = O.rms_envelope(np.linalg.norm(P.horizontal(a, mean, g_hat), axis=1), fs)
    # Only consider onsets with room for a full countdown before and a window after.
    span = int((countdown_s + duration_s) * fs)
    lo, hi = lead, max(lead + 1, len(env) - span + lead)
    peak = int(np.argmax(env[lo:hi])) + lo
    start = max(0, peak - lead)
    return t[start], t[start] + (countdown_s + duration_s) * 1000.0


def load_recording(top="floor5_top.log", ground="floor1_ground.log",
                   location="founders_hall", address=None):
    """Analyse the committed recordings exactly as if they had arrived live."""
    chans = {}
    hello = None
    for name in (top, ground):
        p = RECORDINGS / name
        if not p.exists():
            continue
        rows, h = parse_log(p)
        if not rows:
            continue
        chans[name] = rows
        hello = hello or h
    if not chans:
        return None

    # Pick the window from whichever channel actually carries the excitation. In
    # this dataset that is GROUND: the stomp is applied at the base, so the ground
    # sensor sees the direct impulse (8x its noise floor) while the top sees only
    # the building's filtered response (2.25x). Scanning `top` finds a noise
    # maximum and the session comes back no_onset.
    # The two captures were recorded separately, and the floor-1 node never joined
    # the hotspot so it ran on a RELATIVE clock. Re-base every channel onto one
    # common epoch FIRST, then choose the window in that shared frame. Choosing it
    # in a channel's own frame and re-basing afterwards looks in the wrong place.
    common = 1_757_712_345_678
    aligned = {name: [dict(s, t=s["t"] - rows[0]["t"] + common)
                      for s in rows] for name, rows in chans.items()}

    # Pick the window from whichever channel actually carries the excitation. Here
    # that is GROUND: the stomp is applied at the base, so the ground sensor sees
    # the direct impulse (8x its noise floor) while the top sees only the building's
    # filtered response (2.25x). Scanning `top` finds a noise maximum instead.
    ref = max(aligned.values(), key=_event_strength)
    fs = P.derive_fs([s["t"] for s in ref[:2000]])
    t0, t1 = _best_window(ref, fs, config.COUNTDOWN_S, config.DURATION_S)

    batches = []
    for rows in aligned.values():
        win = [s for s in rows if t0 <= s["t"] <= t1]
        batches += [win[i:i + 20] for i in range(0, len(win), 20)]

    times = {"armed_at": int(t0), "stomp_cue_at": int(t0 + config.COUNTDOWN_S * 1000),
             "window_ends_at": int(t1)}
    source = config.SOURCE_BY_FIRMWARE.get((hello or {}).get("firmware"),
                                           config.SOURCE_DEFAULT)
    res = analyse(batches, times, "building", config.STRUCTURAL_TYPE_DEFAULT,
                  None, source)
    out = res.dict() if hasattr(res, "dict") else dict(res)
    from dataclasses import asdict
    out = asdict(res)
    out.update({"session_id": "recording", "mode": "building", "location": location,
                "address": address, "source": source,
                "recorded_at": "2026-09-12T11:45:38Z", "from_recording": True})
    return out
