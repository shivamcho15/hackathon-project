import { useEffect, useRef } from "react";

/* Hand-rolled canvas, not a chart library. Nothing survives a redraw at 60 fps with
   a few thousand points, and this is the one chart a judge watches react to a
   physical action. Both nodes share ONE y-scale so "top moves more than ground" is
   a real comparison and not an autoscaling artifact. */
export default function LiveTrace({ data, color, label, scale }) {
  const ref = useRef(null);
  useEffect(() => {
    const c = ref.current;
    if (!c) return;
    const dpr = window.devicePixelRatio || 1;
    const w = c.clientWidth, h = c.clientHeight;
    c.width = w * dpr; c.height = h * dpr;
    const g = c.getContext("2d");
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, w, h);
    g.strokeStyle = "#1F2A35"; g.lineWidth = 1;
    g.beginPath(); g.moveTo(0, h / 2); g.lineTo(w, h / 2); g.stroke();
    if (!data.length) return;
    const n = data.length, step = w / Math.max(n - 1, 1);
    g.strokeStyle = color; g.lineWidth = 1.6; g.beginPath();
    for (let i = 0; i < n; i++) {
      const y = h / 2 - (data[i] / scale) * (h / 2) * 0.92;
      i ? g.lineTo(i * step, y) : g.moveTo(i * step, y);
    }
    g.stroke();
  }, [data, color, scale]);
  return (
    <div className="card" style={{ padding: 8, flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
      <div className="label" style={{ color, marginBottom: 4 }}>{label}</div>
      <canvas ref={ref} style={{ width: "100%", flex: 1, minHeight: 48 }} />
    </div>
  );
}
