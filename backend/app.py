# === TOP: All imports ===
import logging
import threading
from typing import Tuple

from flask import Flask, jsonify, request
from model import AviatorPredictor, TensorFlowUnavailable
from risk_engine import (compute_moving_averages, compute_risk_index, compute_round_summary, compute_volatility, detect_streaks)
from trainer import TrainingService
from prediction.predictor import get_predictor
from prediction.risk_management import full_guidance
from utils import (append_decision, ensure_data_files, load_round_history, read_json, setup_logging, utc_now, DECISIONS_PATH, METADATA_PATH, MIN_CONFIDENCE_TO_STORE)
from crash_engine import generate_multiplier, estimate_duration, DEFAULT_HOUSE_EDGE
from game_loop import start_loop, get_loop, get_live_state
from round_logger import get_store as get_round_store, get_all_rounds, get_latest, round_count
from risk_statistics import compute_stats

# === SETUP (runs once at import time) ===
setup_logging()
ensure_data_files()

# === Flask app ===
app = Flask(__name__)

@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response

logger = logging.getLogger("aviator-api")
trainer = TrainingService()
predictor = trainer.predictor

# === Model readiness event ===
_model_ready = threading.Event()

def start_model_prewarm() -> None:
    """Load predictor in background so first /predict call doesn't block or timeout."""
    def _prewarm_model():
        try:
            live = get_all_rounds()
            mults = [r["multiplier"] for r in live] if len(live) >= 20 else \
                    [r["multiplier"] for r in load_round_history()]
            if len(mults) >= 20:
                logger.info("Pre-warming predictor...")
                get_predictor().predict(mults)
                logger.info("Predictor pre-warmed OK")
        except Exception as exc:
            logger.warning("Pre-warm skipped: %s", exc)
        finally:
            _model_ready.set()

    if _model_ready.is_set():
        return
    threading.Thread(target=_prewarm_model, daemon=True, name="model-prewarm").start()

def json_error(message: str, status: int = 400):
    logger.warning(message)
    return jsonify({"error": message, "status": status}), status


# ── Health ───────────────────────────────────────────────────────────

@app.get("/")
def health():
    return jsonify({
        "status": "online",
        "service": "aviator-risk-management",
        "game_loop_alive": get_loop().is_running,
        "stored_rounds": round_count(),
        "model_ready": _model_ready.is_set(),
    })


@app.get("/ready")
def ready():
    """Lightweight readiness probe — returns model warm status."""
    return jsonify({
        "ready": _model_ready.is_set(),
        "stored_rounds": round_count(),
    })


# ── Training ─────────────────────────────────────────────────────────

@app.post("/train")
def train():
    payload = request.get_json(silent=True) or {}
    epochs = int(payload.get("epochs", 30))
    try:
        return jsonify({"status": "trained", **trainer.train(epochs=epochs)})
    except TensorFlowUnavailable as exc:
        return json_error(str(exc), 503)
    except Exception as exc:
        logger.exception("Training failed")
        return json_error(f"Training failed: {exc}", 500)


@app.post("/retrain")
def retrain():
    payload = request.get_json(silent=True) or {}
    epochs = int(payload.get("epochs", 30))
    try:
        return jsonify({"status": "retrained", **trainer.train(epochs=epochs)})
    except TensorFlowUnavailable as exc:
        return json_error(str(exc), 503)
    except Exception as exc:
        logger.exception("Retraining failed")
        return json_error(f"Retraining failed: {exc}", 500)


# ── Prediction ───────────────────────────────────────────────────────

MIN_CONFIDENCE = MIN_CONFIDENCE_TO_STORE  # alias for use in this module

@app.get("/predict")
def predict():
    """
    Returns prediction from the V2 pipeline.
    Waits up to 90s for the TF model to finish loading on cold start.
    Stores at most ONE decision per round_id.
    """
    try:
        # Wait for model pre-warm (max 90s — only blocks on first cold start)
        _model_ready.wait(timeout=90)

        trainer.auto_retrain_if_needed()

        live = get_all_rounds()
        if len(live) >= 20:
            multipliers = [r["multiplier"] for r in live]
        else:
            history = load_round_history()
            multipliers = [r["multiplier"] for r in history]

        v2 = get_predictor()
        result = full_guidance(v2.predict(multipliers))

        current_round_id = live[-1]["round_id"] if live else None
        current_round_ts = live[-1].get("timestamp") if live else None

        decision = {
            **result,
            "created_at":         utc_now(),
            "source_round_count": len(multipliers),
            "last_round_id":      current_round_id,
            "last_multiplier":    multipliers[-1] if multipliers else None,
            "last_round_ts":      current_round_ts,
        }

        # Store at most one decision per round_id — prevents duplicate evaluations
        # that cause fake "✗ Wrong" from double-counting the same predicted round
        if result["confidence"] >= MIN_CONFIDENCE:
            existing = read_json(DECISIONS_PATH, [])
            if not isinstance(existing, list):
                existing = []
            already_stored = any(
                d.get("last_round_id") == current_round_id
                for d in existing[-5:]
            )
            if not already_stored:
                append_decision(decision)
            else:
                decision["cached"] = True

        # Background retrain check
        try:
            from training.retrain import retrain_if_needed
            threading.Thread(target=retrain_if_needed, daemon=True).start()
        except Exception:
            pass

        return jsonify(decision)
    except TensorFlowUnavailable as exc:
        return json_error(str(exc), 503)
    except FileNotFoundError as exc:
        return json_error(str(exc), 404)
    except Exception as exc:
        logger.exception("Prediction failed")
        return json_error(f"Prediction failed: {exc}", 500)


@app.get("/fast-predict")
def fast_predict():
    """
    Ultra-fast prediction endpoint (<50 ms target).
    No retrain check, no disk I/O during the call.
    Used by WebSocket clients and high-frequency polling.
    """
    try:
        live = get_all_rounds()
        if len(live) >= 20:
            multipliers = [r["multiplier"] for r in live]
        else:
            history = load_round_history()
            multipliers = [r["multiplier"] for r in history]

        result = full_guidance(get_predictor().predict(multipliers))
        result["last_round_id"]  = live[-1]["round_id"] if live else None
        result["last_round_ts"]  = live[-1].get("timestamp") if live else None
        result["last_multiplier"] = multipliers[-1] if multipliers else None
        return jsonify(result)
    except Exception as exc:
        return json_error(f"Fast predict failed: {exc}", 500)


# ── History ──────────────────────────────────────────────────────────

@app.get("/history")
def history():
    frame = _get_rounds()
    limit = int(request.args.get("limit", 100))
    records = frame[-limit:]
    return jsonify({"count": int(len(frame)), "rounds": records})


# ── Accuracy ─────────────────────────────────────────────────────────

@app.get("/accuracy")
def accuracy():
    metadata  = read_json(METADATA_PATH, {})
    decisions = read_json(DECISIONS_PATH, [])
    if not isinstance(decisions, list):
        decisions = []
    resolved = [d for d in decisions if d.get("actual_multiplier") is not None]
    correct  = [d for d in resolved  if d.get("correct") is True]
    hit_rate = round(len(correct) / len(resolved) * 100, 2) if resolved else None
    return jsonify({
        "model":               metadata,
        "prediction_count":    len(decisions),
        "resolved_count":      len(resolved),
        "correct_count":       len(correct),
        "hit_rate_pct":        hit_rate,
        "validation_accuracy": metadata.get("validation_accuracy", 0),
        "train_accuracy":      metadata.get("train_accuracy", 0),
    })


@app.post("/backfill")
def backfill():
    """Match past predictions to actual round outcomes."""
    try:
        updated = trainer.backfill_actual_results()
        return jsonify({"updated": updated})
    except Exception as exc:
        logger.exception("Backfill failed")
        return json_error(str(exc), 500)


@app.get("/skip-quality")
def skip_quality():
    """Return skip quality guard metrics."""
    try:
        from prediction.risk_management import get_skip_guard
        return jsonify(get_skip_guard().status())
    except Exception as exc:
        return json_error(str(exc), 500)


@app.get("/vh-quality")
def vh_quality():
    """Return VERY_HIGH false-positive guard metrics."""
    try:
        from prediction.risk_management import get_vh_guard
        return jsonify(get_vh_guard().status())
    except Exception as exc:
        return json_error(str(exc), 500)


@app.get("/calibration")
def calibration_status():
    """Return full calibration engine state: Bayesian priors, boundary optimizer, recalibration mode."""
    try:
        from prediction.calibration_engine import get_calibration_engine
        return jsonify(get_calibration_engine().status())
    except Exception as exc:
        return json_error(str(exc), 500)


@app.post("/calibration/reset")
def calibration_reset():
    """Manually reset calibration state (clears Bayesian priors and boundary adjustments)."""
    try:
        from prediction.calibration_engine import get_calibration_engine
        get_calibration_engine().force_reset()
        return jsonify({"status": "reset"})
    except Exception as exc:
        return json_error(str(exc), 500)


@app.get("/confidence-calibration")
def confidence_calibration_status():
    """Return full confidence calibration state: bins, inversion, correction factors, audit summary."""
    try:
        from prediction.confidence_calibrator import get_confidence_calibrator
        return jsonify(get_confidence_calibrator().status())
    except Exception as exc:
        return json_error(str(exc), 500)


@app.get("/confidence-calibration/audit")
def confidence_calibration_audit():
    """Return recent confidence calibration audit log entries."""
    try:
        from prediction.confidence_calibrator import get_confidence_calibrator
        limit = request.args.get("limit", 50, type=int)
        return jsonify(get_confidence_calibrator().get_audit_log(limit=limit))
    except Exception as exc:
        return json_error(str(exc), 500)


@app.get("/streak-matrix")
def streak_matrix():
    """Return streak success matrix and validity checker state."""
    try:
        from prediction.momentum_streak import get_momentum_engine
        return jsonify(get_momentum_engine().status())
    except Exception as exc:
        return json_error(str(exc), 500)


@app.get("/risk-tier")
def risk_tier_status():
    """Return MEDIUM risk-tier validator state: accuracy, spread, gate results, params."""
    try:
        from prediction.risk_tier_validator import get_risk_tier_validator
        return jsonify(get_risk_tier_validator().status())
    except Exception as exc:
        return json_error(str(exc), 500)


# ── Decisions / Logs ─────────────────────────────────────────────────

@app.get("/decisions")
def decisions():
    limit = int(request.args.get("limit", 50))
    payload = read_json(DECISIONS_PATH, [])
    return jsonify({"decisions": payload[-limit:] if isinstance(payload, list) else []})


# ═════════════════════════════════════════════════════════════════════
# RISK MANAGEMENT ENDPOINTS
# ═════════════════════════════════════════════════════════════════════

def _get_rounds() -> list:
    """
    Single source of truth for all endpoints.
    Uses the live RoundStore (simulator) if it has data,
    otherwise falls back to the static history file.
    Caps at the most recent 500 rounds for risk/stats calculations
    so extreme outliers from early simulator runs don't dominate.
    """
    live = get_all_rounds()
    if len(live) >= 20:
        return live[-500:]   # keep most recent 500 for representative stats
    hist = load_round_history()
    return hist[-500:]


@app.get("/risk/overview")
def risk_overview():
    """Composite risk dashboard data."""
    try:
        rounds_capped = _get_rounds()          # last 500 for stats quality
        rounds_all    = get_all_rounds()       # full store for real total count
        if not rounds_all:
            rounds_all = load_round_history()

        multipliers = [r["multiplier"] for r in rounds_capped]
        summary     = compute_round_summary(rounds_capped)

        # Override total_rounds with the real count, not the capped 500
        summary["total_rounds"]   = len(rounds_all)
        summary["max_multiplier"] = round(max(r["multiplier"] for r in rounds_all), 2)
        summary["min_multiplier"] = round(min(r["multiplier"] for r in rounds_all), 2)

        return jsonify({
            "summary": summary,
            "risk": compute_risk_index(multipliers),
        })
    except Exception as exc:
        logger.exception("Risk overview failed")
        return json_error(str(exc), 500)


@app.get("/risk/volatility")
def risk_volatility():
    """Volatility metrics."""
    try:
        multipliers = [r["multiplier"] for r in _get_rounds()]
        return jsonify(compute_volatility(multipliers))
    except Exception as exc:
        logger.exception("Volatility calculation failed")
        return json_error(str(exc), 500)


@app.get("/risk/streaks")
def risk_streaks():
    """Streak detection results."""
    try:
        multipliers = [r["multiplier"] for r in _get_rounds()]
        return jsonify(detect_streaks(multipliers))
    except Exception as exc:
        logger.exception("Streak detection failed")
        return json_error(str(exc), 500)


@app.get("/risk/moving-averages")
def risk_moving_averages():
    """Moving average values."""
    try:
        multipliers = [r["multiplier"] for r in _get_rounds()]
        return jsonify(compute_moving_averages(multipliers))
    except Exception as exc:
        logger.exception("Moving average calculation failed")
        return json_error(str(exc), 500)


@app.get("/risk/history")
def risk_history():
    """
    Full history enriched with risk metrics per round (rolling).
    Useful for charts that show risk evolution over time.
    """
    try:
        rounds = _get_rounds()
        limit = int(request.args.get("limit", 100))
        records = rounds[-limit:]
        multipliers = [r["multiplier"] for r in records]

        enriched = []
        for i in range(len(records)):
            window = multipliers[: i + 1]
            volatility = compute_volatility(window)
            streaks = detect_streaks(window)
            mas = compute_moving_averages(window)
            risk = compute_risk_index(window)
            enriched.append({
                **records[i],
                "volatility": volatility["recent_std"],
                "streak_category": streaks["current_streak"]["category"],
                "streak_length": streaks["current_streak"]["length"],
                "sma_5": mas["sma_5"],
                "sma_10": mas["sma_10"],
                "risk_score": risk["risk_score"],
                "risk_level": risk["risk_level"],
            })

        return jsonify({"count": len(enriched), "rounds": enriched})
    except Exception as exc:
        logger.exception("Risk history failed")
        return json_error(str(exc), 500)


# ═════════════════════════════════════════════════════════════════════
# CRASH SIMULATOR ENDPOINTS
# ═════════════════════════════════════════════════════════════════════

@app.get("/state")
def game_state():
    """Real-time game state for the live frontend."""
    return jsonify(get_live_state())


@app.get("/rounds")
def get_rounds():
    """
    Return rounds from the crash simulator's store (paginated).
    """
    limit = request.args.get("limit", 200, type=int)
    offset = request.args.get("offset", 0, type=int)

    rounds = get_all_rounds()
    total = len(rounds)
    page = rounds[-limit - offset: -offset or None] if offset else rounds[-limit:]

    return jsonify({
        "total": total,
        "returned": len(page),
        "limit": limit,
        "offset": offset,
        "rounds": page,
    })


@app.get("/latest")
def get_latest_round():
    """Return the single most-recent crash simulator round."""
    latest = get_latest(1)
    if not latest:
        return jsonify({"error": "No rounds yet"}), 404
    return jsonify(latest[0])


@app.get("/stats")
def get_stats():
    """
    Return summary statistics from the crash simulator store.

    Query params
    ------------
    n : int, optional  –  Compute stats over the last *n* rounds (default: all).
    """
    n = request.args.get("n", 0, type=int)
    rounds = get_all_rounds()
    if n > 0 and n < len(rounds):
        rounds = rounds[-n:]
    return jsonify(compute_stats(rounds))


@app.post("/generate")
def generate():
    """
    Manually generate one or more rounds (bypasses the game loop).

    JSON body (optional)::

        {"count": 10, "house_edge": 0.01}
    """
    import time as _time

    body = request.get_json(silent=True) or {}
    count = max(1, min(int(body.get("count", 1)), 10_000))
    house_edge = float(body.get("house_edge", DEFAULT_HOUSE_EDGE))

    store = get_round_store()
    last_id = store.last_round_id() or 0
    server_seed = body.get("server_seed")
    client_seed = body.get("client_seed")

    new_rounds = []
    ts = _time.time()
    for i in range(1, count + 1):
        nonce = last_id + i
        mult = generate_multiplier(server_seed, client_seed, nonce, house_edge)
        dur = estimate_duration(mult)
        new_rounds.append({
            "round_id": last_id + i,
            "timestamp": round(ts + sum(r["duration"] for r in new_rounds) + i * 0.5, 3),
            "multiplier": mult,
            "duration": dur,
        })

    store.append_batch(new_rounds)

    return jsonify({
        "generated": count,
        "rounds": new_rounds,
    }), 201


@app.get("/evaluate")
def evaluate():
    """Run model evaluation on recent rounds and return summary."""
    try:
        from training.evaluate_model import evaluate as _eval
        n = request.args.get("rounds", 200, type=int)
        return jsonify(_eval(n))
    except FileNotFoundError as exc:
        return json_error(str(exc), 404)
    except Exception as exc:
        logger.exception("Evaluation failed")
        return json_error(str(exc), 500)


@app.post("/train-rf")
def train_rf():
    """Train the RandomForest classifier in background."""
    def _run():
        try:
            from training.train_rf import train as _train_rf
            metrics = _train_rf()
            # Reset RF singleton so it reloads the new model
            import prediction.rf_predictor as _rfp
            _rfp._rf_predictor = None
            logger.info("RF training complete. val_acc=%.2f%%",
                        metrics.get("validation_accuracy", 0))
        except Exception as exc:
            logger.exception("RF training failed: %s", exc)

    threading.Thread(target=_run, daemon=True, name="rf-train").start()
    return jsonify({"status": "rf_training_started",
                    "message": "RandomForest training in background."})

def training_status():
    """Return last training metrics + retrain state."""
    import json as _json
    from pathlib import Path as _Path
    logs_dir = _Path(__file__).resolve().parent / "logs"
    result = {}
    for name, fname in [("last_training", "last_training.json"),
                         ("last_evaluation", "last_evaluation.json"),
                         ("retrain_state", "retrain_state.json")]:
        fp = logs_dir / fname
        if fp.exists():
            try:
                result[name] = _json.loads(fp.read_text())
            except Exception:
                pass
    return jsonify(result)


if __name__ == "__main__":
    # Start game loop
    start_loop()
    logger.info("Crash simulator game loop started")

    start_model_prewarm()

    # Start with SocketIO if available
    try:
        from flask_socketio import SocketIO as _SocketIO
        import ws_server as _ws
        _sio = _SocketIO(app, cors_allowed_origins="*", async_mode="threading", logger=False, engineio_logger=False)
        _ws._sio = _sio
        _ws.start_state_broadcaster()
        logger.info("WebSocket ready on port 5000")
        _sio.run(app, host="0.0.0.0", port=5000, debug=False, allow_unsafe_werkzeug=True)
    except ImportError:
        logger.warning("flask-socketio not installed")
        app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)

