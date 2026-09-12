import { LineChart, Line, XAxis, YAxis, ReferenceLine, ReferenceArea,
         ResponsiveContainer, Label } from "recharts";

/* X is PERIOD, not frequency — the orientation an engineer expects, and the reason
   the app converts Hz to seconds before plotting. Everything here is labelled twice:
   once in the engineering term, once in words, because this chart has to read to a
   judge who has never seen a response spectrum and to one who has seen hundreds. */
export default function HazardCurve({ spectrum, period, uncertainty, t0, ts }) {
  const d = spectrum?.two_period;
  if (!d?.length) return <div className="empty">no spectrum</div>;
  return (
    <ResponsiveContainer width="100%" height="100%">
      <LineChart data={d} margin={{ top: 30, right: 22, bottom: 42, left: 10 }}>
        <XAxis dataKey="period_s" type="number" domain={[0, 2.5]} allowDataOverflow
               stroke="#1F2A35" tick={{ fill: "#9BAAB8", fontSize: 15 }}
               tickFormatter={(v) => v.toFixed(1)}>
          <Label value="how slowly a building sways  ·  period (seconds)"
                 position="insideBottom" offset={-32}
                 style={{ fill: "#9BAAB8", fontSize: 15 }} />
        </XAxis>
        <YAxis stroke="#1F2A35" tick={{ fill: "#9BAAB8", fontSize: 15 }} width={62}
               tickFormatter={(v) => v.toFixed(1)}>
          <Label value="shaking delivered  ·  Sa (g)" angle={-90}
                 position="insideLeft" offset={4}
                 style={{ fill: "#9BAAB8", fontSize: 15, textAnchor: "middle" }} />
        </YAxis>

        {t0 != null && ts != null && (
          <ReferenceArea x1={t0} x2={ts} fill="#38BDF8" fillOpacity={0.12}
                         stroke="#38BDF8" strokeOpacity={0.35}>
            <Label value="this ground hits hardest here" position="insideTop"
                   style={{ fill: "#7FC8EE", fontSize: 14 }} />
          </ReferenceArea>)}

        <Line dataKey="sa_g" stroke="#38BDF8" dot={false} strokeWidth={2.4}
              isAnimationActive={false} />

        {period != null && uncertainty > 0 && (
          <ReferenceArea x1={Math.max(0, period - uncertainty)} x2={period + uncertainty}
                         fill="#E8EEF4" fillOpacity={0.18} />)}
        {period != null && (
          <ReferenceLine x={period} stroke="#E8EEF4" strokeWidth={2}>
            <Label value={`your building — ${period.toFixed(2)} s`} position="top"
                   offset={10} style={{ fill: "#E8EEF4", fontSize: 15, fontWeight: 600 }} />
          </ReferenceLine>)}

        {/* The two corner periods are named on the axis so the T₀ and T_S listed
            under this chart on the Site screen connect to something visible on it. */}
        {t0 != null && <ReferenceLine x={t0} stroke="#38BDF8" strokeOpacity={0.5}
          strokeDasharray="3 3">
          <Label value="T₀" position="insideBottomLeft" offset={8}
                 style={{ fill: "#7FC8EE", fontSize: 14 }} /></ReferenceLine>}
        {ts != null && <ReferenceLine x={ts} stroke="#38BDF8" strokeOpacity={0.5}
          strokeDasharray="3 3">
          <Label value="T_S" position="insideBottomRight" offset={8}
                 style={{ fill: "#7FC8EE", fontSize: 14 }} /></ReferenceLine>}
      </LineChart>
    </ResponsiveContainer>
  );
}
