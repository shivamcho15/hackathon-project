import { useEffect, useRef, useState } from "react";
import HazardCurve from "../charts/HazardCurve.jsx";
import SwayScale from "../charts/SwayScale.jsx";
import { set } from "../store.js";

/* The Site screen answers three questions a homeowner would actually ask, in the
 * order they would ask them: what am I standing on, can it turn to soup, and does
 * any of it have anything to do with MY building.
 *
 * It used to answer a fourth one nobody asked — "what are S_DS, S_D1, T_0, T_S,
 * SDC and PGA_M" — in a grid of six acronyms that took up a third of the screen.
 * Those are real and they still matter, so they did not get deleted: the full
 * parameter table lives in the Report (§8), and the curve they describe is one
 * click away at the bottom of this screen. Default state is the version a person
 * can read in five seconds.
 *
 * Everything here is a POINT LOOKUP at one pair of coordinates. Saying so is the
 * credibility of the whole screen: real government data for a real address.
 */

/* NEHRP site class: shear-wave velocity in the top 30 m. Slower wave, softer
   ground, more amplification. Ranges per ASCE 7. */
const CLASSES = {
  A: ["hard rock", "over 1500 m/s", "About the best ground there is."],
  B: ["rock", "760–1500 m/s", "Solid rock. Amplifies shaking only slightly."],
  C: ["very dense soil / soft rock", "360–760 m/s", "Firm, but not bedrock. Moderate amplification."],
  D: ["stiff soil", "180–360 m/s", "Amplifies noticeably. The code's default assumption."],
  E: ["soft clay", "under 180 m/s", "Amplifies strongly — the Mexico City 1985 condition."],
  F: ["needs a site-specific study", "—", "Unusual ground the standard classes don't cover."],
};
const LETTERS = ["A", "B", "C", "D", "E", "F"];

/* WA DNR returns these words, and backend/hazard.py weights the same five. */
const LIQ = ["very low", "low", "moderate", "high", "very high"];
const liqIndex = (v) => {
  const t = (v || "").toLowerCase();
  if (!t) return -1;
  if (t.includes("very low")) return 0;
  if (t.includes("very high")) return 4;
  if (t.includes("high")) return 3;
  if (t.includes("moderate")) return 2;
  if (t.includes("low")) return 1;
  return -1;
};

function Card({ title, source, children, flex = 1 }) {
  return (
    <div className="card" style={{ flex, minWidth: 0, display: "flex", flexDirection: "column",
                                   padding: "16px 18px 15px", minHeight: 226 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
        <div className="label">{title}</div>
        {source && <div style={{ fontSize: 12, color: "var(--muted)" }}>{source}</div>}
      </div>
      {children}
    </div>
  );
}

/* One track, two cards. The scales read the same way so the eye learns it once. */
function Track({ steps, active, left, right }) {
  return (
    <div style={{ marginTop: "auto" }}>
      <div style={{ display: "flex", gap: 3 }}>
        {steps.map((s, i) => (
          <div key={s} style={{ flex: 1, textAlign: "center", padding: "6px 2px", borderRadius: 5,
                 fontSize: 13, whiteSpace: "nowrap", overflow: "hidden",
                 fontWeight: i === active ? 700 : 400,
                 background: i === active ? "var(--top)" : "#18222D",
                 color: i === active ? "#06121C" : "var(--muted)" }}>{s}</div>))}
      </div>
      {/* The ends are what make a scale mean anything — "C" says nothing until you
          can see that one end is rock and the other is mud. They get read at a
          glance from two metres away, so they are sized to be read that way. */}
      <div style={{ display: "flex", justifyContent: "space-between", marginTop: 7,
                    fontSize: 16, fontWeight: 600, color: "#C6D3DF" }}>
        <span>← {left}</span><span>{right} →</span>
      </div>
    </div>
  );
}

/* What Vs30 actually is, drawn instead of described: a wave climbing out through
   the top 30 m of whatever is under this address. Dot density tracks how soft the
   class is, so the picture changes with the address like everything else here. */
function Section({ cls }) {
  const soft = Math.max(0, LETTERS.indexOf(cls));      // 0 = hard rock, 5 = worst
  const dots = 5 + soft * 4;
  return (
    <div style={{ flex: "0 0 auto", textAlign: "center" }}>
      <svg width="92" height="86" style={{ display: "block" }}>
        <rect x="0" y="6" width="76" height="3" fill="var(--ground)" opacity=".6" />
        <rect x="0" y="9" width="76" height="70" fill="var(--ground)"
              opacity={0.06 + soft * 0.022} />
        {Array.from({ length: dots }, (_, i) => (
          <circle key={i} cx={6 + ((i * 29) % 66)} cy={16 + ((i * 41) % 58)}
                  r={soft > 2 ? 2.4 : 1.5} fill="var(--ground)" opacity=".5" />))}
        {/* the wave, climbing */}
        <path d="M20 76 q5 -8 10 0 t10 0" fill="none" stroke="var(--top)" strokeWidth="1.8" />
        <path d="M35 72 L35 18" fill="none" stroke="var(--top)" strokeWidth="1.8" />
        <path d="M30 25 L35 16 L40 25" fill="none" stroke="var(--top)" strokeWidth="1.8"
              strokeLinejoin="round" />
        {/* the depth it is measured over */}
        <line x1="82" y1="9" x2="82" y2="79" stroke="var(--muted)" strokeWidth="1"
              strokeDasharray="3 3" />
        <line x1="78" y1="9" x2="86" y2="9" stroke="var(--muted)" strokeWidth="1" />
        <line x1="78" y1="79" x2="86" y2="79" stroke="var(--muted)" strokeWidth="1" />
        <text x="74" y="47" fontSize="11" fill="var(--muted)" textAnchor="end">30 m</text>
      </svg>
      <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 2, lineHeight: 1.25 }}>
        wave speed<br />through the top 30 m</div>
    </div>
  );
}

/* The real outline OSM has for this address, drawn small. "14-point outline" is a
   claim; the shape is the evidence. */
function Footprint({ geometry, size = 76 }) {
  if (!geometry?.length) return null;
  const k = Math.cos((geometry[0][0] * Math.PI) / 180);
  const pts = geometry.map(([la, lo]) => [lo * k, la]);
  const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
  const x0 = Math.min(...xs), y0 = Math.min(...ys);
  const w = Math.max(...xs) - x0 || 1e-9, h = Math.max(...ys) - y0 || 1e-9;
  const sc = (size - 8) / Math.max(w, h);
  const ox = (size - w * sc) / 2, oy = (size - h * sc) / 2;
  const d = pts.map(([x, y], i) =>
    `${i ? "L" : "M"}${((x - x0) * sc + ox).toFixed(1)},${(size - oy - (y - y0) * sc).toFixed(1)}`
  ).join(" ") + " Z";
  return (
    <svg width={size} height={size} style={{ flex: "0 0 auto" }}>
      <path d={d} fill="rgba(56,189,248,.22)" stroke="var(--top)" strokeWidth="1.5"
            strokeLinejoin="round" />
    </svg>
  );
}

export default function Site({ s }) {
  const [addr, setAddr] = useState(s.site?.address || "");
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState(null);
  const [deep, setDeep] = useState(false);
  const scroller = useRef(null);
  useEffect(() => { if (!addr && s.site?.address) setAddr(s.site.address); }, [s.site]);

  const lookup = async (a) => {
    setLoading(true); setErr(null);
    try {
      const d = await fetch(`/api/site?address=${encodeURIComponent(a)}`).then((r) => r.json());
      d.error ? setErr(d.error) : set({ site: d });
    } finally { setLoading(false); }
  };

  const site = s.site, sp = site?.usgs_spectrum, bf = site?.building_footprint;
  const cls = site?.site_class, letter = (cls || "")[0];
  const meaning = CLASSES[letter];
  const p = s.pinned;
  const measuredHz = p ? (p.location_median_hz ?? p.frequency_hz) : null;
  const floors = bf?.levels || 5;
  const coords = site?.latitude != null
    ? `${site.latitude.toFixed(4)}, ${site.longitude.toFixed(4)}` : null;
  const li = liqIndex(site?.liquefaction_susceptibility);

  return (
    <div ref={scroller} style={{ display: "flex", flexDirection: "column", gap: 13,
                  height: "100%", overflowY: "auto", paddingRight: 6 }}>
      <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
        <input value={addr} onChange={(e) => setAddr(e.target.value)}
               onKeyDown={(e) => e.key === "Enter" && lookup(addr)}
               placeholder="type any address"
               style={{ flex: 1, padding: "10px 12px", fontSize: "var(--body)", borderRadius: 8,
                        background: "var(--surface)", border: "1px solid var(--border)",
                        color: "var(--text)", fontFamily: "inherit" }} />
        <button className="btn" style={{ padding: "10px 18px", fontSize: "var(--body)" }}
                onClick={() => lookup(addr)}>Look up ⏎</button>
        <span className="empty" style={{ whiteSpace: "nowrap" }}>
          {coords ? <>real data for <b style={{ color: "var(--text)" }}>{coords}</b></>
                  : "type an address to look up its ground"}</span>
      </div>

      {err && <div className="card" style={{ borderColor: "var(--amber)", padding: "10px 14px" }}>
        <b>{err}</b> <span className="empty">— try one of the measured locations.</span></div>}

      <div style={{ display: "flex", gap: 13, flex: "0 0 auto" }}>
        <Card title="what it's standing on" source="WA DNR" flex={1.45}>
          {loading ? <div className="empty" style={{ marginTop: 14 }}>…</div> : <>
            <div style={{ display: "flex", gap: 14, alignItems: "flex-start", marginTop: 6 }}>
              <div style={{ minWidth: 0, flex: 1 }}>
                <div style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
                  <div style={{ fontSize: 62, fontWeight: 700, lineHeight: .9,
                                color: letter ? "var(--text)" : "var(--muted)" }}>
                    {letter || "D"}</div>
                  <div style={{ minWidth: 0 }}>
                    <div style={{ fontSize: 19, lineHeight: 1.2 }}>
                      {meaning?.[0] || "boundary class"}</div>
                    <div className="empty" style={{ fontSize: 13 }}>{meaning?.[1]}</div>
                  </div>
                </div>
                <div style={{ fontSize: 14, color: "var(--muted)", marginTop: 8, lineHeight: 1.4 }}>
                  {site?.site_class_assumed
                    ? <b style={{ color: "var(--text)" }}>No Washington coverage here — class D
                        assumed for the hazard lookup.</b>
                    : meaning?.[2]}
                </div>
              </div>
              <Section cls={letter || "D"} />
            </div>
            <Track steps={LETTERS} active={LETTERS.indexOf(letter)}
                   left="solid rock" right="soft mud" />
          </>}
        </Card>

        <Card title="can the ground turn to soup" source="WA DNR">
          <div style={{ fontSize: 38, marginTop: 12, textTransform: "capitalize", lineHeight: 1.1 }}>
            {loading ? "…" : site?.liquefaction_susceptibility || "unknown"}</div>
          <div style={{ fontSize: 14, color: "var(--muted)", marginTop: 8, lineHeight: 1.4 }}>
            Saturated loose ground can lose its strength mid-quake and behave like a
            liquid. Separate map layer, same coordinates.</div>
          <Track steps={LIQ} active={li}
                 left="stays solid" right="can liquefy" />
        </Card>

        <Card title="your building" source="OpenStreetMap">
          {/* The two numbers that make this building this building, side by side —
              and the pair the skyline underneath is about. */}
          <div style={{ display: "flex", gap: 20, alignItems: "flex-start", marginTop: 10 }}>
            <div>
              <div style={{ fontSize: 50, fontWeight: 700, lineHeight: .9,
                            color: bf?.levels ? "var(--text)" : "var(--border)" }}>
                {bf?.levels || "—"}</div>
              <div className="empty" style={{ marginTop: 4, fontSize: 14 }}>
                {bf?.levels ? "levels" : "levels unknown"}</div>
            </div>
            <div style={{ borderLeft: "1px solid var(--border)", paddingLeft: 20 }}>
              <div style={{ fontSize: 50, fontWeight: 700, lineHeight: .9,
                            color: measuredHz ? "var(--top)" : "var(--muted)",
                            fontVariantNumeric: "tabular-nums" }}>
                {(measuredHz || 10 / floors).toFixed(2)}</div>
              <div className="empty" style={{ marginTop: 4, fontSize: 14 }}>
                {measuredHz ? "sways per second, measured" : "sways per second, estimated"}</div>
            </div>
            <div style={{ marginLeft: "auto" }}><Footprint geometry={bf?.geometry} /></div>
          </div>
          <div style={{ fontSize: 14, color: "var(--muted)", marginTop: "auto", lineHeight: 1.4 }}>
            {bf?.name && <b style={{ color: "var(--text)" }}>{bf.name}. </b>}
            {bf?.geometry?.length
              ? `Real ${bf.geometry.length}-point outline, ${bf.address_matched
                  ? "matched by street number" : "matched to the nearest footprint"}.`
              : "No footprint on record for this address."}
            {bf?.year_built ? ` Built ${bf.year_built}.` : ""}
          </div>
        </Card>
      </div>

      <div className="card" style={{ flex: "1 1 auto", minHeight: 400, padding: "16px 20px 14px",
                                     display: "flex", flexDirection: "column" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline",
                      flex: "0 0 auto" }}>
          <div className="label">which buildings this ground shakes hardest</div>
          <div style={{ fontSize: 13, color: "var(--muted)" }}>
            USGS · ASCE 7-22 · risk category II</div>
        </div>
        <SwayScale spectrum={sp} measuredHz={measuredHz} floors={floors}
                   floorsKnown={!!bf?.levels} />
      </div>

      {/* Not deleted, just not first. The six parameters are in the Report, §8. */}
      {sp && <div className="card" style={{ flex: "0 0 auto", padding: "12px 20px",
                                            marginBottom: 4 }}>
        {/* The panel opens at the very bottom of a scrolling column, so it has to
            bring itself into view — and late enough that the chart has laid out. */}
        <button onClick={() => { setDeep((v) => !v);
                     setTimeout(() => { const el = scroller.current;
                       if (el) el.scrollTop = el.scrollHeight; }, 260); }}
          style={{ background: "none", border: "none", padding: 0, cursor: "pointer",
                   fontFamily: "inherit", fontSize: "var(--caption)", color: "var(--muted)",
                   display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ color: "var(--top)" }}>{deep ? "▾" : "▸"}</span>
          the engineering curve behind this — ASCE 7-22 design response spectrum
        </button>
        {deep && <>
          <div style={{ height: 260, marginTop: 10 }}>
            <HazardCurve spectrum={sp} period={measuredHz ? 1 / measuredHz : null}
                         t0={sp.t0} ts={sp.ts} />
          </div>
          <div className="empty" style={{ margin: "2px 0 10px", lineHeight: 1.45 }}>
            The same band as the skyline above, in the units a structural engineer
            works in. Higher means more shaking delivered to a building of that size —
            <b> g</b> is a multiple of gravity, so 1.0 g sideways is as hard as gravity
            pulls down.</div>
          <div style={{ display: "flex", gap: 26, flexWrap: "wrap", marginTop: 4 }}>
            {[["S_DS", sp.sds, "g"], ["S_D1", sp.sd1, "g"], ["T₀", sp.t0, "s"],
              ["T_S", sp.ts, "s"], ["SDC", sp.sdc, ""], ["PGA_M", sp.pgam, "g"]]
              .filter(([, v]) => v != null).map(([k, v, u]) => (
                <div key={k}>
                  <span style={{ fontSize: 13, color: "var(--muted)", letterSpacing: ".04em" }}>
                    {k}</span>{" "}
                  <b style={{ fontVariantNumeric: "tabular-nums" }}>{v}{u && ` ${u}`}</b>
                </div>))}
            <div className="empty" style={{ fontSize: 13 }}>
              full parameter table in the Report, §8</div>
          </div>
        </>}
      </div>}
    </div>
  );
}
