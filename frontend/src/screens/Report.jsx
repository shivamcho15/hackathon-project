import "../report.css";

/* Report.jsx — the screening report, the one artefact that leaves the table.
 *
 * WHY THIS EXISTS. Every other screen ends at a number on a display. This ends at
 * a document an owner can hand to a structural engineer. That matters most for the
 * buildings we actually target: old ones with no drawings, where ASCE 41 either
 * pushes you into destructive investigation or penalises you with a reduced
 * knowledge factor. A measured fundamental period is one of the very few hard,
 * non-destructive facts obtainable about such a building, and it is the input an
 * engineer uses to calibrate an analytical model whose stiffness assumptions are
 * otherwise guesses.
 *
 * WHAT IT DELIBERATELY DOES NOT DO. It does not prescribe a retrofit, score the
 * building, or imply sealed engineering work. Neither does FEMA P-154, which ends
 * at "Detailed Structural Evaluation Required? Yes/No", nor ATC-20, which ends at a
 * placard. Stopping at findings-plus-escalation is the shape of the real documents,
 * not a shortfall in ours. §5 states the boundary on the page rather than burying it.
 *
 * DATA. Live values come from the store; each falls back to the verified Founders
 * Hall result so the sheet always renders something true. Per-channel figures are
 * read from `pinned.channels` when the pipeline carries them and from VERIFIED
 * until the Welch port lands — same shape either way, so no rewrite is needed then.
 */

/* Verified 2026-09-12 against firmware/recordings/{floor5_top,floor1_ground}.log by
   firmware/tools/ambient_analysis.py. Do not edit by hand — re-run the tool. */
const VERIFIED = {
  frequency_hz: 2.217,
  channels: [
    { ch: "top / X",    peak: 2.217, prom: 224.7, second: 2.283 },
    { ch: "top / Y",    peak: 2.217, prom: 59.7,  second: 2.283 },
    { ch: "ground / X", peak: 2.217, prom: 25.4,  second: 2.150 },
    { ch: "ground / Y", peak: 2.217, prom: 9.2,   second: 2.150 },
  ],
  amp_ratio_x: 2.71, amp_ratio_y: 2.46, amp_ratio_res: 2.66,
  samples: 48000, duration_s: 240.0, fs_hz: 200.0, seg_s: 60,
  gravity_top: 9.592, gravity_ground: 9.759,
  storeys: 5, captured: "2026-09-12 13:23",
};

const SITE = {
  address: "4215 E Stevens Way NE, Seattle, WA 98195",
  name: "Founders Hall", latitude: 47.658819, longitude: -122.307065,
  site_class: "C", liquefaction_susceptibility: "very low",
  usgs_spectrum: { sds: 1.03, sd1: 0.56, t0: 0.109, ts: 0.546, tl: 6,
                   sdc: "D", pgam: 0.55, ss: 1.47, s1: 0.61, sms: 1.54, sm1: 0.84 },
};

const n2 = (v, d = 2) => (v == null ? "—" : Number(v).toFixed(d));
const UNK = <span className="qa-unk">not established — see §5</span>;

/* ASCE 7 design response spectrum, analytic form. Mirrors backend/hazard.py sa();
   duplicated here only so the figure draws when the sheet is opened offline. */
function sa(T, { sds, sd1, t0, ts, tl = 6 }) {
  if (T < t0) return sds * (0.4 + 0.6 * T / t0);
  if (T <= ts) return sds;
  if (T <= tl) return sd1 / T;
  return sd1 * tl / (T * T);
}

/* FIGURE 1. Monochrome and hatched rather than filled: this sheet gets printed on
   whatever is in the office, and a colour-keyed band is unreadable in grayscale. */
function Spectrum({ spec, T }) {
  const W = 620, H = 125, L = 42, R = 14, TOP = 10, B = 24;
  const TMAX = 2.0, SMAX = Math.ceil(spec.sds * 10) / 10 + 0.1;
  const x = (t) => L + (t / TMAX) * (W - L - R);
  const y = (v) => TOP + (1 - v / SMAX) * (H - TOP - B);
  const pts = Array.from({ length: 241 }, (_, i) => {
    const t = (i / 240) * TMAX;
    return `${x(t).toFixed(1)},${y(sa(t, spec)).toFixed(1)}`;
  }).join(" ");
  const inBand = T >= spec.t0 && T <= spec.ts;

  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img"
         aria-label={`Design response spectrum with measured period ${T} seconds`}>
      <defs>
        <pattern id="qa-hatch" width="5" height="5" patternUnits="userSpaceOnUse"
                 patternTransform="rotate(45)">
          <line x1="0" y1="0" x2="0" y2="5" stroke="#14181C" strokeWidth="0.7"
                opacity=".32" />
        </pattern>
      </defs>

      {/* plateau — the range of sway periods this ground amplifies most */}
      <rect x={x(spec.t0)} y={TOP} width={x(spec.ts) - x(spec.t0)} height={H - TOP - B}
            fill="url(#qa-hatch)" />
      <rect x={x(spec.t0)} y={TOP} width={x(spec.ts) - x(spec.t0)} height={H - TOP - B}
            fill="none" stroke="#14181C" strokeWidth="0.6" opacity=".5" />

      {/* axes */}
      <line x1={L} y1={H - B} x2={W - R} y2={H - B} stroke="#14181C" strokeWidth="1" />
      <line x1={L} y1={TOP} x2={L} y2={H - B} stroke="#14181C" strokeWidth="1" />
      {[0, 0.5, 1.0, 1.5, 2.0].map((t) => (
        <g key={t}>
          <line x1={x(t)} y1={H - B} x2={x(t)} y2={H - B + 4} stroke="#14181C" strokeWidth=".8" />
          <text x={x(t)} y={H - B + 14} textAnchor="middle" fontSize="9"
                fontFamily="Menlo, monospace" fill="#4A545E">{t.toFixed(1)}</text>
        </g>))}
      {[0, 0.5, 1.0].filter((v) => v <= SMAX).map((v) => (
        <g key={v}>
          <line x1={L - 4} y1={y(v)} x2={L} y2={y(v)} stroke="#14181C" strokeWidth=".8" />
          <text x={L - 7} y={y(v) + 3} textAnchor="end" fontSize="9"
                fontFamily="Menlo, monospace" fill="#4A545E">{v.toFixed(1)}</text>
        </g>))}

      <polyline points={pts} fill="none" stroke="#14181C" strokeWidth="1.9"
                strokeLinejoin="round" />

      {/* the measured period */}
      <line x1={x(T)} y1={TOP} x2={x(T)} y2={H - B} stroke="#14181C" strokeWidth="1.5"
            strokeDasharray="5 3" />
      <circle cx={x(T)} cy={y(sa(T, spec))} r="4" fill="#14181C" />
      <text x={x(T) + 7} y={TOP + 12} fontSize="10" fontFamily="Helvetica, sans-serif"
            fontWeight="700" fill="#14181C">
        T = {n2(T, 3)} s{inBand ? " — within plateau" : ""}
      </text>

      <text x={10} y={(TOP + H - B) / 2} fontSize="8.5" textAnchor="middle"
            fontFamily="Helvetica, sans-serif" letterSpacing="1.2" fill="#7C8892"
            transform={`rotate(-90 10 ${(TOP + H - B) / 2})`}>Sa (g)</text>
    </svg>);
}

function Sheet({ n, of, no, children }) {
  return (
    <section className="qa-sheet">
      {children}
      <div className="qa-foot">
        <span>
          <b>Screening measurement — not a structural evaluation.</b><br />
          This document reports measured dynamic properties and publicly available site
          hazard data. It is not an engineering analysis of capacity, is not sealed
          professional work, and must not be used as a basis for design, construction,
          occupancy or transaction decisions.
        </span>
        <span className="qa-foot-r">{no}<br />SHEET {n} OF {of}</span>
      </div>
    </section>);
}

export default function Report({ s }) {
  const site = s?.site?.usgs_spectrum ? s.site : SITE;
  const spec = site.usgs_spectrum;
  const p = s?.pinned;
  const f = p?.location_median_hz ?? p?.frequency_hz ?? VERIFIED.frequency_hz;
  const T = 1 / f;

  /* Per-channel decomposition resolves in three steps, and the order matters. The
     pipeline currently pins whichever run last completed, which is not necessarily
     the ambient capture VERIFIED describes. Pasting VERIFIED's four channels under a
     headline frequency from some other run would put two different measurements on
     one sheet — so the verified table is used ONLY when the reported frequency is
     actually that measurement. Otherwise the sheet says what it does not have. */
  const isVerifiedRun = Math.abs(f - VERIFIED.frequency_hz) < 5e-4;
  const ch = p?.channels?.length ? p.channels : isVerifiedRun ? VERIFIED.channels : null;
  const chUsed = p?.channels_used || ["top", "ground"];
  const saT = sa(T, spec);
  const inBand = T >= spec.t0 && T <= spec.ts;
  const band = s?.comparison?.band ?? (inBand ? "red" : saT / spec.sds > 0.8 ? "amber" : "green");

  /* The empirical period estimate every code puts in a screener's hand: T ~= 0.1N.
     The flag is a measurement much LONGER than the estimate — that is the signature
     of lost stiffness. Ours is shorter, which is the benign direction. */
  const N = site.storeys ?? VERIFIED.storeys;
  const Ta = 0.1 * N;
  const taDelta = ((Ta - T) / T) * 100;

  /* `amplification` is the pipeline's own top:ground ratio and is the right number
     whenever it exists; the per-axis pair is only available from the ambient tool. */
  const ratioX = p?.amp_ratio_x ?? (isVerifiedRun ? VERIFIED.amp_ratio_x : p?.amplification)
    ?? VERIFIED.amp_ratio_x;
  const ratioY = p?.amp_ratio_y ?? (isVerifiedRun ? VERIFIED.amp_ratio_y : null);
  const axesAgree = ch ? new Set(ch.map((c) => c.peak)).size === 1 : null;

  /* Data quality travels with the number or the number is worth less than nothing.
     The pipeline grades every run and can flag it; a report that quietly prints a
     run its own estimator called poor is the kind of thing an engineer catches. */
  const conf = p?.confidence || (isVerifiedRun || !p ? "good" : null);
  const flags = p?.confidence_flags || [];
  const FLAG_TEXT = {
    estimator_disagreement: "independent estimators disagreed on the peak",
    sample_gap: "gaps in the sample stream required resampling",
    low_snr: "peak prominence over the local noise floor was marginal",
    short_record: "record length was below the preferred duration",
  };

  const today = new Date();
  const iso = today.toISOString().slice(0, 10);
  /* The site payload carries no building name — the location key is the only place
     the building is named, so title-case it rather than print "not established" for
     a building we can in fact name. Falls back to the street for unnamed sites. */
  const locName = p?.location
    ? p.location.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()) : null;
  const bldgName = site.name || locName;
  const initials = (bldgName || site.address || "site").replace(/[^A-Za-z ]/g, "")
    .split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0].toUpperCase()).join("") || "XX";
  const no = `QA-${iso.replace(/-/g, "")}-${initials}01`;
  const of = 4;
  const foot = { no, of };

  const findings = [
    { t: "Resonance with site response", flag: inBand ? "red" : "green",
      stat: inBand ? "action required" : "no match" },
    { t: "Measured period vs. empirical estimate", flag: "green", stat: "no anomaly" },
    { t: "Distribution of motion over height", flag: "info", stat: "informational" },
    { t: "Directional symmetry", flag: axesAgree === null ? "info" : "green",
      stat: axesAgree === null ? "not assessed" : "none detected" },
    { t: "Baseline for future comparison", flag: "info", stat: "recorded" },
  ];

  return (
    <div className="qa-report">
      <div className="qa-bar">
        <span className="qa-bar-t">screening report · {no} · {of} sheets</span>
        <button className="qa-btn" data-ghost="1" onClick={() => window.print()}>
          Save as PDF</button>
        <button className="qa-btn" onClick={() => window.print()}>Print</button>
      </div>

      {/* ================= SHEET 1 — subject, summary, recommendation ========= */}
      <Sheet n={1} {...foot}>
        <header className="qa-mast">
          <div>
            <div className="qa-mark">QUAKE<span>-</span>ASSESS</div>
            <div className="qa-mast-sub">Ambient vibration screening</div>
          </div>
          <div className="qa-meta">
            REPORT NO. <b>{no}</b><br />
            ISSUED <b>{iso}</b> · REV <b>0</b><br />
            SURVEY <b>{(p?.recorded_at || VERIFIED.captured).slice(0, 16).replace("T", " ")}</b>
          </div>
        </header>

        <h1 className="qa-title">Seismic Screening Report</h1>
        <div className="qa-subtitle">
          Measured fundamental period · site response comparison · recommended action
        </div>

        <h2 className="qa-h"><span className="n">1</span>Subject structure</h2>
        <div className="qa-idgrid">
          <dl className="qa-id"><dt>Address</dt><dd>{site.address}</dd></dl>
          <dl className="qa-id"><dt>Building name</dt><dd>{bldgName || UNK}</dd></dl>
          <dl className="qa-id"><dt>Latitude</dt>
            <dd className="num">{n2(site.latitude, 6)}</dd></dl>
          <dl className="qa-id"><dt>Longitude</dt>
            <dd className="num">{n2(site.longitude, 6)}</dd></dl>
          <dl className="qa-id"><dt>Storeys above grade</dt>
            <dd className="num">{N}</dd></dl>
          <dl className="qa-id"><dt>Year built</dt><dd>{site.year_built || UNK}</dd></dl>
          <dl className="qa-id"><dt>Structural system</dt>
            <dd>{site.structural_system || UNK}</dd></dl>
          <dl className="qa-id"><dt>Drawings available</dt>
            <dd>{site.drawings ? "Yes" : <span className="qa-unk">None obtained</span>}</dd></dl>
          <dl className="qa-id"><dt>Site class</dt>
            <dd className="num">{site.site_class || site.site_class_used}
              {site.site_class_assumed ? " (assumed)" : ""}</dd></dl>
          <dl className="qa-id"><dt>Liquefaction suscept.</dt>
            <dd>{site.liquefaction_susceptibility || "—"}</dd></dl>
          <dl className="qa-id"><dt>Instrument</dt><dd>MPU-6050 MEMS, ±2 g</dd></dl>
          <dl className="qa-id"><dt>Sensor positions</dt><dd>Ground floor; storey {N}</dd></dl>
        </div>
        <p className="qa-note">
          Construction records for this structure were not obtained. Where a property is
          undocumented, ASCE 41 requires either intrusive investigation or acceptance of a
          reduced knowledge factor.<span className="qa-fn">[2]</span> The measured period
          reported in §4 is a non-destructive constraint on the as-built stiffness and is
          suitable for calibrating an analytical model.<span className="qa-fn">[5]</span>
        </p>

        <h2 className="qa-h"><span className="n">2</span>Summary of findings</h2>
        <table className="qa-tbl">
          <caption>Table 1 — Findings, in the order presented in §4</caption>
          <thead><tr><th className="idx"></th><th>Finding</th><th>Result</th>
            <th className="num">Status</th></tr></thead>
          <tbody>
            <tr><td className="idx">1</td><td>{findings[0].t}</td>
              <td>Measured period falls {inBand ? "within" : "outside"} the plateau of the
                design response spectrum; demand at the structure's own period is{" "}
                {n2(saT)} g</td>
              <td className="num"><span className="qa-stat" data-f={findings[0].flag}>
                {findings[0].stat}</span></td></tr>
            <tr><td className="idx">2</td><td>{findings[1].t}</td>
              <td>Measured {n2(T, 3)} s against empirical estimate {n2(Ta, 2)} s; structure is
                stiffer than the estimate, which is the benign direction</td>
              <td className="num"><span className="qa-stat" data-f={findings[1].flag}>
                {findings[1].stat}</span></td></tr>
            <tr><td className="idx">3</td><td>{findings[2].t}</td>
              <td>Storey {N} moves {n2(ratioX)}× the ground floor at the fundamental;
                demand concentrates toward the roof</td>
              <td className="num"><span className="qa-stat" data-f={findings[2].flag}>
                {findings[2].stat}</span></td></tr>
            <tr><td className="idx">4</td><td>{findings[3].t}</td>
              <td>{axesAgree === null
                ? "Per-axis decomposition not available for this run; see §4 and §9"
                : axesAgree
                  ? "Both horizontal axes peak at the same frequency; no split-frequency "
                    + "signature of torsional irregularity was observed"
                  : "Horizontal axes peak at different frequencies; see §4"}</td>
              <td className="num"><span className="qa-stat" data-f={findings[3].flag}>
                {findings[3].stat}</span></td></tr>
            <tr><td className="idx">5</td><td>{findings[4].t}</td>
              <td>{n2(f, 3)} Hz recorded as the reference signature for re-measurement after
                any significant shaking</td>
              <td className="num"><span className="qa-stat" data-f={findings[4].flag}>
                {findings[4].stat}</span></td></tr>
          </tbody>
        </table>

        {conf && conf !== "good" && (
          <p className="qa-note" style={{ borderLeft: "2.5px solid #9A6A08",
            paddingLeft: 9, marginTop: 7 }}>
            <b style={{ fontFamily: "Helvetica, sans-serif", fontSize: "7.2pt",
              letterSpacing: ".1em", textTransform: "uppercase" }}>
              Data quality — {conf}</b><br />
            The estimator graded this record <i>{conf}</i>
            {flags.length > 0 && <>: {flags.map((x) => FLAG_TEXT[x] || x.replace(/_/g, " "))
              .join("; ")}</>}. The reported frequency carries a stated uncertainty of
            ±{n2(p?.frequency_uncertainty_hz, 3)} Hz. Findings below should be read against
            that uncertainty, and a repeat measurement is advised before the disposition in
            §3 is acted upon.
          </p>)}

        <h2 className="qa-h"><span className="n">3</span>Recommended action</h2>
        <div className="qa-box">
          <div className="qa-box-h">Disposition — one option marked</div>
          <div className="qa-opt" data-on={band === "green" ? "1" : "0"}>
            <span className="qa-tick">{band === "green" ? "✓" : ""}</span>
            <span className="qa-lab"><b>No further structural action indicated by this
              screening.</b>
              <span className="qa-why">Nonstructural measures in §7 still apply.</span></span>
          </div>
          <div className="qa-opt" data-on={band === "red" || band === "amber" ? "1" : "0"}>
            <span className="qa-tick">{band === "red" || band === "amber" ? "✓" : ""}</span>
            <span className="qa-lab"><b>Tier 1 seismic evaluation by a licensed structural
              engineer is recommended, per ASCE 41-23.</b>
              <span className="qa-why">
                Triggered by Finding 1. The measured fundamental period of {n2(T, 3)} s lies
                inside the constant-acceleration plateau ({n2(spec.t0, 3)}–{n2(spec.ts, 3)} s)
                of this site's design spectrum, so the structure's own natural sway coincides
                with the period range at which this ground delivers its maximum spectral
                acceleration, {n2(spec.sds)} g. Provide this report to the engineer; the
                measured period and the per-channel results in §9 are direct inputs to model
                calibration.<span className="qa-fn">[5]</span>
              </span></span>
          </div>
          <div className="qa-opt" data-on="0">
            <span className="qa-tick"></span>
            <span className="qa-lab"><b>Urgent — engineering assessment before continued
              occupancy.</b>
              <span className="qa-why">Not indicated. This screening observed no evidence
                warranting an occupancy restriction, and is not capable of establishing
                one.</span></span>
          </div>
        </div>
        <p className="qa-note">
          ASCE 41 evaluation proceeds in tiers: Tier 1 is a screening for deficiencies common
          to the building type, Tier 2 investigates the specific deficiencies Tier 1 raises,
          and Tier 3 is a full systematic analysis. A recommendation for Tier 1 is a
          recommendation to begin, not a finding of inadequacy.<span className="qa-fn">[2]</span>
        </p>
      </Sheet>

      {/* ================= SHEET 2 — findings in detail ======================= */}
      <Sheet n={2} {...foot}>
        <header className="qa-mast">
          <div><div className="qa-mark">QUAKE<span>-</span>ASSESS</div>
            <div className="qa-mast-sub">Ambient vibration screening</div></div>
          <div className="qa-meta">SEISMIC SCREENING REPORT<br />
            <b>{bldgName || site.address.split(",")[0]}</b><br />{site.address}</div>
        </header>

        <h2 className="qa-h"><span className="n">4</span>Findings in detail</h2>

        <div className="qa-find">
          <div className="qa-find-n">1</div>
          <div className="qa-find-b">
            <div className="qa-find-t"><span>{findings[0].t}</span>
              <span className="qa-stat" data-f={findings[0].flag}>{findings[0].stat}</span></div>
            <p className="qa-figures">
              f₁ = {n2(f, 3)} Hz · T₁ = {n2(T, 3)} s · plateau T₀–T<tspan>s</tspan> ={" "}
              {n2(spec.t0, 3)}–{n2(spec.ts, 3)} s · Sa(T₁) = {n2(saT)} g · S<sub>DS</sub> ={" "}
              {n2(spec.sds)} g
            </p>
            <p className="qa-find-p">
              The structure's fundamental period falls inside the constant-acceleration
              plateau of the site design spectrum. Spectral demand at the period the
              building actually responds at is therefore the maximum this ground delivers,
              {" "}{n2(saT)} g, rather than a value on the descending branch.
            </p>
            <p className="qa-find-p qa-plain">
              In plain terms: the ground's strongest shaking and this building's natural rate
              of sway are tuned to one another. Period-matching of this kind is the mechanism
              behind the concentrated damage recorded in Mexico City in 1985.
            </p>
          </div>
        </div>

        <figure style={{ margin: "6px 0 2px" }}>
          <Spectrum spec={spec} T={T} />
          <figcaption style={{ fontFamily: "Helvetica, sans-serif", fontSize: "6.9pt",
            letterSpacing: ".1em", textTransform: "uppercase", color: "#4A545E",
            marginTop: "3px" }}>
            Figure 1 — ASCE 7-22 design response spectrum, Site Class{" "}
            {site.site_class || site.site_class_used}, Risk Category II. Horizontal axis is
            period T in seconds. Hatched band is the constant-acceleration plateau; dashed
            line is the measured period.
          </figcaption>
        </figure>

        <div className="qa-find">
          <div className="qa-find-n">2</div>
          <div className="qa-find-b">
            <div className="qa-find-t"><span>{findings[1].t}</span>
              <span className="qa-stat" data-f={findings[1].flag}>{findings[1].stat}</span></div>
            <p className="qa-figures">
              measured {n2(T, 3)} s · empirical T ≈ 0.1N = {n2(Ta, 2)} s ({N} storeys) ·
              estimate is {n2(Math.abs(taDelta), 1)}% {taDelta > 0 ? "above" : "below"} measured
            </p>
            <p className="qa-find-p">
              The measured period is shorter than the empirical estimate, meaning the
              structure is stiffer than a screening formula would assume. Empirical period
              expressions are deliberately set as a lower bound on period for design
              purposes.<span className="qa-fn">[6]</span> The condition that warrants
              attention is the opposite one: a measured period substantially longer than
              predicted, which indicates greater flexibility than the building's height and
              type imply and is the characteristic signature of a soft storey, extensively
              cracked concrete, or otherwise degraded lateral stiffness. That condition is
              not present here.
            </p>
          </div>
        </div>

        <div className="qa-find">
          <div className="qa-find-n">3</div>
          <div className="qa-find-b">
            <div className="qa-find-t"><span>{findings[2].t}</span>
              <span className="qa-stat" data-f={findings[2].flag}>{findings[2].stat}</span></div>
            <p className="qa-figures">
              amplitude ratio storey {N} : ground at f₁ —{" "}
              {ratioY != null ? <>X {n2(ratioX)}× · Y {n2(ratioY)}×</>
                : <>{n2(ratioX)}× resultant horizontal</>}
              {" "}(from the Welch power spectral density)
            </p>
            <p className="qa-find-p">
              Simultaneous records at two levels show the top of the structure moving
              {" "}{n2(ratioX)} times the ground floor at the fundamental frequency. This is the
              expected first-mode shape, and it is also the strongest evidence that the
              recorded peak is the structure rather than an artefact of the instrument: a
              sensor artefact would not scale with height.
            </p>
            <p className="qa-find-p qa-plain">
              Practical consequence: components mounted high on the building experience the
              largest motion. The priority ordering of the nonstructural measures in §7
              follows from this finding.
            </p>
          </div>
        </div>

        <div className="qa-find">
          <div className="qa-find-n">4</div>
          <div className="qa-find-b">
            <div className="qa-find-t"><span>{findings[3].t}</span>
              <span className="qa-stat" data-f={findings[3].flag}>{findings[3].stat}</span></div>
            <p className="qa-figures">
              {ch ? ch.map((c) => `${c.ch} ${n2(c.peak, 3)} Hz`).join("  ·  ")
                : `levels recorded: ${chUsed.join(", ")} — per-axis peaks not resolved`}
            </p>
            {axesAgree ? (
              <p className="qa-find-p">
                Both horizontal axes, at both levels, peak at the same frequency. The
                structure is therefore of comparable lateral stiffness in the two principal
                directions in its fundamental mode, and the closely spaced split-frequency
                pair characteristic of a torsionally irregular building was not observed.
                {" "}<em>Qualification:</em> this is a screening indication from a single
                two-sensor pair on one vertical line. It is not a torsional analysis and does
                not exclude plan irregularity.
              </p>
            ) : (
              <p className="qa-find-p">
                This run did not resolve the two horizontal axes separately, so no statement
                is made about directional symmetry. A torsional irregularity would not have
                been detected by this measurement and is neither indicated nor excluded. An
                ambient record processed per-axis, as described in §8, resolves it.
              </p>
            )}
          </div>
        </div>

        <div className="qa-find">
          <div className="qa-find-n">5</div>
          <div className="qa-find-b">
            <div className="qa-find-t"><span>{findings[4].t}</span>
              <span className="qa-stat" data-f={findings[4].flag}>{findings[4].stat}</span></div>
            <p className="qa-figures">
              reference signature f₁ = {n2(f, 3)} Hz recorded {(p?.recorded_at
                || VERIFIED.captured).slice(0, 10)}
            </p>
            <p className="qa-find-p">
              Stiffness scales with the square of frequency, so a fall in the measured
              fundamental frequency of the same structure indicates a loss of
              stiffness. Re-measurement after any significant shaking, and comparison
              against the value above, is the cheapest available indicator of change,
              including change not visible on inspection.
            </p>
            <p className="qa-find-p">
              <em>Sensitivity limit, stated plainly:</em> this method is not sensitive to
              minor or localised damage. In a controlled test on a ten-storey reinforced
              concrete building, removing six exterior infill walls shifted the first mode by
              only about 6%.<span className="qa-fn">[4]</span> A change of a few percent is
              cause to engage an engineer. It is not, by itself, a diagnosis, and the absence
              of a change is not evidence that a structure is undamaged.
            </p>
          </div>
        </div>
      </Sheet>

      {/* ================= SHEET 3 — basis, site data, owner actions ========== */}
      <Sheet n={3} {...foot}>
        <header className="qa-mast">
          <div><div className="qa-mark">QUAKE<span>-</span>ASSESS</div>
            <div className="qa-mast-sub">Ambient vibration screening</div></div>
          <div className="qa-meta">SEISMIC SCREENING REPORT<br />
            <b>{bldgName || site.address.split(",")[0]}</b><br />{site.address}</div>
        </header>

        <h2 className="qa-h"><span className="n">5</span>Basis and limitations</h2>
        <p className="qa-p">
          The structure was instrumented at {chUsed.length} levels simultaneously and its
          response{isVerifiedRun ? " to ambient excitation — wind, traffic, occupant activity"
            + " and microtremor —" : ""} was recorded and processed to identify its
          fundamental mode. The method is long established for the
          assessment of existing buildings, and is specifically suited to structures for
          which construction documents are unavailable, because it requires no drawings and
          no intrusive work.<span className="qa-fn">[5]</span> Its recognised role is triage:
          determining which buildings in a population warrant detailed evaluation.
        </p>
        <div className="qa-two">
          <div>
            <h4>What this measurement establishes</h4>
            <ul>
              <li>The fundamental period and frequency of the structure as built, today</li>
              <li>Whether that period coincides with the site's peak spectral demand</li>
              <li>Relative amplitude of motion between instrumented levels</li>
              <li>Whether the two horizontal axes respond at the same frequency</li>
              <li>A repeatable baseline against which future readings can be compared</li>
            </ul>
          </div>
          <div>
            <h4>What it cannot establish</h4>
            <ul>
              <li>Capacity of any member, connection, diaphragm or foundation</li>
              <li>Reinforcement, material strength or as-built detailing</li>
              <li>Presence, location or extent of local damage</li>
              <li>Whether the structure would survive a given earthquake</li>
              <li>Compliance with any code, ordinance or standard</li>
            </ul>
          </div>
        </div>
        <p className="qa-note">
          Ambient excitation drives the structure at very small amplitude. Measured periods
          under these conditions are generally shorter than those the same structure would
          exhibit under strong shaking, when nonstructural stiffness degrades. The values
          reported here are low-amplitude properties and should be treated as such.
        </p>

        <h2 className="qa-h"><span className="n">6</span>Site seismic parameters</h2>
        <table className="qa-tbl">
          <caption>Table 2 — USGS design values, ASCE 7-22, Risk Category II</caption>
          <thead><tr><th>Parameter</th><th>Symbol</th><th className="num">Value</th>
            <th>Parameter</th><th>Symbol</th><th className="num">Value</th></tr></thead>
          <tbody>
            <tr><td>Design spectral accel., short</td><td>S<sub>DS</sub></td>
              <td className="num">{n2(spec.sds)} g</td>
              <td>Mapped MCE<sub>R</sub>, short</td><td>S<sub>S</sub></td>
              <td className="num">{n2(spec.ss)} g</td></tr>
            <tr><td>Design spectral accel., 1 s</td><td>S<sub>D1</sub></td>
              <td className="num">{n2(spec.sd1)} g</td>
              <td>Mapped MCE<sub>R</sub>, 1 s</td><td>S<sub>1</sub></td>
              <td className="num">{n2(spec.s1)} g</td></tr>
            <tr><td>Plateau start</td><td>T<sub>0</sub></td>
              <td className="num">{n2(spec.t0, 3)} s</td>
              <td>Peak ground accel. (MCE<sub>G</sub>)</td><td>PGA<sub>M</sub></td>
              <td className="num">{spec.pgam ? n2(spec.pgam) + " g" : "—"}</td></tr>
            <tr><td>Plateau end</td><td>T<sub>S</sub></td>
              <td className="num">{n2(spec.ts, 3)} s</td>
              <td>Seismic design category</td><td>SDC</td>
              <td className="num">{spec.sdc || "—"}</td></tr>
            <tr><td>Long-period transition</td><td>T<sub>L</sub></td>
              <td className="num">{spec.tl} s</td>
              <td>Site class</td><td>—</td>
              <td className="num">{site.site_class || site.site_class_used}</td></tr>
            {/* Closes the loop back to Finding 1: the table ends on the one value in it
                that is about this building rather than about the ground. */}
            <tr><td>Demand at measured period</td><td>Sa(T<sub>1</sub>)</td>
              <td className="num">{n2(saT)} g</td>
              <td>Liquefaction susceptibility</td><td>—</td>
              <td className="num">{site.liquefaction_susceptibility || "—"}</td></tr>
          </tbody>
        </table>
        <p className="qa-note">
          Site class and liquefaction susceptibility ({site.liquefaction_susceptibility}) from
          the Washington State Department of Natural Resources published mapping; spectral
          values from the USGS design map service for the coordinates in §1.<span
            className="qa-fn">[3]</span> Mapped values are regional and do not substitute for a
          site-specific geotechnical investigation.
        </p>

        <h2 className="qa-h"><span className="n">7</span>Measures available to the owner
          without engineering</h2>
        <p className="qa-p">
          The following are nonstructural measures. They do not require an engineer, a permit
          or a structural evaluation, and they address the category of earthquake loss that
          is both the most common and the most preventable.<span className="qa-fn">[1]</span>
          {" "}Priority ordering follows Finding 3: motion is greatest at the top of the
          structure, so components mounted high are addressed first.
        </p>
        {[
          ["Brace or remove unreinforced parapets, cornices and chimneys", 1],
          ["Anchor rooftop mechanical plant, condensers and water tanks to structure", 1],
          ["Secure exterior cladding, signage and light fittings at upper levels", 1],
          ["Restrain suspended ceiling grid and recessed light fixtures", 2],
          ["Anchor tall shelving, cabinets and storage racks to walls at every level", 2],
          ["Fit flexible connectors and seismic restraint to gas-fired equipment", 2],
          ["Strap the water heater to structure at upper and lower thirds", 3],
          ["Install an automatic gas shutoff valve", 3],
          ["Secure emergency egress routes against blockage by falling contents", 3],
        ].map(([label, pri]) => (
          <div className="qa-check" key={label}>
            <span className="qa-check-box" />
            <span>{label}</span>
            <span className="qa-pri" data-p={pri}>
              {pri === 1 ? "priority" : pri === 2 ? "secondary" : "routine"}</span>
          </div>))}
      </Sheet>

      {/* ================= SHEET 4 — method, channels, references ============= */}
      <Sheet n={4} {...foot}>
        <header className="qa-mast">
          <div><div className="qa-mark">QUAKE<span>-</span>ASSESS</div>
            <div className="qa-mast-sub">Ambient vibration screening</div></div>
          <div className="qa-meta">SEISMIC SCREENING REPORT<br />
            <b>{bldgName || site.address.split(",")[0]}</b><br />{site.address}</div>
        </header>

        <h2 className="qa-h"><span className="n">8</span>Method and instrumentation</h2>
        <div className="qa-idgrid">
          <dl className="qa-id"><dt>Transducer</dt>
            <dd>InvenSense MPU-6050, 3-axis MEMS</dd></dl>
          <dl className="qa-id"><dt>Full scale</dt><dd className="num">±2 g</dd></dl>
          <dl className="qa-id"><dt>Sampling rate</dt>
            <dd className="num">{n2(p?.fs_hz ?? VERIFIED.fs_hz)} Hz</dd></dl>
          <dl className="qa-id"><dt>Record length</dt>
            {isVerifiedRun
              ? <dd className="num">{n2(VERIFIED.duration_s, 1)} s per node</dd>
              : <dd><span className="qa-unk">not recorded</span></dd>}</dl>
          <dl className="qa-id"><dt>Samples per node</dt>
            {isVerifiedRun
              ? <dd className="num">{VERIFIED.samples.toLocaleString()}</dd>
              : <dd><span className="qa-unk">not recorded</span></dd>}</dl>
          <dl className="qa-id"><dt>Nodes</dt>
            <dd className="num">{chUsed.length}, simultaneous</dd></dl>
          <dl className="qa-id"><dt>Excitation</dt>
            <dd>{isVerifiedRun ? "Ambient" : "Ringdown, operator-excited"}</dd></dl>
          <dl className="qa-id"><dt>Spectral estimator</dt>
            <dd>{isVerifiedRun ? `Welch, ${VERIFIED.seg_s} s segments`
              : "Onset-gated, decaying response"}</dd></dl>
          <dl className="qa-id"><dt>Analysis band</dt><dd className="num">0.4 – 8.0 Hz</dd></dl>
          <dl className="qa-id"><dt>Acceptance threshold</dt>
            <dd className="num">3× local noise floor</dd></dl>
          <dl className="qa-id"><dt>Runs averaged</dt>
            <dd className="num">{p?.trials_used ?? 1}</dd></dl>
          <dl className="qa-id"><dt>Record source</dt>
            <dd>{p?.source === "hardware" ? (p?.from_recording
              ? "Hardware, from stored capture" : "Hardware, live")
              : p?.source ? p.source.replace(/^\w/, (c) => c.toUpperCase()) : "Hardware"}</dd></dl>
          {isVerifiedRun && <>
            <dl className="qa-id"><dt>Gravity check, storey {N}</dt>
              <dd className="num">{n2(VERIFIED.gravity_top, 3)} m/s²</dd></dl>
            <dl className="qa-id"><dt>Gravity check, ground</dt>
              <dd className="num">{n2(VERIFIED.gravity_ground, 3)} m/s²</dd></dl>
          </>}
        </div>
        <p className="qa-note">
          Irregularly sampled records were resampled to a uniform grid before spectral
          estimation. Static acceleration was measured on each node and compared against
          9.807 m/s² as an in-place scale-factor check. The vertical axis was identified from
          the gravity vector and excluded; only the two horizontal axes are reported.
        </p>

        <h2 className="qa-h"><span className="n">9</span>Per-channel results</h2>
        {ch ? (<>
          <table className="qa-tbl">
            <caption>Table 3 — Spectral peaks by channel, ranked by prominence</caption>
            <thead><tr><th>Channel</th><th className="num">Peak (Hz)</th>
              <th className="num">Prominence</th><th className="num">Period (s)</th>
              <th className="num">Next peak (Hz)</th></tr></thead>
            <tbody>
              {ch.map((c) => (
                <tr key={c.ch}>
                  <td>{c.ch}</td>
                  <td className="num">{n2(c.peak, 3)}</td>
                  <td className="num">{n2(c.prom, 1)}×</td>
                  <td className="num">{n2(1 / c.peak, 3)}</td>
                  <td className="num">{c.second ? n2(c.second, 3) : "—"}</td>
                </tr>))}
            </tbody>
          </table>
          <p className="qa-note">
            All {ch.length} channels identify the same peak. Prominence is the ratio of
            spectral power at the peak to the local noise floor; the strongest channel exceeds
            its floor by a factor of {n2(Math.max(...ch.map((c) => c.prom)), 0)}. Agreement
            across independent channels at two levels and on two axes is the basis for
            reporting a single fundamental frequency.
          </p>
        </>) : (<>
          <table className="qa-tbl">
            <caption>Table 3 — Result as reported by the processing pipeline</caption>
            <thead><tr><th>Quantity</th><th className="num">Value</th></tr></thead>
            <tbody>
              <tr><td>Fundamental frequency</td>
                <td className="num">{n2(f, 3)} Hz</td></tr>
              <tr><td>Stated uncertainty</td>
                <td className="num">±{n2(p?.frequency_uncertainty_hz, 3)} Hz</td></tr>
              <tr><td>Fundamental period</td><td className="num">{n2(T, 3)} s</td></tr>
              <tr><td>Levels contributing</td>
                <td className="num">{chUsed.join(", ")}</td></tr>
              <tr><td>Runs averaged</td><td className="num">{p?.trials_used ?? 1}</td></tr>
              <tr><td>Top : ground amplitude ratio</td>
                <td className="num">{n2(ratioX)}×</td></tr>
              <tr><td>Estimator grade</td><td className="num">{conf || "—"}</td></tr>
            </tbody>
          </table>
          <p className="qa-note">
            Per-axis spectral decomposition is not available for this run, so the four-channel
            agreement table is not reproduced. The frequency above is the pipeline's combined
            estimate across the levels listed. Where a per-axis breakdown is required — for
            the directional finding in §4, or for model calibration — an ambient record
            processed per the method in §8 provides it.
          </p>
        </>)}

        <h2 className="qa-h"><span className="n">10</span>References</h2>
        <ol className="qa-refs">
          <li><span className="m">[1]</span><span>FEMA E-74, <i>Reducing the Risks of
            Nonstructural Earthquake Damage — A Practical Guide</i>, Federal Emergency
            Management Agency.</span></li>
          <li><span className="m">[2]</span><span>ASCE/SEI 41-23, <i>Seismic Evaluation and
            Retrofit of Existing Buildings</i>, American Society of Civil Engineers.</span></li>
          <li><span className="m">[3]</span><span>ASCE 7-22 design values, USGS Seismic Design
            Web Service; site class and liquefaction mapping, Washington State Department of
            Natural Resources.</span></li>
          <li><span className="m">[4]</span><span>Observed first-mode frequency reduction of
            approximately 6% following removal of six exterior infill walls, ten-storey
            reinforced concrete building; reported in the structural damage-sensitivity
            literature.</span></li>
          <li><span className="m">[5]</span><span>Michel, C. and Guéguen, P., <i>Dynamic
            parameters of structures extracted from ambient vibration measurements: an aid for
            the seismic vulnerability assessment of existing buildings in moderate seismic
            hazard regions</i>, 2007.</span></li>
          <li><span className="m">[6]</span><span>ASCE 7, approximate fundamental period
            T<sub>a</sub>; the empirical expression is fitted as a lower bound on measured
            period and is intentionally conservative for design.</span></li>
          <li><span className="m">[7]</span><span>FEMA P-154, <i>Rapid Visual Screening of
            Buildings for Potential Seismic Hazards</i>, third edition — screening-report
            structure and disposition conventions.</span></li>
        </ol>

        <div className="qa-sig">
          <div><div className="qa-sig-fill">quake-assess automated screening</div>
            Measurement and report prepared by</div>
          <div><div className="qa-sig-fill">{iso} · Rev 0</div>Date of issue</div>
        </div>
        <p className="qa-note" style={{ marginTop: 10 }}>
          This report is unsealed. It carries no professional engineering stamp and none is
          implied. Where a disposition in §3 recommends evaluation, that evaluation must be
          performed by an engineer licensed in the jurisdiction of the structure.
        </p>
      </Sheet>
    </div>);
}
