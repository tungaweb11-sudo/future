import { useEffect, useRef, useImperativeHandle, forwardRef } from 'react';

const PAD = { l: 56, r: 24, t: 28, b: 40 };

// Stars are generated once per canvas size, stored outside component to survive re-renders
let _stars = [], _starsW = 0, _starsH = 0;

function ensureStars(W, H) {
  if (_starsW === W && _starsH === H) return;
  _starsW = W; _starsH = H;
  _stars = Array.from({ length: 100 }, () => ({
    x: Math.random() * W, y: Math.random() * H,
    r: Math.random() * 1.3 + 0.2,
    a: Math.random() * 0.5 + 0.1,
  }));
}

function draw(ctx, W, H, points, crashed) {
  const cW = W - PAD.l - PAD.r;
  const cH = H - PAD.b - PAD.t;

  ctx.clearRect(0, 0, W, H);

  // Background gradient
  const bgGrad = ctx.createLinearGradient(0, 0, 0, H);
  bgGrad.addColorStop(0, '#080d1a');
  bgGrad.addColorStop(1, '#0d1120');
  ctx.fillStyle = bgGrad;
  ctx.fillRect(0, 0, W, H);

  // Stars
  ensureStars(W, H);
  for (const s of _stars) {
    ctx.beginPath();
    ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2);
    ctx.fillStyle = `rgba(255,255,255,${s.a})`;
    ctx.fill();
  }

  if (points.length < 2) {
    // Draw axes even with no data
    _drawAxes(ctx, W, H, cW, cH, 2);
    return;
  }

  const maxM = Math.max(...points.map(p => p.m), 2);
  _drawAxes(ctx, W, H, cW, cH, maxM);

  const px = t => PAD.l + t * cW;
  const py = m => PAD.t + cH - (Math.log(Math.max(m, 1)) / Math.log(maxM)) * cH;

  const lineColor = crashed ? '#e94560' : '#00e676';
  const fillTop   = crashed ? 'rgba(233,69,96,0.20)' : 'rgba(0,230,118,0.20)';
  const fillBot   = crashed ? 'rgba(233,69,96,0.00)' : 'rgba(0,230,118,0.00)';

  // Area fill
  const areaGrad = ctx.createLinearGradient(0, PAD.t, 0, PAD.t + cH);
  areaGrad.addColorStop(0, fillTop);
  areaGrad.addColorStop(1, fillBot);
  ctx.beginPath();
  _traceCurve(ctx, points, px, py);
  ctx.lineTo(px(points.at(-1).t), PAD.t + cH);
  ctx.lineTo(px(points[0].t), PAD.t + cH);
  ctx.closePath();
  ctx.fillStyle = areaGrad;
  ctx.fill();

  // Curve stroke
  ctx.beginPath();
  _traceCurve(ctx, points, px, py);
  ctx.strokeStyle = lineColor;
  ctx.lineWidth = 2.5;
  ctx.lineJoin = 'round';
  ctx.lineCap = 'round';
  ctx.shadowColor = lineColor;
  ctx.shadowBlur = 10;
  ctx.stroke();
  ctx.shadowBlur = 0;

  // Tip glow dot
  const tip = points.at(-1);
  const tx = px(tip.t), ty = py(tip.m);
  const rg = ctx.createRadialGradient(tx, ty, 0, tx, ty, 18);
  rg.addColorStop(0,   crashed ? 'rgba(233,69,96,0.75)' : 'rgba(0,230,118,0.75)');
  rg.addColorStop(0.5, crashed ? 'rgba(233,69,96,0.15)' : 'rgba(0,230,118,0.15)');
  rg.addColorStop(1,   'rgba(0,0,0,0)');
  ctx.beginPath(); ctx.arc(tx, ty, 18, 0, Math.PI * 2);
  ctx.fillStyle = rg; ctx.fill();
  ctx.beginPath(); ctx.arc(tx, ty, 4.5, 0, Math.PI * 2);
  ctx.fillStyle = lineColor; ctx.fill();

  return { tx, ty };
}

function _traceCurve(ctx, points, px, py) {
  ctx.moveTo(px(points[0].t), py(points[0].m));
  for (let i = 1; i < points.length; i++) {
    const p0 = points[i - 1], p1 = points[i];
    const cx = (px(p0.t) + px(p1.t)) / 2;
    ctx.bezierCurveTo(cx, py(p0.m), cx, py(p1.m), px(p1.t), py(p1.m));
  }
}

function _drawAxes(ctx, W, H, cW, cH, maxM) {
  ctx.font = '11px system-ui, sans-serif';
  ctx.textAlign = 'right';

  for (let i = 1; i <= 4; i++) {
    const y = PAD.t + (cH / 4) * i;
    ctx.strokeStyle = 'rgba(255,255,255,0.05)';
    ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(PAD.l, y); ctx.lineTo(W - PAD.r, y); ctx.stroke();

    const mVal = Math.exp(Math.log(Math.max(maxM, 1.01)) * (1 - i / 4));
    ctx.fillStyle = 'rgba(255,255,255,0.20)';
    ctx.fillText(mVal.toFixed(2) + '×', PAD.l - 6, y + 4);
  }

  // Bottom axis line
  ctx.strokeStyle = 'rgba(255,255,255,0.08)';
  ctx.beginPath();
  ctx.moveTo(PAD.l, PAD.t + cH);
  ctx.lineTo(W - PAD.r, PAD.t + cH);
  ctx.stroke();
}

// ── React component ────────────────────────────────────────────────────────

const AviatorCanvas = forwardRef(function AviatorCanvas({ points, crashed }, ref) {
  const canvasRef = useRef(null);
  const dprRef    = useRef(1);
  const pointsRef = useRef(points);
  pointsRef.current = points;

  useImperativeHandle(ref, () => ({
    getTipPixel() {
      const canvas = canvasRef.current;
      const pts = pointsRef.current;
      if (!canvas || pts.length < 2) return null;
      const dpr = dprRef.current;
      const W = canvas.width / dpr, H = canvas.height / dpr;
      const cW = W - PAD.l - PAD.r, cH = H - PAD.b - PAD.t;
      const maxM = Math.max(...pts.map(p => p.m), 2);
      const tip = pts.at(-1);
      return {
        x: PAD.l + tip.t * cW,
        y: PAD.t + cH - (Math.log(Math.max(tip.m, 1)) / Math.log(maxM)) * cH,
        W, H,
      };
    },
  }));

  // Setup resize observer once
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;
    dprRef.current = dpr;

    const resize = () => {
      const p = canvas.parentElement;
      canvas.width  = p.clientWidth  * dpr;
      canvas.height = p.clientHeight * dpr;
      canvas.style.width  = p.clientWidth  + 'px';
      canvas.style.height = p.clientHeight + 'px';
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      // Force star regen on next draw
      _starsW = 0;
      draw(ctx, p.clientWidth, p.clientHeight, pointsRef.current, crashed);
    };

    const ro = new ResizeObserver(resize);
    ro.observe(canvas.parentElement);
    resize();
    return () => ro.disconnect();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Redraw when points or crashed changes
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const dpr = dprRef.current;
    draw(ctx, canvas.width / dpr, canvas.height / dpr, points, crashed);
  }, [points, crashed]);

  return (
    <canvas
      ref={canvasRef}
      style={{ position: 'absolute', inset: 0, width: '100%', height: '100%' }}
    />
  );
});

export default AviatorCanvas;
