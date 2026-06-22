import {
  ComposedChart, Bar, Line, XAxis, YAxis, Tooltip,
  ResponsiveContainer, CartesianGrid, Cell, ReferenceLine,
} from 'recharts';
import { formatMultiplier } from '../lib/format.js';

function barFill(val) {
  if (val >= 15) return '#ff5277';
  if (val >= 5)  return '#f97316';
  if (val >= 2)  return '#9cff45';
  return '#35d4ff';
}

function CustomTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  const mult = payload[0]?.value ?? 0;
  return (
    <div className="rounded-lg border border-line bg-panel/95 px-4 py-3 shadow-xl backdrop-blur">
      <p className="text-xs text-slate-400">Round #{label}</p>
      <p className="text-sm font-bold" style={{ color: barFill(mult) }}>
        {formatMultiplier(mult)}
      </p>
      <p className="text-[10px] text-slate-500 mt-0.5">
        {mult >= 15 ? 'Very High' : mult >= 5 ? 'High' : mult >= 2 ? 'Medium' : 'Low / Very Low'}
      </p>
    </div>
  );
}

export default function MultiplierChart({ rounds = [] }) {
  const recent = rounds.slice(-40);
  const multipliers = recent.map(r => Number(r.multiplier || 1));

  const avg = multipliers.length
    ? multipliers.reduce((s, v) => s + v, 0) / multipliers.length
    : 0;

  // Rolling SMA-5 for trend line
  const data = recent.map((r, i) => {
    const window = multipliers.slice(Math.max(0, i - 4), i + 1);
    const sma5 = window.reduce((s, v) => s + v, 0) / window.length;
    return {
      round:      r.round_id ?? i + 1,
      multiplier: Number(r.multiplier || 1),
      sma5:       Math.round(sma5 * 100) / 100,
    };
  });

  const maxMult = Math.max(...multipliers, 2);

  return (
    <div className="rounded-xl border border-line bg-panel/80 p-5 shadow-lg backdrop-blur">
      <div className="mb-4 flex items-start justify-between">
        <div>
          <h2 className="text-lg font-bold text-white">Recent Multipliers</h2>
          <p className="text-xs text-slate-500">Last {data.length} rounds with SMA(5) trend</p>
        </div>
        <div className="text-right">
          <div className="text-xs text-slate-500">Average</div>
          <div className="text-sm font-black text-lime-400">{avg.toFixed(2)}×</div>
        </div>
      </div>

      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={data} margin={{ top: 8, right: 8, left: -20, bottom: 0 }}>
            <defs>
              <linearGradient id="barGlow" x1="0" x2="0" y1="0" y2="1">
                <stop offset="0%" stopOpacity={1} />
                <stop offset="100%" stopOpacity={0.6} />
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
              domain={[0, Math.ceil(maxMult * 1.1)]}
            />
            <Tooltip content={<CustomTooltip />} cursor={{ fill: 'rgba(255,255,255,0.04)' }} />
            <ReferenceLine y={avg} stroke="#9cff45" strokeDasharray="4 4" strokeOpacity={0.5} />
            <ReferenceLine y={2}   stroke="#35d4ff" strokeDasharray="4 4" strokeOpacity={0.3} />
            <ReferenceLine y={5}   stroke="#f97316" strokeDasharray="4 4" strokeOpacity={0.3} />

            <Bar dataKey="multiplier" radius={[3, 3, 0, 0]} maxBarSize={18}>
              {data.map((entry, i) => (
                <Cell key={i} fill={barFill(entry.multiplier)} />
              ))}
            </Bar>

            <Line
              type="monotone"
              dataKey="sma5"
              stroke="#ffffff"
              strokeWidth={1.5}
              dot={false}
              strokeDasharray="none"
              opacity={0.6}
              name="SMA(5)"
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      <div className="mt-3 grid grid-cols-4 gap-2 text-center text-[10px]">
        {[
          { label: 'Very Low',  color: 'bg-cyan-400',   range: '<1.5×' },
          { label: 'Low/Med',   color: 'bg-lime-400',   range: '1.5–5×' },
          { label: 'High',      color: 'bg-orange-400', range: '5–15×' },
          { label: 'Very High', color: 'bg-rose-500',   range: '15×+' },
        ].map(({ label, color, range }) => (
          <div key={label} className="flex flex-col items-center gap-1">
            <span className={`h-2 w-6 rounded-sm ${color}`} />
            <span className="text-slate-500">{label}</span>
            <span className="text-slate-600">{range}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
