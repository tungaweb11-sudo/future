import {
  ComposedChart, Area, Line, XAxis, YAxis, Tooltip,
  ResponsiveContainer, CartesianGrid, Legend, ReferenceLine,
} from 'recharts';

function CustomTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border border-line bg-panel/95 px-4 py-3 shadow-xl backdrop-blur min-w-[150px]">
      <p className="mb-1.5 text-xs text-slate-400">Round #{label}</p>
      {payload.map((p, i) => (
        <p key={i} className="text-xs font-semibold" style={{ color: p.color }}>
          {p.name}: {typeof p.value === 'number' ? p.value.toFixed(2) : '—'}×
        </p>
      ))}
    </div>
  );
}

export default function MACrossoverChart({ rounds = [] }) {
  if (!rounds?.length) {
    return (
      <div className="rounded-xl border border-line bg-panel/80 p-5 shadow-lg backdrop-blur">
        <h2 className="mb-1 text-lg font-bold text-white">Moving Averages</h2>
        <p className="mb-4 text-xs text-slate-500">SMA(5) vs SMA(20) crossover signals</p>
        <div className="flex h-64 items-center justify-center text-sm text-slate-500">No data yet</div>
      </div>
    );
  }

  const multipliers = rounds.map(r => Number(r.multiplier || 1));
  const slice = multipliers.slice(-60);
  const sliceRounds = rounds.slice(-60);

  const smaWindow = (arr, i, w) => {
    const win = arr.slice(Math.max(0, i - w + 1), i + 1);
    return win.reduce((s, v) => s + v, 0) / win.length;
  };

  const data = slice.map((m, i) => {
    const s5  = smaWindow(slice, i, 5);
    const s20 = i >= 19 ? smaWindow(slice, i, 20) : null;
    return {
      round:      sliceRounds[i]?.round_id ?? i + 1,
      multiplier: m,
      sma5:       Math.round(s5 * 100) / 100,
      sma20:      s20 != null ? Math.round(s20 * 100) / 100 : undefined,
    };
  });

  // Detect crossover points for annotation
  const crossovers = [];
  for (let i = 1; i < data.length; i++) {
    const prev = data[i - 1];
    const curr = data[i];
    if (prev.sma20 != null && curr.sma20 != null) {
      if (prev.sma5 < prev.sma20 && curr.sma5 >= curr.sma20) {
        crossovers.push({ round: curr.round, type: 'bull' });
      } else if (prev.sma5 > prev.sma20 && curr.sma5 <= curr.sma20) {
        crossovers.push({ round: curr.round, type: 'bear' });
      }
    }
  }

  const lastCross = crossovers[crossovers.length - 1];
  const trend = (() => {
    const last = data[data.length - 1];
    if (!last?.sma20) return null;
    return last.sma5 > last.sma20 ? 'bullish' : 'bearish';
  })();

  return (
    <div className="rounded-xl border border-line bg-panel/80 p-5 shadow-lg backdrop-blur">
      <div className="mb-4 flex items-start justify-between">
        <div>
          <h2 className="text-lg font-bold text-white">Moving Averages</h2>
          <p className="text-xs text-slate-500">SMA(5) vs SMA(20) crossover signals</p>
        </div>
        {trend && (
          <div className={`rounded-full px-2.5 py-1 text-[11px] font-bold ${
            trend === 'bullish'
              ? 'bg-lime-500/15 text-lime-400'
              : 'bg-rose-500/15 text-rose-400'
          }`}>
            {trend === 'bullish' ? '▲ Bullish' : '▼ Bearish'}
          </div>
        )}
      </div>

      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={data} margin={{ top: 8, right: 8, left: -20, bottom: 0 }}>
            <defs>
              <linearGradient id="maGrad" x1="0" x2="0" y1="0" y2="1">
                <stop offset="0%"   stopColor="#64748b" stopOpacity={0.15} />
                <stop offset="100%" stopColor="#64748b" stopOpacity={0.01} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
            <XAxis
              dataKey="round"
              tick={{ fill: '#64748b', fontSize: 10 }}
              axisLine={false} tickLine={false}
              interval="preserveStartEnd"
            />
            <YAxis
              tick={{ fill: '#64748b', fontSize: 10 }}
              axisLine={false} tickLine={false}
              domain={['auto', 'auto']}
            />
            <Tooltip content={<CustomTooltip />} cursor={{ stroke: '#ffffff20', strokeWidth: 1 }} />

            {/* Crossover markers */}
            {crossovers.map((c, i) => (
              <ReferenceLine
                key={i}
                x={c.round}
                stroke={c.type === 'bull' ? '#9cff45' : '#ff5277'}
                strokeDasharray="4 2"
                strokeOpacity={0.5}
              />
            ))}

            {/* Raw crash bars (muted) */}
            <Area
              type="monotone"
              dataKey="multiplier"
              stroke="#334155"
              strokeWidth={1}
              fill="url(#maGrad)"
              dot={false}
              name="Crash"
            />
            <Line
              type="monotone"
              dataKey="sma5"
              stroke="#35d4ff"
              strokeWidth={2.5}
              dot={false}
              name="SMA(5)"
            />
            <Line
              type="monotone"
              dataKey="sma20"
              stroke="#fbbf24"
              strokeWidth={2.5}
              dot={false}
              name="SMA(20)"
              connectNulls={false}
              strokeDasharray="6 2"
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-4 text-[11px] text-slate-500">
        <span className="flex items-center gap-1.5">
          <span className="h-0.5 w-5 bg-cyan-400 inline-block" /> SMA(5) fast
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-0.5 w-5 bg-amber-400 inline-block" style={{ borderTop: '2px dashed #fbbf24' }} /> SMA(20) slow
        </span>
        {crossovers.length > 0 && (
          <span className="ml-auto text-slate-600">
            {crossovers.length} crossover{crossovers.length > 1 ? 's' : ''} detected
          </span>
        )}
      </div>
    </div>
  );
}
