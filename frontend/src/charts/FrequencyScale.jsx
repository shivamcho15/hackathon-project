/* Where a sway rate sits among real buildings, and which rates matter HERE.

   Band edges follow the code's own period formula T ~ 0.1N (N = storeys), so
   f ~ 10/N: two storeys is about 5 Hz, six is about 1.7, fifteen is about 0.7,
   forty is about 0.25. That is a rule of thumb, not a measurement, and is labelled
   as one.

   The shaded band is NOT a rule of thumb — it is this address's own USGS spectrum
   plateau, 1/Ts to 1/T0, so it moves when the address does. */

const LO = 0.2, HI = 12;
const pos = (f) => (Math.log(Math.min(HI, Math.max(LO, f))) - Math.log(LO)) /
                   (Math.log(HI) - Math.log(LO)) * 100;

const BANDS = [
  [0.2, 0.5, "skyscraper", "20–40 floors"],
  [0.5, 1.4, "high-rise", "7–15 floors"],
  [1.4, 3.5, "mid-rise", "3–7 floors"],
  [3.5, 12, "house / low-rise", "1–2 floors"],
];

export default function FrequencyScale({ measured, t0, ts, floors }) {
  const worstLo = ts ? 1 / ts : null;      // slow edge of the plateau
  const worstHi = t0 ? 1 / t0 : null;      // fast edge
  return (
    <div>
      <div style={{ position: "relative", height: 74, marginTop: 10 }}>
        {worstLo && (
          <div title="this ground amplifies most in here"
               style={{ position: "absolute", top: 0, bottom: 26,
                        left: `${pos(worstLo)}%`, width: `${pos(worstHi) - pos(worstLo)}%`,
                        background: "rgba(239,68,68,.20)", border: "1px solid rgba(239,68,68,.5)",
                        borderRadius: 4 }} />)}
        {BANDS.map(([a, b, name, sub]) => (
          <div key={name} style={{ position: "absolute", top: 4, bottom: 30,
                                   left: `${pos(a)}%`, width: `${pos(b) - pos(a)}%`,
                                   borderLeft: "1px solid var(--border)", padding: "2px 0 0 6px",
                                   overflow: "hidden" }}>
            <div style={{ fontSize: 13, color: "var(--text)", whiteSpace: "nowrap" }}>{name}</div>
            <div style={{ fontSize: 12, color: "var(--muted)", whiteSpace: "nowrap" }}>{sub}</div>
          </div>))}
        {measured != null && (
          <div style={{ position: "absolute", top: 0, bottom: 26, left: `${pos(measured)}%`,
                        width: 2, background: "var(--text)" }}>
            <div style={{ position: "absolute", bottom: -25, left: -32, width: 78,
                          textAlign: "center", fontSize: 13, fontWeight: 700 }}>
              {measured.toFixed(2)} Hz</div>
          </div>)}
        <div style={{ position: "absolute", bottom: 12, left: 0, right: 0, height: 1,
                      background: "var(--border)" }} />
        {[0.2, 0.5, 1, 2, 5, 10].map((f) => (
          <div key={f} style={{ position: "absolute", bottom: 0, left: `${pos(f)}%`,
                                fontSize: 12, color: "var(--muted)", transform: "translateX(-50%)" }}>
            {f}</div>))}
      </div>
      <div className="empty" style={{ marginTop: 16, lineHeight: 1.55 }}>
        Taller buildings sway slower. A house is around 5–10 Hz; a downtown tower is
        under half a hertz. The rough rule engineers use is one tenth of a second per
        floor, so a {floors}-floor building should land near{" "}
        <b style={{ color: "var(--text)" }}>{(10 / Math.max(floors, 1)).toFixed(1)} Hz</b>.
        {worstLo && <> The red band is what makes this address specific:{" "}
          <b style={{ color: "var(--text)" }}>{worstLo.toFixed(1)}–{worstHi.toFixed(1)} Hz</b>{" "}
          is where <i>this</i> ground amplifies hardest — roughly{" "}
          {Math.max(1, Math.round(10 / worstHi))}–{Math.round(10 / worstLo)} floor buildings.</>}
      </div>
    </div>
  );
}
