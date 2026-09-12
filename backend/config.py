"""Every tuned constant in the system, in one place.

If a threshold appears as a literal anywhere else in the backend, that is a bug.
Section references are to IMPLEMENTATION_PLAN.md.
"""
import os
from pathlib import Path

# --- runtime -----------------------------------------------------------------
HOST = "0.0.0.0"          # not 127.0.0.1 — the ESP32 must reach it
PORT = 48266              # the only port open through Saahil's Windows firewall
UI_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]

BASE_DIR = Path(__file__).resolve().parent
FIXTURES = BASE_DIR / "fixtures"
DATA = BASE_DIR / "data"
SESSIONS = DATA / "sessions"

def offline() -> bool:
    """Read live so the `~` overlay can toggle it without a restart (§2.5)."""
    return os.environ.get("QUAKE_OFFLINE", "0") not in ("0", "", "false", "False")

FOUNDERS_HALL_ADDRESS = "4215 E Stevens Way NE, Seattle, WA 98195"
FOUNDERS_HALL_LATLON = (47.6588, -122.3072)   # OSM centroid, NOT the doc's old value

# --- session timing (§4.3, §6.5) ---------------------------------------------
DURATION_S = 12           # recording window; excludes the countdown
COUNTDOWN_S = 3           # mechanical settle -> the guaranteed-quiet baseline
ANALYSIS_WINDOW_S = 8.0   # from onset
ONSET_LEAD_S = 0.1        # window starts this far before onset
ONSET_SLACK_S = 0.5       # onset search starts this far before the cue
MIN_POST_ONSET_S = 3.0    # below this, use what exists and demote

# --- sampling and ingest (§5, §6.2) ------------------------------------------
FS_NOMINAL = 200.0        # design target only; fs is ALWAYS derived (I4)
FS_MIN, FS_MAX = 150.0, 250.0
EPOCH_MS_FLOOR = 1.0e12   # t below this => NTP failed, clock is relative
DUP_FRACTION_FLAG = 0.01
GAP_FRACTION_FLAG = 0.005
GAP_LONGEST_ABORT_S = 0.250
BURST_RATIO = 5.0         # min(dt) < median/5 => catch-up burst
RAIL_MS2 = 19.62          # +/-2g
CLIP_THRESHOLD_MS2 = 19.5
CLIP_VERTICAL_DOT = 0.7   # |axis.g| above this => vertical clip, informational
MOVED_ANGLE_DEG = 10.0

# --- node connection states (§16.1) ------------------------------------------
STALE_AFTER_S = 2.0
RECOVERING_AFTER_S = 10.0
ABSENT_AFTER_S = 180.0    # sized by the SLOWER watchdog (~145s) + margin
HANDSHAKE_NO_DATA_S = 5.0
NODE_STATUS_HZ = 2.0
TRACE_HZ = 20.0
TRACE_DECIMATE = 10
TRACE_GRAVITY_WINDOW = 200   # rolling samples for the cheap gravity estimate

# --- DSP (§6) ----------------------------------------------------------------
BANDPASS_LOW_HZ, BANDPASS_HIGH_HZ, BANDPASS_ORDER = 0.3, 25.0, 4
SEARCH_HZ_BUILDING = (0.5, 15.0)
SEARCH_HZ_CALIBRATION = (0.5, 20.0)
ZERO_PAD_N = 8192
ENVELOPE_WINDOW_S = 0.25
ONSET_THRESHOLD_MULT = 6.0    # envelope must exceed 6x baseline RMS
PROMINENCE_MULT = 3.0         # >= 3x in-band median
PROMINENCE_MULT_RELAXED = 1.5 # for the harmonic-partner search
SNR_MIN_DB = 6.0
HARMONIC_TOLERANCE = 0.05     # +/-5% of 2x or 3x
HARMONIC_MIN_RATIO = 0.40     # partner must be >=40% of the main peak (see confidence.py)
ESTIMATOR_REJECT = 0.25       # gross FFT-vs-ringdown disagreement => no coherent mode
DECAY_RATIO_MIN = 2.0         # early/late band energy: a ringdown decays, noise does not
NEAR_CEILING_HZ = 2.0
PLAUSIBILITY_FACTOR = 3.0     # T ~ 0.1N, flag only beyond 3x
ESTIMATOR_AGREEMENT = 0.10    # FFT vs ringdown cross-check (§6.10)

# --- damping (§8) ------------------------------------------------------------
DAMPING_R2_MIN = 0.7
DAMPING_ZETA_BOUNDS = (0.001, 0.20)
DAMPING_EDGE_TRIM_CYCLES = 1.0

# --- two-sensor (§9) ---------------------------------------------------------
COHERENCE_MIN = 0.6
GROUND_SNR_MIN_DB = 6.0
WATER_LEVEL_K = 1.5
TRIAL_HISTORY_MAX = 5
AMPLIFICATION_CEILING = {"wood": 35.0, "urm": 35.0, "concrete": 50.0, "steel": 90.0}
DAMPING_DEFAULT = {"wood": 0.035, "urm": 0.035, "concrete": 0.0325, "steel": 0.014}
STRUCTURAL_TYPE_DEFAULT = "concrete"

# --- trials (§10) ------------------------------------------------------------
SPREAD_FAIR = 0.05
SPREAD_POOR = 0.15
UNCERTAINTY_FLOOR_HZ = 0.03
LOCATION_KEYS = ("expo_table", "founders_hall", "tower_rig")
LOCATION_DEFAULT = "expo_table"   # fail-safe: never pollute founders_hall (§10.1)

# --- hazard bands (§12.3) ----------------------------------------------------
BAND_GREEN_MAX = 0.6
BAND_AMBER_MAX = 0.85
USGS_SITE_CLASS_ENUM = {"A","B","B-estimated","BC","C","CD","D","D-default","DEFAULT","DE","E"}
USGS_SITE_CLASS_FALLBACK = "D"    # explicit, never USGS's undocumented "BC"
USGS_RISK_CATEGORY = "II"

# --- external API timeouts (§11.5) — one attempt, no retries (I7) ------------
TIMEOUT_GEOCODE = 3.0
TIMEOUT_DNR = 3.0
TIMEOUT_USGS = 4.0
TIMEOUT_OVERPASS = 8.0
OVERPASS_RADIUS_M = 100

# --- provenance (§4.2, I9) ---------------------------------------------------
SOURCE_BY_FIRMWARE = {
    "stream_node": "hardware",
    "fake_node": "simulated",
    "replay_node": "replay",
}
SOURCE_DEFAULT = "unknown"   # whitelist; never default to "hardware"
