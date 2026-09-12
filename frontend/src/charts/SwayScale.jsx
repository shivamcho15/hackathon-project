/* SwayScale — the one picture on the Site screen.
 *
 * The whole project rests on one idea a homeowner has never heard: every building
 * has a rate it sways at, every patch of ground has a rate it shakes hardest at,
 * and trouble is when those two are the same number. A response spectrum states
 * that in units nobody outside the field reads. This states it as a skyline.
 *
 * Horizontal axis is sway rate. Tall buildings sway slowly, so the axis doubles as
 * a height axis and is LABELLED in floors — the unit the person at the table
 * actually owns. The floor labels come from the code's own rule of thumb, T ~= 0.1N
 * (one tenth of a second per floor), and are marked "about" because that is what a
 * rule of thumb is.
 *
 * The two things on here that are NOT rules of thumb are the two that matter:
 * the shaded band is this address's own USGS spectrum plateau (1/Ts to 1/T0), and
 * the highlighted building is placed at its MEASURED frequency. Both move when the
 * address does.
 *
 * Each building leans at its own rate, and how far it leans is Sa(T)/S_DS at its
 * own period — the same ratio backend/hazard.py calls the resonance score. So the
 * buildings standing in the band visibly swing wider than the ones outside it,
 * which is the entire point of the screen, made without a paragraph.
 */

const MAXE = 40;                       // floors at the right edge
const L = Math.log(MAXE);
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const pos = (n) => (Math.log(clamp(n, 1, MAXE)) / L) * 100;
const posHz = (hz) => pos(10 / hz);    // T ~= 0.1N  =>  N ~= 10/f
/* Inset, so the bungalow at the left end and the tower at the right end stand on
   the ruler rather than half off the edge of it. */
const X = (n) => 3.5 + pos(n) * 0.95;

/* ASCE 7 design spectrum, analytic. Mirrors backend/hazard.py sa(); duplicated
   here only so the lean amplitudes draw without a round trip. */
function sa(T, { sds, sd1, t0, ts, tl = 6 }) {
  if (T < t0) return sds * (0.4 + 0.6 * T / t0);
  if (T <= ts) return sds;
  if (T <= tl) return sd1 / T;
  return sd1 * tl / (T * T);
}

const REPS = [1, 2, 4, 8, 16, 32];
const FLOOR_LABEL = { 1: "1 floor", 32: "32 floors" };
const hOf = (n) => 30 + 170 * (Math.log(clamp(n, 1, MAXE)) / L);
const wOf = (n) => (n <= 1 ? 62 : 28 + 17 * (Math.log(clamp(n, 1, MAXE)) / L));

const hzLabel = (f) => (f >= 10 ? String(Math.round(f)) : f.toFixed(1));

const GROUND = 58;                     // px from the bottom to the ground surface

/* A building. Boxy on purpose — it has to read as a building at two metres. */
function Body({ floors, colour, accent }) {
  const n = clamp(floors, 1, MAXE);
  const w = wOf(n), h = hOf(n);
  const rows = Math.max(1, Math.min(Math.round(n), 11));
  const lines = Array.from({ length: rows - 1 }, (_, i) => ((i + 1) * h) / rows);
  const cap = n >= 12 ? 0.16 : 0;      // setback on the tall ones reads as a skyline

  return (
    <svg width={w} height={h} style={{ display: "block", overflow: "visible",
           filter: accent ? "drop-shadow(0 0 12px rgba(56,189,248,.45))" : "none" }}>
      {floors <= 1 ? (
        <>
          <polygon points={`1,${h * 0.42} ${w / 2},1 ${w - 1},${h * 0.42}`} fill={colour} />
          <rect x={w * 0.08} y={h * 0.42} width={w * 0.84} height={h * 0.58} fill={colour} />
          <rect x={w / 2 - 4} y={h - 10} width="8" height="10" fill="#0B0F14" opacity=".55" />
        </>
      ) : (
        <>
          {cap > 0 && <rect x={w * 0.28} y="0" width={w * 0.44} height={h * cap} fill={colour} />}
          <rect x="0" y={h * cap} width={w} height={h * (1 - cap)} fill={colour} />
          {lines.filter((y) => y > h * cap).map((y) => (
            <line key={y} x1="0" y1={y} x2={w} y2={y} stroke="#0B0F14" strokeWidth="1"
                  opacity=".38" />))}
          <line x1={w / 2} y1={h * cap} x2={w / 2} y2={h} stroke="#0B0F14" strokeWidth="1"
                opacity=".22" />
        </>
      )}
    </svg>
  );
}

/* One building, planted on the ground line at `left`, leaning at its own rate. */
function Tower({ left, floors, period, spec, colour, accent, phase }) {
  const ratio = spec ? clamp(sa(period, spec) / spec.sds, 0, 1) : 0.4;
  const h = hOf(clamp(floors, 1, MAXE));
  // Lean is set in PIXELS of tip travel first, then converted to an angle, so a
  // bungalow in the band still visibly buzzes instead of being too short to see.
  // The exponent widens the gap between in-band and out: the contrast IS the point.
  const amp = clamp((Math.atan((14 * ratio ** 1.6) / h) * 180) / Math.PI, 0.5, 5.5);
  const dur = clamp(period * 2, 0.5, 4);
  return (
    <div style={{ position: "absolute", bottom: GROUND, left: `${left}%`,
                  transform: "translateX(-50%)" }}>
      <div className="sway" style={{ "--amp": amp.toFixed(2), "--dur": `${dur.toFixed(2)}s`,
                                     animationDelay: `${phase}s` }}>
        <Body floors={floors} colour={colour} accent={accent} />
      </div>
    </div>
  );
}

export default function SwayScale({ spectrum, measuredHz, floors = 5,
                                   floorsKnown = true }) {
  const spec = spectrum?.sds ? spectrum : null;
  const bandLo = spec ? 10 * spec.t0 : null;     // fast/short edge, in floors
  const bandHi = spec ? 10 * spec.ts : null;     // slow/tall edge
  const hzLo = spec ? 1 / spec.ts : null;        // same band, in hertz
  const hzHi = spec ? 1 / spec.t0 : null;

  const hz = measuredHz || 10 / Math.max(floors, 1);
  const T = 1 / hz;
  const inBand = spec ? T >= spec.t0 && T <= spec.ts : false;
  const mine = posHz(hz);

  return (
    /* Grows into whatever height the card has: the buildings stand on the bottom,
       so spare room becomes sky rather than a gap under the picture. */
    <div style={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0,
                  justifyContent: "center" }}>
      <div style={{ position: "relative", flex: "0 0 auto", height: 330 }}>
        {/* The band: not a rule of thumb — this address's own spectrum plateau. */}
        {spec && (
          <div style={{ position: "absolute", bottom: GROUND - 2, height: 250,
                        left: `${X(bandLo)}%`, width: `${X(bandHi) - X(bandLo)}%`,
                        background: "linear-gradient(rgba(167,139,250,0), rgba(167,139,250,.20))",
                        borderLeft: "1px dashed rgba(167,139,250,.45)",
                        borderRight: "1px dashed rgba(167,139,250,.45)" }}>
            <div style={{ textAlign: "center", marginTop: 6, fontSize: 12.5, letterSpacing: ".08em",
                          color: "var(--ground)", opacity: .95, whiteSpace: "nowrap" }}>
              THIS GROUND HITS THESE HARDEST</div>
          </div>)}

        {/* Reference buildings. The one nearest yours steps aside rather than
            standing on top of it. */}
        {REPS.filter((n) => Math.abs(pos(n) - mine) > 7).map((n, i) => (
          <Tower key={n} left={X(n)} floors={n} period={0.1 * n} spec={spec}
                 colour="#3A4A5C" phase={-0.31 * i} />))}

        {/* Yours, at its measured rate. */}
        <Tower left={X(10 / hz)} floors={floors} period={T} spec={spec}
               colour="var(--top)" accent phase={-0.17} />
        <div style={{ position: "absolute", left: `${X(10 / hz)}%`, transform: "translateX(-50%)",
                      bottom: GROUND + hOf(clamp(floors, 1, MAXE)) + 9, textAlign: "center",
                      whiteSpace: "nowrap" }}>
          <div style={{ fontSize: 12, letterSpacing: ".1em", color: "var(--top)",
                        fontWeight: 700 }}>YOUR BUILDING</div>
          <div style={{ fontSize: 15, fontVariantNumeric: "tabular-nums" }}>
            {floors} floors<span style={{ color: "var(--muted)" }}>
              {floorsKnown ? "" : " assumed"}</span> · {hz.toFixed(2)} Hz
            <span style={{ color: "var(--muted)" }}>{measuredHz ? " measured" : " estimated"}</span>
          </div>
        </div>

        {/* Ground surface. */}
        <div style={{ position: "absolute", left: 0, right: 0, bottom: GROUND - 3, height: 3,
                      background: "var(--ground)", opacity: .6 }} />
        <div style={{ position: "absolute", left: 0, right: 0, bottom: GROUND - 21, height: 18,
                      background: "linear-gradient(rgba(167,139,250,.22), rgba(167,139,250,0))" }} />

        {/* Two units on one ruler: floors, because that is what people own, and
            hertz, because that is what the sensor measures. */}
        {/* Same rule as the scales in the cards above: the two ENDS carry the
            meaning of the whole ruler, so they are sized to be read first. */}
        {REPS.map((n, i) => {
          const end = i === 0 || i === REPS.length - 1;
          return (
            <div key={n} style={{ position: "absolute", left: `${X(n)}%`,
                                  transform: "translateX(-50%)", bottom: 0, textAlign: "center",
                                  whiteSpace: "nowrap" }}>
              <div style={{ height: 7, width: 1, margin: "0 auto 5px",
                            background: end ? "#C6D3DF" : "var(--border)" }} />
              <div style={{ fontSize: end ? 18 : 14, fontWeight: end ? 700 : 400,
                            color: end ? "#C6D3DF" : "var(--text)" }}>
                {FLOOR_LABEL[n] || n}</div>
              <div style={{ fontSize: end ? 15 : 13, marginTop: 1,
                            color: end ? "#9BAAB8" : "var(--muted)" }}>
                {hzLabel(10 / n)} Hz{end ? (i === 0 ? " — fast" : " — slow") : ""}</div>
            </div>);
        })}
      </div>

      <div style={{ fontSize: "var(--caption)", color: "var(--muted)", lineHeight: 1.55,
                    marginTop: 10 }}>
        Taller buildings sway slower — about a tenth of a second per floor.
        {spec && <> This ground amplifies{" "}
          <b style={{ color: "var(--ground)" }}>{hzLo.toFixed(1)}–{hzHi.toFixed(1)} Hz</b>{" "}
          hardest, which is roughly{" "}
          <b style={{ color: "var(--ground)" }}>
            {Math.max(1, Math.round(bandLo))}–{Math.round(bandHi)} floor</b> buildings.</>}
        {" "}Yours sways at <b style={{ color: "var(--text)" }}>{hz.toFixed(2)} Hz</b>
        {spec && (inBand ? " — inside that range." : " — outside that range.")}
        <div style={{ fontSize: 13, opacity: .72, marginTop: 3 }}>
          Each building leans at its own rate, slowed to be watchable. How far it leans is
          how hard this ground drives a building that size.</div>
      </div>
    </div>
  );
}
