"""Synthetic sessions with a KNOWN answer — the ground truth Gate 1 grades against.

Deliberately hostile in the ways the real sensor is: gravity sits on a tilted axis
(so no raw axis is horizontal), the sway is linearly polarised (the case that makes
the rectification bug produce exactly 2x), and the two channels differ in gain.
"""
import numpy as np
import pytest

FS = 200.0
COUNTDOWN_S = 3.0
DURATION_S = 12.0


def _frame(tilt_deg, psi_deg=30.0):
    """Gravity direction at `tilt_deg` from vertical, plus a sway direction in the
    genuine horizontal plane. No raw axis is horizontal, which is the point."""
    t = np.radians(tilt_deg)
    g_hat = np.array([0.0, np.sin(t), np.cos(t)])
    e1 = np.array([1.0, 0.0, 0.0])                 # already perpendicular to g_hat
    e2 = np.cross(g_hat, e1)
    e2 /= np.linalg.norm(e2)
    p = np.radians(psi_deg)
    return g_hat, np.cos(p) * e1 + np.sin(p) * e2


def synth_signal(freq=3.2, damping=0.03, tilt_deg=25.0, noise=0.02, amp=0.30,
                 gain=1.0, mode="stomp", fs=FS, seed=0):
    """Return (t_ms, a[n,3]) for one channel over the full 15 s buffer."""
    rng = np.random.default_rng(seed)
    n = int(round((COUNTDOWN_S + DURATION_S) * fs))
    t = np.arange(n) / fs
    g_hat, sway_dir = _frame(tilt_deg)

    a = np.tile(9.81 * g_hat, (n, 1)) + rng.normal(0, noise, (n, 3))

    onset_s = COUNTDOWN_S + 0.35                    # a human stomps just after the cue
    k = t >= onset_s
    if mode == "stomp":
        tau = 1.0 / (2 * np.pi * damping * freq)
        env = np.zeros(n)
        env[k] = amp * gain * np.exp(-(t[k] - onset_s) / tau)
        a += env[:, None] * sway_dir * np.sin(2 * np.pi * freq * (t - onset_s))[:, None]
    elif mode == "noisy":
        # Real motion, no resonance: a broadband burst 8x the resting noise floor.
        burst = rng.normal(0, noise * 8 * gain, (n, 3))
        a[k] += burst[k]
    elif mode == "quiet":
        pass                                        # nobody stomped
    else:
        raise ValueError(mode)

    t0 = 1_757_712_345_678
    return (t0 + (t * 1000).round().astype(np.int64)), a


def synth_session(freq=3.2, damping=0.03, tilt_deg=25.0, noise=0.02, amp=0.30,
                  mode="stomp", ground_gain=0.25, single=False, fs=FS, seed=0):
    """Wire-format batches for both channels plus the session's absolute times.

    ground_gain 0.25 gives the ~4x top/ground ratio the real building shows.
    """
    chans = [("top", 1.0, seed)] + ([] if single else [("ground", ground_gain, seed + 1)])
    batches, t0 = [], None
    for node, gain, sd in chans:
        t_ms, a = synth_signal(freq, damping, tilt_deg, noise, amp, gain, mode, fs, sd)
        t0 = int(t_ms[0])
        for i in range(0, len(t_ms), 20):
            batches.append([
                {"t": int(tt), "node": node, "ax": float(r[0]), "ay": float(r[1]), "az": float(r[2])}
                for tt, r in zip(t_ms[i:i + 20], a[i:i + 20])
            ])
    times = {"armed_at": t0,
             "stomp_cue_at": t0 + int(COUNTDOWN_S * 1000),
             "window_ends_at": t0 + int((COUNTDOWN_S + DURATION_S) * 1000)}
    return batches, times


@pytest.fixture
def session():
    return synth_session
