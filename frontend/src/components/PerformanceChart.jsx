import {
  ComposedChart, Area, Line, XAxis, YAxis, Tooltip,
  ResponsiveContainer, CartesianGrid, ReferenceLine,
} from 'recharts';
import { formatMultiplier } from '../lib/format.js';

function CustomTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  const mult = payload.find(p => p.dataKey === 'multiplier')?.value;
  const sma  = payload.find(p => p.dataKey === 'sma20')?.value;
  return (
    <div className="rounded-lg border border-line bg-panel/95 px-4 py-3 shadow-xl backdrop-blur min-w-[130px]">
      <p className="mb-1.5 text-xs text-slate-400">Round #{label}</p>
      {mult != null && (
        <p className="text-sm font-bold text-white">{formatMultiplier(mult)}</p>
      )}
      {sma != null && (
        <p className="text-xs text-amber-300">SMA(20): {sma.toFixed(2)}×</p>
      )}
    </div>
  );
}

export default function PerformanceChart({ rounds = [] }) {
  if (!rounds?.length) {
    return (
      <div className="rounded-xl border border-line bg-panel/80 p-5 shadow-lg backdrop-blur">
        <h2 className="mb-1 text-lg font-bold text-white">Performance Trend</h2>
        <p className="mb-4 text-xs text-slate-500">Multiplier progression over time</p>
        <div className="flex h-64 items-center justify-center text-sm text-slate-500">No data yet</div>
      </div>
    );
  }

  const multipliers = rounds.map(r => Number(r.multiplier || 1));
  const avg = multipliers.reduce((s, v) => s + v, 0) / multipliers.length;
  const max = Math.max(...multipliers);

  // SMA-20 for trend context
  const data = rounds.map((r, i) => {
    const window = multipliers.slice(Math.max(0, i - 19), i + 1);
    const sma20 = window.reduce((s, v) => s + v, 0) / window.length;
    return {
      round:      r.round_id ?? i + 1,
      multiplier: Number(r.multiplier || 1),
      sma20:      Math.round(sma20 * 100) / 100,
    };
  });

  return (
    <div className="rounded-xl border border-line bg-panel/80 p-5 shadow-lg backdrop-blur">
      <div className="mb-4 flex items-start justify-between">
        <div>
          <h2 className="text-lg font-bold text-white">Performance Trend</h2>
          <p className="text-xs text-slate-500">Multiplier progression with SMA(20)</p>
        </div>
        <div className="flex gap-3 text-right">
          <div>
            <div className="text-[10px] text-slate-500">Average</div>
            <div className="text-sm font-black text-cyan-400">{avg.toFixed(2)}×</div>
          </div>
          <div>
            <div className="text-[10px] text-slate-500">Peak</div>
            <div className="text-sm font-black text-rose-400">{formatMultiplier(max)}</div>
          </div>
        </div>
      </div>

      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={data} margin={{ top: 8, right: 8, left: -20, bottom: 0 }}>
            <defs>
              <linearGradient id="perfGrad" x1="0" x2="0" y1="0" y2="1">
                <stop offset="0%"   stopColor="#35d4ff" stopOpacity={0.3} />
                <stop offset="100%" stopColor="#35d4ff" stopOpacity={0.02} />
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
            <Tooltip content={<CustomTooltip />} cursor={{ stroke: '#35d4ff', strokeWidth: 1, strokeDasharray: '4 4' }} />

            {/* Average reference line */}
            <ReferenceLine y={avg} stroke="#9cff45" strokeDasharray="4 4" strokeOpacity={0.5}
              label={{ value: `avg ${avg.toFixed(1)}×`, position: 'insideTopRight', fill: '#9cff45', fontSize: 10 }}
            />

            <Area
              type="monotone"
              dataKey="multiplier"
              stroke="#35d4ff"
              strokeWidth={2}
              fill="url(#perfGrad)"
              dot={false}
              activeDot={{ r: 5, fill: '#35d4ff', stroke: '#070a12', strokeWidth: 2 }}
              name="Multiplier"
            />
            <Line
              type="monotone"
              dataKey="sma20"
              stroke="#fbbf24"
              strokeWidth={2}
              dot={false}
              name="SMA(20)"
              strokeDasharray="5 3"
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      <div className="mt-3 flex items-center gap-4 text-[11px] text-slate-500">
        <span className="flex items-center gap-1.5">
          <span className="h-2 w-4 rounded-sm bg-cyan-400/60" /> Multiplier
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-0.5 w-4 bg-amber-400" style={{ borderTop: '2px dashed #fbbf24' }} /> SMA(20)
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-0.5 w-4" style={{ borderTop: '2px dashed #9cff45' }} /> Average
        </span>
      </div>
    </div>
  );
}
