/* Between judges the laptop becomes the printed sign: one huge number on a dark
   screen, visible from across the room. Near-zero cost, and it works on every judge
   who walks past without stopping. Any keypress exits. */
export default function Attract({ s, onExit }) {
  const p = s.pinned;
  const f = p ? (p.location_median_hz ?? p.frequency_hz) : null;
  const c = s.comparison;
  const real = p?.source === "hardware";
  return (
    <div className="overlay" style={{ cursor: "none" }} onClick={onExit}>
      <div className="label" style={{ letterSpacing: ".18em" }}>
        {(p?.location || "seismic resonance screening").replace(/_/g, " ")}
      </div>
      <div style={{ fontSize: 240, fontWeight: 700, lineHeight: 1,
                    fontVariantNumeric: "tabular-nums", margin: "10px 0" }}>
        {f != null ? f.toFixed(2) : "—"}<span style={{ fontSize: 90, color: "var(--muted)" }}> Hz</span>
      </div>
      {/* The sign is read from across the room, so the SENTENCE has to carry the
          provenance — a small pill under a claim of "we measured" is contradicted by
          the claim itself, and this is the most public-facing surface in the app. */}
      <div style={{ fontSize: 28, color: "var(--muted)", textAlign: "center", maxWidth: 900 }}>
        {real
          ? <>We measured how fast this building sways.
              {c && " Its ground shakes hardest at exactly that rate."}</>
          : <>How fast a building sways, and whether its ground
              shakes hardest at that same rate.</>}
      </div>
      {!real &&
        <div className="pill" data-warn="1" style={{ marginTop: 22, fontSize: 18, padding: "6px 14px" }}>
          {p.source === "replay" ? "REPLAY OF A REAL RECORDING" : "SIMULATED DATA — NOT A MEASUREMENT"}</div>}
      <div className="empty" style={{ marginTop: 30 }}>press any key</div>
    </div>
  );
}
