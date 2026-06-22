import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { RefreshCw, Brain, TrendingUp, ClipboardList, AlertTriangle, Wifi, WifiOff } from 'lucide-react';
import { fetchDecisions, fetchPrediction, fetchAccuracy, fetchReadiness, runBackfill, trainModel } from '../api/client.js';
import PredictionLog from '../components/PredictionLog.jsx';
import MetricCard from '../components/MetricCard.jsx';
import ConfidenceMeter from '../components/ConfidenceMeter.jsx';
import Sidebar from '../components/Sidebar.jsx';
import { formatPercent, formatMultiplier, predictionColor, predictionLabel, riskColor } from '../lib/format.js';
import useSocket from '../lib/useSocket.js';

export default function Predictions() {
  const navigate = useNavigate();
  const { connected: wsConnected, lastPrediction, updatedDecisions } = useSocket();

  const [prediction, setPrediction] = useState(null);
  const [accuracy, setAccuracy] = useState(null);
  const [decisions, setDecisions] = useState([]);
  const [loading, setLoading] = useState(false);
  const [training, setTraining] = useState(false);
  const [error, setError] = useState('');
  const [lastUpdated, setLastUpdated] = useState(null);
  const [modelReady, setModelReady] = useState(false);

  // Wait for TF model to warm up before first refresh
  useEffect(() => {
    let cancelled = false;
    async function waitForReady() {
      while (!cancelled) {
        try {
          const { ready } = await fetchReadiness();
          if (ready) { if (!cancelled) { setModelReady(true); refresh(); } return; }
        } catch (_) {}
        await new Promise(r => setTimeout(r, 2000));
      }
    }
    waitForReady();
    return () => { cancelled = true; };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const refresh = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [predictionData, accuracyData, decisionData] = await Promise.all([
        fetchPrediction(),
        fetchAccuracy(),
        fetchDecisions(100),
      ]);
      runBackfill().catch(() => {});
      setPrediction(predictionData);
      setAccuracy(accuracyData);
      setDecisions(decisionData.decisions || []);
      setLastUpdated(new Date());
    } catch (err) {
      setError(err.response?.data?.error || err.message || 'Refresh failed.');
    } finally {
      setLoading(false);
    }
  }, []);

  // Fallback poll — only after model is ready
  useEffect(() => {
    if (!modelReady) return;
    const timer = window.setInterval(refresh, wsConnected ? 30000 : 8000);
    return () => window.clearInterval(timer);
  }, [refresh, wsConnected, modelReady]);

  // WebSocket: new prediction pushed after every round
  useEffect(() => {
    if (!lastPrediction) return;
    setPrediction(lastPrediction);
    setLastUpdated(new Date());
    // Prepend instantly — no extra HTTP call
    if (lastPrediction.last_round_id != null) {
      setDecisions(prev => {
        const exists = prev.some(d => d.last_round_id === lastPrediction.last_round_id);
        if (exists) return prev;
        return [lastPrediction, ...prev].slice(0, 100);
      });
    }
    fetchAccuracy().then(setAccuracy).catch(() => {});
    runBackfill().catch(() => {});
  }, [lastPrediction]);

  // ── WS: decisions_updated — Actual column fills in real-time ─────────────
  useEffect(() => {
    if (!updatedDecisions || !updatedDecisions.length) return;
    setDecisions(updatedDecisions);
  }, [updatedDecisions]);

  // ── Train ──
  const train = async () => {
    setTraining(true);
    setError('');
    try {
      await trainModel(30);
      await refresh();
    } catch (err) {
      setError(err.response?.data?.error || err.message || 'Training failed.');
    } finally {
      setTraining(false);
    }
  };

  // ── Derived ──
  const riskLevel = prediction?.risk_level || 'LOW';

  // Hit rate from accuracy endpoint
  const hitRatePct = accuracy?.hit_rate_pct ?? null;

  return (
    <div className="flex min-h-screen bg-ink text-white">
      {/* Sidebar */}
      <Sidebar
        activeTab="predictions"
        onTabChange={() => {}}
        onRefresh={refresh}
        loading={loading}
        onTrain={train}
        training={training}
      />

      {/* Mobile bottom bar */}
      <div className="fixed bottom-0 left-0 right-0 z-50 flex border-t border-line bg-panel/95 backdrop-blur lg:hidden">
        {['predictions'].map((tab) => (
          <button
            key={tab}
            className="flex-1 py-3 text-center text-[11px] font-bold uppercase tracking-[0.12em] text-cyan border-t-2 border-cyan"
          >
            {tab}
          </button>
        ))}
      </div>

      {/* Main content */}
      <main className="flex-1 overflow-auto pb-20 lg:pb-0">
        <div className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-6 lg:px-8">

          {/* Header */}
          <header className="mb-6 flex flex-col gap-4 border-b border-line pb-5 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.22em]">
                {riskLevel === 'HIGH' ? (
                  <AlertTriangle className="h-3.5 w-3.5 text-danger" />
                ) : riskLevel === 'MEDIUM' ? (
                  <TrendingUp className="h-3.5 w-3.5 text-amber-300" />
                ) : (
                  <ClipboardList className="h-3.5 w-3.5 text-cyan" />
                )}
                <span className={
                  riskLevel === 'HIGH' ? 'text-danger' :
                  riskLevel === 'MEDIUM' ? 'text-amber-300' :
                  'text-cyan'
                }>
                  Aviator Risk Management
                </span>
              </div>
              <h1 className="mt-2 text-3xl font-black sm:text-4xl">Prediction Log</h1>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <span className={`flex items-center gap-1.5 rounded-md border px-3 py-2 text-xs font-semibold ${
                wsConnected
                  ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400'
                  : 'border-amber-500/30 bg-amber-500/10 text-amber-400'
              }`}>
                {wsConnected ? <Wifi className="h-3.5 w-3.5" /> : <WifiOff className="h-3.5 w-3.5" />}
                {wsConnected ? 'Live' : 'Polling'}
              </span>
              <span className="rounded-md border border-line px-3 py-2 text-sm text-slate-300">
                {lastUpdated ? `Updated ${lastUpdated.toLocaleTimeString()}` : 'Waiting for data'}
              </span>
              <button
                onClick={refresh}
                disabled={loading}
                className="flex items-center gap-2 rounded-md border border-cyan px-4 py-2 text-sm font-bold text-cyan transition hover:bg-cyan hover:text-ink disabled:opacity-50"
              >
                <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
                {loading ? 'Refreshing' : 'Refresh'}
              </button>
              <button
                onClick={train}
                disabled={training}
                className="flex items-center gap-2 rounded-md bg-acid px-4 py-2 text-sm font-black text-ink transition hover:brightness-110 disabled:opacity-50"
              >
                <Brain className="h-4 w-4" />
                {training ? 'Training' : 'Train Model'}
              </button>
            </div>
          </header>

          {/* Error */}
          {error && (
            <div className="mb-5 rounded-lg border border-danger/60 bg-danger/10 p-4 text-sm text-rose-100">
              {error}
            </div>
          )}

          {/* Metric cards */}
          <section className="grid gap-4 md:grid-cols-3 mb-6">
            {/* Next Prediction */}
            <MetricCard label="Next Prediction" value={predictionLabel(prediction?.prediction)}>
              <div className={`mt-1 h-2 rounded-full bg-gradient-to-r ${predictionColor(prediction?.prediction)}`} />
            </MetricCard>

            {/* Confidence */}
            <MetricCard label="Confidence" value={formatPercent(prediction?.confidence)} accent="text-cyan">
              <ConfidenceMeter value={prediction?.confidence || 0} />
            </MetricCard>

            {/* Hit Rate */}
            <MetricCard
              label="Hit Rate"
              value={hitRatePct != null ? formatPercent(hitRatePct) : '—'}
              accent="text-acid"
            >
              <div className="mt-1 flex items-center justify-between text-xs text-slate-400">
                <span>Resolved: {accuracy?.resolved_count ?? 0}</span>
                <span className={`font-bold ${riskColor(prediction?.risk_level)}`}>
                  {prediction?.risk_level ?? '—'} RISK
                </span>
              </div>
            </MetricCard>
          </section>

          {/* Full-width Prediction Log */}
          <PredictionLog decisions={decisions} />
        </div>
      </main>
    </div>
  );
}
