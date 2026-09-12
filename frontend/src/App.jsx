import { useEffect, useSyncExternalStore } from "react";
import "./theme.css";
import { get, subscribe, set } from "./store.js";
import { getState, startSession } from "./api.js";
import { connect } from "./ws.js";
import { onKey } from "./keys.js";
import Measure from "./screens/Measure.jsx";
import Site from "./screens/Site.jsx";
import Verdict from "./screens/Verdict.jsx";
import { SourceBanner } from "./screens/Explain.jsx";
import Building3D from "./screens/Building3D.jsx";
import Attract from "./screens/Attract.jsx";
import Address from "./screens/Address.jsx";
import Report from "./screens/Report.jsx";

/* One name per screen, used by the rail AND the page header, so the two can never
   drift apart. A judge walking up mid-demo has to be able to tell what they are
   looking at without asking, and the blurb says what the screen is FOR in one line
   — the question the rail number alone cannot answer. */
const PAGES = [
  ["Measurement", "how fast this building sways, measured from its own vibration"],
  ["Site", "the ground under this address, from public survey data"],
  ["Verdict", "what the measurement and the ground add up to"],
  ["3D Model", "the building itself, swaying at the rate we measured"],
  ["Report", "the document an owner hands to a structural engineer"],
];
const RAIL = PAGES.map(([name]) => name);

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

    // Attract mode after 90 s of no input. Any key or click wakes it.
    let idle;
    const defer = () => {
      clearTimeout(idle);
      idle = setTimeout(() => set({ attract: true }), 90_000);
    };
    // Deliberate split: any pointer motion DEFERS attract mode, but only a real
    // input — key, click, scroll — WAKES it. Waking on mousemove meant a hand
    // passing over the trackpad blanked the sign, which is the opposite of what a
    // sign is for.
    // ?attract=1 LOCKS the sign on: it is a deliberate park, so a stray event must
    // not dismiss it. Only Escape or clicking the sign clears the lock.
    const wake = () => {
      if (get().attractLocked) return;
      if (get().attract) set({ attract: false });
      defer();
    };
    const poke = defer;
    // ?attract=1 parks it on the sign deliberately, rather than waiting out 90 s.
    // ?screen=N opens straight onto a screen — useful for parking the laptop on a
    // particular beat, and it removes the rail click from any debugging loop.
    // ?screen=N also bypasses the gate — for parking the laptop on a beat, and so
    // a mid-demo reload does not send you back to the address prompt.
    const scr = new URLSearchParams(window.location.search).get("screen");
    if (scr && /^[1-5]$/.test(scr)) set({ view: +scr, gated: false });
    if (new URLSearchParams(window.location.search).get("attract") === "1")
      set({ attract: true, attractLocked: true });
    else poke();
    window.addEventListener("mousemove", defer, { passive: true });
    ["keydown", "mousedown", "wheel"].forEach((e) =>
      window.addEventListener(e, wake, { passive: true }));
    return () => {
      clearTimeout(idle);
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("mousemove", defer);
      ["keydown", "mousedown", "wheel"].forEach((e) =>
        window.removeEventListener(e, wake));
    };
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
        {s.gated
          ? <span style={{ marginLeft: 10, color: "var(--muted)" }}>enter an address to begin</span>
          : <>
            <span style={{ marginLeft: 10, letterSpacing: ".05em" }}>
              {(s.site?.address?.split(",")[0] || p?.location || "—").replace(/_/g, " ").toUpperCase()}
              {f != null && <b style={{ marginLeft: 12 }}>{f.toFixed(2)} Hz</b>}
            </span>
            {p?.recorded_at && <span style={{ color: "var(--muted)" }}>
              {p.trials_used} run{p.trials_used === 1 ? "" : "s"} · {p.recorded_at.slice(11, 16)}
            </span>}
          </>}
        <span className="spacer" />
        <span className="pill">{s.offline ? "OFFLINE" : s.site?.tier === "fixture" ? "CACHED" : "LIVE"}</span>
        {badge && <span className="pill" data-warn="1">{badge}</span>}
      </div>

      <div className="content" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {!s.gated && (
          <div style={{ display: "flex", alignItems: "baseline", gap: 14, flex: "0 0 auto",
                        padding: "0 2px 9px", borderBottom: "1px solid var(--border)" }}>
            <span style={{ fontSize: 13, letterSpacing: ".16em", color: "var(--muted)",
                           fontVariantNumeric: "tabular-nums" }}>
              {s.view} / {PAGES.length}</span>
            <h1 style={{ fontSize: 30, fontWeight: 700, margin: 0, letterSpacing: "-.01em" }}>
              {PAGES[s.view - 1]?.[0]}</h1>
            <span className="empty">{PAGES[s.view - 1]?.[1]}</span>
          </div>)}
        {!s.gated && <SourceBanner s={s} onRunOwn={() => {
          set({ view: 1, bannerDismissed: true });
          if (s.sessionState === "idle" && s.nodes.some((n) => ["streaming", "stale"].includes(n.state)))
            startSession({ mode: "building" });
        }} />}
        <div style={{ flex: 1, minHeight: 0 }}>
        {s.gated ? <Address s={s} /> :
         s.view === 1 ? <Measure s={s} /> : s.view === 2 ? <Site s={s} /> : s.view === 3 ? <Verdict s={s} /> :
         s.view === 4 ? <Building3D s={s} /> :
         s.view === 5 ? <Report s={s} /> : <Placeholder n={s.view} />}
        </div>
      </div>

      <div className="rail">
        {RAIL.map((label, i) => (
          <button key={label} data-on={s.view === i + 1 ? "1" : "0"} disabled={s.gated}
                  title={s.gated ? "enter an address first" : undefined}
                  style={s.gated ? { opacity: 0.35, cursor: "not-allowed" } : undefined}
                  onClick={() => set({ view: i + 1 })}>{i + 1} {label}</button>
        ))}
        {/* Space advances the rail, but nobody discovers that. A visible Next is what
            actually walks a first-time user through the four stages. */}
        <button disabled={s.gated || s.view >= RAIL.length}
                onClick={() => set({ view: Math.min(RAIL.length, s.view + 1) })}
                style={{ flex: "0 0 190px", borderRight: "none", fontWeight: 700,
                         color: s.gated || s.view >= RAIL.length ? "var(--muted)" : "#06121C",
                         background: s.gated || s.view >= RAIL.length ? "transparent" : "var(--top)",
                         cursor: s.gated || s.view >= RAIL.length ? "default" : "pointer",
                         opacity: s.gated ? 0.35 : 1 }}>
          {s.view >= RAIL.length ? "end of walkthrough" : `Next: ${RAIL[s.view]}  →`}
        </button>
      </div>

      {s.attract && <Attract s={s}
        onExit={() => set({ attract: false, attractLocked: false })} />}

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
            <div className="kv"><span>site tier</span><span>{s.site?.tier || "none"}</span>
            </div>
            <div className="kv"><span>site address</span>
              <span>{s.site?.address?.split(",")[0] || "none"}</span></div>
            <div className="kv"><span>pinned source</span>
              <span>{s.pinned?.source || "none"}
                {s.pinned?.from_recording ? " · dev recording" : ""}</span></div>
            <div className="kv"><span>trials on file</span>
              <span>{(s.known_locations || []).join(", ") || "none"}</span></div>
            <div style={{ display: "flex", gap: 8, marginTop: 14 }}
                 onClick={(e) => e.stopPropagation()}>
              {/* The 5:20 PM rehearsal: force Tier 3 and confirm Founders Hall still
                  works, as a keystroke rather than an experiment with the router. */}
              <button className="btn" style={{ fontSize: "var(--caption)", padding: "8px 12px" }}
                onClick={() => fetch("/api/offline", { method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ offline: !s.offline }) })
                  .then((r) => r.json()).then((d) => set({ offline: d.offline }))}>
                {s.offline ? "go back online" : "simulate no internet"}</button>
              <button className="btn" style={{ fontSize: "var(--caption)", padding: "8px 12px",
                  background: "transparent", color: "var(--muted)", borderColor: "var(--border)" }}
                onClick={() => getState().then((d) => set(d))}>reload from backend</button>
            </div>
            <div className="empty" style={{ marginTop: 10 }}>press ~ or click to close</div>
          </div>
        </div>
      )}
    </div>
  );
}
