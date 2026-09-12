/* Plain-language layer. The numbers are already right; this makes them legible to
   someone who has never seen a response spectrum. Shown as a dismissible strip
   rather than a modal so it never blocks the demo. */
import { set } from "../store.js";

export function SourceBanner({ s, onRunOwn }) {
  const p = s.pinned;
  if (!p || s.bannerDismissed) return null;
  const sim = p.source !== "hardware";
  return (
    <div className="card" style={{
      borderColor: sim ? "var(--amber)" : "var(--border)",
      padding: "12px 16px", display: "flex", alignItems: "center", gap: 16 }}>
      <div style={{ flex: 1, lineHeight: 1.5 }}>
        {sim ? <>
          <b>This is a simulated dataset, not a measurement of a real building.</b>
          <div className="empty" style={{ marginTop: 4 }}>
            Loaded so every screen has something to show. It runs through exactly the
            same analysis a real sensor would — nothing here is pre-computed.
          </div>
        </> : <>
          <b>Showing a real measurement.</b>
          <div className="empty" style={{ marginTop: 4 }}>Recorded from the sensors.</div>
        </>}
      </div>
      <button className="btn" style={{ fontSize: "var(--body)", padding: "10px 16px" }}
              onClick={onRunOwn}>Run your own measurement</button>
      <button className="btn" onClick={() => set({ bannerDismissed: true })}
              style={{ fontSize: "var(--body)", padding: "10px 14px",
                       background: "transparent", color: "var(--muted)",
                       borderColor: "var(--border)" }}>Dismiss</button>
    </div>
  );
}

/* One sentence per number, in the words a non-engineer would use. */
export const PLAIN = {
  frequency: "How many times a second the building sways back and forth.",
  period: "How long one full sway takes. The ground data uses this, not the frequency.",
  damping: "How quickly the sway dies away. Higher means it settles faster.",
  amplification: "How much bigger the movement is at the top than at the ground.",
  coherence: "How closely the two sensors agreed across repeated stomps. 1.0 is perfect.",
  siteClass: "How soft the ground is. Softer ground shakes more.",
  liquefaction: "How likely this ground is to behave like liquid in a quake.",
  score: "How close this building's sway is to the rate this ground amplifies most.",
};

export function Hint({ children }) {
  return <div className="empty" style={{ marginTop: 6, lineHeight: 1.45,
    fontSize: "var(--caption)" }}>{children}</div>;
}
