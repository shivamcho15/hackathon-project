import { set, get, pushTrace } from "./store.js";

let started = false;
export function connect() {
  if (started) return;          // StrictMode mounts effects twice in dev; one socket.
  started = true;
  const url = `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/ui`;
  let ws, delay = 500;
  const open = () => {
    ws = new WebSocket(url);
    ws.onmessage = (e) => {
      const m = JSON.parse(e.data);
      if (m.type === "node_status") set({ nodes: m.nodes });
      else if (m.type === "comparison") set({ comparison: m.comparison });
      else if (m.type === "pinned") set({ pinned: m.pinned, live: m.live });
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
        // Only promote to pinned when the result belongs to the address on screen.
        if (m.frequency_hz != null && m.mode !== "calibration"
            && m.address === get().site?.address) patch.pinned = m;
        set(patch);
      }
    };
    // Back off rather than retrying at a fixed interval forever. Restarting the
    // backend under an open page left this hammering a dead proxy, which wedged the
    // tab — and restarting the backend mid-session is a thing that actually happens.
    ws.onclose = () => { delay = Math.min(delay * 1.8, 10000); setTimeout(open, delay); };
    ws.onopen = () => { delay = 500; };          // reset once a connection succeeds
  };
  open();
}
