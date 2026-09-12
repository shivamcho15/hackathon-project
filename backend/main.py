"""FastAPI app: routing, the session clock, and the two sockets.

Boot (plan §16.6) never blocks on hardware — the app is fully usable with zero
nodes connected. Screens 2-6 need no sensor at all and screen 1 renders `pinned`.
"""
import asyncio
import contextlib
import json
import re
from dataclasses import asdict

from fastapi import FastAPI, WebSocket, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import config, store, hazard
from .state import NodeRegistry, Buffers, Measurement, Slots, now_ms
from .ingest import socket as sock
from .site import resolve as site_resolve
from .ingest.trace import Trace
from .dsp import project as P
from .dsp.analyse import analyse

app = FastAPI(title="quake-assess")
app.add_middleware(CORSMiddleware, allow_origins=config.UI_ORIGINS,
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


def location_key_for(address):
    """Stable key for an address. The demo address keeps its historical key so the
    committed recording and anything already in the JSONL still match."""
    if not address:
        return None
    if site_resolve.is_demo_address(address):
        return "founders_hall"
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", address.lower())).strip("_")[:60]


class App:
    def __init__(self):
        self.nodes = NodeRegistry()
        self.buffers = Buffers()
        self.measurement = Measurement()
        self.slots = Slots()
        self.trace = Trace()
        self.node_sockets, self.ui_sockets = {}, set()
        self.site = None
        self.comparison = None
        self.trial_store = []          # complex FFTs for coherence; in memory only
        self.history = []              # frequencies at the active location
        self.history_key = None
        self.offline = config.offline()

    # ---- ingest -------------------------------------------------------------
    def on_samples(self, conn_id, rows):
        label = rows[0].get("node")
        if not label or not self.nodes.samples(label, rows, conn_id):
            return
        self.buffers.add(label, rows)
        self.trace.add(label, rows)
        n = self.nodes.nodes[label]
        if n["samples"] % 200 < len(rows):
            with contextlib.suppress(ValueError):
                n["derived_fs"] = round(P.derive_fs([s["t"] for s in
                                        list(self.buffers.data[label])[-400:]]), 3)

    # ---- outbound -----------------------------------------------------------
    async def broadcast(self, msg):
        dead = []
        for ws in list(self.ui_sockets):
            try:
                await ws.send_text(json.dumps(msg))
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.ui_sockets.discard(ws)

    async def push_nodes(self):
        await self.broadcast({"type": "node_status", "nodes": self.nodes.snapshot()})

    async def push_session(self, state, **extra):
        s = self.measurement.session or {}
        await self.broadcast({"type": "session_state", "state": state, **s, **extra})

    def site_location_key(self):
        """The location key for the loaded address.

        Since the address gate, the ADDRESS is the identity of a measurement — so
        the key is derived from it rather than picked from a menu. A separate
        picker could disagree with the address on screen, and did: the default sat
        on `expo_table` while Founders Hall was loaded, so a measurement filed
        itself under a key that matched no address and then refused to display.
        """
        return location_key_for((self.site or {}).get("address"))

    def recompute_comparison(self):
        m = self.slots.pinned
        if not (m and self.site and self.site.get("usgs_spectrum")):
            self.comparison = None
            return
        # A verdict is a measurement joined to a site. If the pinned measurement was
        # not taken at THIS address there is no verdict to show — computing one
        # anyway put Founders Hall's 0.446 s on the Space Needle's spectrum and
        # rendered 100% RED for a building nobody has measured.
        if m.get("location") != self.site_location_key():
            self.comparison = None
            return
        f = m.get("location_median_hz") or m.get("frequency_hz")
        self.comparison = hazard.compare(
            f, self.site["usgs_spectrum"], m.get("location"), self.site.get("address"),
            m.get("location") == self.site_location_key())
        if self.comparison:
            bf = self.site.get("building_footprint") or {}
            self.comparison["assessment"] = hazard.assess(
                self.site["usgs_spectrum"], self.site.get("site_class"),
                self.site.get("liquefaction_susceptibility"), bf.get("year_built"), f)

    # ---- the session clock; the backend owns it, the frontend animates to it --
    async def run_session(self):
        s = self.measurement.session
        try:
            await self.push_session("armed")
            await asyncio.sleep(max(0, (s["stomp_cue_at"] - now_ms()) / 1000))
            self.measurement.state = "recording"
            await self.push_session("recording")
            await asyncio.sleep(max(0, (s["window_ends_at"] - now_ms()) / 1000))
            self.measurement.state = "analyzing"
            await self.push_session("analyzing")

            batches = self.buffers.batches(s["armed_at"], s["window_ends_at"])
            self.buffers.record(s["session_id"], s["armed_at"], s["window_ends_at"])
            if s["location"] != self.history_key:
                self.history, self.trial_store, self.history_key = [], [], s["location"]

            res = await asyncio.to_thread(
                analyse, batches, s, s["mode"], config.STRUCTURAL_TYPE_DEFAULT, None,
                self.nodes.live_source(), list(self.history), self.trial_store)
            out = asdict(res) if not isinstance(res, dict) else res
            out.update({k: s.get(k) for k in ("session_id", "mode", "location", "address")})
            # Carry the beam geometry onto the result, and predict from it, so a
            # calibration row is self-contained: without this the Validation screen
            # cannot tell which overhang a run belongs to and the measured series
            # never populates.
            beam = {k: s.get(k) for k in ("beam_overhang_m", "beam_width_m",
                                          "beam_thickness_m", "beam_tip_mass_kg")
                    if s.get(k) is not None}
            out.update(beam)
            if s["mode"] == "calibration" and beam.get("beam_overhang_m"):
                from .calibration import predict
                out["predicted_frequency_hz"] = round(predict(
                    beam["beam_overhang_m"],
                    beam.get("beam_width_m", 0.030),
                    beam.get("beam_thickness_m", 0.0012),
                    beam.get("beam_tip_mass_kg", 0.050)), 4)
            out["recorded_at"] = __import__("datetime").datetime.utcnow().isoformat() + "Z"
            if out.get("frequency_hz") is not None:
                self.history.append(out["frequency_hz"])

            self.measurement.state = "idle"
            self.slots.write(out, self.site_location_key())
            self.recompute_comparison()
            # Result to the screen FIRST; persistence is best-effort and backgrounded.
            await self.broadcast({"type": "result", **out})
            await self.broadcast({"type": "comparison", "comparison": self.comparison})
            await self.push_session("done")
            for ws in list(self.node_sockets.values()):
                with contextlib.suppress(Exception):
                    await ws.send_text(json.dumps({
                        "type": "result", "frequency_hz": out.get("frequency_hz"),
                        "confidence": out.get("confidence")}))
            store.append_measurement(out)
        except Exception as e:
            self.measurement.state = "idle"
            await self.push_session("aborted", reason=str(e))

    async def status_loop(self):
        while True:
            await self.push_nodes()
            await asyncio.sleep(1.0 / config.NODE_STATUS_HZ)

    async def trace_loop(self):
        while True:
            for label in list(self.trace.pending):
                v = self.trace.drain(label)
                if v:
                    await self.broadcast({"type": "trace", "node": label,
                                          "t": now_ms(), "v": v})
            await asyncio.sleep(1.0 / config.TRACE_HZ)


A = App()


@app.on_event("startup")
async def boot():
    A.slots.boot()
    f = config.FIXTURES / "founders_hall.json"
    A.site = json.loads(f.read_text()) if f.exists() else None
    A.recompute_comparison()
    A.tasks = [asyncio.create_task(A.status_loop()), asyncio.create_task(A.trace_loop())]


@app.get("/api/state")
def get_state():
    key = A.site_location_key()
    belongs = lambda m: bool(m) and m.get("location") == key
    pinned = A.slots.pinned if belongs(A.slots.pinned) else None
    live = A.slots.live if belongs(A.slots.live) else None
    return {"pinned": pinned, "live": live, "comparison": A.comparison,
            "location_key": key,
            "site": A.site, "nodes": A.nodes.snapshot(), "offline": A.offline,
            "measurement_state": A.measurement.state,
            # Include the pinned measurement's own location: it may have come from
            # the boot recording rather than the JSONL, and the address gate offers
            # these as one-click entries — typing live at the table is the risky path.
            "known_locations": sorted(set(store.known_locations())
                                      | ({A.slots.pinned["location"]}
                                         if (A.slots.pinned or {}).get("location") else set()))}


@app.post("/api/sessions")
async def post_session(req: Request):
    body = await req.json()
    body["location"] = A.site_location_key()
    body.setdefault("address", (A.site or {}).get("address"))
    try:
        s = A.measurement.arm(body, A.nodes)
    except RuntimeError as e:
        return {"error": str(e)}
    asyncio.create_task(A.run_session())
    return {k: s[k] for k in ("session_id", "armed_at", "stomp_cue_at", "window_ends_at")}


@app.get("/api/site")
async def get_site(address: str = ""):
    s = await site_resolve.resolve(address or config.FOUNDERS_HALL_ADDRESS, A.offline)
    if not s.get("error"):
        A.site = s
        A.recompute_comparison()
        await A.broadcast({"type": "comparison", "comparison": A.comparison})
        key = A.site_location_key()
        belongs = lambda m: bool(m) and m.get("location") == key
        await A.broadcast({
            "type": "pinned",
            "pinned": A.slots.pinned if belongs(A.slots.pinned) else None,
            "live": A.slots.live if belongs(A.slots.live) else None})
    return s


@app.post("/api/pin")
async def post_pin():
    ok = A.slots.pin_live()
    A.recompute_comparison()
    await A.broadcast({"type": "comparison", "comparison": A.comparison})
    return {"pinned": ok}


@app.post("/api/offline")
async def post_offline(req: Request):
    A.offline = bool((await req.json()).get("offline"))
    return {"offline": A.offline}


@app.get("/api/measurements")
def get_measurements(location: str = None):
    return {"measurements": store.history(location) if location else []}


@app.get("/api/calibration")
def get_calibration():
    return {"runs": store.calibration_series()}


@app.websocket("/ws")
async def ws_node(ws: WebSocket):
    await sock.handle_node(ws, A)


@app.websocket("/ws/ui")
async def ws_ui(ws: WebSocket):
    await ws.accept()
    A.ui_sockets.add(ws)
    await ws.send_text(json.dumps({"type": "node_status", "nodes": A.nodes.snapshot()}))
    try:
        while True:
            await ws.receive_text()
    except Exception:
        pass
    finally:
        A.ui_sockets.discard(ws)


# Serve the built frontend from the backend, so the demo is ONE process on ONE port
# with no dev server and no proxy in the path. Mounted last so /api and /ws win.
_DIST = config.BASE_DIR.parent / "frontend" / "dist"
if _DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(_DIST), html=True), name="app")
