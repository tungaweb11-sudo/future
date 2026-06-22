import { RadarChart, Radar, PolarGrid, PolarAngleAxis, ResponsiveContainer, Tooltip } from 'recharts';

const FACTOR_META = {
  volatility_factor:    { label: 'Volatility',   desc: 'Price dispersion',        icon: '📊' },
  streak_factor:        { label: 'Streak',        desc: 'Consecutive pattern',     icon: '🔗' },
  trend_factor:         { label: 'Momentum',      desc: 'MA trend direction',      icon: '📈' },
  high_frequency_factor:{ label: 'High Crash',    desc: 'Frequency of 5×+',        icon: '💥' },
};

function barColor(val) {
  if (val >= 65) return { bar: 'bg-rose-500', text: 'text-rose-400', glow: 'shadow-rose-500/20' };
  if (val >= 35) return { bar: 'bg-amber-400', text: 'text-amber-400', glow: 'shadow-amber-400/20' };
  return { bar: 'bg-cyan-400', text: 'text-cyan-400', glow: 'shadow-cyan-400/20' };
}

function CustomRadarTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const { subject, value } = payload[0].payload;
  return (
    <div className="rounded-lg border border-line bg-panel/95 px-3 py-2 shadow-xl backdrop-blur text-xs">
      <p className="font-bold text-white">{subject}</p>
      <p className="text-slate-300">{Number(value).toFixed(1)} / 100</p>
    </div>
  );
}

export default function FactorBreakdown({ factors = {} }) {
  const keys = Object.keys(FACTOR_META);
  const hasData = keys.some(k => factors[k] != null);

  if (!hasData) {
    return (
      <div className="rounded-xl border border-line bg-panel/80 p-5 shadow-lg backdrop-blur">
        <h2 className="mb-1 text-lg font-bold text-white">Risk Factor Breakdown</h2>
        <p className="mb-4 text-xs text-slate-500">Contributing factors to risk score</p>
        <div className="flex h-40 items-center justify-center text-sm text-slate-500">No data yet</div>
      </div>
    );
  }

  const radarData = keys.map(k => ({
    subject: FACTOR_META[k].label,
    value: factors[k] ?? 0,
    fullMark: 100,
  }));

  const overall = Math.round(keys.reduce((s, k) => s + (factors[k] ?? 0), 0) / keys.length);

  return (
    <div className="rounded-xl border border-line bg-panel/80 p-5 shadow-lg backdrop-blur">
      <div className="mb-4 flex items-start justify-between">
        <div>
          <h2 className="text-lg font-bold text-white">Risk Factor Breakdown</h2>
          <p className="text-xs text-slate-500">Contributing factors to composite risk score</p>
        </div>
        <div className={`rounded-full px-2.5 py-1 text-xs font-bold ${
          overall >= 65 ? 'bg-rose-500/15 text-rose-400' :
          overall >= 35 ? 'bg-amber-400/15 text-amber-400' :
          'bg-cyan-500/15 text-cyan-400'
        }`}>
          avg {overall}%
        </div>
      </div>

      {/* Radar chart */}
      <div className="h-48">
        <ResponsiveContainer width="100%" height="100%">
          <RadarChart data={radarData} margin={{ top: 4, right: 24, bottom: 4, left: 24 }}>
            <PolarGrid stroke="#1e293b" />
            <PolarAngleAxis
              dataKey="subject"
              tick={{ fill: '#64748b', fontSize: 11 }}
            />
            <Radar
              dataKey="value"
              stroke="#35d4ff"
              fill="#35d4ff"
              fillOpacity={0.18}
              strokeWidth={2}
            />
            <Tooltip content={<CustomRadarTooltip />} />
          </RadarChart>
        </ResponsiveContainer>
      </div>

      {/* Bar breakdown */}
      <div className="mt-4 space-y-3">
        {keys.map(k => {
          const val = factors[k] ?? 0;
          const meta = FACTOR_META[k];
          const { bar, text, glow } = barColor(val);
          return (
            <div key={k}>
              <div className="mb-1 flex items-center justify-between text-xs">
                <span className="flex items-center gap-1.5">
                  <span>{meta.icon}</span>
                  <span className="font-semibold text-white">{meta.label}</span>
                  <span className="text-slate-500">{meta.desc}</span>
                </span>
                <span className={`font-bold ${text}`}>{val.toFixed(0)}</span>
              </div>
              <div className="h-1.5 overflow-hidden rounded-full bg-slate-800">
                <div
                  className={`h-full rounded-full transition-all duration-700 ${bar} shadow-sm ${glow}`}
                  style={{ width: `${Math.min(100, val)}%` }}
                />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
