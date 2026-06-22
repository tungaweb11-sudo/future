import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts';

const CATEGORY_ORDER = ['VERY_LOW', 'LOW', 'MEDIUM', 'HIGH', 'VERY_HIGH'];

const CATEGORY_META = {
  VERY_LOW:  { color: '#35d4ff', short: 'V.Low'  },
  LOW:       { color: '#9cff45', short: 'Low'     },
  MEDIUM:    { color: '#fbbf24', short: 'Medium'  },
  HIGH:      { color: '#f97316', short: 'High'    },
  VERY_HIGH: { color: '#ff5277', short: 'V.High'  },
};

export default function CategoryDistribution({ counts = {} }) {
  // Build data in canonical order; include all 5 categories even if 0
  const data = CATEGORY_ORDER.map(key => ({
    name: key,
    short: CATEGORY_META[key].short,
    value: Number(counts[key] ?? 0),
    color: CATEGORY_META[key].color,
  }));

  const total = data.reduce((s, d) => s + d.value, 0);
  const hasData = total > 0;

  return (
    <div className="rounded-xl border border-line bg-panel/80 p-5 shadow-lg backdrop-blur">
      <div className="mb-4">
        <h2 className="text-lg font-bold text-white">Crash Distribution</h2>
        <p className="text-xs text-slate-500">
          {hasData ? `${total.toLocaleString()} rounds across 5 categories` : 'Outcome breakdown by category'}
        </p>
      </div>

      {hasData ? (
        <>
          <div className="h-44">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={data} margin={{ top: 4, right: 8, left: -20, bottom: 0 }}>
                <XAxis
                  dataKey="short"
                  tick={{ fill: '#64748b', fontSize: 11 }}
                  axisLine={false}
                  tickLine={false}
                />
                <YAxis
                  tick={{ fill: '#64748b', fontSize: 10 }}
                  axisLine={false}
                  tickLine={false}
                />
                <Tooltip
                  cursor={{ fill: 'rgba(255,255,255,0.04)' }}
                  content={({ active, payload }) => {
                    if (!active || !payload?.length) return null;
                    const d = payload[0].payload;
                    return (
                      <div className="rounded-lg border border-line bg-panel/95 px-4 py-3 shadow-xl backdrop-blur">
                        <p className="text-sm font-bold text-white">{d.name}</p>
                        <p className="text-xs text-slate-300">
                          {d.value.toLocaleString()} rounds
                        </p>
                        <p className="text-xs font-bold" style={{ color: d.color }}>
                          {total > 0 ? ((d.value / total) * 100).toFixed(1) : 0}%
                        </p>
                      </div>
                    );
                  }}
                />
                <Bar dataKey="value" radius={[4, 4, 0, 0]} maxBarSize={52}>
                  {data.map(entry => (
                    <Cell key={entry.name} fill={entry.color} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>

          {/* Summary row */}
          <div className="mt-4 grid grid-cols-5 gap-2 text-center">
            {data.map(d => (
              <div key={d.name} className="space-y-0.5">
                <div
                  className="h-1 rounded-full mx-auto w-8"
                  style={{ backgroundColor: d.color }}
                />
                <div className="text-xs font-bold text-white">
                  {d.value.toLocaleString()}
                </div>
                <div className="text-[10px] text-slate-500">
                  {total > 0 ? ((d.value / total) * 100).toFixed(1) : 0}%
                </div>
              </div>
            ))}
          </div>
        </>
      ) : (
        <div className="flex h-44 items-center justify-center text-sm text-slate-500">
          No round data yet
        </div>
      )}
    </div>
  );
}

