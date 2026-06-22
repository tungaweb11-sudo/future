import StatCard from './StatCard.jsx';

// Fallback if react-sparklines not installed — simple inline SVG bars
function MiniBar({ value, max, color }) {
  const pct = max > 0 ? (value / max) * 100 : 0;
  return (
    <div className="h-1 w-full rounded-full bg-slate-800 overflow-hidden">
      <div className="h-full rounded-full transition-all duration-700" style={{ width: `${pct}%`, backgroundColor: color }} />
    </div>
  );
}

export default function StatsGrid({ summary = {}, risk = {} }) {
  const s = summary || {};
  const { factors = {} } = risk || {};

  const totalRounds   = s.total_rounds ?? 0;
  const avgMultiplier = +(s.avg_multiplier ?? s.mean_multiplier ?? 0);
  const maxMultiplier = +(s.max_multiplier ?? 0);
  const minMultiplier = +(s.min_multiplier ?? 0);
  const volatility    = +(factors.volatility_factor ?? 0);
  const riskScore     = +(risk.risk_score ?? 0);

  const trendIcons = { increasing: 'up', decreasing: 'down', stable: 'neutral' };
  const trend = trendIcons[s.recent_trend] || 'neutral';

  const riskLevel = risk.risk_level ?? 'LOW';
  const riskAccent = riskLevel === 'HIGH' ? 'text-rose-400' : riskLevel === 'MEDIUM' ? 'text-amber-300' : 'text-cyan-400';

  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">

      {/* Total Rounds */}
      <StatCard
        label="Total Rounds"
        value={totalRounds.toLocaleString()}
        subtitle={`Peak: ${maxMultiplier >= 1000 ? maxMultiplier.toLocaleString() + '×' : maxMultiplier + '×'}  ·  Min: ${minMultiplier}×`}
        accent="text-white"
        trend="neutral"
      >
        {/* Category mini bars */}
        {s.category_counts && (
          <div className="space-y-1">
            {['VERY_LOW','LOW','MEDIUM','HIGH','VERY_HIGH'].map((cat, i) => {
              const colors = ['#35d4ff','#9cff45','#fbbf24','#f97316','#ff5277'];
              const cnt = s.category_counts[cat] ?? 0;
              return (
                <div key={cat} className="flex items-center gap-2">
                  <span className="w-12 text-[9px] text-slate-500">{cat.replace('_',' ')}</span>
                  <div className="flex-1 h-1 rounded-full bg-slate-800 overflow-hidden">
                    <div className="h-full rounded-full" style={{
                      width: `${totalRounds > 0 ? (cnt / totalRounds) * 100 : 0}%`,
                      backgroundColor: colors[i],
                    }} />
                  </div>
                  <span className="w-8 text-right text-[9px] text-slate-500">{totalRounds > 0 ? ((cnt/totalRounds)*100).toFixed(0) : 0}%</span>
                </div>
              );
            })}
          </div>
        )}
      </StatCard>

      {/* Average Multiplier */}
      <StatCard
        label="Average Multiplier"
        value={`${avgMultiplier.toFixed(2)}×`}
        subtitle={`Range: ${minMultiplier}× – ${maxMultiplier >= 1000 ? maxMultiplier.toLocaleString() : maxMultiplier}×`}
        accent="text-cyan-400"
        trend={trend}
      >
        {/* Range visual */}
        <div className="relative h-2 rounded-full bg-slate-800">
          {maxMultiplier > 0 && (
            <div
              className="absolute top-0 h-full rounded-full bg-gradient-to-r from-cyan-400 to-lime-400"
              style={{ left: 0, width: `${Math.min(100, (avgMultiplier / maxMultiplier) * 100)}%` }}
            />
          )}
        </div>
        <div className="mt-1 flex justify-between text-[9px] text-slate-600">
          <span>{minMultiplier}×</span>
          <span className="text-cyan-500">{avgMultiplier.toFixed(1)}× avg</span>
          <span>{maxMultiplier >= 1000 ? '∞' : maxMultiplier + '×'}</span>
        </div>
      </StatCard>

      {/* Volatility */}
      <StatCard
        label="Volatility"
        value={`${volatility.toFixed(0)}%`}
        subtitle="Coefficient of variation"
        accent={volatility >= 65 ? 'text-rose-400' : volatility >= 35 ? 'text-amber-300' : 'text-cyan-400'}
        trend={volatility >= 50 ? 'down' : 'up'}
      >
        <div className="space-y-1">
          <div className="h-2 rounded-full bg-slate-800 overflow-hidden">
            <div
              className="h-full rounded-full transition-all duration-700 bg-gradient-to-r from-cyan-400 via-amber-300 to-rose-500"
              style={{ width: `${Math.min(100, volatility)}%` }}
            />
          </div>
          <div className="flex justify-between text-[9px] text-slate-600">
            <span>Stable</span>
            <span>Volatile</span>
          </div>
        </div>
      </StatCard>

      {/* Market Trend + Risk Score */}
      <StatCard
        label="Market Trend"
        value={s.recent_trend ? s.recent_trend.charAt(0).toUpperCase() + s.recent_trend.slice(1) : '—'}
        subtitle={
          s.recent_trend === 'increasing' ? 'Rising multipliers' :
          s.recent_trend === 'decreasing' ? 'Falling multipliers' :
          'Sideways market'
        }
        accent={
          s.recent_trend === 'increasing' ? 'text-rose-400' :
          s.recent_trend === 'decreasing' ? 'text-cyan-400' :
          'text-amber-300'
        }
        trend={trend}
      >
        {/* Risk score mini gauge */}
        <div className="flex items-center gap-3 mt-1">
          <div className="flex-1">
            <div className="flex justify-between text-[9px] text-slate-500 mb-1">
              <span>Risk Score</span>
              <span className={riskAccent}>{riskScore.toFixed(0)} / 100</span>
            </div>
            <div className="h-1.5 rounded-full bg-slate-800 overflow-hidden">
              <div
                className="h-full rounded-full transition-all duration-700"
                style={{
                  width: `${riskScore}%`,
                  backgroundColor: riskLevel === 'HIGH' ? '#ff5277' : riskLevel === 'MEDIUM' ? '#fbbf24' : '#35d4ff',
                }}
              />
            </div>
          </div>
          <div className={`rounded-full px-2 py-0.5 text-[9px] font-bold ${riskAccent} ${
            riskLevel === 'HIGH' ? 'bg-rose-500/15' : riskLevel === 'MEDIUM' ? 'bg-amber-400/15' : 'bg-cyan-500/15'
          }`}>
            {riskLevel}
          </div>
        </div>
      </StatCard>
    </div>
  );
}
