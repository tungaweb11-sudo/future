import { useEffect, useState } from 'react';
import {
  RadarChart, Radar, PolarGrid, PolarAngleAxis,
  ResponsiveContainer, Tooltip,
} from 'recharts';
import { fetchRiskTier } from '../api/client.js';

function pct(v, digits = 1) {
  return v != null ? `${(v * 100).toFixed(digits)}%` : '—';
}

function GateRow({ label, pass, value, detail }) {
  return (
    <div className={`flex items-start justify-between rounded-lg border px-4 py-3 ${
      pass === false
        ? 'border-rose-500/30 bg-rose-500/8'
        : pass === true
        ? 'border-lime-500/20 bg-lime-500/8'
        : 'border-line bg-ink/40'
    }`}>
      <div className="flex items-center gap-2.5">
        <span className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[10px] font-black ${
          pass === false ? 'bg-rose-500/30 text-rose-400'
          : pass === true ? 'bg-lime-500/30 text-lime-400'
          : 'bg-slate-700 text-slate-400'
        }`}>
          {pass === false ? '✗' : pass === true ? '✓' : '?'}
        </span>
        <div>
          <div className="text-xs font-semibold text-white">{label}</div>
          {detail && <div className="text-[10px] text-slate-500">{detail}</div>}
        </div>
      </div>
      <span className={`text-xs font-bold ${
        pass === false ? 'text-rose-400' : pass === true ? 'text-lime-400' : 'text-slate-400'
      }`}>{value}</span>
    </div>
  );
}

function ParamsPanel({ params, isDefault }) {
  if (!params) return null;
  return (
    <div className="rounded-lg border border-line bg-ink/50 p-4">
      <div className="mb-3 flex items-center justify-between">
        <h4 className="text-xs font-bold text-white">MEDIUM Risk Parameters</h4>
        {!isDefault && (
          <span className="rounded-full border border-amber-500/30 bg-amber-500/15 px-2 py-0.5 text-[9px] font-bold text-amber-400">
            Recalibrated
          </span>
        )}
      </div>
      <div className="grid grid-cols-3 gap-3 text-center">
        {[
          { label: 'Cashout Base', value: `${params.base?.toFixed(2)}×` },
          { label: 'Cashout Top',  value: `${params.top?.toFixed(2)}×`  },
          { label: 'Min Conf',     value: `${params.min_conf?.toFixed(1)}%` },
        ].map(({ label, value }) => (
          <div key={label} className="rounded bg-slate-800/60 py-2">
            <div className="text-sm font-black text-white">{value}</div>
            <div className="text-[9px] uppercase tracking-wide text-slate-500">{label}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function RadarGates({ accuracy, spread, rcs }) {
  // Normalise each gate metric to 0-100 for the radar
  const accScore  = accuracy  != null ? Math.round(accuracy  * 100) : 50;
  const spreadScore = spread  != null ? Math.round(Math.max(0, 1 - spread / 1.0) * 100) : 50;
  const rcsScore  = rcs       != null ? Math.round(rcs * 100) : 50;

  const data = [
    { metric: 'Accuracy',  value: accScore   },
    { metric: 'Spread',    value: spreadScore },
    { metric: 'RCS',       value: rcsScore    },
  ];

  return (
    <div className="h-44">
      <ResponsiveContainer width="100%" height="100%">
        <RadarChart data={data} margin={{ top: 8, right: 28, bottom: 8, left: 28 }}>
          <PolarGrid stroke="#1e293b" />
          <PolarAngleAxis dataKey="metric" tick={{ fill: '#64748b', fontSize: 11 }} />
          <Radar dataKey="value" stroke="#35d4ff" fill="#35d4ff" fillOpacity={0.2} strokeWidth={2} />
          <Tooltip
            content={({ active, payload }) => active && payload?.length ? (
              <div className="rounded border border-line bg-panel/95 px-3 py-2 text-xs shadow-xl">
                <p className="font-bold text-white">{payload[0].payload.metric}</p>
                <p className="text-cyan-400">{payload[0].value}/100</p>
              </div>
            ) : null}
          />
        </RadarChart>
      </ResponsiveContainer>
    </div>
  );
}

export default function RiskTierPanel({ prediction = null }) {
  const [data,    setData]    = useState(null);
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    try { setData(await fetchRiskTier()); } catch (_) {}
    setLoading(false);
  };

  useEffect(() => { load(); }, []);

  const locked   = data?.locked ?? false;
  const accuracy = data?.accuracy;
  const spread   = data?.spread;
  const recalCount = data?.recal_count ?? 0;
  const thresholds = data?.thresholds ?? {};
  const params   = data?.medium_params;

  // Live gate results from latest prediction
  const liveGates = prediction?.medium_gates;
  const liveRcs   = prediction?.risk_confidence_score;
  const liveReason = prediction?.risk_tier_downgrade;
  const liveLocked = prediction?.medium_locked;

  return (
    <div className="rounded-xl border border-line bg-panel/80 p-5 shadow-lg backdrop-blur">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-bold text-white">Risk-Tier Validator</h2>
          <p className="text-xs text-slate-500">
            MEDIUM risk gate system · recalibration on failure
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className={`rounded-full border px-3 py-1 text-xs font-bold ${
            locked || liveLocked
              ? 'border-rose-500/30 bg-rose-500/15 text-rose-400'
              : 'border-lime-500/30 bg-lime-500/15 text-lime-400'
          }`}>
            {locked || liveLocked ? '🔒 MEDIUM Locked' : '✓ MEDIUM Active'}
          </span>
          <button onClick={load} disabled={loading}
            className="rounded-md border border-cyan/40 px-3 py-1.5 text-xs font-bold text-cyan hover:bg-cyan/10 disabled:opacity-50">
            {loading ? '…' : 'Refresh'}
          </button>
        </div>
      </div>

      {/* Live downgrade notice */}
      {liveReason && (
        <div className="mb-4 rounded-lg border border-amber-500/30 bg-amber-500/8 px-4 py-3 text-xs text-amber-400">
          ⚡ Risk-tier override: {liveReason}
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        {/* Gate radar */}
        <div className="rounded-lg border border-line bg-ink/50 p-4">
          <h3 className="mb-1 text-sm font-bold text-white">Gate Radar</h3>
          <p className="mb-2 text-[10px] text-slate-500">Higher = better for each gate metric</p>
          <RadarGates
            accuracy={liveGates?.accuracy?.value ?? accuracy}
            spread={liveGates?.spread?.value ?? spread}
            rcs={liveRcs ?? null}
          />
        </div>

        {/* Live gate status */}
        <div className="rounded-lg border border-line bg-ink/50 p-4">
          <h3 className="mb-3 text-sm font-bold text-white">Gate Results</h3>
          <div className="space-y-2">
            <GateRow
              label="Gate 1 — Accuracy"
              pass={liveGates?.accuracy?.pass ?? (accuracy != null ? accuracy >= (thresholds.accuracy_floor ?? 0.35) : null)}
              value={pct(liveGates?.accuracy?.value ?? accuracy)}
              detail={`≥${pct(thresholds.accuracy_floor ?? 0.35)} over ${liveGates?.accuracy?.window ?? data?.outcomes_tracked ?? '—'} rounds`}
            />
            <GateRow
              label="Gate 2 — Spread"
              pass={liveGates?.spread?.pass ?? (spread != null ? spread < (thresholds.spread_max ?? 0.5) : null)}
              value={liveGates?.spread?.value != null ? `${liveGates.spread.value.toFixed(3)}×` : spread != null ? `${spread.toFixed(3)}×` : '—'}
              detail={`< ${thresholds.spread_max ?? 0.5}× cashout vs actual`}
            />
            <GateRow
              label="Gate 3 — Risk Confidence"
              pass={liveGates?.rcs?.pass ?? (liveRcs != null ? liveRcs >= (thresholds.rcs_min ?? 0.4) : null)}
              value={liveGates?.rcs?.value != null ? liveGates.rcs.value.toFixed(3) : liveRcs != null ? liveRcs.toFixed(3) : '—'}
              detail={`≥ ${thresholds.rcs_min ?? 0.4} combined score`}
            />
          </div>
        </div>

        {/* Parameters */}
        <ParamsPanel params={params} isDefault={recalCount === 0} />

        {/* Stats */}
        <div className="rounded-lg border border-line bg-ink/50 p-4">
          <h3 className="mb-3 text-sm font-bold text-white">Validator Stats</h3>
          <div className="grid grid-cols-2 gap-3">
            {[
              { label: 'MEDIUM Accuracy', value: pct(accuracy), color: accuracy != null && accuracy < 0.35 ? 'text-rose-400' : 'text-lime-400' },
              { label: 'Avg Spread',      value: spread != null ? `${spread.toFixed(3)}×` : '—', color: spread != null && spread >= 0.5 ? 'text-rose-400' : 'text-slate-300' },
              { label: 'Outcomes Tracked', value: data?.outcomes_tracked ?? '—', color: 'text-cyan-400' },
              { label: 'Recalibrations',   value: recalCount, color: recalCount > 0 ? 'text-amber-400' : 'text-slate-500' },
            ].map(({ label, value, color }) => (
              <div key={label} className="rounded bg-slate-800/60 px-3 py-2 text-center">
                <div className={`text-lg font-black ${color}`}>{value}</div>
                <div className="text-[9px] uppercase tracking-wide text-slate-500">{label}</div>
              </div>
            ))}
          </div>
          {data?.last_recal_accuracy != null && (
            <p className="mt-3 text-[10px] text-slate-500">
              Last recal triggered at {pct(data.last_recal_accuracy)} accuracy
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
