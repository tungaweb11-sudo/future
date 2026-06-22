import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip, Legend } from 'recharts';
import { formatPercent } from '../lib/format.js';

const CATEGORY_ORDER = ['VERY_LOW', 'LOW', 'MEDIUM', 'HIGH', 'VERY_HIGH'];

const CATEGORY_META = {
  VERY_LOW:  { color: '#35d4ff', label: 'Very Low'  },
  LOW:       { color: '#9cff45', label: 'Low'        },
  MEDIUM:    { color: '#fbbf24', label: 'Medium'     },
  HIGH:      { color: '#f97316', label: 'High'       },
  VERY_HIGH: { color: '#ff5277', label: 'Very High'  },
};

function CustomTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const { name, value } = payload[0];
  const meta = CATEGORY_META[name] ?? {};
  return (
    <div className="rounded-lg border border-line bg-panel/95 px-4 py-3 shadow-xl backdrop-blur">
      <p className="text-sm font-bold text-white">{meta.label ?? name}</p>
      <p className="text-xs text-slate-300">{formatPercent(value)}</p>
    </div>
  );
}

function CustomLegend({ payload }) {
  if (!payload) return null;
  return (
    <div className="mt-4 flex flex-wrap justify-center gap-x-5 gap-y-2">
      {payload.map((entry, i) => {
        const meta = CATEGORY_META[entry.value] ?? {};
        return (
          <div key={i} className="flex items-center gap-1.5 text-xs">
            <span className="h-2.5 w-2.5 rounded-full shrink-0" style={{ backgroundColor: entry.color }} />
            <span className="text-slate-300">{meta.label ?? entry.value}</span>
          </div>
        );
      })}
    </div>
  );
}

export default function DistributionChart({ probabilities = {} }) {
  // Sort into canonical order, skip zero-value entries
  const data = CATEGORY_ORDER
    .filter(key => key in probabilities && Number(probabilities[key]) > 0)
    .map(key => ({ name: key, value: Number(probabilities[key]) }));

  // If no canonical keys found, fall back to whatever keys exist
  const fallback = !data.length
    ? Object.entries(probabilities)
        .map(([name, value]) => ({ name, value: Number(value || 0) }))
        .filter(d => d.value > 0)
    : [];

  const chartData = data.length ? data : fallback;

  if (!chartData.length) {
    return (
      <div className="rounded-xl border border-line bg-panel/80 p-5 shadow-lg backdrop-blur">
        <h2 className="mb-1 text-lg font-bold text-white">Probability Distribution</h2>
        <p className="mb-4 text-xs text-slate-500">Prediction outcome breakdown</p>
        <div className="flex h-64 items-center justify-center text-sm text-slate-500">
          No prediction data yet
        </div>
      </div>
    );
  }

  const total = chartData.reduce((s, d) => s + d.value, 0);

  return (
    <div className="rounded-xl border border-line bg-panel/80 p-5 shadow-lg backdrop-blur">
      <div className="mb-4">
        <h2 className="text-lg font-bold text-white">Probability Distribution</h2>
        <p className="text-xs text-slate-500">Prediction outcome breakdown</p>
      </div>

      {/* Donut chart */}
      <div className="h-56">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={chartData}
              cx="50%"
              cy="50%"
              innerRadius={52}
              outerRadius={88}
              paddingAngle={2}
              dataKey="value"
              stroke="none"
            >
              {chartData.map((entry) => (
                <Cell
                  key={entry.name}
                  fill={CATEGORY_META[entry.name]?.color ?? '#64748b'}
                />
              ))}
            </Pie>
            <Tooltip content={<CustomTooltip />} />
            <Legend
              content={<CustomLegend />}
              payload={chartData.map(d => ({ value: d.name, color: CATEGORY_META[d.name]?.color ?? '#64748b' }))}
            />
          </PieChart>
        </ResponsiveContainer>
      </div>

      {/* Bar breakdown below the chart */}
      <div className="mt-4 space-y-2">
        {chartData.map(d => {
          const meta = CATEGORY_META[d.name] ?? { color: '#64748b', label: d.name };
          const pct = total > 0 ? (d.value / total) * 100 : 0;
          return (
            <div key={d.name} className="flex items-center gap-3">
              <span className="w-20 text-[11px] font-semibold text-slate-400">{meta.label}</span>
              <div className="flex-1 h-1.5 rounded-full bg-slate-800 overflow-hidden">
                <div
                  className="h-full rounded-full transition-all duration-500"
                  style={{ width: `${pct}%`, backgroundColor: meta.color }}
                />
              </div>
              <span className="w-12 text-right text-xs font-bold text-white">
                {formatPercent(d.value)}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

