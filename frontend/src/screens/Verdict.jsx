import { useState } from "react";
import HazardCurve from "../charts/HazardCurve.jsx";

/* The payoff screen answers one question in plain words: is this building okay?
   It used to lead with "100% OF MAXIMUM · RED" and the Mexico City collapse, off a
   score that only measures whether the sway period lands on the design spectrum's
   plateau — which is the expected case for a low-rise building on firm ground, and
   is exactly what a modern building is designed for. That read as a death sentence
   for a 2022 university building. The verdict is now built from the factors that
   actually drive vulnerability (backend/hazard.py assess). */

const TONE = {
  good:  { c: "var(--green)", mark: "✓" },
  ok:    { c: "var(--amber)", mark: "!" },
  watch: { c: "var(--red)",   mark: "!" },
};

export default function Verdict({ s }) {
  const [showChart, setShowChart] = useState(false);
  const c = s.comparison, a = c?.assessment, sp = s.site?.usgs_spectrum;
  const p = s.pinned;

  if (!sp) return <Empty title="No ground data for this address"
    body="The measured frequency is still real — see Measure." />;
  if (!a) return <Empty title="No measurement for this address yet"
    body="Take one on the Measure screen and the verdict appears here." />;

  const tone = TONE[a.level];
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14, height: "100%",
                  overflowY: "auto", paddingRight: 6 }}>
      {c && !c.location_matches_site && (
        <div className="card" style={{ borderColor: "var(--amber)", padding: "10px 14px" }}>
          <b>This measurement was taken somewhere else</b>
          <span className="empty"> — not at this address.</span>
        </div>)}

      <div className="card" style={{ padding: 26, borderColor: tone.c }}>
        <div style={{ fontSize: 52, fontWeight: 700, lineHeight: 1.1, color: tone.c }}>
          {a.headline}
        </div>
        <div style={{ fontSize: 22, color: "var(--muted)", marginTop: 10, lineHeight: 1.5,
                      maxWidth: 900 }}>
          {a.sub}
        </div>
      </div>

      <div className="card" style={{ padding: 20 }}>
        <div className="label" style={{ marginBottom: 12 }}>what went into that</div>
        {a.factors.map(([lvl, title, detail]) => (
          <div key={title} style={{ display: "flex", gap: 14, padding: "11px 0",
                                    borderTop: "1px solid var(--border)" }}>
            <div style={{ flex: "0 0 26px", height: 26, borderRadius: 13, marginTop: 1,
                          display: "flex", alignItems: "center", justifyContent: "center",
                          background: TONE[lvl].c, color: "#06121C", fontWeight: 700 }}>
              {TONE[lvl].mark}</div>
            <div style={{ minWidth: 0 }}>
              <div style={{ fontSize: "var(--body)" }}>{title}</div>
              <div className="empty" style={{ marginTop: 2, lineHeight: 1.45 }}>{detail}</div>
            </div>
          </div>))}
      </div>

      <div className="card" style={{ padding: 18 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span className="empty">
            Screening guidance — not engineering design.
            {p?.recorded_at && ` · ${p.trials_used} run${p.trials_used === 1 ? "" : "s"} · ${p.recorded_at.slice(11, 16)}`}
          </span>
          <button onClick={() => setShowChart((v) => !v)}
            style={{ background: "none", border: "none", color: "var(--top)", cursor: "pointer",
                     fontFamily: "inherit", fontSize: "var(--caption)", textDecoration: "underline" }}>
            {showChart ? "hide the hazard curve" : "show the hazard curve"}
          </button>
        </div>
        {showChart && <div style={{ height: 260, marginTop: 12 }}>
          <HazardCurve spectrum={sp} period={c.measured_period_s} t0={sp.t0} ts={sp.ts} />
        </div>}
      </div>
    </div>
  );
}

function Empty({ title, body }) {
  return <div className="card" style={{ height: "100%", display: "flex", alignItems: "center",
    justifyContent: "center", flexDirection: "column", gap: 10 }}>
    <div style={{ fontSize: 34, fontWeight: 600 }}>{title}</div>
    <div className="empty">{body}</div>
  </div>;
}
