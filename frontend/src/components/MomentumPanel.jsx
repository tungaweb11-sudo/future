import { useEffect, useState } from 'react';
import {
  RadarChart, Radar, PolarGrid, PolarAngleAxis,
  ResponsiveContainer, Tooltip, BarChart, Bar,
  XAxis, YAxis, CartesianGrid, Cell,
} from 'recharts';
import { fetchStreakMatrix } from '../api/client.js';

// ── Helpers ───────────────────────────────────────────────────────────────

const TREND_META = {
  HOT:     { color: '#ff5277', bg: 'bg-rose-500/15',   border: 'border-rose-500/30',   label: '🔥 HOT'     },
  WARM:    { color: '#f97316', bg: 'bg-orange-500/15', border: 'border-orange-500/30', label: '☀ WARM'     },
  NEUTRAL: { color: '#fbbf24', bg: 'bg-amber-400/15',  border: 'border-amber-400/30',  label: '〰 NEUTRAL' },
  COOL:    { color: '#35d4ff', bg: 'bg-cyan-500/15',   border: 'border-cyan-500/30',   label: '🌊 COOL'    },
  COLD:    { color: '#38bdf8', bg: 'bg-sky-500/15',    border: 'border-sky-500/30',    label: '🧊 COLD'    },
};

const REGIME_COLORS = { low: '#35d4ff', medium: '#fbbf24', high: '#ff5277' };

function TrendBadge({ trend }) {
  const m = TREND_META[trend] ?? TREND_META.NEUTRAL;
  return (
    <span className={`rounded-full border px-2.5 py-0.5 text-[10px] font-bold ${m.bg} ${m.border}`}
      style={{ color: m.color }}>
      {m.label}
    </span>
  );
}

// ── Sub-panels ────────────────────────────────────────────────────────────

function SuccessMatrixChart({ matrix }) {
  if (!matrix || !Object.keys(matrix).length) return (
    <div className="flex h-40 items-center justify-center text-xs text-slate-500">No matrix data yet</div>
  );

  const TRENDS  = ['HOT','WARM','NEUTRAL','COOL','COLD'];
  const REGIMES = ['low','medium','high'];

  const rows = TRENDS.map(trend => {
    const row = { trend };
    REGIMES.forEach(r => {
      const cell = matrix[trend]?.[r];
      row[r] = cell?.accuracy != null ? Math.round(cell.accuracy * 100) : null;
      row[`${r}_n`] = cell?.total ?? 0;
    });
    return row;
  });

  return (
    <div className="overflow-auto rounded-lg border border-line">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-line text-[9px] uppercase tracking-wide text-slate-500">
            <th className="px-3 py-2 text-left">Trend</th>
            {REGIMES.map(r => (
              <th key={r} className="px-3 py-2 text-center" style={{ color: REGIME_COLORS[r] }}>{r}</th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-line/40">
          {rows.map(row => (
            <tr key={row.trend} className="hover:bg-slate-800/30">
              <td className="px-3 py-2">
                <TrendBadge trend={row.trend} />
              </td>
              {REGIMES.map(r => {
                const val = row[r];
                const n   = row[`${r}_n`];
                const color = val == null ? '#475569'
                  : val >= 55 ? '#9cff45'
                  : val >= 40 ? '#fbbf24'
                  : '#ff5277';
                return (
                  <td key={r} className="px-3 py-2 text-center">
                    {val != null ? (
                      <div>
                        <span className="font-bold" style={{ color }}>{val}%</span>
                        <span className="ml-1 text-[9px] text-slate-600">n={n}</span>
                      </div>
                    ) : <span className="text-slate-600">—</span>}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ValidityPanel({ validity }) {
  if (!validity || !Object.keys(validity).length) return (
    <div className="flex h-28 items-center justify-center text-xs text-slate-500">No validity data yet</div>
  );

  const entries = Object.entries(validity).map(([key, v]) => {
    const [trend, regime] = key.split('|');
    return { key, trend, regime, ...v };
  });

  return (
    <div className="space-y-2 overflow-auto" style={{ maxHeight: 200 }}>
      {entries.map(e => (
        <div key={e.key} className={`flex items-center justify-between rounded-lg border px-3 py-2 ${
          e.downgraded ? 'border-amber-500/30 bg-amber-500/8' : 'border-line bg-ink/40'
        }`}>
          <div className="flex items-center gap-2">
            <TrendBadge trend={e.trend} />
            <span className="text-[10px]" style={{ color: REGIME_COLORS[e.regime] ?? '#64748b' }}>
              {e.regime}
            </span>
          </div>
          <div className="flex items-center gap-3 text-[10px]">
            {e.fail_rate != null && (
              <span className={e.fail_rate > 0.6 ? 'text-rose-400' : e.fail_rate > 0.4 ? 'text-amber-400' : 'text-slate-400'}>
                fail: {Math.round(e.fail_rate * 100)}%
              </span>
            )}
            <span className="text-slate-500">n={e.samples}</span>
            {e.downgraded && (
              <span className="rounded bg-amber-500/20 px-1.5 py-0.5 text-[9px] text-amber-400 border border-amber-500/30">
                ↓ {e.effective_trend}
              </span>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

// ── Main Export ───────────────────────────────────────────────────────────

export default function MomentumPanel({ prediction = null }) {
  const [matrixData, setMatrixData] = useState(null);
  const [loading,    setLoading]    = useState(false);

  const load = async () => {
    setLoading(true);
    try { setMatrixData(await fetchStreakMatrix()); } catch (_) {}
    setLoading(false);
  };

  useEffect(() => { load(); }, []);

  // Live momentum from latest prediction
  const streak      = prediction?.streak ?? {};
  const rawTrend    = (streak.raw_trend || 'NEUTRAL').toUpperCase();
  const effTrend    = (streak.trend      || streak.effective_trend || rawTrend).toUpperCase();
  const momentum    = streak.momentum_score ?? 0.5;
  const magnitude   = streak.magnitude ?? 0;
  const downgradeReason = streak.downgrade_reason || null;

  const momentumPct = Math.round(momentum * 100);
  const effMeta     = TREND_META[effTrend] ?? TREND_META.NEUTRAL;

  return (
    <div className="rounded-xl border border-line bg-panel/80 p-5 shadow-lg backdrop-blur">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-bold text-white">Momentum & Streak</h2>
          <p className="text-xs text-slate-500">Weighted momentum · validity checks · success matrix</p>
        </div>
        <button onClick={load} disabled={loading}
          className="rounded-md border border-cyan/40 px-3 py-1.5 text-xs font-bold text-cyan hover:bg-cyan/10 disabled:opacity-50">
          {loading ? 'Loading…' : 'Refresh'}
        </button>
      </div>

      {/* Live momentum from prediction */}
      {prediction && (
        <div className="mb-4 grid gap-3 sm:grid-cols-3">
          {/* Current effective trend */}
          <div className={`rounded-xl border p-4 text-center ${effMeta.bg} ${effMeta.border}`}>
            <div className="text-[10px] uppercase tracking-wide text-slate-400 mb-1">Effective Trend</div>
            <div className="text-2xl font-black" style={{ color: effMeta.color }}>{effTrend}</div>
            {rawTrend !== effTrend && (
              <div className="text-[9px] text-slate-500 mt-1">raw: {rawTrend}</div>
            )}
          </div>

          {/* Momentum score */}
          <div className="rounded-xl border border-line bg-ink/60 p-4 text-center">
            <div className="text-[10px] uppercase tracking-wide text-slate-400 mb-1">Momentum Score</div>
            <div className="text-2xl font-black" style={{ color: effMeta.color }}>{momentumPct}</div>
            <div className="mt-1.5 h-1.5 rounded-full bg-slate-800 overflow-hidden">
              <div className="h-full rounded-full transition-all duration-700"
                style={{ width: `${momentumPct}%`, backgroundColor: effMeta.color }} />
            </div>
            <div className="flex justify-between text-[9px] text-slate-600 mt-0.5">
              <span>COLD</span><span>NEUTRAL</span><span>HOT</span>
            </div>
          </div>

          {/* Magnitude */}
          <div className="rounded-xl border border-line bg-ink/60 p-4 text-center">
            <div className="text-[10px] uppercase tracking-wide text-slate-400 mb-1">Signal Strength</div>
            <div className="text-2xl font-black text-white">{Math.round(magnitude * 100)}%</div>
            <div className="mt-1.5 h-1.5 rounded-full bg-slate-800 overflow-hidden">
              <div className="h-full rounded-full bg-gradient-to-r from-slate-500 to-amber-400 transition-all duration-700"
                style={{ width: `${Math.round(magnitude * 100)}%` }} />
            </div>
            <div className="text-[9px] text-slate-600 mt-0.5">diminishing returns applied</div>
          </div>
        </div>
      )}

      {/* Downgrade warning */}
      {downgradeReason && (
        <div className="mb-4 rounded-lg border border-amber-500/30 bg-amber-500/8 px-4 py-3 text-xs text-amber-400">
          ⚠ {downgradeReason}
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        {/* Success Matrix */}
        <div>
          <h3 className="mb-2 text-sm font-bold text-white">Success Matrix</h3>
          <p className="mb-2 text-[10px] text-slate-500">Accuracy per trend × regime combination</p>
          <SuccessMatrixChart matrix={matrixData?.matrix} />
        </div>

        {/* Validity Checker */}
        <div>
          <h3 className="mb-2 text-sm font-bold text-white">Validity Checker</h3>
          <p className="mb-2 text-[10px] text-slate-500">Automatic HOT→WARM / COLD→NEUTRAL downgrades</p>
          <ValidityPanel validity={matrixData?.validity} />
        </div>
      </div>
    </div>
  );
}
