import { useEffect, useSyncExternalStore } from "react";
import "./theme.css";
import { get, subscribe, set } from "./store.js";
import { getState } from "./api.js";
import { connect } from "./ws.js";
import { onKey } from "./keys.js";
import Measure from "./screens/Measure.jsx";

const RAIL = ["Measure", "Site", "Verdict", "3D", "Retrofit", "Validation"];

function Placeholder({ n }) {
  return <div className="card" style={{ height: "100%", display: "flex", alignItems: "center",
    justifyContent: "center", flexDirection: "column", gap: 8 }}>
    <div className="label">{RAIL[n - 1]}</div>
    <div className="empty">built in a later phase</div>
  </div>;
}

export default function App() {
  const s = useSyncExternalStore(subscribe, get);

  useEffect(() => {
    getState().then((d) => set(d));
    connect();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // The status strip follows `pinned` — the building under discussion, the narrative
  // thread across all six screens. The Measure hero follows `live`.
  const p = s.pinned;
  const f = p ? (p.location_median_hz ?? p.frequency_hz) : null;
  const src = s.nodes.find((n) => n.source && n.source !== "hardware")?.source;
  const badge = { simulated: "SIM", replay: "REPLAY", unknown: "UNVERIFIED" }[src];

  return (
    <div className="shell">
      <div className="strip">
        {["top", "ground"].map((n) => {
          const nd = s.nodes.find((x) => x.node === n);
          return <span key={n} className="node">
            <i className="dot" data-s={nd?.state || "absent"} />{n.toUpperCase()}</span>;
        })}
        <span style={{ marginLeft: 10, letterSpacing: ".05em" }}>
          {(p?.location || s.site?.address?.split(",")[0] || "NO MEASUREMENT").replace(/_/g, " ").toUpperCase()}
          {f != null && <b style={{ marginLeft: 12 }}>{f.toFixed(2)} Hz</b>}
        </span>
        {p?.recorded_at && <span style={{ color: "var(--muted)" }}>
          {p.trials_used} run{p.trials_used === 1 ? "" : "s"} · {p.recorded_at.slice(11, 16)}
        </span>}
        <span className="spacer" />
        <span className="pill">{s.offline ? "OFFLINE" : s.site?.tier === "fixture" ? "CACHED" : "LIVE"}</span>
        {badge && <span className="pill" data-warn="1">{badge}</span>}
      </div>

      <div className="content">
        {s.view === 1 ? <Measure s={s} /> : <Placeholder n={s.view} />}
      </div>

      <div className="rail">
        {RAIL.map((label, i) => (
          <button key={label} data-on={s.view === i + 1 ? "1" : "0"}
                  onClick={() => set({ view: i + 1 })}>{i + 1} {label}</button>
        ))}
      </div>

      {s.overlay && (
        <div className="overlay" onClick={() => set({ overlay: false })}>
          <div className="card" style={{ minWidth: 520 }}>
            <div className="label" style={{ marginBottom: 10 }}>system</div>
            {s.nodes.length === 0 && <div className="empty">no nodes connected</div>}
            {s.nodes.map((n) => (
              <div key={n.node} className="kv">
                <span>{n.node} · {n.firmware || "?"} · {n.source}</span>
                <span>{`${n.state} · ${n.fs_hz ?? "—"} Hz · ${n.last_sample_age_ms ?? "—"} ms · restarts ${Math.max(0, (n.hellos || 1) - 1)}`}</span>
              </div>))}
            <div className="kv"><span>measurement</span><span>{s.sessionState}</span></div>
            <div className="kv"><span>site tier</span><span>{s.site?.tier || "none"}</span></div>
            <div className="empty" style={{ marginTop: 10 }}>press ~ or click to close</div>
          </div>
        </div>
      )}
    </div>
  );
}
