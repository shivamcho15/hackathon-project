import { set, get, pushTrace } from "./store.js";

let started = false;
export function connect() {
  if (started) return;          // StrictMode mounts effects twice in dev; one socket.
  started = true;
  const url = `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/ui`;
  let ws;
  const open = () => {
    ws = new WebSocket(url);
    ws.onmessage = (e) => {
      const m = JSON.parse(e.data);
      if (m.type === "node_status") set({ nodes: m.nodes });
      else if (m.type === "trace") pushTrace(m.node, m.v);
      else if (m.type === "session_state") {
        // `done` and `aborted` are TERMINAL, not states the UI sits in. Mapping them
        // to idle is what re-enables the START button: without it `busy` stays true
        // forever and the second stomp of the day is impossible.
        const over = m.state === "done" || m.state === "aborted";
        set({ sessionState: over ? "idle" : m.state, session: over ? null : m });
      } else if (m.type === "result") {
        // A failed measurement writes `live` and never touches `pinned` — one bad
        // stomp must not empty four screens.
        const patch = { live: m };
        if (m.frequency_hz != null && m.mode !== "calibration") patch.pinned = m;
        set(patch);
      }
    };
    ws.onclose = () => setTimeout(open, 800);   // the demo cannot end because a socket blipped
  };
  open();
}
