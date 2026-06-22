export function formatPercent(value) {
  const n = Number(value || 0);
  return `${n.toFixed(1)}%`;
}

export function formatMultiplier(value) {
  const n = Number(value || 0);
  if (!n) return '—';
  return `${n.toFixed(2)}×`;
}

export function riskColor(risk) {
  if (risk === 'LOW')    return 'text-acid';
  if (risk === 'MEDIUM') return 'text-amber-300';
  return 'text-danger';
}

export function predictionColor(prediction) {
  if (prediction === 'VERY_LOW')  return 'from-sky-500 to-sky-300';
  if (prediction === 'LOW')       return 'from-cyan to-sky-300';
  if (prediction === 'MEDIUM')    return 'from-acid to-emerald-300';
  if (prediction === 'HIGH')      return 'from-orange-400 to-amber-300';
  if (prediction === 'VERY_HIGH') return 'from-danger to-orange-300';
  return 'from-slate-500 to-slate-400';
}

export function predictionLabel(prediction) {
  const map = {
    VERY_LOW:  'Very Low  (1.0–1.5×)',
    LOW:       'Low       (1.5–2.0×)',
    MEDIUM:    'Medium    (2.0–5.0×)',
    HIGH:      'High      (5.0–15×)',
    VERY_HIGH: 'Very High (15×+)',
  };
  return map[prediction] ?? prediction ?? '—';
}
