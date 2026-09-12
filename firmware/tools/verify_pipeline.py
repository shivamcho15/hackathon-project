#!/usr/bin/env python3
"""Reference implementation of the PIPELINE.md analysis, used to check data.

Not the product - Shivam's backend is. This exists so the hardware side can prove
its own output is analysable without waiting on the backend, and so the fake
generator can be checked against a known answer.

It follows PIPELINE.md as written: baseline gravity removal, data-driven vertical
axis identification, onset detection, Butterworth bandpass, PCA projection onto the
dominant horizontal direction, Hann window, zero-padded rFFT, peak with adaptive
prominence, parabolic interpolation.

  python fake_node.py --stdout --freq 3.2 > data.jsonl
  python verify_pipeline.py data.jsonl --expect 3.2
"""

from __future__ import annotations

import argparse
import json
import sys

import numpy as np
from scipy.signal import butter, filtfilt, find_peaks


def load(path: str, node: str):
    """Read batched JSON lines, keep one node, return (t_seconds, Nx3 accel).

    Accepts both transports without being told which it is given:

      * WebSocket capture (test_server.py --out) - bare `[{...},{...}]` per line.
      * USB serial capture (`serial on`, capture_serial.py) - the same batch behind
        a `[DATA] ` prefix, interleaved with `[BOOT]`/`[HEALTH]`/`[HELLO]` log lines
        and, on a reset, binary ROM-bootloader garbage.

    The serial transport is the one that matters for a multi-floor building
    measurement, where WiFi cannot reach across five floors of concrete - so it has
    to be analysable, not just capturable. Malformed lines are skipped rather than
    raised on: a capture that is 99 % good is still a measurement, and a truncated
    final line is normal when a capture is stopped by its timer.
    """
    rows = []
    skipped = 0
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if line.startswith("[DATA] "):
                line = line[len("[DATA] "):].strip()
            if not line.startswith("[") or not line.endswith("]"):
                continue
            try:
                batch = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                skipped += 1
                continue
            if not isinstance(batch, list):
                continue
            for s in batch:
                try:
                    if s["node"] == node:
                        rows.append((s["t"], s["ax"], s["ay"], s["az"]))
                except (TypeError, KeyError):
                    skipped += 1
    if skipped:
        print(f"{node:7s}: note - skipped {skipped} malformed line(s)/sample(s)")
    if not rows:
        return None, None
    rows.sort(key=lambda r: r[0])
    a = np.array(rows, dtype=float)
    return (a[:, 0] - a[0, 0]) / 1000.0, a[:, 1:]


def analyse(t, acc, fs, fmin=0.5, fmax=15.0):
    n = len(acc)
    if n < 600:
        return {"error": f"only {n} samples"}

    # Baseline = first second, assumed quiet. PIPELINE.md §5 uses this one segment
    # three times: gravity removal, vertical-axis ID, and the onset threshold.
    nb = int(fs)
    base = acc[:nb].mean(axis=0)
    vert = int(np.argmax(np.abs(base)))
    horiz = [i for i in range(3) if i != vert]
    d = acc - base

    # Onset: first crossing of 6x the baseline RMS envelope.
    env = np.sqrt(np.mean(d[:, horiz] ** 2, axis=1))
    k = max(1, int(0.25 * fs))
    smooth = np.convolve(env, np.ones(k) / k, mode="same")
    base_rms = smooth[:nb].mean()
    idx = np.where(smooth > 6 * base_rms)[0]
    if len(idx) == 0:
        return {"frequency_hz": None, "reason": "no onset detected", "vertical_axis": "XYZ"[vert]}
    onset = max(0, idx[0] - int(0.1 * fs))
    seg = d[onset:onset + int(8 * fs)]
    if len(seg) < int(3 * fs):
        return {"frequency_hz": None, "reason": "too little data after onset"}

    b, a = butter(4, [0.3 / (fs / 2), 25.0 / (fs / 2)], btype="band")
    seg = filtfilt(b, a, seg, axis=0)

    # PCA onto the dominant horizontal direction -> one phase-preserving scalar.
    h = seg[:, horiz]
    w, v = np.linalg.eigh(np.cov(h.T))
    s = h @ v[:, np.argmax(w)]

    win = s * np.hanning(len(s))
    N = 8192
    spec = np.abs(np.fft.rfft(win, N))
    freqs = np.fft.rfftfreq(N, 1 / fs)

    band = (freqs >= fmin) & (freqs <= fmax)
    mag, fb = spec[band], freqs[band]
    med = np.median(mag)
    peaks, _ = find_peaks(mag, prominence=3 * med)
    if len(peaks) == 0:
        return {"frequency_hz": None, "reason": "no peak cleared prominence",
                "vertical_axis": "XYZ"[vert]}

    pk = peaks[np.argmax(mag[peaks])]
    f = fb[pk]
    # Parabolic interpolation on log-magnitude for sub-bin accuracy.
    if 0 < pk < len(mag) - 1:
        y0, y1, y2 = np.log(mag[pk - 1: pk + 2] + 1e-30)
        denom = y0 - 2 * y1 + y2
        if denom != 0:
            f = fb[pk] + 0.5 * (y0 - y2) / denom * (fb[1] - fb[0])

    return {
        "frequency_hz": round(float(f), 4),
        "period_s": round(1.0 / float(f), 4),
        "vertical_axis": "XYZ"[vert],
        "prominence_ratio": round(float(mag[pk] / med), 1),
        "n_samples": int(len(seg)),
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("path")
    p.add_argument("--expect", type=float, help="ground-truth frequency, if known")
    p.add_argument("--tolerance", type=float, default=2.0, help="percent")
    args = p.parse_args()

    ok = True
    for node in ("ground", "top"):
        t, acc = load(args.path, node)
        if t is None:
            print(f"{node:7s}: no data")
            continue
        # Derived from timestamps, not assumed to be 200 - firmware/README.md.
        # Guard the degenerate case explicitly: duplicate timestamps give a median
        # delta of 0 and an infinite fs, which is a data bug worth naming rather
        # than a crash to debug later.
        dt = float(np.median(np.diff(t)))
        if dt <= 0:
            print(f"{node:7s}: BAD DATA - median sample spacing is {dt}s "
                  f"(duplicate timestamps); cannot derive fs")
            ok = False
            continue
        fs = 1.0 / dt
        r = analyse(t, acc, fs)
        got = r.get("frequency_hz")
        line = f"{node:7s}: fs={fs:.2f} Hz  " + "  ".join(f"{k}={v}" for k, v in r.items())
        if args.expect and got:
            err = abs(got - args.expect) / args.expect * 100
            verdict = "PASS" if err <= args.tolerance else "FAIL"
            ok &= err <= args.tolerance
            line += f"   [{verdict}] {err:.2f}% from {args.expect} Hz"
        elif args.expect and not got:
            ok = False
            line += f"   [no frequency]"
        print(line)

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
