"""Persistence behind one interface. JSONL today; Supabase slots in here later.

Writes are best-effort and OFF the hot path: the result reaches the screen before
this is called. Trial history is in memory, mirrored here, so the "three stomps
agree" check survives a dead hotspot — which is exactly when a judge asks about it.
"""
import json
from . import config

MEASUREMENTS = config.DATA / "measurements.jsonl"


def append_measurement(result: dict):
    try:
        config.DATA.mkdir(parents=True, exist_ok=True)
        with MEASUREMENTS.open("a") as f:
            f.write(json.dumps(result) + "\n")
        return True
    except OSError:
        return False            # surfaced only in the system overlay; user sees nothing


def _read_all():
    if not MEASUREMENTS.exists():
        return []
    rows = []
    for line in MEASUREMENTS.read_text().splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                pass            # a torn final line must not take the app down
    return rows


def history(location, mode="building"):
    return [r for r in _read_all()
            if r.get("location") == location and r.get("mode") == mode]


def calibration_series():
    return [r for r in _read_all() if r.get("mode") == "calibration"]


def known_locations():
    return sorted({r["location"] for r in _read_all()
                   if r.get("location") and r.get("frequency_hz")})


def load_pinned():
    """Most recent good founders_hall row with source='hardware', else the fixture.

    The source filter is what stops a morning development artefact becoming the
    demo's headline number.
    """
    rows = [r for r in history("founders_hall")
            if r.get("frequency_hz") and r.get("source") == "hardware"]
    if rows:
        return max(rows, key=lambda r: r.get("recorded_at", ""))
    f = config.FIXTURES / "founders_hall_measurement.json"
    if f.exists():
        return json.loads(f.read_text())
    # Last resort: analyse the committed dev recording. SIMULATED, and it says so —
    # provenance comes from its hello line like any other source, so it lights the
    # SIM badge and cannot be mistaken for a measurement of a real building.
    try:
        from .recordings import load_recording
        return load_recording()
    except Exception:
        return None
