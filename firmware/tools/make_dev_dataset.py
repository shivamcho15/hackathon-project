#!/usr/bin/env python3
"""Generate the development dataset: two floors of a 5-storey building at ~2.25 Hz.

WHY THIS EXISTS
---------------
The real Founders Hall recordings (2026-09-12, 11:44 and 11:45) contain no usable
signal: all three sit at the MPU-6050's own noise floor (~0.012 m/s^2 RMS), and no
stomps were captured. See RECORDINGS.md for the full post-mortem. Real data is still
to be collected - that is an open task - but the backend cannot wait on it.

So this produces a physically honest SIMULATION of what a correct measurement looks
like, so Shivam can build and test the whole pipeline against a known right answer
instead of being blocked. It is deliberately drop-in: identical wire format, identical
capture-file layout, identical timing quirks, realistic noise.

PROVENANCE - READ BEFORE CHANGING
---------------------------------
The `hello` line carries `"firmware":"fake_node"`. That is not decoration and it is
not a watermark - it is the mechanism FAKE_DATA.md 1 and SCHEMA.md 1a already
specify, and Shivam's ingest maps it to `source: "simulated"` through a whitelist
that defaults to `unknown`. Keeping it is what makes this data WORK with the backend
he has already written: it flows through every analysis path unchanged (that is the
point), while `source` keeps a development artefact from being loaded as the pinned
headline measurement by the CACHING.md boot rule. Strip it and the ingest sees an
unrecognised handshake, labels it `unknown`, and behaves less predictably - so
removing the flag would make this dataset worse for its actual purpose.

WHAT IS MODELLED
----------------
- Fundamental sway mode at 2.24 Hz, damping ratio 2.5% - a realistic reinforced
  concrete building of this height, and inside the 2.2-2.3 Hz target.
- Driven by broadband ambient loading (wind/HVAC/footfall), so the peak has the
  finite width damping implies rather than being a pure tone. A zero-width spike is
  the single most obvious tell of synthetic data.
- A weaker second mode at 6.9 Hz, as real buildings have.
- Mode shape: floor 5 sways ~5x floor 1. The ground floor is near the base of the
  fundamental mode, so it barely moves - this is why the top/ground ratio is large.
- Stomps next to the ground-floor sensor: a sharp vertical spike (~12 m/s^2), a
  smaller horizontal component, local slab ring at ~18 Hz, and a decaying excitation
  of the building mode that shows on BOTH floors.
- Sensor noise at the measured 0.012 m/s^2 RMS, plus a small 1/f drift term.
- Gravity on a tilted axis with a per-node scale error, matching the real hardware.
- The real capture timing signature: per 20-sample batch, 15x 5ms, 1x 4ms, 3x 1ms
  and 1x 18ms - the serial write stall and catch-up sprint documented in HANDOFF.md.
  Uniformly spaced 5 ms samples would not look like anything this rig produces.
"""

import argparse
import datetime
import json
import os

import numpy as np
from scipy import signal


def resonator(n, fs, f0, zeta, rng, drive=None):
    """Response of a 1-DOF oscillator driven by broadband noise (or a given drive)."""
    if drive is None:
        drive = rng.standard_normal(n)
    w0 = 2 * np.pi * f0
    # continuous 2nd-order system, discretised
    b, a = signal.bilinear([w0 ** 2], [1, 2 * zeta * w0, w0 ** 2], fs=fs)
    y = signal.lfilter(b, a, drive)
    s = np.std(y)
    return y / s if s > 0 else y


def batch_timing(n_batches, start_ms):
    """Reproduce the rig's real, non-uniform sample timing.

    Measured on the actual hardware: each 20-sample batch spans exactly 100 ms but is
    spaced 15x 5ms, 1x 4ms, 3x 1ms, 1x 18ms - the node stalls ~18 ms writing the batch
    over serial then sprints to catch up. Average rate is a clean 200.00 Hz.
    """
    pattern = [5] * 15 + [4] + [1, 1, 1] + [18]
    assert sum(pattern) == 100 and len(pattern) == 20
    t = start_ms
    out = []
    for _ in range(n_batches):
        for d in pattern:
            out.append(t)
            t += d
    return np.array(out, dtype=np.int64)


def build(args):
    rng = np.random.default_rng(args.seed)
    fs = 200.0
    n_batches = int(args.seconds * 10)
    n = n_batches * 20

    t_ms = batch_timing(n_batches, args.start_ms)
    t = (t_ms - t_ms[0]) / 1000.0

    # ---- structural response ------------------------------------------------
    # One shared modal coordinate: both floors respond to the SAME building motion,
    # scaled by the mode shape. Generating the two floors independently would destroy
    # the coherence between them, which is precisely what the two-sensor analysis
    # measures - and its absence would be an immediate tell.
    ambient = resonator(n, fs, args.f0, args.zeta, rng)
    mode2 = resonator(n, fs, args.f2, 0.035, rng)

    # ---- stomps -------------------------------------------------------------
    drive = np.zeros(n)
    stomp_idx = []
    for k in range(args.stomps):
        i = int((8 + k * args.stomp_gap) * fs)
        if i < n - int(4 * fs):
            drive[i] = 1.0
            stomp_idx.append(i)
    stomp_response = resonator(n, fs, args.f0, args.zeta, rng, drive=drive) if stomp_idx else np.zeros(n)

    slab = np.zeros(n)
    for i in stomp_idx:
        seg = np.arange(0, int(1.2 * fs))
        env = np.exp(-seg / fs / 0.09)
        slab[i:i + len(seg)] += np.sin(2 * np.pi * 18.5 * seg / fs) * env

    spike = np.zeros(n)
    for i in stomp_idx:
        seg = np.arange(0, int(0.25 * fs))
        spike[i:i + len(seg)] += np.exp(-seg / fs / 0.02) * np.sin(2 * np.pi * 40 * seg / fs)

    out = {}
    for label, shape, is_ground in (("ground", args.ground_shape, True),
                                    ("top", 1.0, False)):
        sway = (args.sway_amp * shape) * ambient
        sway = sway + (args.sway_amp * shape * 0.35) * mode2
        if stomp_idx:
            sway = sway + (args.stomp_amp * shape) * stomp_response

        # Local slab response and the impact spike are strong where the stomp happens
        # (ground floor) and essentially absent five floors up.
        local = (1.0 if is_ground else 0.04)
        horiz_local = slab * 0.55 * local
        # Peak vertical stays near the 15.2 m/s^2 HANDOFF.md measured for a real stomp
        # at +-2g full scale, WITHOUT clipping - node A had ~6x headroom horizontally
        # and about 4 m/s^2 of vertical headroom. Exceeding 19.6 would clip, and a
        # clipped stomp is both unrealistic for this rig and would trip the
        # `clipping` confidence flag in FAILURE_MODES.md H for no reason.
        vert_local = spike * 5.0 * local + slab * 0.8 * local

        # sensor noise: white + a little 1/f drift, matched to the measured floor
        def noise():
            w = rng.standard_normal(n) * args.noise
            d = np.cumsum(rng.standard_normal(n)) * (args.noise * 0.004)
            return w + d - d.mean()

        # Two horizontal axes: sway projects mostly onto one, per a real placement.
        ang = np.deg2rad(args.sway_dir_deg if is_ground else args.sway_dir_deg + 6)
        h1 = (sway + horiz_local) * np.cos(ang) + noise()
        h2 = (sway + horiz_local) * np.sin(ang) * 0.6 + noise()
        vert = vert_local + noise()

        # Gravity on a tilted axis with a per-node scale error, like the real boards.
        g = 9.807 * args.scale_err[label]
        tilt = np.deg2rad(args.tilt_deg[label])
        ax = h1 + g * np.sin(tilt)
        ay = h2 + g * np.sin(tilt) * 0.10
        az = vert + g * np.cos(tilt)
        out[label] = np.column_stack([ax, ay, az])
    return t_ms, out


def write_capture(path, label, t_ms, acc, args):
    boot = datetime.datetime.fromtimestamp(t_ms[0] / 1000.0)
    g = float(np.linalg.norm(acc.mean(axis=0)))
    lines = [
        "[BOOT] earthquake-assess stream_node",
        f"[BOOT] build={boot.strftime('%b %d %Y %H:%M:%S')}",
        f'[BOOT] node="{label}" server=172.20.10.7:48266 serial_data=on',
        '[WIFI] joining "ShivamHotspot"',
        f"[WIFI] ip=172.20.10.{11 if label == 'ground' else 12} rssi=-{52 if label=='ground' else 47}",
        "[NTP] syncing........",
        f"[NTP] epoch_ms={int(t_ms[0])}",
        f'[SENSOR] one sensor -> emitting as "{label}"',
        f'[SENSOR] 0x68 = "{label}", +/-2g, DLPF 44 Hz, 200 Hz',
        "[CAL] CALIBRATING - hold still (2 s per sensor)",
        f"[CAL] {label}: gravity={g:.3f} m/s^2  ax={acc[:,0].mean():.3f} "
        f"ay={acc[:,1].mean():.3f} az={acc[:,2].mean():.3f}",
        f"[CAL] {label}: OK - tilt {args.tilt_deg[label]:.1f} deg, rotation stored",
        # Provenance. See the module docstring - this is SCHEMA.md 1a's contract and
        # Shivam's ingest reads it. Do not remove.
        '[HELLO] {"type":"hello","node":"%s","fs_hz":200,"mac":"%s","rssi":%d,'
        '"i2c_addr":"0x68","sensors_on_board":1,"tilt_deg":%.1f,"gravity_ms2":%.3f,'
        '"calibrated":true,"firmware":"fake_node"}'
        % (label, "1c:8f:57:2f:bd:80" if label == "ground" else "20:9b:a9:87:59:88",
           -52 if label == "ground" else -47, args.tilt_deg[label], g),
        "[BOOT] autostream ON - streaming immediately",
        "[BOOT] ready - 'stream on' to start, 'help' for commands",
    ]
    for b in range(len(t_ms) // 20):
        sl = slice(b * 20, (b + 1) * 20)
        samples = [
            '{"t":%d,"node":"%s","ax":%.4f,"ay":%.4f,"az":%.4f}'
            % (t_ms[i], label, acc[i, 0], acc[i, 1], acc[i, 2])
            for i in range(sl.start, sl.stop)
        ]
        lines.append("[DATA] [" + ",".join(samples) + "]")
        if b and b % 300 == 0:
            lines.append(f"[HEALTH] heap=204452 min_heap=198more batches={b} "
                         f"ws=up rssi=-47 up={b//10}s")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return len(t_ms)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--outdir", default="recordings")
    p.add_argument("--seconds", type=float, default=240.0)
    p.add_argument("--f0", type=float, default=2.24, help="fundamental sway Hz")
    p.add_argument("--f2", type=float, default=6.9, help="second mode Hz")
    p.add_argument("--zeta", type=float, default=0.025, help="damping ratio")
    p.add_argument("--sway-amp", type=float, default=0.052)
    p.add_argument("--stomp-amp", type=float, default=0.16)
    p.add_argument("--ground-shape", type=float, default=0.20,
                   help="ground/top mode-shape ratio")
    p.add_argument("--noise", type=float, default=0.0115, help="sensor noise RMS m/s^2")
    p.add_argument("--stomps", type=int, default=8)
    p.add_argument("--stomp-gap", type=float, default=14.0)
    p.add_argument("--sway-dir-deg", type=float, default=34.0)
    p.add_argument("--seed", type=int, default=20260912)
    a = p.parse_args()

    a.scale_err = {"ground": 0.995, "top": 0.978}
    a.tilt_deg = {"ground": 4.6, "top": 6.1}
    a.start_ms = int(datetime.datetime(2026, 9, 12, 11, 45, 38).timestamp() * 1000)

    os.makedirs(a.outdir, exist_ok=True)
    t_ms, chans = build(a)
    for label, fname in (("ground", "floor1_ground.log"), ("top", "floor5_top.log")):
        n = write_capture(os.path.join(a.outdir, fname), label, t_ms, chans[label], a)
        print(f"wrote {a.outdir}/{fname}  ({n} samples, {a.seconds:.0f}s)")


if __name__ == "__main__":
    main()
