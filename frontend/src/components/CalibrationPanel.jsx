import { useEffect, useState } from 'react';
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  CartesianGrid, Cell, ReferenceLine, LineChart, Line,
} from 'recharts';
import { fetchCalibration, fetchConfidenceCalibration, fetchConfidenceAudit, resetCalibration } from '../api/client.js';

// ── Helpers ───────────────────────────────────────────────────────────────

function pct(v) { return v != null ? `${(v * 100).toFixed(1)}%` : '—'; }

function Badge({ children, color = 'text-slate-400', bg = 'bg-slate-700/30', border = 'border-slate-600/30' }) {
  return (
    <span className={`rounded-full border px-2.5 py-0.5 text-[10px] font-bold ${color} ${bg} ${border}`}>
      {children}
    </span>
  );
}

function MiniBar({ value, max = 100, color = '#35d4ff' }) {
  const pct = Math.min(100, Math.max(0, (value / max) * 100));
  return (
    <div className="h-1.5 w-full rounded-full bg-slate-800">
      <div className="h-full rounded-full transition-all duration-700" style={{ width: `${pct}%`, backgroundColor: color }} />
    </div>
  );
}

const BIN_COLORS = {
  '0-20':   '#64748b',
  '20-40':  '#35d4ff',
  '40-60':  '#fbbf24',
  '60-80':  '#f97316',
  '80-100': '#ff5277',
};

// ── Sub-panels ────────────────────────────────────────────────────────────

function BayesianPanel({ data }) {
  if (!data) return null;
  const posterior = data.posterior || {};
  const chartData = Object.entries(posterior).map(([cat, val]) => ({
    cat: cat.replace('_', ' '),
    value: Math.round(val * 100),
  }));
  const CAT_COLORS = ['#38bdf8','#35d4ff','#fbbf24','#f97316','#ff5277'];
  return (
    <div className="rounded-lg border border-line bg-ink/50 p-4">
      <h3 className="mb-1 text-sm font-bold text-white">Bayesian Posterior</h3>
      <p className="mb-3 text-[10px] text-slate-500">
        Category probability after {data.n_updates ?? 0} updates
      </p>
      <div className="h-36">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={chartData} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
            <XAxis dataKey="cat" tick={{ fill: '#64748b', fontSize: 9 }} axisLine={false} tickLine={false} />
            <YAxis tick={{ fill: '#64748b', fontSize: 9 }} axisLine={false} tickLine={false} domain={[0, 100]} />
            <Tooltip
              content={({ active, payload }) => active && payload?.length ? (
                <div className="rounded border border-line bg-panel/95 px-3 py-2 text-xs shadow-xl">
                  <p className="font-bold text-white">{payload[0].payload.cat}</p>
                  <p className="text-slate-300">{payload[0].value}%</p>
                </div>
              ) : null}
              cursor={{ fill: 'rgba(255,255,255,0.04)' }}
            />
            <Bar dataKey="value" radius={[3,3,0,0]} maxBarSize={40}>
              {chartData.map((_, i) => <Cell key={i} fill={CAT_COLORS[i % CAT_COLORS.length]} />)}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function BoundaryPanel({ optimizer }) {
  if (!optimizer) return null;
  const boundaries  = optimizer.boundaries || {};
  const defaults    = optimizer.default_boundaries || {};
  const adjustments = optimizer.last_adjustments || [];
  const CATS = ['VERY_LOW','LOW','MEDIUM','HIGH','VERY_HIGH'];
  const COLORS = ['#38bdf8','#35d4ff','#fbbf24','#f97316','#ff5277'];
  return (
    <div className="rounded-lg border border-line bg-ink/50 p-4">
      <div className="mb-3 flex items-start justify-between">
        <div>
          <h3 className="text-sm font-bold text-white">Boundary Optimizer</h3>
          <p className="text-[10px] text-slate-500">{optimizer.optimisation_count ?? 0} runs · next in {50 - (optimizer.resolved_since_last ?? 0)} rounds</p>
        </div>
      </div>
      <div className="space-y-1.5">
        {CATS.map((cat, i) => {
          const cur = boundaries[cat] || [0,0];
          const def = defaults[cat]   || [0,0];
          const drifted = Math.abs(cur[1] - def[1]) > 0.05;
          return (
            <div key={cat} className="flex items-center gap-3">
              <span className="w-16 text-[10px] font-semibold" style={{ color: COLORS[i] }}>{cat.replace('_',' ')}</span>
              <span className="w-20 text-[10px] text-slate-400">{cur[0].toFixed(2)}–{cur[1].toFixed(2)}×</span>
              {drifted && (
                <span className="text-[9px] text-amber-400">
                  (def {def[1].toFixed(2)}×)
                </span>
              )}
            </div>
          );
        })}
      </div>
      {adjustments.length > 0 && (
        <div className="mt-3 border-t border-line pt-3">
          <p className="mb-1 text-[9px] uppercase tracking-wide text-slate-600">Last adjustments</p>
          {adjustments.map((adj, i) => (
            <p key={i} className="text-[9px] text-amber-400 leading-relaxed">{adj}</p>
          ))}
        </div>
      )}
    </div>
  );
}

function RecalPanel({ recal }) {
  if (!recal) return null;
  const active    = recal.active;
  const hitRate   = recal.current_hit_rate != null ? Math.round(recal.current_hit_rate * 100) : null;
  const collected = recal.collected ?? 0;
  const target    = recal.collect_target ?? 20;
  const remaining = recal.remaining ?? 0;
  return (
    <div className={`rounded-lg border p-4 ${active ? 'border-amber-500/40 bg-amber-500/8' : 'border-line bg-ink/50'}`}>
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-bold text-white">Recalibration Mode</h3>
        <Badge
          color={active ? 'text-amber-400' : 'text-slate-500'}
          bg={active ? 'bg-amber-500/15' : 'bg-slate-700/30'}
          border={active ? 'border-amber-500/30' : 'border-slate-600/30'}
        >
          {active ? '⚠ Active' : '✓ Idle'}
        </Badge>
      </div>
      {active && (
        <>
          <div className="mb-2">
            <div className="mb-1 flex justify-between text-[10px] text-slate-400">
              <span>Data collection</span>
              <span className="font-bold text-amber-400">{collected}/{target}</span>
            </div>
            <MiniBar value={collected} max={target} color="#fbbf24" />
          </div>
          <p className="text-[10px] text-amber-400">{remaining} rounds before betting resumes</p>
          {recal.trigger_hit_rate != null && (
            <p className="text-[9px] text-slate-500 mt-1">
              Triggered at {Math.round(recal.trigger_hit_rate * 100)}% hit rate (&lt;45% threshold)
            </p>
          )}
        </>
      )}
      {!active && hitRate !== null && (
        <div>
          <div className="mb-1 flex justify-between text-[10px] text-slate-400">
            <span>Current hit rate (20-round)</span>
            <span className={`font-bold ${hitRate >= 45 ? 'text-lime-400' : 'text-rose-400'}`}>{hitRate}%</span>
          </div>
          <MiniBar value={hitRate} color={hitRate >= 45 ? '#9cff45' : '#ff5277'} />
          <p className="text-[9px] text-slate-500 mt-1">Recalibration triggers below 45%</p>
        </div>
      )}
    </div>
  );
}

function ConfBinsPanel({ bins, inverted, correction }) {
  if (!bins) return null;
  const BIN_ORDER = ['0-20','20-40','40-60','60-80','80-100'];
  const chartData = BIN_ORDER.map(label => {
    const b = bins[label] || {};
    return {
      label,
      accuracy:     b.accuracy != null ? Math.round(b.accuracy * 100) : 0,
      mean_conf:    b.mean_predicted_conf != null ? Math.round(b.mean_predicted_conf) : 0,
      correction:   b.correction_factor != null ? b.correction_factor : 1,
      total:        b.total ?? 0,
    };
  });
  return (
    <div className="rounded-lg border border-line bg-ink/50 p-4">
      <div className="mb-3 flex items-center justify-between">
        <div>
          <h3 className="text-sm font-bold text-white">Confidence Calibration</h3>
          <p className="text-[10px] text-slate-500">Actual accuracy vs predicted confidence per bin</p>
        </div>
        {inverted && (
          <Badge color="text-rose-400" bg="bg-rose-500/15" border="border-rose-500/30">
            ⟲ Inverted
          </Badge>
        )}
      </div>
      <div className="h-40">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={chartData} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
            <XAxis dataKey="label" tick={{ fill: '#64748b', fontSize: 9 }} axisLine={false} tickLine={false} />
            <YAxis tick={{ fill: '#64748b', fontSize: 9 }} axisLine={false} tickLine={false} domain={[0,100]} />
            <Tooltip
              content={({ active, payload }) => active && payload?.length ? (
                <div className="rounded border border-line bg-panel/95 px-3 py-2 text-xs shadow-xl min-w-[130px]">
                  <p className="font-bold text-white">Bin {payload[0].payload.label}%</p>
                  <p style={{ color: '#35d4ff' }}>Predicted: {payload[0].payload.mean_conf}%</p>
                  <p style={{ color: '#9cff45' }}>Actual: {payload[0].payload.accuracy}%</p>
                  <p className="text-slate-400">Factor: ×{payload[0].payload.correction.toFixed(3)}</p>
                  <p className="text-slate-500">n={payload[0].payload.total}</p>
                </div>
              ) : null}
              cursor={{ fill: 'rgba(255,255,255,0.04)' }}
            />
            <ReferenceLine y={50} stroke="#64748b" strokeDasharray="4 2" strokeOpacity={0.4} />
            <Bar dataKey="mean_conf" fill="#35d4ff" radius={[2,2,0,0]} maxBarSize={20} opacity={0.5} name="Predicted" />
            <Bar dataKey="accuracy"  fill="#9cff45" radius={[2,2,0,0]} maxBarSize={20} name="Actual" />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <div className="mt-2 flex items-center gap-4 text-[10px] text-slate-500">
        <span className="flex items-center gap-1"><span className="h-2 w-3 bg-cyan-400/60 rounded-sm" /> Predicted conf</span>
        <span className="flex items-center gap-1"><span className="h-2 w-3 bg-lime-400 rounded-sm" /> Actual accuracy</span>
      </div>
    </div>
  );
}

function AuditLogPanel({ audit }) {
  if (!audit?.length) return (
    <div className="rounded-lg border border-line bg-ink/50 p-4">
      <h3 className="text-sm font-bold text-white mb-2">Confidence Audit Log</h3>
      <p className="text-xs text-slate-500">No entries yet</p>
    </div>
  );
  return (
    <div className="rounded-lg border border-line bg-ink/50 p-4">
      <h3 className="mb-3 text-sm font-bold text-white">Confidence Audit Log</h3>
      <div className="space-y-1.5 overflow-auto" style={{ maxHeight: 180 }}>
        {[...audit].reverse().slice(0,20).map((entry, i) => (
          <div key={i} className="flex items-start gap-2 text-[10px]">
            <span className="shrink-0 font-mono text-slate-600">
              {new Date(entry.ts).toLocaleTimeString([], { hour:'2-digit', minute:'2-digit' })}
            </span>
            <span className="text-slate-400">
              <span className={entry.inverted ? 'text-rose-400' : 'text-cyan-400'}>
                {entry.raw_conf?.toFixed(1)}%
              </span>
              {' → '}
              <span className="font-bold text-white">{entry.calibrated_conf?.toFixed(1)}%</span>
              {' '}
              <span className="text-slate-600">[{entry.bin}] ×{entry.correction_factor?.toFixed(3)}</span>
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Main Export ───────────────────────────────────────────────────────────

export default function CalibrationPanel() {
  const [calibration, setCalibration]   = useState(null);
  const [confCal,     setConfCal]       = useState(null);
  const [audit,       setAudit]         = useState([]);
  const [loading,     setLoading]       = useState(false);
  const [resetting,   setResetting]     = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const [cal, cc, au] = await Promise.all([
        fetchCalibration(),
        fetchConfidenceCalibration(),
        fetchConfidenceAudit(40),
      ]);
      setCalibration(cal);
      setConfCal(cc);
      setAudit(Array.isArray(au) ? au : []);
    } catch (_) {}
    setLoading(false);
  };

  useEffect(() => { load(); }, []);

  const handleReset = async () => {
    if (!window.confirm('Reset all calibration state? This cannot be undone.')) return;
    setResetting(true);
    try { await resetCalibration(); await load(); } catch (_) {}
    setResetting(false);
  };

  return (
    <div className="rounded-xl border border-line bg-panel/80 p-5 shadow-lg backdrop-blur">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-bold text-white">Calibration Engine</h2>
          <p className="text-xs text-slate-500">Bayesian priors · boundary optimizer · recalibration · confidence audit</p>
        </div>
        <div className="flex gap-2">
          <button onClick={load} disabled={loading}
            className="rounded-md border border-cyan/40 px-3 py-1.5 text-xs font-bold text-cyan hover:bg-cyan/10 disabled:opacity-50">
            {loading ? 'Loading…' : 'Refresh'}
          </button>
          <button onClick={handleReset} disabled={resetting}
            className="rounded-md border border-rose-500/30 px-3 py-1.5 text-xs font-bold text-rose-400 hover:bg-rose-500/10 disabled:opacity-50">
            {resetting ? 'Resetting…' : 'Reset'}
          </button>
        </div>
      </div>

      {!calibration && !confCal ? (
        <div className="flex h-40 items-center justify-center text-sm text-slate-500">Loading calibration data…</div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          <BayesianPanel data={calibration?.bayesian} />
          <BoundaryPanel optimizer={calibration?.optimizer} />
          <RecalPanel recal={calibration?.recalibration} />
          <ConfBinsPanel
            bins={confCal?.bins}
            inverted={confCal?.inverted}
            correction={confCal?.correction}
          />
          <div className="md:col-span-2">
            <AuditLogPanel audit={audit} />
          </div>
        </div>
      )}

      {confCal?.summary && (
        <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
          {[
            { label: 'Total Calibrated',    value: confCal.summary.total_calibrated   ?? 0, color: 'text-cyan-400' },
            { label: 'Over-conf Events',    value: confCal.summary.over_confidence_events  ?? 0, color: 'text-amber-400' },
            { label: 'Under-conf Events',   value: confCal.summary.under_confidence_events ?? 0, color: 'text-sky-400'  },
            { label: 'Inversions Applied',  value: confCal.summary.inversions_applied       ?? 0, color: 'text-rose-400' },
          ].map(({ label, value, color }) => (
            <div key={label} className="rounded-lg border border-line bg-ink/60 px-3 py-2 text-center">
              <div className={`text-xl font-black ${color}`}>{value}</div>
              <div className="text-[9px] uppercase tracking-wide text-slate-500">{label}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
