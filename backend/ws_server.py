"""
ws_server.py
============
Flask-SocketIO WebSocket server.

Events pushed to clients:
  "round_complete"  — after every crash (raw round data)
  "prediction"      — fresh prediction + stored decision after every round
  "state"           — live game phase/multiplier at 100 ms intervals
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict

log = logging.getLogger("ws-server")

_sio = None


def _get_sio():
    """Return the SocketIO instance set by run.py / app.py — never create a duplicate."""
    if _sio is None:
        raise RuntimeError("SocketIO not initialized — start the server via run.py")
    return _sio


def emit_round(round_data: Dict[str, Any]) -> None:
    """
    Called by game_loop after every completed round.
    1. Emits round_complete immediately
    2. Runs prediction and stores decision (if new round)
    3. Runs backfill so Actual column fills in real-time
    4. Emits prediction + decisions_updated events
    """
    try:
        sio = _get_sio()

        # Emit round immediately — <1ms
        sio.emit("round_complete", round_data)

        # Build prediction
        from round_logger import get_all_rounds
        from prediction.predictor import get_predictor
        from prediction.risk_management import full_guidance
        from utils import utc_now, append_decision, read_json, DECISIONS_PATH, MIN_CONFIDENCE_TO_STORE

        live        = get_all_rounds()
        multipliers = [r["multiplier"] for r in live] if len(live) >= 20 else []

        if len(multipliers) < 20:
            return

        result = full_guidance(get_predictor().predict(multipliers))

        current_round_id = live[-1]["round_id"]
        decision = {
            **result,
            "created_at":         utc_now(),
            "source_round_count": len(multipliers),
            "last_round_id":      current_round_id,
            "last_multiplier":    multipliers[-1],
            "last_round_ts":      live[-1].get("timestamp"),
        }

        # Store once per round_id
        stored = False
        if result["confidence"] >= MIN_CONFIDENCE_TO_STORE:
            existing = read_json(DECISIONS_PATH, [])
            if not isinstance(existing, list):
                existing = []
            already = any(d.get("last_round_id") == current_round_id for d in existing[-5:])
            if not already:
                append_decision(decision)
                stored = True

        # Push prediction event — frontend updates current prediction card instantly
        sio.emit("prediction", decision)

        # ── Real-time backfill ─────────────────────────────────────────
        # Run backfill right now so the Actual column fills in immediately
        # without waiting for the next manual /backfill HTTP call.
        try:
            from app import trainer
            updated = trainer.backfill_actual_results()
            if updated > 0:
                # Push the updated decisions list so frontend rows update in real-time
                updated_decisions = read_json(DECISIONS_PATH, [])
                if isinstance(updated_decisions, list):
                    sio.emit("decisions_updated", {
                        "decisions": updated_decisions[-100:],
                        "updated":   updated,
                    })
        except Exception as exc:
            log.debug("Real-time backfill: %s", exc)

    except Exception as exc:
        log.error("emit_round error: %s", exc)


def emit_state(state: Dict[str, Any]) -> None:
    try:
        _get_sio().emit("state", state)
    except Exception:
        pass


def emit_decisions_updated() -> None:
    """
    Push the latest decisions to all connected clients after backfill.
    Clients use this to update the Actual column in real-time.
    """
    try:
        from utils import read_json, DECISIONS_PATH
        decisions = read_json(DECISIONS_PATH, [])
        if isinstance(decisions, list):
            _get_sio().emit("decisions_updated", {"decisions": decisions[-100:]})
    except Exception as exc:
        log.debug("emit_decisions_updated error: %s", exc)


def start_state_broadcaster() -> None:
    """Push live game state at 100 ms intervals."""
    def _run():
        from game_loop import get_live_state
        while True:
            try:
                emit_state(get_live_state())
            except Exception:
                pass
            time.sleep(0.1)

    threading.Thread(target=_run, daemon=True, name="ws-state-broadcaster").start()
    log.info("WebSocket state broadcaster started (10 Hz)")
