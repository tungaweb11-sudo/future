import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowLeft, Plane, Wifi, WifiOff } from 'lucide-react';
import Sidebar from '../components/Sidebar.jsx';
import AviatorCanvas from '../components/AviatorCanvas.jsx';
import GameBadges from '../components/GameBadges.jsx';
import { fetchRounds, fetchCrashStats } from '../api/client.js';
import useSocket from '../lib/useSocket.js';

// ── WebAudio ─────────────────────────────────────────────────────────
let _ac;
function beep(freq, dur, type = 'sine', vol = 0.1) {
  try {
    _ac = _ac || new (window.AudioContext || window.webkitAudioContext)();
    const o = _ac.createOscillator(), g = _ac.createGain();
    o.type = type; o.frequency.value = freq;
    g.gain.setValueAtTime(vol, _ac.currentTime);
    g.gain.exponentialRampToValueAtTime(0.001, _ac.currentTime + dur);
    o.connect(g); g.connect(_ac.destination);
    o.start(); o.stop(_ac.currentTime + dur);
  } catch (_) {}
}
const sfx = {
  crash: () => { beep(180, 0.35, 'sawtooth', 0.18); setTimeout(() => beep(130, 0.4, 'sawtooth', 0.12), 130); },
  tick:  () => beep(900, 0.04, 'square', 0.05),
};

export default function AviatorGame() {
  const navigate = useNavigate();
  const canvasRef   = useRef(null);
  const rafRef      = useRef(null);
  const prevPhase   = useRef(null);
  const prevRoundId = useRef(null);
  const flyStartRef = useRef(null);

  // ── WebSocket — real-time state at 100 ms (replaces 300 ms HTTP poll) ──
  const { connected: wsConnected, liveState: wsState, lastRound } = useSocket();

  const [state,       setState]       = useState(null);
  const [points,      setPoints]      = useState([]);
  const [dispMult,    setDispMult]    = useState(1.00);
  const [history,     setHistory]     = useState([]);
  const [stats,       setStats]       = useState(null);
  const [planePos,    setPlanePos]    = useState({ left: -200, bottom: 0, angle: -15 });

  // ── Live state from WebSocket ─────────────────────────────────────────
  useEffect(() => {
    const s = wsState;
    if (!s) return;
    setState(s);

    const phase = s.phase;
    const prev  = prevPhase.current;

    if (phase === 'waiting' && prev !== 'waiting') {
      sfx.tick();
      cancelAnimationFrame(rafRef.current);
      setPoints([]);
      setDispMult(1.00);
    }
    if (phase === 'flying' && prev !== 'flying') {
      flyStartRef.current = {
        ts:        performance.now() - s.elapsed * 1000,
        duration:  s.duration,
        crashMult: s.crash_mult,
      };
      if (prev === 'waiting') setPoints([{ t: 0, m: 1.00 }]);
    }
    if (phase === 'crashed' && prev !== 'crashed') {
      sfx.crash();
      setDispMult(s.crash_mult);
    }

    prevPhase.current = phase;
  }, [wsState]);

  // ── New round complete — refresh history + stats ──────────────────────
  useEffect(() => {
    if (!lastRound) return;
    if (prevRoundId.current !== lastRound.round_id) {
      prevRoundId.current = lastRound.round_id;
      fetchRounds(20).then(r => setHistory(r.rounds || [])).catch(() => {});
      fetchCrashStats().then(setStats).catch(() => {});
    }
  }, [lastRound]);

  // ── HTTP fallback poll when WS disconnected ───────────────────────────
  useEffect(() => {
    if (wsConnected) return; // WS is working, no need to poll
    let dead = false;
    async function poll() {
      try {
        const { fetchGameState } = await import('../api/client.js');
        const s = await fetchGameState();
        if (!dead) setState(s);
      } catch (_) {}
    }
    poll();
    const id = setInterval(poll, 500);
    return () => { dead = true; clearInterval(id); };
  }, [wsConnected]);

  // ── rAF for smooth multiplier + plane during flying ──────────────────
  useEffect(() => {
    if (!state || state.phase !== 'flying') {
      cancelAnimationFrame(rafRef.current);
      return;
    }

    const fly = flyStartRef.current;
    if (!fly) return;

    const speed = Math.log(Math.max(fly.crashMult, 1.01)) / fly.duration;

    function tick() {
      const elapsed  = (performance.now() - fly.ts) / 1000;
      const progress = Math.min(elapsed / fly.duration, 1);
      const m        = Math.exp(speed * elapsed);

      setDispMult(m);
      setPoints(prev => {
        // Throttle: only push a new point every ~50 ms worth of progress
        const last = prev.at(-1);
        if (!last || progress - last.t > 0.008) {
          return [...prev, { t: progress, m }];
        }
        return prev;
      });

      // Plane position from canvas tip
      const tip = canvasRef.current?.getTipPixel?.();
      if (tip) {
        const yNorm = Math.log(Math.max(m, 1)) / Math.log(Math.max(fly.crashMult, 2));
        setPlanePos({
          left:   tip.x - 32,
          bottom: tip.H - tip.y - 20,
          angle:  Math.max(-42, yNorm * -40),
        });
      }

      if (progress < 1) {
        rafRef.current = requestAnimationFrame(tick);
      }
    }

    rafRef.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafRef.current);
  }, [state?.phase]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Initial history + stats load ─────────────────────────────────────
  useEffect(() => {
    fetchRounds(20).then(r => setHistory(r.rounds || [])).catch(() => {});
    fetchCrashStats().then(setStats).catch(() => {});
  }, []);

  // ── Derived display values ────────────────────────────────────────────
  const phase      = state?.phase ?? 'waiting';
  const isCrashed  = phase === 'crashed';
  const isFlying   = phase === 'flying';
  const isWaiting  = phase === 'waiting';
  const countdown  = isWaiting ? Math.ceil(state?.countdown ?? 0) : null;
  const crashMult  = state?.crash_mult;
  const shownMult  = isCrashed ? (crashMult ?? dispMult) : dispMult;

  const multCls = isFlying  ? 'text-emerald-400 drop-shadow-[0_0_24px_#00e676]'
                : isCrashed ? 'text-rose-400    drop-shadow-[0_0_24px_#e94560]'
                : 'text-white';

  // live info row from state + latest history
  const latest    = history.at(-1);
  const serverSeed = state?.server_seed ?? latest?.server_seed ?? '—';
  const clientSeed = state?.client_seed ?? latest?.client_seed ?? '—';
  const nonce      = state?.nonce       ?? latest?.nonce       ?? '—';

  return (
    <div className="flex min-h-screen bg-ink text-white">
      <Sidebar activeTab="overview" onTabChange={() => navigate('/')}
        onRefresh={() => {}} loading={false} onTrain={() => {}} training={false} />

      {/* Mobile nav */}
      <div className="fixed bottom-0 left-0 right-0 z-50 flex border-t border-line bg-panel/95 backdrop-blur lg:hidden">
        <button onClick={() => navigate('/')}
          className="flex-1 py-3 text-center text-[11px] font-bold uppercase tracking-[0.12em] text-slate-400">
          Dashboard
        </button>
        <button className="flex-1 py-3 text-center text-[11px] font-bold uppercase tracking-[0.12em] text-rose-400 border-t-2 border-rose-400">
          Live Game
        </button>
      </div>

      <main className="flex-1 overflow-auto pb-20 lg:pb-0">
        <div className="mx-auto w-full max-w-5xl px-4 py-6 sm:px-6 lg:px-8">

          {/* Header */}
          <header className="mb-5 border-b border-line pb-5">
            <button onClick={() => navigate('/')}
              className="mb-3 flex items-center gap-1.5 text-xs font-semibold text-slate-400 hover:text-white transition">
              <ArrowLeft className="h-3.5 w-3.5" /> Back to Dashboard
            </button>
            <div className="flex items-center justify-between">
              <div>
                <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.22em] text-rose-400">
                  <Plane className="h-3.5 w-3.5" /> Aviator Live Game
                </div>
                <h1 className="mt-1 text-3xl font-black sm:text-4xl">Live Crash Simulator</h1>
              </div>
              <div className="flex items-center gap-2 text-sm">
                {wsConnected
                  ? <><Wifi className="h-4 w-4 text-emerald-400"/><span className="text-emerald-400 font-semibold">Live</span></>
                  : <><WifiOff className="h-4 w-4 text-rose-400"/><span className="text-rose-400 font-semibold">Offline</span></>}
              </div>
            </div>
          </header>

          {/* ── Canvas panel ─────────────────────────────────────────── */}
          <div className="relative overflow-hidden rounded-2xl border border-line shadow-2xl"
               style={{ height: 360, background: '#080d1a' }}>

            <AviatorCanvas ref={canvasRef} points={points} crashed={isCrashed} />

            {/* Plane (only during flying) */}
            {isFlying && (
              <div className="av-plane pointer-events-none"
                   style={{ left: planePos.left, bottom: planePos.bottom,
                            transform: `rotate(${planePos.angle}deg)` }}>
                <svg viewBox="0 0 72 44" width="72" height="44">
                  <path d="M2 22 L46 2 L70 22 L46 27 Z" fill="white" opacity=".93"/>
                  <path d="M20 22 L27 36 L36 22 Z" fill="white" opacity=".7"/>
                  <path d="M44 22 L51 14 L58 22 Z" fill="white" opacity=".6"/>
                  <ellipse cx="8"  cy="22" rx="9"   ry="4.5" fill="#ff6a00" className="av-flame" opacity=".9"/>
                  <ellipse cx="4"  cy="22" rx="5.5" ry="2.8" fill="#ffdd00" className="av-flame" opacity=".8"/>
                </svg>
              </div>
            )}

            {/* Centre multiplier */}
            <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none gap-1">
              {!isWaiting && (
                <>
                  <span className={`av-multiplier ${multCls}`}>
                    {shownMult.toFixed(2)}<span className="text-[55%] opacity-60">×</span>
                  </span>
                  <span className={`text-[11px] font-bold tracking-[5px] uppercase ${
                    isFlying ? 'text-emerald-500' : isCrashed ? 'text-rose-500' : 'text-slate-500'}`}>
                    {isFlying ? 'FLYING' : 'FLEW AWAY'}
                  </span>
                </>
              )}
            </div>

            {/* Crashed overlay */}
            {isCrashed && (
              <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none av-crash-overlay">
                <p className="av-crash-text">FLEW AWAY!</p>
                <p className="text-5xl font-black text-white mt-1">{(crashMult ?? dispMult).toFixed(2)}×</p>
              </div>
            )}

            {/* Waiting / countdown overlay */}
            {isWaiting && (
              <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none"
                   style={{ background: 'rgba(8,13,26,0.7)', backdropFilter: 'blur(4px)' }}>
                <p className="text-[11px] font-bold tracking-[4px] uppercase text-slate-400 mb-3">
                  Next round in
                </p>
                <span key={countdown} className="av-countdown">{countdown ?? '…'}</span>
              </div>
            )}
          </div>

          {/* ── Info row ────────────────────────────────────────────── */}
          <div className="mt-4 grid gap-4 sm:grid-cols-2">

            {/* Round info */}
            <div className="rounded-xl border border-line bg-panel/80 p-5 backdrop-blur">
              <p className="mb-4 text-[10px] font-bold uppercase tracking-[0.2em] text-slate-500">Round Info</p>
              <ul className="space-y-2.5 text-sm">
                {[
                  ['Round ID',    state ? `#${state.round_id}`                    : '—'],
                  ['Phase',       phase.toUpperCase()],
                  ['Multiplier',  shownMult.toFixed(2) + '×'],
                  ['Crash point', crashMult != null ? `${crashMult.toFixed(2)}×`  : isFlying ? '???' : '—'],
                  ['Duration',    state?.duration ? `${state.duration.toFixed(2)}s` : '—'],
                  ['Elapsed',     state?.elapsed  ? `${state.elapsed.toFixed(2)}s`  : '—'],
                ].map(([k, v]) => (
                  <li key={k} className="flex justify-between">
                    <span className="text-slate-500">{k}</span>
                    <span className="font-semibold text-white">{v}</span>
                  </li>
                ))}
              </ul>
            </div>

            {/* Provably fair */}
            <div className="rounded-xl border border-line bg-panel/80 p-5 backdrop-blur">
              <p className="mb-4 text-[10px] font-bold uppercase tracking-[0.2em] text-slate-500">Provably Fair</p>
              <ul className="space-y-2.5 text-sm">
                <li className="flex flex-col gap-0.5">
                  <span className="text-slate-500">Server Seed</span>
                  <span className="font-mono text-xs text-cyan-400 break-all">{serverSeed}</span>
                </li>
                <li className="flex flex-col gap-0.5">
                  <span className="text-slate-500">Client Seed</span>
                  <span className="font-mono text-xs text-cyan-400 break-all">{clientSeed}</span>
                </li>
                <li className="flex justify-between">
                  <span className="text-slate-500">Nonce</span>
                  <span className="font-semibold text-white">{nonce}</span>
                </li>
              </ul>
            </div>
          </div>

          {/* ── Stats row ────────────────────────────────────────────── */}
          <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
            {[
              ['Total Rounds',   stats?.total_rounds  ?? '—',  'text-white'],
              ['Avg Mult',       stats?.mean_multiplier ? `${stats.mean_multiplier.toFixed(2)}×` : '—', 'text-white'],
              ['Highest',        stats?.max_multiplier  ? `${stats.max_multiplier.toFixed(2)}×`  : '—', 'text-yellow-400'],
              ['Lowest',         stats?.min_multiplier  ? `${stats.min_multiplier.toFixed(2)}×`  : '—', 'text-rose-400'],
            ].map(([k, v, c]) => (
              <div key={k} className="rounded-xl border border-line bg-panel/80 p-4 backdrop-blur">
                <div className={`text-xl font-black ${c}`}>{v}</div>
                <div className="mt-0.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-500">{k}</div>
              </div>
            ))}
          </div>

          {/* ── History badges ───────────────────────────────────────── */}
          <div className="mt-4 rounded-xl border border-line bg-panel/80 p-5 backdrop-blur">
            <div className="mb-3 flex items-center gap-2">
              <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-500">Recent Rounds</p>
              {history.length > 0 && (
                <span className="rounded-full border border-line bg-ink/60 px-2 py-0.5 text-[10px] text-slate-500">
                  {history.length}
                </span>
              )}
            </div>
            <GameBadges rounds={history} />
          </div>

          {/* ── History table ────────────────────────────────────────── */}
          <div className="mt-4 rounded-xl border border-line bg-panel/80 backdrop-blur overflow-hidden">
            <div className="px-5 py-4 border-b border-line">
              <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-500">Round History</p>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-line text-[10px] uppercase tracking-[0.15em] text-slate-500">
                    <th className="px-5 py-3 text-left font-semibold">Round</th>
                    <th className="px-5 py-3 text-left font-semibold">Time</th>
                    <th className="px-5 py-3 text-right font-semibold">Multiplier</th>
                    <th className="px-5 py-3 text-right font-semibold">Duration</th>
                    <th className="px-5 py-3 text-right font-semibold">Nonce</th>
                  </tr>
                </thead>
                <tbody>
                  {[...history].reverse().map((r, i) => {
                    const m   = r.multiplier;
                    const col = m >= 10 ? 'text-yellow-400' : m >= 2 ? 'text-purple-400' : 'text-rose-400';
                    return (
                      <tr key={r.round_id}
                          className={`border-b border-line/50 transition-colors hover:bg-slate-800/30 ${i === 0 ? 'bg-slate-800/20' : ''}`}>
                        <td className="px-5 py-3 font-mono text-slate-300">#{r.round_id}</td>
                        <td className="px-5 py-3 text-slate-400">
                          {new Date(r.timestamp * 1000).toLocaleTimeString()}
                        </td>
                        <td className={`px-5 py-3 text-right font-black ${col}`}>
                          {m.toFixed(2)}×
                        </td>
                        <td className="px-5 py-3 text-right text-slate-300">
                          {r.duration?.toFixed(2)}s
                        </td>
                        <td className="px-5 py-3 text-right font-mono text-slate-400">
                          {r.nonce ?? '—'}
                        </td>
                      </tr>
                    );
                  })}
                  {history.length === 0 && (
                    <tr>
                      <td colSpan={5} className="px-5 py-8 text-center text-slate-500 italic">
                        Waiting for rounds…
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

        </div>
      </main>
    </div>
  );
}
