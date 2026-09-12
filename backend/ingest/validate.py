"""Pure functions over sample arrays. No sockets, no state — this is where D1-D11 hit.

Every check here exists because the corresponding failure is SILENT: it produces a
number that looks fine. The loud failures need no help.
"""
import numpy as np
from .. import config


def dedupe_sort(rows):
    """Sort by t, then drop duplicate (node, t). Returns (t_ms, a[n,3], stats).

    Order matters: sort first, so a de-dup keeps the first of an out-of-order pair
    deterministically rather than whichever arrived first.
    """
    ordered = sorted(rows, key=lambda r: r["t"])
    out_of_order = sum(1 for a, b in zip(rows, rows[1:]) if b["t"] < a["t"])
    seen, keep = set(), []
    for r in ordered:
        if r["t"] in seen:
            continue
        seen.add(r["t"])
        keep.append(r)
    stats = {"duplicates": len(rows) - len(keep), "out_of_order": out_of_order,
             "n": len(keep)}
    return (np.array([r["t"] for r in keep], dtype=float),
            np.array([[r["ax"], r["ay"], r["az"]] for r in keep], dtype=float),
            stats)


def clock_mode(t_ms):
    """`relative` means NTP failed, so this node's samples cannot be aligned with
    another node's. Single-channel analysis is unaffected."""
    return "relative" if len(t_ms) and float(t_ms[0]) < config.EPOCH_MS_FLOOR else "epoch"


def check_fs(fs):
    if not (config.FS_MIN <= fs <= config.FS_MAX):
        raise ValueError(f"sample timing implausible (fs = {fs:.0f} Hz)")
    return fs


def gap_stats(t_ms):
    """Implied-loss fraction, longest hole, and the catch-up burst check.

    max(dt) alone is the WRONG statistic and it is the obvious one to reach for: a
    single dropped sample gives dt = 2 x median, well under any sensible threshold,
    so a run losing one sample in twenty passes a max-gap test cleanly while having
    lost 5% of the window. The observed hardware failure was a BURST of gaps, which
    a max test under-reports further.
    """
    d = np.diff(np.asarray(t_ms, dtype=float))
    if len(d) == 0:
        return {"fraction": 0.0, "longest_ms": 0.0, "burst": False}
    med = float(np.median(d))
    if med <= 0:
        raise ValueError("sensor timestamps are not increasing")
    missing = float(np.sum(np.maximum(np.round(d / med) - 1, 0)))
    return {"fraction": missing / max(len(d), 1),
            "longest_ms": float(np.max(d)),
            # After a blocking call the firmware's paced loop sprints at ~968 Hz to
            # catch up rather than resyncing. The backend would analyse the burst as
            # real, so it is caught by dt running SHORT, not long.
            "burst": bool(np.min(d) < med / config.BURST_RATIO)}


def gap_flags(stats):
    """(flags, abort_reason). A 250 ms hole distorts the spectrum in ways a flag
    does not honestly cover, so it aborts rather than degrades."""
    flags = []
    if stats["longest_ms"] > config.GAP_LONGEST_ABORT_S * 1000:
        return flags, f"sample gap of {stats['longest_ms']:.0f} ms in the analysis window"
    if stats["fraction"] > config.GAP_FRACTION_FLAG:
        flags.append("sample_gap")
    if stats["burst"]:
        flags.append("timestamps_unstable")
    return flags, None


def timestamp_flags(stats):
    n = max(stats["n"], 1)
    return (["timestamps_unstable"]
            if (stats["duplicates"] / n > config.DUP_FRACTION_FLAG
                or stats["out_of_order"] / n > config.DUP_FRACTION_FLAG) else [])


def clipping_flag(a, g_hat):
    """Which axis railed matters. The pipeline projects gravity out, so a rail on an
    axis aligned with g is largely removed and is informational only. Without the
    split the flag fires on nearly every hard stomp (measured: 15.2 m/s^2 vertical
    against a 19.62 rail vs 3.3 horizontal) and stops meaning anything.
    """
    a = np.asarray(a, dtype=float)
    if not np.any(np.abs(a) >= config.CLIP_THRESHOLD_MS2):
        return None
    axis = np.zeros(3)
    axis[int(np.argmax(np.max(np.abs(a), axis=0)))] = 1.0
    return ("clipping_vertical" if abs(float(axis @ g_hat)) > config.CLIP_VERTICAL_DOT
            else "clipping")


def moved_flag(a_window, g_hat, fs):
    """Compare baseline gravity with gravity over the final second. If the sensor
    rotated after the baseline, the projection plane is wrong for the rest of the
    window and nothing else would notice. Two means and a dot product."""
    n = int(round(fs))
    if len(a_window) < 2 * n:
        return None
    late = np.asarray(a_window[-n:], dtype=float).mean(axis=0)
    norm = np.linalg.norm(late)
    if norm == 0:
        return None
    cos = float(np.clip((late / norm) @ g_hat, -1.0, 1.0))
    return "moved_during_recording" if np.degrees(np.arccos(cos)) > config.MOVED_ANGLE_DEG else None
