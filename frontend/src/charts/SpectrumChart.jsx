import { LineChart, Line, XAxis, YAxis, ReferenceLine, ResponsiveContainer } from "recharts";

export default function SpectrumChart({ spectrum, peak, band = [0.5, 15] }) {
  if (!spectrum?.length) return <div className="empty">no spectrum yet</div>;
  return (
    <ResponsiveContainer width="100%" height="100%">
      <LineChart data={spectrum} margin={{ top: 6, right: 10, bottom: 4, left: -18 }}>
        <XAxis dataKey="f" type="number" domain={band} tick={{ fill: "#9BAAB8", fontSize: 16 }}
               tickFormatter={(v) => v.toFixed(0)} stroke="#1F2A35" />
        <YAxis tick={false} axisLine={false} />
        <Line dataKey="mag" stroke="#38BDF8" dot={false} isAnimationActive={false} strokeWidth={1.6} />
        {peak != null && <ReferenceLine x={peak} stroke="#E8EEF4" strokeDasharray="4 3"
          label={{ value: `${peak.toFixed(2)} Hz`, fill: "#E8EEF4", fontSize: 16, position: "top" }} />}
      </LineChart>
    </ResponsiveContainer>
  );
}
