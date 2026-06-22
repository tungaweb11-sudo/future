export default function ConfidenceMeter({ value = 0 }) {
  const safe = Math.max(0, Math.min(Number(value || 0), 100));

  const color = safe >= 70 ? '#9cff45' : safe >= 40 ? '#fbbf24' : '#ff5277';
  const label = safe >= 70 ? 'High' : safe >= 40 ? 'Moderate' : 'Low';

  // Arc parameters
  const r = 28, cx = 40, cy = 36;
  const halfC = Math.PI * r;
  const progress = (safe / 100) * halfC;
  const trackD = `M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${cx + r} ${cy}`;

  return (
    <div className="flex items-center gap-4">
      {/* Mini arc gauge */}
      <svg width={80} height={42} viewBox="0 0 80 42" className="shrink-0">
        <path d={trackD} fill="none" stroke="#1e293b" strokeWidth={8} strokeLinecap="round" />
        <path
          d={trackD} fill="none"
          stroke={color} strokeWidth={8} strokeLinecap="round"
          strokeDasharray={`${progress} ${halfC - progress}`}
          className="transition-all duration-700"
        />
        <text x={cx} y={cy - 4} textAnchor="middle" fill="white" fontSize={13} fontWeight="900">
          {safe.toFixed(0)}%
        </text>
        <text x={cx} y={cy + 8} textAnchor="middle" fill={color} fontSize={8} fontWeight="700">
          {label}
        </text>
      </svg>

      {/* Bar */}
      <div className="flex-1">
        <div className="mb-1.5 flex justify-between text-xs">
          <span className="text-slate-400">Confidence</span>
          <span className="font-bold" style={{ color }}>{safe.toFixed(1)}%</span>
        </div>
        <div className="h-2 overflow-hidden rounded-full bg-slate-800">
          <div
            className="h-full rounded-full transition-all duration-700"
            style={{ width: `${safe}%`, backgroundColor: color }}
          />
        </div>
        <div className="mt-1 flex justify-between text-[10px] text-slate-600">
          <span>0%</span>
          <span>50%</span>
          <span>100%</span>
        </div>
      </div>
    </div>
  );
}
