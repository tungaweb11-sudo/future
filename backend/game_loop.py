"""
game_loop.py
Continuous Aviator-style game loop running on a daemon thread.

Exposes a thread-safe ``LIVE_STATE`` dict that the Flask /state endpoint
reads to give the frontend real-time phase information.
"""

from __future__ import annotations

import logging
import math
import random
import threading
import time
from typing import Optional

import crash_engine as engine
import round_logger as rlog

_log = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────

MIN_INTERROUND_GAP = 3.0   # seconds
MAX_INTERROUND_GAP = 6.0   # seconds

# ── Shared live state (read by /state endpoint) ───────────────────────────

_state_lock = threading.Lock()

LIVE_STATE: dict = {
    "phase":           "waiting",   # "waiting" | "flying" | "crashed"
    "round_id":        0,
    "multiplier":      1.00,        # current live multiplier (during flying)
    "crash_mult":      None,        # set after crash
    "elapsed":         0.0,         # seconds since round start
    "duration":        0.0,         # expected full round duration
    "countdown":       0.0,         # seconds remaining in waiting phase
    "server_seed":     engine.DEFAULT_SERVER_SEED,
    "client_seed":     engine.DEFAULT_CLIENT_SEED,
    "nonce":           0,
    "round_start_ts":  0.0,
    "gap_end_ts":      0.0,
}


def get_live_state() -> dict:
    """Return a snapshot of the current live state (thread-safe copy)."""
    with _state_lock:
        s = dict(LIVE_STATE)

    # Compute live multiplier from elapsed time so callers always get fresh value
    if s["phase"] == "flying" and s["duration"] > 0:
        elapsed = time.time() - s["round_start_ts"]
        speed   = math.log(max(s["crash_mult"] or 1.01, 1.01)) / s["duration"]
        s["multiplier"] = round(math.exp(speed * min(elapsed, s["duration"])), 2)
        s["elapsed"]    = round(elapsed, 3)
    elif s["phase"] == "waiting":
        s["countdown"] = round(max(0.0, s["gap_end_ts"] - time.time()), 2)

    return s


def _set(**kwargs) -> None:
    with _state_lock:
        LIVE_STATE.update(kwargs)


# ── Game loop ─────────────────────────────────────────────────────────────

class GameLoop:
    def __init__(self):
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.is_running:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="game-loop")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def join(self, timeout: Optional[float] = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def _run(self) -> None:
        last_id = rlog.get_last_round_id()
        round_id = (last_id + 1) if last_id is not None else 1
        nonce    = round_id

        server_seed = engine.DEFAULT_SERVER_SEED
        client_seed = engine.DEFAULT_CLIENT_SEED

        while not self._stop_event.is_set():
            try:
                # ── 1. Generate crash point ───────────────────────────
                multiplier = engine.generate_multiplier(
                    server_seed=server_seed,
                    client_seed=client_seed,
                    nonce=nonce,
                )
                duration = engine.estimate_duration(multiplier)

                # ── 2. Flying phase ───────────────────────────────────
                start_ts = time.time()
                _set(
                    phase="flying",
                    round_id=round_id,
                    crash_mult=multiplier,
                    duration=duration,
                    elapsed=0.0,
                    multiplier=1.00,
                    countdown=0.0,
                    round_start_ts=start_ts,
                    server_seed=server_seed,
                    client_seed=client_seed,
                    nonce=nonce,
                )

                _sleep_with_abort(duration, self._stop_event, interval=0.05)
                if self._stop_event.is_set():
                    break

                # ── 3. Crashed phase ──────────────────────────────────
                _set(phase="crashed", multiplier=multiplier, elapsed=duration)

                # Persist round — wrapped so a disk error never kills the thread
                try:
                    round_record = {
                        "round_id":    round_id,
                        "timestamp":   round(start_ts, 3),
                        "multiplier":  multiplier,
                        "duration":    round(duration, 2),
                        "server_seed": server_seed,
                        "client_seed": client_seed,
                        "nonce":       nonce,
                    }
                    rlog.append_round(round_record)

                    # Push real-time WebSocket event (non-blocking, best-effort)
                    try:
                        import ws_server
                        threading.Thread(
                            target=ws_server.emit_round,
                            args=(round_record,),
                            daemon=True,
                        ).start()
                    except ImportError:
                        pass
                except Exception as exc:  # noqa: BLE001
                    _log.error("Failed to persist round %d: %s", round_id, exc)

                # Brief crashed display
                _sleep_with_abort(1.5, self._stop_event, interval=0.1)
                if self._stop_event.is_set():
                    break

                # ── 4. Waiting phase ──────────────────────────────────
                gap = random.uniform(MIN_INTERROUND_GAP, MAX_INTERROUND_GAP)
                gap_end = time.time() + gap
                _set(phase="waiting", countdown=gap, gap_end_ts=gap_end)

                _sleep_with_abort(gap, self._stop_event, interval=0.1)
                if self._stop_event.is_set():
                    break

                round_id += 1
                nonce    += 1

            except Exception as exc:  # noqa: BLE001
                _log.exception("Unexpected error in game loop round %d: %s", round_id, exc)
                _set(phase="waiting", countdown=5.0, gap_end_ts=time.time() + 5.0)
                _sleep_with_abort(5.0, self._stop_event)
                round_id += 1
                nonce    += 1


def _sleep_with_abort(total: float, abort: threading.Event, interval: float = 0.1) -> None:
    elapsed = 0.0
    while elapsed < total:
        if abort.wait(min(interval, total - elapsed)):
            return
        elapsed += interval


# ── Module-level singleton ────────────────────────────────────────────────

_loop: Optional[GameLoop] = None


def get_loop() -> GameLoop:
    global _loop
    if _loop is None:
        _loop = GameLoop()
    return _loop


def start_loop() -> None:
    get_loop().start()


def stop_loop() -> None:
    get_loop().stop()

