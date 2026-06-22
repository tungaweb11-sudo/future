import {
  AreaChart, Area, XAxis, YAxis, Tooltip,
  ResponsiveContainer, CartesianGrid, ReferenceLine,
} from 'recharts';

function scoreColor(score) {
  if (score >= 65) return '#ff5277';
  if (score >= 35) return '#fbbf24';
  return '#35d4ff';
}

function CustomTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  const score = payload[0]?.value ?? 0;
  const mult  = payload[1]?.value;
  return (
    <div className="rounded-lg border border-line bg-panel/95 px-4 py-3 shadow-xl backdrop-blur min-w-[140px]">
      <p className="mb-1.5 text-xs text-slate-400">Round #{label}</p>
      <p className="text-xs font-bold" style={{ color: scoreColor(score) }}>
        Risk Score: {score.toFixed(1)}
      </p>
      {mult != null && (
        <p className="text-xs text-slate-300">Multiplier: {Number(mult).toFixed(2)}×</p>
      )}
      <p className="mt-1 text-[10px] text-slate-500">
        {score >= 65 ? 'High Risk' : score >= 35 ? 'Caution' : 'Safe'}
      </p>
    </div>
  );
}

export default function RiskHistoryChart({ rounds = [] }) {
  if (!rounds?.length) {
    return (
      <div className="rounded-xl border border-line bg-panel/80 p-5 shadow-lg backdrop-blur">
        <h2 className="mb-1 text-lg font-bold text-white">Risk Score Trend</h2>
        <p className="mb-4 text-xs text-slate-500">Risk index evolution over recent rounds</p>
        <div className="flex h-64 items-center justify-center text-sm text-slate-500">
          No risk history data — visit Overview tab to load
        </div>
      </div>
    );
  }

  const data = rounds.map((r) => ({
    round:     r.round_id ?? 0,
    riskScore: typeof r.risk_score === 'number' ? r.risk_score : 0,
    multiplier: Number(r.multiplier || 1),
  }));

  // Current score for the gradient stop color
  const latest = data[data.length - 1]?.riskScore ?? 0;
  const lineColor = scoreColor(latest);

  return (
    <div className="rounded-xl border border-line bg-panel/80 p-5 shadow-lg backdrop-blur">
      <div className="mb-4 flex items-start justify-between">
        <div>
          <h2 className="text-lg font-bold text-white">Risk Score Trend</h2>
          <p className="text-xs text-slate-500">Risk index evolution over recent rounds</p>
        </div>
        <div className={`rounded-full px-2.5 py-1 text-xs font-bold ${
          latest >= 65 ? 'bg-rose-500/15 text-rose-400' :
          latest >= 35 ? 'bg-amber-400/15 text-amber-400' :
          'bg-cyan-500/15 text-cyan-400'
        }`}>
          {latest.toFixed(0)} / 100
        </div>
      </div>

      <div className="h-56">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ top: 8, right: 8, left: -20, bottom: 0 }}>
            <defs>
              <linearGradient id="riskGrad" x1="0" x2="0" y1="0" y2="1">
                <stop offset="0%"   stopColor={lineColor} stopOpacity={0.35} />
                <stop offset="100%" stopColor={lineColor} stopOpacity={0.02} />
              </linearGradient>
            </defs>

            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />

            {/* Zone reference lines */}
            <ReferenceLine y={35} stroke="#fbbf24" strokeDasharray="4 4" strokeOpacity={0.4} />
            <ReferenceLine y={65} stroke="#ff5277" strokeDasharray="4 4" strokeOpacity={0.4} />

            <XAxis
              dataKey="round"
              tick={{ fill: '#64748b', fontSize: 10 }}
              axisLine={false}
              tickLine={false}
              interval="preserveStartEnd"
            />
            <YAxis
              tick={{ fill: '#64748b', fontSize: 10 }}
              axisLine={false}
              tickLine={false}
              domain={[0, 100]}
              ticks={[0, 25, 50, 75, 100]}
            />
            <Tooltip
              content={<CustomTooltip />}
              cursor={{ stroke: lineColor, strokeWidth: 1, strokeDasharray: '4 4' }}
            />

            {/* Risk score area */}
            <Area
              type="monotone"
              dataKey="riskScore"
              stroke={lineColor}
              strokeWidth={2.5}
              fill="url(#riskGrad)"
              dot={false}
              activeDot={{ r: 5, fill: lineColor, stroke: '#070a12', strokeWidth: 2 }}
              name="Risk Score"
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      {/* Legend */}
      <div className="mt-3 flex items-center gap-4 text-[11px] text-slate-500">
        <span className="flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-full bg-[#35d4ff]" />
          0–34 Safe
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-full bg-[#fbbf24]" />
          35–64 Caution
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-full bg-[#ff5277]" />
          65–100 High Risk
        </span>
        <span className="ml-auto text-slate-600">{data.length} rounds</span>
      </div>
    </div>
  );
}
