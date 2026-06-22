/**
 * app.js — Aviator frontend core
 * Connects to the Flask backend and drives the game UI.
 *
 * Backend endpoints used:
 *   GET /latest  → most recent completed round
 *   GET /rounds  → paginated round history
 *   GET /stats   → summary statistics
 */

const API = 'http://localhost:5000';

// ── DOM refs ────────────────────────────────────────────────────────
const dom = {
  dot:         document.getElementById('connection-dot'),
  connLabel:   document.getElementById('connection-label'),
  canvas:      document.getElementById('game-canvas'),
  planeWrap:   document.getElementById('plane-wrap'),
  planeSvg:    document.getElementById('plane-svg'),
  multVal:     document.getElementById('multiplier-value'),
  statusLabel: document.getElementById('game-status-label'),
  countdown:   document.getElementById('countdown-overlay'),
  countNum:    document.getElementById('countdown-number'),
  crashOvl:    document.getElementById('crash-overlay'),
  crashFinal:  document.getElementById('crash-final'),
  // live info
  infoId:      document.getElementById('info-round-id'),
  infoMult:    document.getElementById('info-multiplier'),
  infoCrash:   document.getElementById('info-crash'),
  infoDur:     document.getElementById('info-duration'),
  infoTs:      document.getElementById('info-timestamp'),
  // stats
  statTotal:   document.getElementById('stat-total'),
  statAvg:     document.getElementById('stat-avg'),
  statMax:     document.getElementById('stat-max'),
  statMin:     document.getElementById('stat-min'),
  // history
  histBadges:  document.getElementById('history-badges'),
  histCount:   document.getElementById('history-count'),
};

// ── State ────────────────────────────────────────────────────────────
const state = {
  phase:         'waiting',   // 'waiting' | 'flying' | 'crashed'
  lastRoundId:   null,
  currentMult:   1.00,
  flyStart:      null,
  flyDuration:   0,
  crashMult:     null,
  countdownSecs: 0,
  countdownEnd:  null,
  history:       [],
};

const chart = new AviatorChart('game-canvas');

// ── Sounds (optional, WebAudio) ──────────────────────────────────────
const audio = (() => {
  let ctx;
  function _ctx() { if (!ctx) ctx = new (window.AudioContext || window.webkitAudioContext)(); return ctx; }
  function beep(freq = 440, dur = 0.1, type = 'sine', vol = 0.15) {
    try {
      const ac = _ctx();
      const osc = ac.createOscillator();
      const gain = ac.createGain();
      osc.type = type;
      osc.frequency.value = freq;
      gain.gain.setValueAtTime(vol, ac.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, ac.currentTime + dur);
      osc.connect(gain); gain.connect(ac.destination);
      osc.start(); osc.stop(ac.currentTime + dur);
    } catch (_) {}
  }
  return {
    fly:     () => beep(520, 0.08, 'triangle', 0.1),
    crash:   () => { beep(200, 0.3, 'sawtooth', 0.2); setTimeout(() => beep(150, 0.4, 'sawtooth', 0.15), 120); },
    tick:    () => beep(880, 0.05, 'square', 0.06),
  };
})();

// ── Fetch helpers ─────────────────────────────────────────────────────
async function api(path) {
  const r = await fetch(API + path);
  if (!r.ok) throw new Error(r.status);
  return r.json();
}

function setOnline(ok) {
  dom.dot.className = 'dot ' + (ok ? 'dot--online' : 'dot--offline');
  dom.connLabel.textContent = ok ? 'Live' : 'Offline';
}

// ── Main polling loop ─────────────────────────────────────────────────
async function poll() {
  try {
    const latest = await api('/latest');
    setOnline(true);
    handleLatest(latest);
  } catch (_) {
    setOnline(false);
  }
}

async function pollStats() {
  try {
    const s = await api('/stats');
    updateStats(s);
  } catch (_) {}
}

async function pollHistory() {
  try {
    const { rounds } = await api('/rounds?limit=20');
    updateHistory(rounds);
  } catch (_) {}
}

// ── Game state machine ────────────────────────────────────────────────
function handleLatest(round) {
  const { round_id, multiplier, duration, timestamp } = round;

  // Same round we already know about → stay in current phase
  if (round_id === state.lastRoundId) {
    if (state.phase === 'flying') _tickFly();
    return;
  }

  // New round finished → show crash then countdown then fly next
  state.lastRoundId = round_id;
  state.crashMult   = multiplier;
  state.flyDuration = duration;

  _enterCrash(round);
}

// ── Phase: Flying ─────────────────────────────────────────────────────
function _enterFly() {
  state.phase    = 'flying';
  state.flyStart = performance.now();
  state.currentMult = 1.00;

  chart.reset();

  _showMultiplier(1.00, 'flying');
  dom.statusLabel.textContent = 'FLYING';
  dom.crashOvl.classList.add('hidden');
  dom.countdown.classList.add('hidden');
  dom.planeWrap.classList.remove('hidden', 'crashing');

  audio.fly();
  _tickFly();
}

function _tickFly() {
  if (state.phase !== 'flying') return;

  const elapsed = (performance.now() - state.flyStart) / 1000;
  const progress = Math.min(elapsed / state.flyDuration, 1);

  // Simulate exponential growth: m = exp(speed * t)
  const speed = Math.log(Math.max(state.crashMult, 1.01)) / state.flyDuration;
  const m = Math.exp(speed * elapsed);
  state.currentMult = m;

  _showMultiplier(m, 'flying');
  _updatePlanePos(progress, m);

  const t = progress;
  chart.push(t, m);

  // Update live info
  dom.infoMult.textContent = m.toFixed(2) + '×';

  if (progress < 1) {
    requestAnimationFrame(_tickFly);
  }
}

// ── Phase: Crashed ────────────────────────────────────────────────────
function _enterCrash(round) {
  state.phase = 'crashed';
  const m = round.multiplier;

  _showMultiplier(m, 'crashed');
  dom.statusLabel.textContent = 'CRASHED';
  dom.crashFinal.textContent  = m.toFixed(2) + '×';
  dom.crashOvl.classList.remove('hidden');
  dom.planeWrap.classList.add('crashing');

  chart.drawCrash();
  audio.crash();

  _updateLiveInfo(round);

  // Wait a beat then start countdown
  setTimeout(() => _enterCountdown(), 1200);
}

// ── Phase: Countdown ─────────────────────────────────────────────────
function _enterCountdown() {
  state.phase = 'waiting';
  dom.crashOvl.classList.add('hidden');
  dom.planeWrap.classList.add('hidden');
  dom.countdown.classList.remove('hidden');
  _showMultiplier(1.00, '');
  dom.statusLabel.textContent = 'WAITING';

  // Random 3-5 s countdown matching backend inter-round gap
  let secs = Math.floor(Math.random() * 3) + 3;
  dom.countNum.textContent = secs;

  const tick = setInterval(() => {
    secs--;
    audio.tick();
    dom.countNum.textContent = secs;
    // re-trigger animation
    dom.countNum.style.animation = 'none';
    void dom.countNum.offsetHeight;
    dom.countNum.style.animation = '';

    if (secs <= 0) {
      clearInterval(tick);
      dom.countdown.classList.add('hidden');
      _enterFly();
    }
  }, 1000);
}

// ── Helpers ────────────────────────────────────────────────────────────
function _showMultiplier(m, cls) {
  dom.multVal.innerHTML = m.toFixed(2) + '<span class="x-sign">×</span>';
  dom.multVal.className = 'multiplier-value ' + cls;
}

function _updatePlanePos(t, m) {
  const wrap  = document.querySelector('.canvas-wrap');
  const W     = wrap.clientWidth;
  const H     = wrap.clientHeight;
  const PAD_L = 52, PAD_R = 24, PAD_T = 24, PAD_B = 36;
  const cW    = W - PAD_L - PAD_R;
  const cH    = H - PAD_T - PAD_B;

  const maxM = Math.max(state.crashMult || m, 2);
  const x = PAD_L + t * cW - 32;
  const yNorm = Math.log(Math.max(m, 1)) / Math.log(maxM);
  const y = H - PAD_B - yNorm * cH - 48;

  dom.planeWrap.style.left   = x + 'px';
  dom.planeWrap.style.bottom = (H - y - 64) + 'px';

  // Tilt plane based on curve gradient
  const angle = Math.max(-40, Math.min(40, yNorm * -35));
  dom.planeSvg.style.transform = `rotate(${angle}deg)`;
}

function _updateLiveInfo(round) {
  dom.infoId.textContent    = '#' + round.round_id;
  dom.infoMult.textContent  = round.multiplier.toFixed(2) + '×';
  dom.infoCrash.textContent = round.multiplier.toFixed(2) + '×';
  dom.infoDur.textContent   = round.duration.toFixed(2) + 's';
  dom.infoTs.textContent    = new Date(round.timestamp * 1000).toLocaleTimeString();
}

function updateStats(s) {
  dom.statTotal.textContent = s.total_rounds ?? '—';
  dom.statAvg.textContent   = s.mean_multiplier ? s.mean_multiplier.toFixed(2) + '×' : '—';
  dom.statMax.textContent   = s.max_multiplier  ? s.max_multiplier.toFixed(2) + '×'  : '—';
  dom.statMin.textContent   = s.min_multiplier  ? s.min_multiplier.toFixed(2) + '×'  : '—';
}

function updateHistory(rounds) {
  if (!rounds || !rounds.length) return;
  state.history = rounds;
  dom.histCount.textContent = rounds.length;

  dom.histBadges.innerHTML = '';
  // Show newest first
  [...rounds].reverse().forEach(r => {
    const m   = r.multiplier;
    const cls = m >= 10 ? 'badge--gold' : m >= 2 ? 'badge--purple' : 'badge--red';
    const el  = document.createElement('span');
    el.className = `badge ${cls}`;
    el.textContent = m.toFixed(2) + '×';
    el.title = `Round #${r.round_id}`;
    dom.histBadges.appendChild(el);
  });
}

// ── Bootstrap ──────────────────────────────────────────────────────────
(async function init() {
  // Prime history and stats immediately
  await Promise.allSettled([pollHistory(), pollStats()]);

  // Kick-off the fly animation with data from first /latest call
  try {
    const latest = await api('/latest');
    setOnline(true);
    state.lastRoundId = latest.round_id;
    state.crashMult   = latest.multiplier;
    state.flyDuration = latest.duration;
    _updateLiveInfo(latest);
    _enterCountdown();
  } catch (_) {
    setOnline(false);
    dom.statusLabel.textContent = 'OFFLINE';
  }

  // Poll /latest every 1 s
  setInterval(poll, 1000);

  // Refresh stats + history every 5 s
  setInterval(pollStats,   5000);
  setInterval(pollHistory, 5000);
})();
