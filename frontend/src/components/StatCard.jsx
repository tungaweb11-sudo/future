import { TrendingUp, TrendingDown, Minus } from 'lucide-react';

const icons  = { up: TrendingUp, down: TrendingDown, neutral: Minus };
const trendColors = { up: 'text-lime-400', down: 'text-rose-400', neutral: 'text-amber-300' };
const trendBg     = { up: 'bg-lime-400/10', down: 'bg-rose-400/10', neutral: 'bg-amber-300/10' };

export default function StatCard({ label, value, subtitle, trend = 'neutral', accent, children }) {
  const Icon = icons[trend] || null;
  return (
    <section className="group relative overflow-hidden rounded-xl border border-line bg-panel/80 p-5 shadow-lg backdrop-blur transition-all duration-300 hover:-translate-y-1 hover:border-cyan/40 hover:shadow-[0_0_32px_rgba(53,212,255,0.10)]">
      {/* Glow orb */}
      <div className="pointer-events-none absolute -right-8 -top-8 h-24 w-24 rounded-full bg-gradient-to-br from-cyan/8 to-transparent opacity-0 transition-opacity duration-300 group-hover:opacity-100" />

      <div className="relative z-10">
        {/* Label row */}
        <div className="flex items-center justify-between">
          <span className="text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-500">{label}</span>
          {Icon && (
            <span className={`rounded-full p-1 ${trendBg[trend]}`}>
              <Icon className={`h-3.5 w-3.5 ${trendColors[trend]}`} />
            </span>
          )}
        </div>

        {/* Value */}
        <div className={`mt-2 text-3xl font-black tracking-tight ${accent || 'text-white'}`}>
          {value}
        </div>

        {/* Subtitle */}
        {subtitle && (
          <div className="mt-1 text-xs text-slate-500">{subtitle}</div>
        )}

        {/* Slot for mini chart / bar */}
        {children && <div className="mt-3">{children}</div>}
      </div>
    </section>
  );
}
