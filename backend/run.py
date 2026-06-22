"""
run.py — Production entry point
================================
Starts Flask + SocketIO together so WebSocket and HTTP share the same port.

Usage:
    cd backend && python run.py

Features enabled:
  - HTTP REST API on port 5000
  - WebSocket events on same port (via flask-socketio)
  - Background crash simulator game loop
  - WebSocket state broadcaster (100 ms live state push)
  - Auto-retrain background thread
"""

import logging
import sys
from pathlib import Path

# Ensure backend is importable
sys.path.insert(0, str(Path(__file__).resolve().parent))

from utils import setup_logging, ensure_data_files

setup_logging()
ensure_data_files()

log = logging.getLogger("run")

# ── Start game loop ───────────────────────────────────────────────────────
from game_loop import start_loop
start_loop()
log.info("Crash simulator game loop started")

# ── Import Flask app ──────────────────────────────────────────────────────
from app import app, start_model_prewarm

start_model_prewarm()
log.info("Predictor pre-warm started in background")

# ── Setup SocketIO ────────────────────────────────────────────────────────
try:
    from flask_socketio import SocketIO

    sio = SocketIO(
        app,
        cors_allowed_origins="*",
        async_mode="threading",
        logger=False,
        engineio_logger=False,
    )

    # Patch ws_server to use this sio instance
    import ws_server
    ws_server._sio = sio

    # Start state broadcaster
    ws_server.start_state_broadcaster()
    log.info("WebSocket server ready")

    WS_AVAILABLE = True
except ImportError:
    log.warning("flask-socketio not installed — WebSocket disabled. "
                "Install with: pip install flask-socketio")
    WS_AVAILABLE = False

# ── Run ───────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if WS_AVAILABLE:
        log.info("Starting Flask+SocketIO on http://0.0.0.0:5000")
        sio.run(app, host="0.0.0.0", port=5000, debug=False, allow_unsafe_werkzeug=True)
    else:
        log.info("Starting Flask (no WebSocket) on http://0.0.0.0:5000")
        app.run(host="0.0.0.0", port=5000, debug=False)
