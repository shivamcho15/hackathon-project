import { useEffect, useMemo, useRef, useState } from "react";
import { makeScene } from "../three/scene.js";
import { buildBuilding, applyDisplacement } from "../three/building.js";
import { stiffnessFor, stiffnessMatrix, modeShape, driftProfile, criticalFloor } from "../physics/model.js";
import { magnification, displacement, DAMPING_DEFAULT } from "../physics/modal.js";
import { Hint } from "./Explain.jsx";
import { intensityFor } from "../shaking.js";
import FrequencyScale from "../charts/FrequencyScale.jsx";

const TYPES = ["wood", "urm", "concrete", "steel"];
const EXAGGERATION = 200;          // stated on screen, always

export default function Building3D({ s }) {
  const canvas = useRef(null);
  const view = useRef(null);
  const live = useRef({});
  const p = s.pinned;
  const measured = p ? (p.location_median_hz ?? p.frequency_hz) : null;

  const [floors, setFloors] = useState(s.site?.building_footprint?.levels || 5);
  const [type, setType] = useState("concrete");
  const [fDrive, setFDrive] = useState(measured || 3.2);
  const [pga, setPga] = useState(0.18);      // g at the ground, not a magnitude

  useEffect(() => { if (measured) setFDrive(measured); }, [measured]);
  useEffect(() => { setFloors(s.site?.building_footprint?.levels || 5); },
            [s.site?.building_footprint?.levels]);

  const zeta = p?.damping_ratio || DAMPING_DEFAULT[type];
  const model = useMemo(() => {
    const base = measured || 3.2;
    const k = stiffnessFor(base, floors);
    const plain = modeShape(stiffnessMatrix(k, floors));
    const crit = criticalFloor(plain.phi);
    return { ...plain, crit, drift: driftProfile(plain.phi) };
  }, [measured, floors]);

  // Build the scene once per geometry change.
  useEffect(() => {
    if (!canvas.current) return;
    const fp = s.site?.building_footprint?.geometry;
    const b = buildBuilding({ footprint: fp, floors, type });
    const v = makeScene(canvas.current, { span: b.span, height: b.height });
    v.scene.add(b.group);
    view.current = { ...v, ...b };
    const ro = new ResizeObserver(() => v.resize());
    ro.observe(canvas.current);
    return () => { ro.disconnect(); v.renderer.dispose(); };
  }, [floors, type, s.site?.building_footprint?.geometry]);

  // Display amplitude tracks PGA so the slider means something physical rather
  // than being an arbitrary 0-2 gain.
  live.current = { fDrive, f1: model.f1, zeta, phi: model.phi, amplitude: pga / 0.18 };

  // One rAF loop for the life of the component. No integrator state to carry, so a
  // dropped frame or a parameter change mid-flight cannot destabilise anything.
  useEffect(() => {
    let raf, t0 = performance.now();
    const tick = (now) => {
      const v = view.current;
      if (v) {
        const t = (now - t0) / 1000;
        const L = live.current;
        const x = displacement(t, L);
        // Normalise by the MAXIMUM possible magnification, 1/(2*zeta), so peak sway
        // at resonance reads as ~12% of building height and everything off
        // resonance is proportionally smaller. Scaling by metres directly put 27 m
        // of slide on a 17.5 m building and read as shattered rather than swaying —
        // and normalising by the CURRENT H instead would have flattened the surge,
        // which is the one thing this screen exists to show.
        applyDisplacement(v.slabs, x, v.height * 0.12 * 2 * L.zeta);
        v.render();
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, []);

  // M snaps back to the honest configuration after exploring; B toggles the brace.
  useEffect(() => {
    const on = (e) => {
      if (e.detail === "m" && measured) setFDrive(model.f1);
    };
    window.addEventListener("quake-key", on);
    return () => window.removeEventListener("quake-key", on);
  }, [measured, model.f1]);

  const h = magnification(fDrive, model.f1, zeta);
  const intensity = intensityFor(pga);
  const design = s.site?.usgs_spectrum?.pgam || 0;
  const atRes = measured && Math.abs(fDrive - model.f1) / model.f1 < 0.06;
  const bf = s.site?.building_footprint;
  const fallback = !bf?.geometry?.length;

  return (
    <div style={{ display: "flex", gap: 14, height: "100%" }}>
      <div className="card" style={{ flex: 1.6, minWidth: 0, padding: 0, position: "relative",
                                     overflow: "hidden" }}>
        <canvas ref={canvas} style={{ width: "100%", height: "100%", display: "block" }} />
        <div style={{ position: "absolute", left: 14, bottom: 12 }}>
          <div style={{ fontSize: 22, fontWeight: 600 }}>
            {bf?.name || s.site?.address?.split(",")[0] || "building"}
          </div>
          <div className="empty" style={{ marginTop: 2 }}>
            {floors} floors · {type}
            {bf?.year_built ? ` · built ${bf.year_built}` : ""}
            {fallback ? " · default rectangle, no footprint found"
                      : ` · real ${bf?.geometry?.length}-point outline from OpenStreetMap`}
          </div>
          <div className="empty" style={{ marginTop: 2 }}>
            sway exaggerated ~{EXAGGERATION}× to be visible · drag to turn
          </div>
        </div>
        {atRes && <div style={{ position: "absolute", right: 14, top: 12, padding: "8px 14px",
          borderRadius: 8, background: "var(--amber)", color: "#0B0F14", fontWeight: 700 }}>
          ⚠ AT RESONANCE</div>}
      </div>

      <div style={{ flex: 1, minWidth: 300, display: "flex", flexDirection: "column",
                    gap: 12, overflowY: "auto", paddingRight: 4 }}>
        <div className="card">
          <div className="label">ground shaking</div>
          <div style={{ marginTop: 10, fontSize: 34, fontVariantNumeric: "tabular-nums" }}>
            {fDrive.toFixed(2)} Hz</div>
          <input type="range" min={0.5} max={15} step={0.01} value={fDrive}
                 onChange={(e) => setFDrive(+e.target.value)} style={{ width: "100%" }} />
          <Hint>Drag to shake the ground at different speeds. The building barely
            responds until you hit its own rate — then it takes off.</Hint>
          <div className="kv" style={{ marginTop: 8 }}>
            <span>movement vs a slow push</span><span>{h.toFixed(1)}×</span></div>
          <button className="btn" style={{ width: "100%", marginTop: 10, fontSize: "var(--body)" }}
                  onClick={() => measured && setFDrive(model.f1)}>
            snap to measured ({model.f1.toFixed(2)} Hz) · M</button>
          <div style={{ marginTop: 14 }}>
            <div className="label">how hard the ground shakes</div>
            <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginTop: 6 }}>
              <span style={{ fontSize: 30, fontWeight: 700 }}>{intensity.roman}</span>
              <span style={{ fontSize: 22 }}>{intensity.word}</span>
              <span className="empty" style={{ marginLeft: "auto",
                    fontVariantNumeric: "tabular-nums" }}>{pga.toFixed(2)} g</span>
            </div>
            <input type="range" min={0.02} max={1.3} step={0.01} value={pga}
                   onChange={(e) => setPga(+e.target.value)} style={{ width: "100%" }} />
            <Hint>{intensity.text}</Hint>
            {design > 0 && (
              <button onClick={() => setPga(design)}
                style={{ marginTop: 8, background: "none", border: "none", padding: 0,
                         color: "var(--top)", cursor: "pointer", fontFamily: "inherit",
                         fontSize: "var(--caption)", textDecoration: "underline" }}>
                jump to this site's design event — {design} g (USGS)
              </button>)}
            <Hint><b>Intensity, not magnitude.</b> Magnitude describes the earthquake;
              intensity describes what happens <i>here</i>. A magnitude 9 offshore
              shakes this address less than a magnitude 6.5 underneath it.</Hint>
          </div>
        </div>

        <div className="card">
          <div className="label">what sway rates look like</div>
          <FrequencyScale measured={measured} floors={floors}
                          t0={s.site?.usgs_spectrum?.t0} ts={s.site?.usgs_spectrum?.ts} />
        </div>

        <div className="card">
          <div className="label">building</div>
          <div className="kv" style={{ marginTop: 8 }}><span>floors</span>
            <input type="number" min={1} max={20} value={floors}
                   onChange={(e) => setFloors(Math.max(1, Math.min(20, +e.target.value || 1)))}
                   style={{ width: 70, textAlign: "right", background: "var(--bg)",
                            color: "var(--text)", border: "1px solid var(--border)",
                            borderRadius: 6, padding: "4px 8px", fontFamily: "inherit",
                            fontSize: "var(--caption)" }} /></div>
          <div className="kv"><span>structure</span><span>
            <span className="seg">{TYPES.map((t) => (
              <button key={t} data-on={type === t ? "1" : "0"} onClick={() => setType(t)}
                      style={{ padding: "4px 8px" }}>{t}</button>))}</span></span></div>
          <div className="kv"><span>weakest connection</span>
            <span>level {model.crit + 1}</span></div>
          <Hint>The level that bends most when the building sways — where bracing
            would do the most good.</Hint>
        </div>

      </div>
    </div>
  );
}
