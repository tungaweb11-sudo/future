export default function RiskGauge({ score = 0, level = 'LOW', size = 200 }) {
  const safeScore = Math.max(0, Math.min(Number(score || 0), 100));

  // Half-circle: arc from 180° to 0° (left to right)
  const cx = size / 2;
  const cy = size * 0.52;
  const r  = size * 0.38;

  // Convert 0-100 score to angle on the half circle (180° to 0°)
  const angleRad = (Math.PI) - (safeScore / 100) * Math.PI;
  const needleX  = cx + r * 0.72 * Math.cos(angleRad);
  const needleY  = cy - r * 0.72 * Math.sin(angleRad);

  const colorMap  = { LOW: '#35d4ff', MEDIUM: '#fbbf24', HIGH: '#ff5277' };
  const accent    = colorMap[level] || '#35d4ff';

  // Zone arcs — safe(0-34), caution(35-64), high(65-100)
  function arcPath(startPct, endPct, inset = 0) {
    const rr     = r - inset;
    const aStart = Math.PI - (startPct / 100) * Math.PI;
    const aEnd   = Math.PI - (endPct   / 100) * Math.PI;
    const x1 = cx + rr * Math.cos(Math.PI - aStart + Math.PI);
    const y1 = cy - rr * Math.sin(Math.PI - aStart + Math.PI);
    const x2 = cx + rr * Math.cos(Math.PI - aEnd + Math.PI);
    const y2 = cy - rr * Math.sin(Math.PI - aEnd + Math.PI);
    // simpler: just use stroke-dasharray on the full semicircle arc
    return null;
  }

  // Track path helper
  function semiArcD(radius) {
    return `M ${cx - radius} ${cy} A ${radius} ${radius} 0 0 1 ${cx + radius} ${cy}`;
  }

  const trackD  = semiArcD(r);
  const halfC   = Math.PI * r; // half circumference

  // Each zone: offset + length in stroke-dasharray units
  const safeLen    = (34  / 100) * halfC;
  const cautionLen = (30  / 100) * halfC;
  const highLen    = (36  / 100) * halfC;
  const progressLen = (safeScore / 100) * halfC;

  return (
    <div className="flex flex-col items-center justify-center">
      <svg
        width={size}
        height={size * 0.62}
        viewBox={`0 0 ${size} ${size * 0.62}`}
        className="overflow-visible"
      >
        {/* Background track */}
        <path d={trackD} fill="none" stroke="#1e293b" strokeWidth={12} strokeLinecap="round" />

        {/* Zone: Safe (0–34) — cyan */}
        <path
          d={trackD} fill="none"
          stroke="#35d4ff" strokeWidth={10} strokeLinecap="butt" strokeOpacity={0.25}
          strokeDasharray={`${safeLen} ${halfC - safeLen}`}
          strokeDashoffset={0}
        />
        {/* Zone: Caution (35–64) — amber */}
        <path
          d={trackD} fill="none"
          stroke="#fbbf24" strokeWidth={10} strokeLinecap="butt" strokeOpacity={0.25}
          strokeDasharray={`${cautionLen} ${halfC - cautionLen}`}
          strokeDashoffset={-safeLen}
        />
        {/* Zone: High (65–100) — rose */}
        <path
          d={trackD} fill="none"
          stroke="#ff5277" strokeWidth={10} strokeLinecap="butt" strokeOpacity={0.25}
          strokeDasharray={`${highLen} ${halfC - highLen}`}
          strokeDashoffset={-(safeLen + cautionLen)}
        />

        {/* Progress arc */}
        <path
          d={trackD} fill="none"
          stroke={accent} strokeWidth={10} strokeLinecap="round"
          strokeDasharray={`${progressLen} ${halfC - progressLen}`}
          strokeDashoffset={0}
          className="transition-all duration-1000 ease-out"
        />

        {/* Needle */}
        <line
          x1={cx} y1={cy}
          x2={needleX} y2={needleY}
          stroke={accent} strokeWidth={3} strokeLinecap="round"
          className="transition-all duration-1000 ease-out"
        />
        <circle cx={cx} cy={cy} r={6} fill={accent} />
        <circle cx={cx} cy={cy} r={3} fill="#070a12" />

        {/* Score text */}
        <text x={cx} y={cy - r * 0.22} textAnchor="middle"
          fill="white" fontSize={Math.round(size * 0.14)} fontWeight="900" fontFamily="Inter, sans-serif">
          {safeScore}
        </text>
        <text x={cx} y={cy - r * 0.05} textAnchor="middle"
          fill={accent} fontSize={Math.round(size * 0.07)} fontWeight="700" fontFamily="Inter, sans-serif">
          {level} RISK
        </text>

        {/* Zone labels */}
        <text x={cx - r * 0.95} y={cy + 18} textAnchor="middle" fill="#35d4ff" fontSize={10} fontWeight="600">Safe</text>
        <text x={cx}             y={cy - r * 1.05} textAnchor="middle" fill="#fbbf24" fontSize={10} fontWeight="600">Caution</text>
        <text x={cx + r * 0.95} y={cy + 18} textAnchor="middle" fill="#ff5277" fontSize={10} fontWeight="600">High</text>
      </svg>

      {/* Tick marks */}
      <div className="mt-1 flex w-full max-w-[200px] justify-between text-[10px] text-slate-600">
        <span>0</span>
        <span>25</span>
        <span>50</span>
        <span>75</span>
        <span>100</span>
      </div>
    </div>
  );
}
