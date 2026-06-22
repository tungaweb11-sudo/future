import { useState } from 'react';
import {
  ComposedChart, Bar, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
  CartesianGrid, Cell, ReferenceLine, AreaChart, Area, PieChart, Pie,
} from 'recharts';
import { formatMultiplier, formatPercent, riskColor } from '../lib/format.js';

// ── Constants ─────────────────────────────────────────────────────────────

const CAT_COLOR = {
  VERY_LOW:  { hex: '#38bdf8', pill: 'bg-sky-500/15 text-sky-300 border-sky-500/30',         bar: 'bg-sky-400',    dot: 'bg-sky-400'    },
  LOW:       { hex: '#35d4ff', pill: 'bg-cyan-500/15 text-cyan-300 border-cyan-500/30',       bar: 'bg-cyan-400',   dot: 'bg-cyan-400'   },
  MEDIUM:    { hex: '#9cff45', pill: 'bg-lime-500/15 text-lime-300 border-lime-500/30',       bar: 'bg-lime-400',   dot: 'bg-lime-400'   },
  HIGH:      { hex: '#f97316', pill: 'bg-orange-400/15 text-orange-300 border-orange-400/30', bar: 'bg-orange-400', dot: 'bg-orange-400' },
  VERY_HIGH: { hex: '#ff5277', pill: 'bg-rose-500/15 text-rose-300 border-rose-500/30',       bar: 'bg-rose-400',   dot: 'bg-rose-400'   },
};

const TREND_ICON = { hot: '🔥', cold: '🧊', neutral: '〰' };
const SHORT_CAT  = { VERY_LOW:'VL', LOW:'L', MEDIUM:'M', HIGH:'H', VERY_HIGH:'VH' };


// ── Helpers ───────────────────────────────────────────────────────────────

function fmtTs(ts) {
  if (ts == null) return { time: '—', date: '' };
  try {
    const d = typeof ts === 'number' ? new Date(ts * 1000) : new Date(ts);
    if (isNaN(d.getTime())) return { time: '—', date: '' };
    return {
      time: d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
      date: d.toLocaleDateString(),
    };
  } catch { return { time: '—', date: '' }; }
}

function multColor(v) {
  if (v >= 15) return '#ff5277';
  if (v >= 5)  return '#f97316';
  if (v >= 2)  return '#9cff45';
  return '#35d4ff';
}


// ── Small sub-components ─────────────────────────────────────────────────

function ActionBadge({ action }) {
  if (!action) return <span className="text-slate-600">—</span>;
  return (
    <span className={`rounded-full border px-2 py-0.5 text-[10px] font-black ${
      action === 'BET'
        ? 'bg-lime-500/15 text-lime-300 border-lime-500/30'
        : 'bg-slate-700/30 text-slate-400 border-slate-600/30'
    }`}>{action}</span>
  );
}

function CorrectBadge({ correct }) {
  if (correct === true)
    return <span className="rounded-full bg-lime-500/15 px-2 py-0.5 text-[10px] font-bold text-lime-300 border border-lime-500/30">✓ Correct</span>;
  if (correct === false)
    return <span className="rounded-full bg-rose-500/15 px-2 py-0.5 text-[10px] font-bold text-rose-300 border border-rose-500/30">✗ Wrong</span>;
  return <span className="rounded-full bg-slate-700/40 px-2 py-0.5 text-[10px] font-semibold text-slate-500 border border-slate-700">Pending</span>;
}

function StreakBadge({ streak }) {
  if (!streak?.category) return <span className="text-slate-600">—</span>;
  const { category, length } = streak;
  const dot = CAT_COLOR[category]?.dot ?? 'bg-slate-400';
  const w   = length >= 4 ? 'font-black' : length >= 2 ? 'font-bold' : 'font-medium';
  return (
    <div className="flex items-center gap-1">
      <div className={`h-2 w-2 rounded-full ${dot}`} />
      <span className={`text-[11px] text-white ${w}`}>{SHORT_CAT[category] ?? category}</span>
      <span className="text-[10px] text-slate-500">×{length}</span>
    </div>
  );
}


// ── Chart 1: Predicted vs Actual multipliers ──────────────────────────────

function PredVsActualChart({ decisions }) {
  const resolved = decisions.filter(d => d.actual_multiplier != null).slice(-30);
  if (!resolved.length) return (
    <div className="flex h-full items-center justify-center text-xs text-slate-500">
      Waiting for resolved rounds…
    </div>
  );

  const data = resolved.map((d, i) => ({
    i: d.actual_round_id ?? i + 1,
    actual:    +d.actual_multiplier.toFixed(2),
    cashout:   d.recommended_cashout ? +d.recommended_cashout.toFixed(2) : null,
    correct:   d.correct,
  }));

  return (
    <ResponsiveContainer width="100%" height="100%">
      <ComposedChart data={data} margin={{ top: 6, right: 6, left: -18, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
        <XAxis dataKey="i" tick={{ fill:'#64748b', fontSize:9 }} axisLine={false} tickLine={false} interval="preserveStartEnd" />
        <YAxis tick={{ fill:'#64748b', fontSize:9 }} axisLine={false} tickLine={false} domain={['auto','auto']} />
        <Tooltip
          content={({ active, payload, label }) => {
            if (!active || !payload?.length) return null;
            const d = payload[0]?.payload;
            return (
              <div className="rounded-lg border border-line bg-panel/95 px-3 py-2 text-xs shadow-xl backdrop-blur">
                <p className="text-slate-400 mb-1">Round #{label}</p>
                <p style={{ color: multColor(d.actual) }}>Actual: {d.actual}×</p>
                {d.cashout && <p className="text-lime-400">Cashout: {d.cashout}×</p>}
                <p className={d.correct ? 'text-lime-400' : 'text-rose-400'}>{d.correct ? '✓ Correct' : '✗ Wrong'}</p>
              </div>
            );
          }}
          cursor={{ fill: 'rgba(255,255,255,0.04)' }}
        />
        <Bar dataKey="actual" radius={[3,3,0,0]} maxBarSize={18} name="Actual">
          {data.map((d, i) => (
            <Cell key={i} fill={d.correct === true ? '#9cff45' : d.correct === false ? '#ff5277' : '#64748b'} />
          ))}
        </Bar>
        <Line type="monotone" dataKey="cashout" stroke="#fbbf24" strokeWidth={2} dot={false} name="Cashout target" strokeDasharray="4 2" />
        <ReferenceLine y={2} stroke="#35d4ff" strokeDasharray="3 3" strokeOpacity={0.4} />
      </ComposedChart>
    </ResponsiveContainer>
  );
}


// ── Chart 2: Confidence over time ─────────────────────────────────────────

function ConfidenceChart({ decisions }) {
  const recent = [...decisions].reverse().slice(0, 30).reverse();
  if (!recent.length) return (
    <div className="flex h-full items-center justify-center text-xs text-slate-500">No data</div>
  );

  const data = recent.map((d, i) => ({
    i:          d.last_round_id ?? i,
    confidence: +Number(d.confidence ?? 0).toFixed(1),
    correct:    d.correct,
  }));

  const avg = data.reduce((s, d) => s + d.confidence, 0) / data.length;

  return (
    <ResponsiveContainer width="100%" height="100%">
      <AreaChart data={data} margin={{ top: 6, right: 6, left: -18, bottom: 0 }}>
        <defs>
          <linearGradient id="confGrad" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%"   stopColor="#35d4ff" stopOpacity={0.3} />
            <stop offset="100%" stopColor="#35d4ff" stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
        <XAxis dataKey="i" tick={{ fill:'#64748b', fontSize:9 }} axisLine={false} tickLine={false} interval="preserveStartEnd" />
        <YAxis tick={{ fill:'#64748b', fontSize:9 }} axisLine={false} tickLine={false} domain={[0,100]} ticks={[0,25,50,75,100]} />
        <Tooltip
          content={({ active, payload, label }) => {
            if (!active || !payload?.length) return null;
            const d = payload[0]?.payload;
            return (
              <div className="rounded-lg border border-line bg-panel/95 px-3 py-2 text-xs shadow-xl backdrop-blur">
                <p className="text-slate-400 mb-1">Round #{label}</p>
                <p className="text-cyan-400">Confidence: {d.confidence}%</p>
                {d.correct != null && <p className={d.correct ? 'text-lime-400' : 'text-rose-400'}>{d.correct ? '✓ Correct' : '✗ Wrong'}</p>}
              </div>
            );
          }}
          cursor={{ stroke:'#35d4ff', strokeWidth:1, strokeDasharray:'4 4' }}
        />
        <ReferenceLine y={avg} stroke="#9cff45" strokeDasharray="4 2" strokeOpacity={0.6}
          label={{ value: `avg ${avg.toFixed(0)}%`, position:'insideTopRight', fill:'#9cff45', fontSize:9 }} />
        <Area type="monotone" dataKey="confidence" stroke="#35d4ff" strokeWidth={2}
          fill="url(#confGrad)" dot={false}
          activeDot={{ r:4, fill:'#35d4ff', stroke:'#070a12', strokeWidth:2 }} />
      </AreaChart>
    </ResponsiveContainer>
  );
}


// ── Chart 3: Rolling hit-rate ─────────────────────────────────────────────

function HitRateChart({ decisions }) {
  const resolved = decisions.filter(d => d.actual_multiplier != null);
  if (resolved.length < 3) return (
    <div className="flex h-full items-center justify-center text-xs text-slate-500">
      Need 3+ resolved rounds
    </div>
  );

  // Rolling 10-window hit rate
  const data = resolved.map((_, i) => {
    if (i < 2) return null;
    const window = resolved.slice(Math.max(0, i - 9), i + 1);
    const hits   = window.filter(d => d.correct === true).length;
    return { i: resolved[i].actual_round_id ?? i, rate: Math.round((hits / window.length) * 100) };
  }).filter(Boolean);

  return (
    <ResponsiveContainer width="100%" height="100%">
      <AreaChart data={data} margin={{ top: 6, right: 6, left: -18, bottom: 0 }}>
        <defs>
          <linearGradient id="hrGrad" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%"   stopColor="#9cff45" stopOpacity={0.3} />
            <stop offset="100%" stopColor="#9cff45" stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
        <XAxis dataKey="i" tick={{ fill:'#64748b', fontSize:9 }} axisLine={false} tickLine={false} interval="preserveStartEnd" />
        <YAxis tick={{ fill:'#64748b', fontSize:9 }} axisLine={false} tickLine={false} domain={[0,100]} ticks={[0,25,50,75,100]} />
        <Tooltip
          content={({ active, payload, label }) => {
            if (!active || !payload?.length) return null;
            return (
              <div className="rounded-lg border border-line bg-panel/95 px-3 py-2 text-xs shadow-xl backdrop-blur">
                <p className="text-slate-400 mb-1">Round #{label}</p>
                <p className="text-lime-400 font-bold">Hit Rate: {payload[0].value}%</p>
                <p className="text-slate-500">Rolling 10-window</p>
              </div>
            );
          }}
          cursor={{ stroke:'#9cff45', strokeWidth:1, strokeDasharray:'4 4' }}
        />
        <ReferenceLine y={50} stroke="#fbbf24" strokeDasharray="4 2" strokeOpacity={0.4} />
        <Area type="monotone" dataKey="rate" stroke="#9cff45" strokeWidth={2}
          fill="url(#hrGrad)" dot={false}
          activeDot={{ r:4, fill:'#9cff45', stroke:'#070a12', strokeWidth:2 }} />
      </AreaChart>
    </ResponsiveContainer>
  );
}


// ── Chart 4: Category prediction distribution (donut) ────────────────────

function PredDistChart({ decisions }) {
  const counts = {};
  decisions.forEach(d => { if (d.prediction) counts[d.prediction] = (counts[d.prediction] || 0) + 1; });
  const data = Object.entries(counts).map(([name, value]) => ({ name, value }));
  if (!data.length) return (
    <div className="flex h-full items-center justify-center text-xs text-slate-500">No data</div>
  );
  const total = data.reduce((s, d) => s + d.value, 0);

  return (
    <ResponsiveContainer width="100%" height="100%">
      <PieChart>
        <Pie data={data} cx="50%" cy="50%" innerRadius="45%" outerRadius="75%"
          paddingAngle={3} dataKey="value" stroke="none">
          {data.map(d => (
            <Cell key={d.name} fill={CAT_COLOR[d.name]?.hex ?? '#64748b'} />
          ))}
        </Pie>
        <Tooltip
          content={({ active, payload }) => {
            if (!active || !payload?.length) return null;
            const { name, value } = payload[0];
            return (
              <div className="rounded-lg border border-line bg-panel/95 px-3 py-2 text-xs shadow-xl backdrop-blur">
                <p className="font-bold text-white">{name}</p>
                <p className="text-slate-300">{value} ({((value/total)*100).toFixed(1)}%)</p>
              </div>
            );
          }}
        />
      </PieChart>
    </ResponsiveContainer>
  );
}


// ── Graphical summary panel ───────────────────────────────────────────────

function GraphPanel({ decisions }) {
  const resolved  = decisions.filter(d => d.actual_multiplier != null);
  const correct   = resolved.filter(d => d.correct === true);
  const hitRate   = resolved.length ? Math.round((correct.length / resolved.length) * 100) : null;
  const avgConf   = decisions.length
    ? (decisions.reduce((s, d) => s + Number(d.confidence ?? 0), 0) / decisions.length).toFixed(1)
    : null;
  const lastPred  = [...decisions].reverse()[0];

  return (
    <div className="mb-5 space-y-4">
      {/* KPI row */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[
          { label: 'Hit Rate',       value: hitRate != null ? `${hitRate}%` : '—',           color: hitRate >= 50 ? 'text-lime-400' : hitRate != null ? 'text-rose-400' : 'text-slate-500', bg: 'bg-lime-500/8'  },
          { label: 'Correct',        value: `${correct.length}/${resolved.length}`,           color: 'text-white',      bg: 'bg-slate-800/60' },
          { label: 'Avg Confidence', value: avgConf != null ? `${avgConf}%` : '—',           color: 'text-cyan-400',   bg: 'bg-cyan-500/8'  },
          { label: 'Last Prediction',value: lastPred?.prediction ?? '—',                      color: CAT_COLOR[lastPred?.prediction]?.hex ? '' : 'text-slate-400',
            style: { color: CAT_COLOR[lastPred?.prediction]?.hex }, bg: 'bg-slate-800/60' },
        ].map(({ label, value, color, bg, style }) => (
          <div key={label} className={`rounded-xl border border-line ${bg} px-4 py-3 text-center`}>
            <div className={`text-xl font-black ${color}`} style={style}>{value}</div>
            <div className="mt-0.5 text-[10px] uppercase tracking-[0.12em] text-slate-500">{label}</div>
          </div>
        ))}
      </div>

      {/* 4-chart grid */}
      <div className="grid gap-4 md:grid-cols-2">
        <div className="rounded-xl border border-line bg-ink/60 p-4">
          <h3 className="mb-1 text-sm font-bold text-white">Actual Results</h3>
          <p className="mb-3 text-[10px] text-slate-500">Actual crash × per round — green=correct, red=wrong, dashed=cashout target</p>
          <div className="h-40"><PredVsActualChart decisions={decisions} /></div>
        </div>

        <div className="rounded-xl border border-line bg-ink/60 p-4">
          <h3 className="mb-1 text-sm font-bold text-white">Confidence Trend</h3>
          <p className="mb-3 text-[10px] text-slate-500">Model confidence score over last 30 predictions</p>
          <div className="h-40"><ConfidenceChart decisions={decisions} /></div>
        </div>

        <div className="rounded-xl border border-line bg-ink/60 p-4">
          <h3 className="mb-1 text-sm font-bold text-white">Rolling Hit Rate</h3>
          <p className="mb-3 text-[10px] text-slate-500">10-round sliding window accuracy — dashed=50% baseline</p>
          <div className="h-40"><HitRateChart decisions={decisions} /></div>
        </div>

        <div className="rounded-xl border border-line bg-ink/60 p-4">
          <h3 className="mb-1 text-sm font-bold text-white">Prediction Mix</h3>
          <p className="mb-3 text-[10px] text-slate-500">Category distribution across all predictions</p>
          <div className="flex h-40 items-center">
            <div className="flex-1 h-full"><PredDistChart decisions={decisions} /></div>
            <div className="ml-3 space-y-1.5">
              {['VERY_LOW','LOW','MEDIUM','HIGH','VERY_HIGH'].map(cat => {
                const cnt = decisions.filter(d => d.prediction === cat).length;
                if (!cnt) return null;
                return (
                  <div key={cat} className="flex items-center gap-1.5 text-[10px]">
                    <span className="h-2 w-2 rounded-full shrink-0" style={{ backgroundColor: CAT_COLOR[cat]?.hex }} />
                    <span className="text-slate-400">{cat.replace('_',' ')}</span>
                    <span className="font-bold text-white ml-1">{cnt}</span>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}


// ── Table section ─────────────────────────────────────────────────────────

const COLUMNS = [
  { key: 'time',       label: 'Time'       },
  { key: 'last',       label: 'Last ×'     },
  { key: 'prediction', label: 'Prediction' },
  { key: 'confidence', label: 'Conf'       },
  { key: 'cashout',    label: 'Cashout'    },
  { key: 'action',     label: 'Action'     },
  { key: 'risk',       label: 'Risk'       },
  { key: 'streak',     label: 'Streak'     },
  { key: 'actual',     label: 'Actual'     },
  { key: 'result',     label: 'Result'     },
];

function TableSection({ decisions }) {
  const sorted = [...decisions].reverse();

  return (
    <div className="overflow-auto rounded-lg border border-line" style={{ maxHeight: 480 }}>
      <table className="w-full text-left text-sm" style={{ minWidth: 900 }}>
        <thead className="sticky top-0 z-10 bg-panel border-b border-line">
          <tr className="text-[10px] uppercase tracking-[0.15em] text-slate-500">
            {COLUMNS.map(col => (
              <th key={col.key} className="px-3 py-3 font-semibold whitespace-nowrap">{col.label}</th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-line/40">
          {sorted.length === 0 && (
            <tr>
              <td colSpan={COLUMNS.length} className="px-4 py-10 text-center text-slate-500 italic">
                No predictions yet — click Refresh to fetch the first one.
              </td>
            </tr>
          )}
          {sorted.map((item, i) => {
            const catMeta = CAT_COLOR[item.prediction] ?? { pill: 'bg-slate-700/30 text-slate-300 border-slate-600/30', bar: 'bg-slate-400' };
            const conf    = Math.min(Math.max(Number(item.confidence ?? 0), 0), 100);
            const { time, date } = fmtTs(item.last_round_ts ?? item.created_at);
            const actTs  = fmtTs(item.actual_round_ts);
            const actRid = item.actual_round_id ?? (item.last_round_id != null ? item.last_round_id + 1 : null);

            return (
              <tr key={`${item.created_at}-${i}`}
                className={`transition-colors hover:bg-slate-800/40 ${i === 0 ? 'bg-slate-800/20' : ''}`}>

                <td className="px-3 py-2.5 text-xs whitespace-nowrap">
                  <div className="font-medium text-white">{time}</div>
                  <div className="text-slate-600 text-[10px]">{date}</div>
                </td>

                <td className="px-3 py-2.5 whitespace-nowrap">
                  {item.last_multiplier != null ? (
                    <span className="font-black" style={{ color: multColor(item.last_multiplier) }}>
                      {Number(item.last_multiplier).toFixed(2)}×
                    </span>
                  ) : <span className="text-slate-600 text-xs">—</span>}
                </td>

                <td className="px-3 py-2.5 whitespace-nowrap">
                  <span className={`inline-block rounded-full border px-2.5 py-0.5 text-xs font-bold ${catMeta.pill}`}>
                    {item.prediction ?? '—'}
                  </span>
                </td>

                <td className="px-3 py-2.5">
                  <div className="flex items-center gap-2">
                    <div className="h-1.5 w-12 shrink-0 overflow-hidden rounded-full bg-slate-800">
                      <div className={`h-full rounded-full ${catMeta.bar}`} style={{ width: `${conf}%` }} />
                    </div>
                    <span className="text-xs text-slate-300">{conf.toFixed(0)}%</span>
                  </div>
                </td>

                <td className="px-3 py-2.5 whitespace-nowrap text-xs font-black text-lime-400">
                  {item.recommended_cashout ? `${Number(item.recommended_cashout).toFixed(2)}×` : '—'}
                </td>

                <td className="px-3 py-2.5 whitespace-nowrap"><ActionBadge action={item.action} /></td>

                <td className={`px-3 py-2.5 text-xs font-bold whitespace-nowrap ${riskColor(item.risk_level)}`}>
                  {item.risk_level ?? '—'}
                </td>

                <td className="px-3 py-2.5 whitespace-nowrap"><StreakBadge streak={item.streak} /></td>

                <td className="px-3 py-2.5 text-xs whitespace-nowrap">
                  {item.actual_multiplier != null ? (
                    <div className="space-y-0.5">
                      <div className="font-mono text-slate-400 text-[10px]">#{actRid ?? '?'}</div>
                      <span className="font-bold" style={{ color: multColor(item.actual_multiplier) }}>
                        {Number(item.actual_multiplier).toFixed(2)}×
                      </span>
                      {actTs.time !== '—' && <div className="text-slate-600 text-[10px]">{actTs.time}</div>}
                    </div>
                  ) : <span className="text-slate-600">—</span>}
                </td>

                <td className="px-3 py-2.5 whitespace-nowrap">
                  <CorrectBadge correct={item.correct} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}


// ── Main export ───────────────────────────────────────────────────────────

export default function PredictionLog({ decisions = [] }) {
  const [view, setView] = useState('graphs'); // 'graphs' | 'table'
  const resolved = decisions.filter(d => d.actual_multiplier != null);
  const correct  = resolved.filter(d => d.correct === true);
  const hitRate  = resolved.length ? Math.round((correct.length / resolved.length) * 100) : null;
  const sorted   = [...decisions].reverse();

  return (
    <section className="rounded-xl border border-line bg-panel/85 p-5 shadow-lg backdrop-blur">

      {/* Header */}
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-bold text-white">Prediction Log</h2>
          <p className="text-xs text-slate-500 mt-0.5">
            {decisions.length} decisions · {resolved.length} resolved
            {hitRate !== null && <span className="ml-2 text-lime-400 font-bold">{hitRate}% accuracy</span>}
          </p>
        </div>

        {/* View toggle */}
        <div className="flex rounded-lg border border-line overflow-hidden text-xs font-bold">
          {[['graphs','📊 Charts'],['table','☰ Table']].map(([v, label]) => (
            <button
              key={v}
              onClick={() => setView(v)}
              className={`px-4 py-2 transition ${
                view === v
                  ? 'bg-cyan text-ink'
                  : 'text-slate-400 hover:text-white hover:bg-slate-800'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* Content */}
      {view === 'graphs' ? (
        <GraphPanel decisions={decisions} />
      ) : (
        <TableSection decisions={decisions} />
      )}

      {/* Footer */}
      <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-[10px] text-slate-600">
        <div className="flex items-center gap-3">
          <span>Engine: <span className="text-slate-400 font-medium">{sorted[0]?.engine ?? 'statistical_ensemble'}</span></span>
          {sorted[0]?.regime && (
            <span>Regime: <span className={`font-medium ${
              sorted[0].regime === 'high' ? 'text-rose-400' :
              sorted[0].regime === 'low'  ? 'text-cyan-400' : 'text-amber-300'
            }`}>{sorted[0].regime}</span></span>
          )}
        </div>
        <div className="flex items-center gap-3">
          {resolved.length === 0 && decisions.length > 0 && (
            <span className="text-amber-500/70">Actual results pending…</span>
          )}
          {sorted[0]?.source_round_count != null && (
            <span>Based on <span className="text-slate-400">{sorted[0].source_round_count}</span> rounds</span>
          )}
        </div>
      </div>
    </section>
  );
}
