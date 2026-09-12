#!/usr/bin/env python3
"""Find a building's natural sway frequency from AMBIENT vibration.

Why this exists alongside verify_pipeline.py
--------------------------------------------
verify_pipeline.py implements PIPELINE.md: detect a stomp, analyse the ringdown.
That is the right method for the model towers and for a table demo, where a stomp
genuinely dominates the response.

It is the wrong method for a real five-storey building. A person's stomp is a few
hundred joules against thousands of tonnes of concrete; it excites the local floor
slab (~15-25 Hz) far more than the building's sway mode (~2 Hz), and five floors
away it does not arrive as a detectable impulse at all. Run against the Founders
Hall floor-5 recording, verify_pipeline correctly reports "no onset detected".

What actually excites a building's fundamental mode continuously is ambient
loading - wind, HVAC, traffic, people walking. It is broadband and always present,
so the structure is permanently ringing at its own natural frequency at very small
amplitude. Averaging a long record pulls that peak out of the noise. This is
standard practice for real structures (ambient/operational modal analysis), not a
fallback.

Method
------
1. Identify the vertical axis from the mean acceleration (gravity).
2. Work with the two HORIZONTAL axes - a building sways sideways.
3. Remove the mean, detrend, and high-pass above 0.3 Hz to kill sensor drift.
4. Welch PSD with long segments, so the frequency resolution is fine enough to
   separate a ~2 Hz peak from DC.
5. Report peaks in the plausible band, ranked by prominence over the local floor.

The number to trust is a peak that appears on BOTH horizontal axes and on BOTH
floors, since a building's fundamental mode is a property of the structure and must
show up wherever you put a sensor on it.
"""

import argparse
import json
import sys

import numpy as np

try:
    from scipy import signal
except ImportError:
    sys.exit("scipy is needed:  pip install scipy")


def load(path, node=None):
    rows, skipped = [], 0
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if line.startswith("[DATA] "):
                line = line[len("[DATA] "):].strip()
            if not (line.startswith("[") and line.endswith("]")):
                continue
            try:
                batch = json.loads(line)
            except Exception:
                skipped += 1
                continue
            if not isinstance(batch, list):
                continue
            for s in batch:
                try:
                    if node is None or s["node"] == node:
                        rows.append((s["t"], s["ax"], s["ay"], s["az"], s["node"]))
                except (TypeError, KeyError):
                    skipped += 1
    if not rows:
        return None, None, None, skipped
    rows.sort(key=lambda r: r[0])
    labels = sorted({r[4] for r in rows})
    a = np.array([(r[0], r[1], r[2], r[3]) for r in rows], dtype=float)
    return a[:, 0], a[:, 1:], labels, skipped


def analyse(t_ms, acc, label, fmin=0.4, fmax=8.0, seg_s=60.0):
    n = len(t_ms)
    dt = np.median(np.diff(t_ms)) / 1000.0
    if dt <= 0:
        print(f"  BAD DATA: median sample spacing {dt}s")
        return None
    fs = 1.0 / dt
    dur = (t_ms[-1] - t_ms[0]) / 1000.0

    gaps = np.sum(np.diff(t_ms) > 15)
    mean = acc.mean(axis=0)
    vert = int(np.argmax(np.abs(mean)))
    horiz = [i for i in (0, 1, 2) if i != vert]
    g = np.linalg.norm(mean)

    print(f"\n=== {label} ===")
    print(f"  {n} samples, {dur:.1f}s, fs={fs:.2f} Hz, gaps>15ms: {gaps}")
    print(f"  gravity {g:.3f} m/s^2 ({(g-9.807)/9.807*100:+.1f}% vs 9.807), "
          f"vertical axis = {'XYZ'[vert]}")

    clip = int(np.sum(np.abs(acc) > 19.0))
    if clip:
        print(f"  ⚠ {clip} samples near +-2g full scale (possible clipping)")

    # ---- resample onto a uniform grid before any spectral work -----------------
    # The node does not sample uniformly. Per 20-sample batch the real spacing is
    # 15x 5ms, 1x 4ms, 3x 1ms and 1x 18ms - it stalls ~18 ms writing the batch out
    # over the serial cable (a ~1.9 kB batch at 921600 baud is ~20 ms), then sprints
    # at ~1 kHz to catch up. It sums to exactly 100 ms, so the AVERAGE rate is a
    # clean 200.00 Hz and nothing is lost - but Welch assumes evenly spaced samples,
    # and feeding it a stall-then-sprint pattern that repeats at exactly 10 Hz
    # smears real peaks and can manufacture artefacts.
    #
    # The timestamps are honest about when each sample was actually taken, so linear
    # interpolation onto a true 200 Hz grid recovers the uniform series. This is a
    # correction, not a cleanup: it uses measured time, it invents nothing.
    t_s = (t_ms - t_ms[0]) / 1000.0
    grid = np.arange(0.0, t_s[-1], dt)
    acc_u = np.column_stack([np.interp(grid, t_s, acc[:, k]) for k in range(3)])
    print(f"  resampled {len(acc)} irregular -> {len(grid)} uniform samples at "
          f"{1/dt:.2f} Hz")
    acc = acc_u

    # Long segments so a ~2 Hz peak is well separated from DC. 60 s -> 0.017 Hz bins.
    nper = int(min(len(acc), seg_s * fs))
    results = {}
    for i in horiz:
        x = signal.detrend(acc[:, i], type="linear")
        # High-pass: below ~0.3 Hz is thermal drift and tilt, not structure.
        sos = signal.butter(4, 0.3, btype="highpass", fs=fs, output="sos")
        x = signal.sosfiltfilt(sos, x)
        f, p = signal.welch(x, fs=fs, nperseg=nper, noverlap=nper // 2,
                            window="hann", detrend="linear")
        band = (f >= fmin) & (f <= fmax)
        fb, pb = f[band], p[band]
        # Prominence relative to the LOCAL noise floor (median of the band), which is
        # what PIPELINE.md 9 uses - an absolute threshold would not transfer between
        # a quiet stairwell and a busy lobby.
        floor = np.median(pb)
        peaks, _ = signal.find_peaks(pb, height=floor * 3.0)
        order = np.argsort(pb[peaks])[::-1]
        top = [(fb[peaks[k]], pb[peaks[k]] / floor) for k in order[:5]]
        results["XYZ"[i]] = (fb, pb, floor, top)
        print(f"  axis {'XYZ'[i]} (horizontal): top peaks in {fmin}-{fmax} Hz")
        if not top:
            print("      none cleared 3x the local noise floor")
        for fr, pr in top:
            print(f"      {fr:6.3f} Hz   {pr:5.1f}x floor")
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--fmin", type=float, default=0.4)
    ap.add_argument("--fmax", type=float, default=8.0)
    ap.add_argument("--seg", type=float, default=60.0, help="Welch segment seconds")
    a = ap.parse_args()

    all_res = {}
    for path in a.files:
        t, acc, labels, skipped = load(path)
        if t is None:
            print(f"{path}: no data")
            continue
        if skipped:
            print(f"{path}: skipped {skipped} malformed line(s)")
        for lab in labels:
            t2, acc2, _, _ = load(path, node=lab)
            r = analyse(t2, acc2, f"{lab}  ({path})", a.fmin, a.fmax, a.seg)
            if r:
                all_res[lab] = r

    # A real structural mode appears on both horizontal axes, and on both floors.
    print("\n=== candidates consistent across axes/floors ===")
    cands = {}
    for lab, res in all_res.items():
        for ax, (_, _, _, top) in res.items():
            for fr, pr in top:
                key = round(fr, 1)
                cands.setdefault(key, []).append((lab, ax, fr, pr))
    if not cands:
        print("  none")
    for key in sorted(cands, key=lambda k: -len(cands[k])):
        hits = cands[key]
        who = ", ".join(f"{l}/{ax}" for l, ax, _, _ in hits)
        mean_f = np.mean([fr for _, _, fr, _ in hits])
        best = max(pr for _, _, _, pr in hits)
        print(f"  ~{mean_f:.2f} Hz  seen on {len(hits)}: {who}   (max {best:.0f}x floor)")


if __name__ == "__main__":
    sys.exit(main())
