/**
 * chart.js — Canvas multiplier curve renderer
 * Draws the Aviator-style rising curve on a <canvas> element.
 */

class AviatorChart {
  constructor(canvasId) {
    this.canvas = document.getElementById(canvasId);
    this.ctx    = this.canvas.getContext('2d');
    this.points = [];      // [{t, m}] normalised 0-1 pairs
    this.stars  = [];
    this._resizeObs = new ResizeObserver(() => this._resize());
    this._resizeObs.observe(this.canvas.parentElement);
    this._resize();
    this._initStars();
  }

  // ── Public API ──────────────────────────────────────────────

  /** Push a new {t (0-1), m (multiplier)} sample and redraw. */
  push(t, m) {
    this.points.push({ t, m });
    this.draw();
  }

  /** Reset to blank slate. */
  reset() {
    this.points = [];
    this.draw();
  }

  /** Full redraw. */
  draw() {
    const { ctx, canvas } = this;
    const W = canvas.width, H = canvas.height;
    const PAD_L = 52, PAD_B = 36, PAD_T = 24, PAD_R = 24;
    const cW = W - PAD_L - PAD_R;
    const cH = H - PAD_B - PAD_T;

    ctx.clearRect(0, 0, W, H);

    // Stars
    this._drawStars();

    if (this.points.length < 2) return;

    const maxM = Math.max(...this.points.map(p => p.m), 2);

    // Map helpers
    const px = t  => PAD_L + t * cW;
    const py = m  => PAD_T + cH - ((Math.log(m) / Math.log(maxM)) * cH);

    // ── Grid ───────────────────────────────────────────────────
    ctx.strokeStyle = 'rgba(255,255,255,0.06)';
    ctx.lineWidth = 1;

    // Horizontal grid lines (4)
    for (let i = 1; i <= 4; i++) {
      const y = PAD_T + (cH / 4) * i;
      ctx.beginPath(); ctx.moveTo(PAD_L, y); ctx.lineTo(W - PAD_R, y); ctx.stroke();
      // Label
      const mVal = Math.exp(Math.log(maxM) * (1 - (i / 4)));
      ctx.fillStyle = 'rgba(255,255,255,0.25)';
      ctx.font = '11px Segoe UI, sans-serif';
      ctx.textAlign = 'right';
      ctx.fillText(mVal.toFixed(2) + '×', PAD_L - 6, y + 4);
    }

    // ── Gradient fill under curve ──────────────────────────────
    const grad = ctx.createLinearGradient(0, PAD_T, 0, PAD_T + cH);
    grad.addColorStop(0,   'rgba(0,230,118,0.22)');
    grad.addColorStop(0.6, 'rgba(0,230,118,0.06)');
    grad.addColorStop(1,   'rgba(0,230,118,0)');

    ctx.beginPath();
    ctx.moveTo(px(this.points[0].t), py(this.points[0].m));
    for (let i = 1; i < this.points.length; i++) {
      const p0 = this.points[i - 1], p1 = this.points[i];
      const cpx = (px(p0.t) + px(p1.t)) / 2;
      ctx.bezierCurveTo(cpx, py(p0.m), cpx, py(p1.m), px(p1.t), py(p1.m));
    }
    ctx.lineTo(px(this.points.at(-1).t), PAD_T + cH);
    ctx.lineTo(px(this.points[0].t), PAD_T + cH);
    ctx.closePath();
    ctx.fillStyle = grad;
    ctx.fill();

    // ── Main curve ─────────────────────────────────────────────
    ctx.beginPath();
    ctx.moveTo(px(this.points[0].t), py(this.points[0].m));
    for (let i = 1; i < this.points.length; i++) {
      const p0 = this.points[i - 1], p1 = this.points[i];
      const cpx = (px(p0.t) + px(p1.t)) / 2;
      ctx.bezierCurveTo(cpx, py(p0.m), cpx, py(p1.m), px(p1.t), py(p1.m));
    }
    ctx.strokeStyle = '#00e676';
    ctx.lineWidth = 3;
    ctx.lineJoin = 'round';
    ctx.lineCap = 'round';
    ctx.shadowColor = '#00e676';
    ctx.shadowBlur = 12;
    ctx.stroke();
    ctx.shadowBlur = 0;

    // ── Glowing dot at tip ─────────────────────────────────────
    const tip = this.points.at(-1);
    const tx = px(tip.t), ty = py(tip.m);
    const dotGrad = ctx.createRadialGradient(tx, ty, 0, tx, ty, 14);
    dotGrad.addColorStop(0,   'rgba(0,230,118,0.7)');
    dotGrad.addColorStop(0.4, 'rgba(0,230,118,0.15)');
    dotGrad.addColorStop(1,   'rgba(0,230,118,0)');
    ctx.beginPath(); ctx.arc(tx, ty, 14, 0, Math.PI * 2);
    ctx.fillStyle = dotGrad; ctx.fill();
    ctx.beginPath(); ctx.arc(tx, ty, 5, 0, Math.PI * 2);
    ctx.fillStyle = '#00e676'; ctx.fill();
  }

  drawCrash() {
    const { ctx, canvas } = this;
    const W = canvas.width, H = canvas.height;
    const tip = this.points.at(-1);
    if (!tip) return;

    const PAD_L = 52, PAD_B = 36, PAD_T = 24, PAD_R = 24;
    const cW = W - PAD_L - PAD_R;
    const cH = H - PAD_B - PAD_T;
    const maxM = Math.max(...this.points.map(p => p.m), 2);
    const px = t => PAD_L + t * cW;
    const py = m => PAD_T + cH - ((Math.log(m) / Math.log(maxM)) * cH);

    // Red dot at crash point
    const tx = px(tip.t), ty = py(tip.m);
    const rGrad = ctx.createRadialGradient(tx, ty, 0, tx, ty, 18);
    rGrad.addColorStop(0,   'rgba(233,69,96,0.8)');
    rGrad.addColorStop(0.5, 'rgba(233,69,96,0.2)');
    rGrad.addColorStop(1,   'rgba(233,69,96,0)');
    ctx.beginPath(); ctx.arc(tx, ty, 18, 0, Math.PI * 2);
    ctx.fillStyle = rGrad; ctx.fill();
    ctx.beginPath(); ctx.arc(tx, ty, 6, 0, Math.PI * 2);
    ctx.fillStyle = '#e94560'; ctx.fill();
  }

  // ── Private ─────────────────────────────────────────────────

  _resize() {
    const wrap = this.canvas.parentElement;
    this.canvas.width  = wrap.clientWidth  * devicePixelRatio;
    this.canvas.height = wrap.clientHeight * devicePixelRatio;
    this.canvas.style.width  = wrap.clientWidth  + 'px';
    this.canvas.style.height = wrap.clientHeight + 'px';
    this.ctx.scale(devicePixelRatio, devicePixelRatio);
    this._initStars();
    this.draw();
  }

  _initStars() {
    const W = this.canvas.parentElement.clientWidth;
    const H = this.canvas.parentElement.clientHeight;
    this.stars = Array.from({ length: 80 }, () => ({
      x: Math.random() * W,
      y: Math.random() * H,
      r: Math.random() * 1.2 + 0.3,
      a: Math.random() * 0.6 + 0.2,
    }));
  }

  _drawStars() {
    const { ctx } = this;
    for (const s of this.stars) {
      ctx.beginPath();
      ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(255,255,255,${s.a})`;
      ctx.fill();
    }
  }
}
