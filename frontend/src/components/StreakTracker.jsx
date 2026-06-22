import { Zap, TrendingUp, AlertTriangle, TrendingDown, Minus } from 'lucide-react';

const CAT_META = {
  VERY_LOW:  { icon: TrendingDown, color: 'text-sky-400',    bg: 'bg-sky-500/10',    border: 'border-sky-500/25',    bar: 'bg-sky-400'    },
  LOW:       { icon: Zap,          color: 'text-cyan-400',   bg: 'bg-cyan-500/10',   border: 'border-cyan-500/25',   bar: 'bg-cyan-400'   },
  MEDIUM:    { icon: TrendingUp,   color: 'text-lime-400',   bg: 'bg-lime-500/10',   border: 'border-lime-500/25',   bar: 'bg-lime-400'   },
  HIGH:      { icon: AlertTriangle,color: 'text-orange-400', bg: 'bg-orange-500/10', border: 'border-orange-500/25', bar: 'bg-orange-400' },
  VERY_HIGH: { icon: AlertTriangle,color: 'text-rose-400',   bg: 'bg-rose-500/10',   border: 'border-rose-500/25',   bar: 'bg-rose-400'   },
};

const DEFAULT_META = { icon: Minus, color: 'text-slate-400', bg: 'bg-slate-800', border: 'border-slate-700', bar: 'bg-slate-600' };

// Show all 5 categories for longest streaks
const ALL_CATS = ['VERY_LOW', 'LOW', 'MEDIUM', 'HIGH', 'VERY_HIGH'];
const SHORT = { VERY_LOW: 'V.Low', LOW: 'Low', MEDIUM: 'Med', HIGH: 'High', VERY_HIGH: 'V.High' };

export default function StreakTracker({ streaks }) {
  if (!streaks) return null;

  const { current_streak: current, longest_streaks: longest, recent_streaks: recent } = streaks;
  const meta = (current?.category && CAT_META[current.category]) ? CAT_META[current.category] : DEFAULT_META;
  const Icon = meta.icon;

  // Max streak value for proportional bars
  const maxLongest = Math.max(1, ...ALL_CATS.map(c => longest?.[c] ?? 0));

  return (
    <div className="rounded-xl border border-line bg-panel/80 p-5 shadow-lg backdrop-blur">
      <div className="mb-4">
        <h2 className="text-lg font-bold text-white">Streak Tracker</h2>
        <p className="text-xs text-slate-500">Consecutive round patterns</p>
      </div>

      {/* Current streak hero */}
      <div className={`mb-5 rounded-xl border ${meta.border} ${meta.bg} p-4`}>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className={`rounded-lg p-2.5 ${meta.bg}`}>
              <Icon className={`h-5 w-5 ${meta.color}`} />
            </div>
            <div>
              <div className="text-[10px] uppercase tracking-[0.15em] text-slate-500">Current Streak</div>
              <div className={`text-2xl font-black ${meta.color}`}>
                {current?.category ? SHORT[current.category] ?? current.category : '—'}
                <span className="ml-2 text-base font-bold text-slate-400">×{current?.length ?? 0}</span>
              </div>
            </div>
          </div>
          <div className={`flex flex-col items-end gap-1`}>
            <span className={`rounded-full px-2.5 py-0.5 text-[10px] font-bold ${meta.color} ${meta.bg} border ${meta.border}`}>
              {current?.active ? '● Active' : '○ Ended'}
            </span>
            {current?.length >= 3 && (
              <span className="text-[10px] text-slate-500">⚠ Pattern detected</span>
            )}
          </div>
        </div>
      </div>

      {/* Longest streaks — all 5 categories with proportion bars */}
      <div className="mb-5">
        <div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">Longest Streaks</div>
        <div className="space-y-2">
          {ALL_CATS.map(cat => {
            const m = CAT_META[cat];
            const val = longest?.[cat] ?? 0;
            const pct = Math.round((val / maxLongest) * 100);
            return (
              <div key={cat} className="flex items-center gap-3">
                <span className={`w-12 text-[11px] font-semibold ${m.color}`}>{SHORT[cat]}</span>
                <div className="flex-1 h-1.5 rounded-full bg-slate-800 overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all duration-700 ${m.bar}`}
                    style={{ width: `${pct}%` }}
                  />
                </div>
                <span className="w-6 text-right text-xs font-bold text-white">{val}</span>
              </div>
            );
          })}
        </div>
      </div>

      {/* Recent streaks mini-timeline */}
      {recent?.length > 0 && (
        <div>
          <div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
            Recent Pattern
          </div>
          <div className="flex flex-wrap gap-1.5">
            {recent.slice(-15).map((s, i) => {
              const m = CAT_META[s.category] ?? DEFAULT_META;
              return (
                <div
                  key={i}
                  className={`rounded px-1.5 py-0.5 text-[10px] font-bold border ${m.border} ${m.bg} ${m.color}`}
                  title={`${s.category} ×${s.length}`}
                >
                  {SHORT[s.category] ?? s.category}×{s.length}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
