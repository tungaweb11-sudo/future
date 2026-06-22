import { RadialBarChart, RadialBar, ResponsiveContainer, Tooltip } from 'recharts';

function Badge({ active, onLabel, offLabel, onColor = 'text-lime-400', offColor = 'text-slate-500', onBg = 'bg-lime-500/15', offBg = 'bg-slate-700/30' }) {
  return (
    <span className={`rounded-full border px-2.5 py-0.5 text-[10px] font-bold ${active ? `${onBg} ${onColor} border-lime-500/30` : `${offBg} ${offColor} border-slate-600/30`}`}>
      {active ? onLabel : offLabel}
    </span>
  );
}

function MiniGauge({ value, max = 100, color }) {
  const pct = Math.min(100, Math.max(0, value / max * 100));
  return (
    <div className="relative h-1.5 w-full rounded-full bg-slate-800">
      <div className="h-full rounded-full transition-all duration-700" style={{ width: `${pct}%`, backgroundColor: color }} />
    </div>
  );
}

export default function SkipQualityPanel({ skipQuality = null, vhQuality = null }) {
  if (!skipQuality && !vhQuality) {
    return (
      <div className="rounded-xl border border-line bg-panel/80 p-5 shadow-lg backdrop-blur">
        <h2 className="mb-1 text-lg font-bold text-white">Guard Systems</h2>
        <p className="text-xs text-slate-500">Skip quality, VH filter, cooldown</p>
        <div className="flex h-32 items-center justify-center text-sm text-slate-500 mt-4">Loading…</div>
      </div>
    );
  }

  const sq = skipQuality || {};
  const vh = vhQuality || {};

  const skipRate    = sq.skip_success_rate != null ? Math.round(sq.skip_success_rate * 100) : null;
  const cooldown    = sq.cooldown_remaining ?? 0;
  const conseqFail  = sq.consecutive_fails ?? 0;
  const vhDisabled  = vh.disabled ?? false;
  const vhRate      = vh.success_rate != null ? Math.round(vh.success_rate * 100) : null;
  const vhAvgMult   = vh.avg_actual_mult != null ? Number(vh.avg_actual_mult).toFixed(2) : null;
  const vhTracked   = vh.outcomes_tracked ?? 0;

  return (
    <div className="rounded-xl border border-line bg-panel/80 p-5 shadow-lg backdrop-blur">
      <div className="mb-4">
        <h2 className="text-lg font-bold text-white">Guard Systems</h2>
        <p className="text-xs text-slate-500">Skip quality, VH filter, cooldown status</p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">

        {/* Skip Quality */}
        <div className="rounded-lg border border-line bg-ink/50 p-4 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold text-white">Skip Guard</span>
            <Badge
              active={cooldown === 0 && conseqFail < 3}
              onLabel="Active"
              offLabel={cooldown > 0 ? `Cooldown ${cooldown}` : 'Degraded'}
              onColor="text-lime-400" offColor="text-amber-400"
              onBg="bg-lime-500/15" offBg="bg-amber-500/15"
            />
          </div>

          {skipRate !== null && (
            <div>
              <div className="mb-1 flex justify-between text-[10px] text-slate-400">
                <span>Skip success rate</span>
                <span className={`font-bold ${skipRate >= 60 ? 'text-lime-400' : skipRate >= 40 ? 'text-amber-400' : 'text-rose-400'}`}>
                  {skipRate}%
                </span>
              </div>
              <MiniGauge value={skipRate} color={skipRate >= 60 ? '#9cff45' : skipRate >= 40 ? '#fbbf24' : '#ff5277'} />
            </div>
          )}

          <div className="grid grid-cols-2 gap-2 text-center">
            <div className="rounded bg-slate-800/60 py-2">
              <div className={`text-lg font-black ${cooldown > 0 ? 'text-amber-400' : 'text-slate-400'}`}>{cooldown}</div>
              <div className="text-[9px] text-slate-500 uppercase tracking-wide">Cooldown</div>
            </div>
            <div className="rounded bg-slate-800/60 py-2">
              <div className={`text-lg font-black ${conseqFail >= 2 ? 'text-rose-400' : 'text-slate-300'}`}>{conseqFail}</div>
              <div className="text-[9px] text-slate-500 uppercase tracking-wide">Consec Fails</div>
            </div>
          </div>

          <div className="text-[10px] text-slate-600 space-y-0.5">
            <div>Min conf to SKIP: <span className="text-slate-400">70%</span></div>
            <div>Success rate floor: <span className="text-slate-400">60%</span></div>
            <div>Accuracy floor: <span className="text-slate-400">40%</span></div>
          </div>
        </div>

        {/* VH Guard */}
        <div className="rounded-lg border border-line bg-ink/50 p-4 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold text-white">VERY_HIGH Filter</span>
            <Badge
              active={!vhDisabled}
              onLabel="Enabled"
              offLabel="Disabled"
              onColor="text-lime-400" offColor="text-rose-400"
              onBg="bg-lime-500/15" offBg="bg-rose-500/15"
            />
          </div>

          {vhRate !== null && (
            <div>
              <div className="mb-1 flex justify-between text-[10px] text-slate-400">
                <span>VH success rate</span>
                <span className={`font-bold ${vhRate >= 50 ? 'text-lime-400' : vhRate >= 30 ? 'text-amber-400' : 'text-rose-400'}`}>
                  {vhRate}%
                </span>
              </div>
              <MiniGauge value={vhRate} color={vhRate >= 50 ? '#9cff45' : vhRate >= 30 ? '#fbbf24' : '#ff5277'} />
            </div>
          )}

          <div className="grid grid-cols-2 gap-2 text-center">
            <div className="rounded bg-slate-800/60 py-2">
              <div className="text-lg font-black text-slate-300">{vhAvgMult ?? '—'}<span className="text-xs">×</span></div>
              <div className="text-[9px] text-slate-500 uppercase tracking-wide">Avg Actual</div>
            </div>
            <div className="rounded bg-slate-800/60 py-2">
              <div className="text-lg font-black text-slate-300">{vhTracked}</div>
              <div className="text-[9px] text-slate-500 uppercase tracking-wide">Tracked</div>
            </div>
          </div>

          <div className="text-[10px] text-slate-600 space-y-0.5">
            <div>Multiplier floor: <span className="text-slate-400">3.0×</span></div>
            <div>Min confidence: <span className="text-slate-400">50%</span></div>
            <div>FP disable threshold: <span className="text-slate-400">&lt;30% over 10</span></div>
          </div>
        </div>
      </div>
    </div>
  );
}
