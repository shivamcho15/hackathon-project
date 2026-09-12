"""Four independent state machines, not one chain, plus the two result slots.

Fusing them would make VERDICT and MEASURING mutually exclusive, so a judge asking
"can you show me the 3D one again?" mid-measurement would be blocked or corrupt
state. That request is the single most likely thing a judge says.

Machines: connection (per node) | measurement (one) | site (per address) | view
(frontend only). They communicate ONLY through the result slots below.
"""
import time
import uuid
from collections import deque, defaultdict

from . import config, store
from .ingest import validate as V


def now_ms():
    return int(time.time() * 1000)


class NodeRegistry:
    """Health derived from ARRIVING SAMPLES, never from what a node claims (I5).

    Three firmware reconnect implementations all reported wifi=up, streaming=on and
    STREAMING on their own display while sending nothing. Only the receiving end can
    confirm data is arriving.
    """

    def __init__(self):
        self.nodes = {}
        self.owner = {}          # node label -> connection id that claimed it first

    def release(self, conn_id):
        """A closed connection releases its labels.

        Without this, a node that reconnects — which the firmware does constantly:
        watchdog restarts, WiFi drops, the 12-25 minute silence bug — arrives with a
        new connection id, looks like a SECOND connection claiming `top`, and is
        marked CONFLICT permanently. Arming is then blocked for the rest of the day.
        Ownership is about live connections, not history.
        """
        for label, owner in list(self.owner.items()):
            if owner == conn_id:
                del self.owner[label]
                if label in self.nodes:
                    self.nodes[label]["conflict"] = False

    def hello(self, conn_id, msg):
        label = msg.get("node")
        if not label:
            return None
        src = config.SOURCE_BY_FIRMWARE.get(msg.get("firmware"), config.SOURCE_DEFAULT)
        owner = self.owner.get(label)
        if owner is not None and owner != conn_id:
            # Two CONNECTIONS claiming one label is an error (both flashed `top`).
            # Two hellos on ONE connection with different labels is the normal
            # bench rig: 0x68 = ground, 0x69 = top.
            n = self.nodes.setdefault(label, self._blank(label))
            n["conflict"] = True
            return label
        self.owner[label] = conn_id
        n = self.nodes.setdefault(label, self._blank(label))
        n.update({k: msg.get(k) for k in
                  ("fs_hz", "mac", "rssi", "i2c_addr", "sensors_on_board",
                   "tilt_deg", "calibrated", "firmware")})
        n["source"] = src
        n["hellos"] += 1          # >1 means it rebooted: the watchdog doing its job
        return label

    @staticmethod
    def _blank(label):
        return {"node": label, "hellos": 0, "last_arrival": None, "fs_hz": None,
                "derived_fs": None, "clock": "epoch", "source": config.SOURCE_DEFAULT,
                "conflict": False, "samples": 0, "firmware": None, "mac": None,
                "rssi": None, "i2c_addr": None, "sensors_on_board": None,
                "tilt_deg": None, "calibrated": None}

    def samples(self, label, rows, conn_id=None):
        n = self.nodes.setdefault(label, self._blank(label))
        if conn_id is not None and self.owner.setdefault(label, conn_id) != conn_id:
            n["conflict"] = True
            return False          # refuse to treat a conflicting claim as a channel
        n["last_arrival"] = now_ms()
        n["samples"] += len(rows)
        n["clock"] = V.clock_mode([rows[0]["t"]])
        return True

    def state(self, label):
        n = self.nodes.get(label)
        if not n:
            return "absent"
        if n["conflict"]:
            return "conflict"
        if n["last_arrival"] is None:
            return "handshake"
        age = (now_ms() - n["last_arrival"]) / 1000.0
        if age < config.STALE_AFTER_S:
            return "streaming"
        if age < config.RECOVERING_AFTER_S:
            return "stale"
        if age < config.ABSENT_AFTER_S:
            return "recovering"   # the node restarts ITSELF; not dead yet
        return "absent"

    def snapshot(self):
        out = []
        for label, n in self.nodes.items():
            age = None if n["last_arrival"] is None else now_ms() - n["last_arrival"]
            out.append({**{k: n[k] for k in
                           ("node", "hellos", "i2c_addr", "sensors_on_board",
                            "tilt_deg", "calibrated", "firmware", "clock", "source")},
                        "state": self.state(label),
                        "last_sample_age_ms": age,
                        "fs_hz": n["derived_fs"] or n["fs_hz"],
                        "mac": n["mac"], "rssi": n["rssi"]})
        return out

    def live_source(self):
        """Any non-hardware node makes the whole measurement non-hardware."""
        srcs = {n["source"] for n in self.nodes.values() if n["last_arrival"]}
        if not srcs:
            return config.SOURCE_DEFAULT
        for s in ("unknown", "simulated", "replay"):
            if s in srcs:
                return s
        return "hardware"

    def can_arm(self):
        """STALE still arms: <=10 s of silence is usually jitter, and a dead button
        in front of a judge for a hiccup that resolves itself is worse than a
        slightly noisy trial. RECOVERING/ABSENT block — those are minutes away."""
        return any(self.state(l) in ("streaming", "stale") for l in self.nodes)


class Buffers:
    """Per-node ring of recent samples, plus the automatic session recorder."""

    def __init__(self, seconds=20):
        self.max = int(seconds * config.FS_NOMINAL)
        self.data = defaultdict(lambda: deque(maxlen=self.max))

    def add(self, label, rows):
        self.data[label].extend(rows)

    def window(self, label, t_from, t_to):
        return [s for s in self.data[label] if t_from <= s["t"] <= t_to]

    def batches(self, t_from, t_to):
        out = []
        for label in self.data:
            rows = self.window(label, t_from, t_to)
            out += [rows[i:i + 20] for i in range(0, len(rows), 20)]
        return out

    def record(self, session_id, t_from, t_to):
        """Write the session's raw samples so it can be replayed later.

        Deliberately written at CLOSE rather than per batch: the file then contains
        exactly [armed_at, window_ends_at] with no partial trailing window, and it
        is one write instead of interleaved IO on the hot path. The cost is that a
        crash mid-session loses that session's raw data — acceptable, because a
        crash mid-session loses the measurement anyway.
        """
        import json
        try:
            config.SESSIONS.mkdir(parents=True, exist_ok=True)
            path = config.SESSIONS / f"{session_id}.jsonl"
            with path.open("w") as f:
                for label in self.data:
                    for s in self.window(label, t_from, t_to):
                        f.write(json.dumps(s) + "\n")
            return path
        except OSError:
            return None


class Measurement:
    """IDLE -> ARMED -> RECORDING -> ANALYZING -> IDLE. Four states, not eleven.

    Arming is the ONLY guarded transition in the whole application. Concentrating
    every "not now" here is what keeps the rest impossible to wedge.
    """

    def __init__(self):
        self.state = "idle"
        self.session = None

    def arm(self, req, nodes: NodeRegistry):
        if self.state != "idle":
            raise RuntimeError("a measurement is already running")
        if not nodes.can_arm():
            raise RuntimeError("no sensor is streaming — check the hotspot and the nodes")
        countdown = int(req.get("countdown_s", config.COUNTDOWN_S))
        duration = int(req.get("duration_s", config.DURATION_S))
        t0 = now_ms()
        self.session = {
            "session_id": str(uuid.uuid4()),
            "mode": req.get("mode", "building"),
            "location": req.get("location"),
            "address": req.get("address"),
            "armed_at": t0,
            "stomp_cue_at": t0 + countdown * 1000,
            "window_ends_at": t0 + (countdown + duration) * 1000,
            **{k: req[k] for k in
               ("beam_overhang_m", "beam_width_m", "beam_thickness_m", "beam_tip_mass_kg")
               if k in req},
        }
        self.state = "armed"
        return self.session


class Slots:
    """pinned = the measurement the story is built on; live = the latest attempt.

    A FAILED measurement writes `live` and never touches `pinned`. That single rule
    is what stops one bad stomp at 5:52 PM from emptying four screens.
    """

    def __init__(self):
        self.pinned = None
        self.live = None

    def boot(self):
        self.pinned = store.load_pinned()
        self.live = self.pinned

    def write(self, result, site_location=None):
        self.live = result
        if result.get("frequency_hz") is None or result.get("mode") == "calibration":
            return False          # calibration touches neither slot
        # Promote ONLY on a match. `site_location` is None whenever the loaded site
        # has no measurement on file — a judge-typed address — and None is not a
        # match, so nothing auto-promotes against it. An earlier version skipped the
        # check when it was None, which promoted every result and would have let a
        # judge's address quietly take over the building the story is built on.
        if result.get("location") != site_location:
            return False
        self.pinned = result
        return True

    def pin_live(self):
        if not self.live or self.live.get("frequency_hz") is None:
            return False
        self.pinned = self.live
        return True
