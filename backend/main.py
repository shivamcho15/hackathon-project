"""FastAPI app: routing, the session clock, and the two sockets.

Boot (plan §16.6) never blocks on hardware — the app is fully usable with zero
nodes connected. Screens 2-6 need no sensor at all and screen 1 renders `pinned`.
"""
import asyncio
import contextlib
import json
from dataclasses import asdict

from fastapi import FastAPI, WebSocket, Request
from fastapi.middleware.cors import CORSMiddleware

from . import config, store, hazard
from .state import NodeRegistry, Buffers, Measurement, Slots, now_ms
from .ingest import socket as sock
from .ingest.trace import Trace
from .dsp import project as P
from .dsp.analyse import analyse

app = FastAPI(title="quake-assess")
app.add_middleware(CORSMiddleware, allow_origins=config.UI_ORIGINS,
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


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

    def recompute_comparison(self):
        m = self.slots.pinned
        if not (m and self.site):
            self.comparison = None
            return
        f = m.get("location_median_hz") or m.get("frequency_hz")
        self.comparison = hazard.compare(
            f, self.site.get("usgs_spectrum"), m.get("location"),
            self.site.get("address"),
            m.get("location") in (None, self.site.get("location_key", "founders_hall")))

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
            out["recorded_at"] = __import__("datetime").datetime.utcnow().isoformat() + "Z"
            if out.get("frequency_hz") is not None:
                self.history.append(out["frequency_hz"])

            self.measurement.state = "idle"
            self.slots.write(out, None)
            self.recompute_comparison()
            # Result to the screen FIRST; persistence is best-effort and backgrounded.
            await self.broadcast({"type": "result", **out})
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
    return {"pinned": A.slots.pinned, "live": A.slots.live, "comparison": A.comparison,
            "site": A.site, "nodes": A.nodes.snapshot(), "offline": A.offline,
            "measurement_state": A.measurement.state,
            "known_locations": store.known_locations()}


@app.post("/api/sessions")
async def post_session(req: Request):
    body = await req.json()
    try:
        s = A.measurement.arm(body, A.nodes)
    except RuntimeError as e:
        return {"error": str(e)}
    asyncio.create_task(A.run_session())
    return {k: s[k] for k in ("session_id", "armed_at", "stomp_cue_at", "window_ends_at")}


@app.post("/api/pin")
def post_pin():
    ok = A.slots.pin_live()
    A.recompute_comparison()
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
