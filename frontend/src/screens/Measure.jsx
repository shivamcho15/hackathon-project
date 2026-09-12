import { useEffect, useState } from "react";
import LiveTrace from "../charts/LiveTrace.jsx";
import SpectrumChart from "../charts/SpectrumChart.jsx";
import { set } from "../store.js";
import { startSession, measurements } from "../api.js";

const FLAG_TEXT = {
  low_snr: "weak signal", low_prominence: "no clear peak", possible_harmonic: "possible harmonic",
  near_ceiling: "near the filter ceiling", plausibility_mismatch: "unexpected for the storey count",
  clipping: "stomp clipped the sensor", clipping_vertical: "vertical clipping (harmless)",
  sample_gap: "dropped samples", timestamps_unstable: "unstable timing",
  moved_during_recording: "sensor moved", ground_lost_midrun: "ground node dropped",
  single_node_ground: "ground node only", no_clock_sync: "clocks not synced",
  no_onset: "no stomp detected", no_peak: "no clear resonance",
  no_decay: "no ringdown — motion without resonance",
  estimator_disagreement: "estimators disagree", low_ground_snr: "ground signal too weak",
  low_coherence: "stomps not consistent", short_window: "stomp landed late",
};
const DOTS = { good: "●●●", fair: "●●○", poor: "●○○" };

export default function Measure({ s }) {
  const [now, setNow] = useState(Date.now());
  const [runs, setRuns] = useState([]);
  const r = s.live;
  const busy = s.sessionState !== "idle";

  // Animate against the BACKEND's absolute timestamps. Never run an independent
  // timer: two clocks drifting is how a UI says "recording..." over a landed result.
  useEffect(() => {
    if (!busy) return;
    let raf;
    const tick = () => { setNow(Date.now()); raf = requestAnimationFrame(tick); };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [busy]);

  useEffect(() => {
    if (!busy) measurements(s.location).then((d) =>
      setRuns((d.measurements || []).map((m) => m.frequency_hz).filter(Boolean).slice(-5)));
  }, [busy, s.location, r]);

  const sess = s.session;
  const counting = sess && now < sess.stomp_cue_at;
  const secs = counting ? Math.ceil((sess.stomp_cue_at - now) / 1000) : 0;
  const pct = sess && !counting
    ? Math.min(1, (now - sess.stomp_cue_at) / (sess.window_ends_at - sess.stomp_cue_at)) : 0;

  const nodes = Object.fromEntries(s.nodes.map((n) => [n.node, n]));
  const canArm = s.nodes.some((n) => ["streaming", "stale"].includes(n.state));
  const all = [...(s.trace.top || []), ...(s.trace.ground || [])];
  const scale = Math.max(0.05, ...all.map(Math.abs));   // ONE scale for both traces

  return (
    <div style={{ display: "flex", gap: 14, height: "100%" }}>
      {counting && (
        <div className="overlay">
          <div className="count">{secs}</div>
          <div className="label" style={{ marginTop: 12 }}>get ready to stomp</div>
        </div>
      )}
      <div style={{ flex: 1.55, display: "flex", flexDirection: "column", gap: 12, minWidth: 0 }}>
        {["top", "ground"].map((n) => (
          nodes[n] || s.trace[n]?.length
            ? <LiveTrace key={n} data={s.trace[n] || []} scale={scale}
                         color={n === "top" ? "var(--top)" : "var(--ground)"} label={n} />
            : <div key={n} className="card" style={{ flex: 1 }}>
                <div className="label">{n}</div>
                <div className="empty" style={{ marginTop: 8 }}>
                  No sensor connected. Check: hotspot on and 2.4 GHz, both nodes switched to it,
                  backend port 48266. If you just restarted the backend, power-cycle the nodes.
                </div>
              </div>
        ))}
        <div className="card" style={{ flex: 1.2, minHeight: 0, display: "flex", flexDirection: "column" }}>
          <div className="label">spectrum</div>
          <div style={{ flex: 1, minHeight: 0 }}>
            <SpectrumChart spectrum={r?.spectrum} peak={r?.frequency_hz} />
          </div>
        </div>
      </div>

      <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 12, minWidth: 300 }}>
        <div className="card" style={{ flex: 1 }}>
          <div className="label">result</div>
          {r?.frequency_hz != null ? (
            <>
              <div className="hero" style={{ marginTop: 10 }}>
                {r.frequency_hz.toFixed(2)} <span style={{ fontSize: 44, color: "var(--muted)" }}>Hz</span>
              </div>
              {r.frequency_uncertainty_hz != null &&
                <div className="sub">± {r.frequency_uncertainty_hz.toFixed(2)}</div>}
              <div style={{ marginTop: 8, color: "var(--muted)", fontSize: 22 }}>
                {DOTS[r.confidence]} {r.confidence}
              </div>
              <div style={{ marginTop: 14 }}>
                {r.period_s != null && <div className="kv"><span>Period</span><span>{r.period_s.toFixed(3)} s</span></div>}
                {r.damping_ratio != null && <div className="kv"><span>Damping</span><span>{(r.damping_ratio * 100).toFixed(1)} %</span></div>}
                {r.amplification != null && <div className="kv"><span>Amplification</span><span>{r.amplification.toFixed(1)}×</span></div>}
                {r.coherence != null && <div className="kv"><span>Coherence</span><span>{r.coherence.toFixed(2)}</span></div>}
                <div className="kv"><span>Channels</span>
                  <span>{(r.channels_used || []).join(" + ") || "—"} · {r.trials_used} run{r.trials_used === 1 ? "" : "s"}</span></div>
              </div>
            </>
          ) : (
            <div style={{ marginTop: 14 }}>
              <div style={{ fontSize: 34, fontWeight: 600 }}>
                {r ? "No clear peak" : "Ready"}
              </div>
              <div className="empty" style={{ marginTop: 10, lineHeight: 1.5 }}>
                {r ? "We recorded motion but found no clear resonance. Stomp harder, or move the sensor nearer a wall or column."
                   : "Press S to arm a measurement."}
              </div>
            </div>
          )}
          <div style={{ marginTop: 12 }}>
            {(r?.confidence_flags || []).map((f) =>
              <span key={f} className="chip">{FLAG_TEXT[f] || f}</span>)}
          </div>
        </div>

        <div className="card">
          <div className="label" style={{ marginBottom: 8 }}>location</div>
          <div className="seg">
            {["expo_table", "founders_hall", "tower_rig"].map((k) => (
              <button key={k} data-on={s.location === k ? "1" : "0"}
                      onClick={() => set({ location: k })}>{k.replace("_", " ")}</button>
            ))}
          </div>
          <button className="btn" style={{ width: "100%", marginTop: 12 }} disabled={busy || !canArm}
            onClick={() => startSession({ mode: "building", location: s.location,
                                          address: s.site?.address ?? null })}>
            {busy ? (counting ? "STOMP IN " + secs
                     : `recording… ${Math.ceil((1 - pct) * 12)}s`) : "▶  START MEASUREMENT  (S)"}
          </button>
          {!canArm && <div className="empty" style={{ marginTop: 8 }}>
            No sensor streaming — start a node, or check the hotspot and port 48266.</div>}
          {busy && !counting && (
            <div style={{ height: 6, background: "var(--border)", borderRadius: 3, marginTop: 10 }}>
              <div style={{ height: "100%", width: `${pct * 100}%`, background: "var(--top)", borderRadius: 3 }} />
            </div>)}
          {runs.length > 0 && <div className="empty" style={{ marginTop: 10 }}>
            runs: {runs.map((f) => f.toFixed(2)).join(" · ")} Hz</div>}
        </div>
      </div>
    </div>
  );
}
