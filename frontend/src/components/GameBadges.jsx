export default function GameBadges({ rounds }) {
  if (!rounds?.length) return (
    <p className="text-sm text-slate-500 italic">No rounds yet.</p>
  );

  return (
    <div className="flex flex-wrap gap-2">
      {[...rounds].reverse().map((r) => {
        const m = r.multiplier;
        const cls =
          m >= 10  ? 'av-badge av-badge--gold'   :
          m >= 2   ? 'av-badge av-badge--purple'  :
                     'av-badge av-badge--red';
        return (
          <span key={r.round_id} className={cls} title={`Round #${r.round_id}`}>
            {m.toFixed(2)}×
          </span>
        );
      })}
    </div>
  );
}
