"""
Subprocess manager for the Node.js Playwright automation bot.

Manages the lifecycle of the bot subprocess:
  - start(phone, password, headless) — spawns the Node.js bot
  - stop() — sends SIGTERM for graceful shutdown
  - status() — returns current state (idle / running / error)
  - get_logs() — retrieves recent stdout from the subprocess

The bot uses a persistent Chrome profile so login cookies survive across
restarts — credentials are only needed on the first run or after logout.
"""

import json
import logging
import os
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

ROOT_DIR = Path(__file__).resolve().parent.parent
BOT_DIR = ROOT_DIR / "bot"
BOT_SCRIPT = BOT_DIR / "runner.js"
STATUS_PATH = ROOT_DIR / "data" / "bot" / "status.json"
CONFIG_PATH = ROOT_DIR / "data" / "bot" / "config.json"
LOG_PATH = ROOT_DIR / "data" / "bot" / "bot.log"
COMMAND_PATH = ROOT_DIR / "data" / "bot" / "command.json"
ACTIVE_STATUSES = {
    "starting",
    "running",
    "launching_browser",
    "browser_ready",
    "opening_page",
    "page_ready",
    "checking_session",
    "logging_in",
    "login_success",
    "navigating_aviator",
    "aviator_loaded",
    "preparing_monitor",
    "prepared_monitor",
    "monitoring",
    "monitoring_hidden",
    "no_data",
    "monitor_error",
    "restarting",
}

logger = logging.getLogger("bot-runner")


# ── File helpers ──────────────────────────────────────────────────────

def _write_config(phone: str, password: str, headless: bool = False) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = {"phone": phone, "password": password, "headless": headless}
    tmp = CONFIG_PATH.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, CONFIG_PATH)


def _read_status(default: Optional[Dict] = None) -> Dict[str, Any]:
    if default is None:
        default = {"status": "idle", "updated_at": _now_iso()}
    try:
        if not STATUS_PATH.exists():
            return default
        with STATUS_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def request_manual_start() -> Dict[str, Any]:
    """Signal the browser bot that the user has manually reached Aviator."""
    status = _read_status({})
    if not status.get("running") and not _pid_is_bot_alive(_status_pid(status)):
        return {"success": False, "error": "Bot is not running", "status": status.get("status", "idle")}

    COMMAND_PATH.parent.mkdir(parents=True, exist_ok=True)
    command = {"command": "start_monitor", "created_at": _now_iso()}
    tmp = COMMAND_PATH.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(command, f, indent=2)
    os.replace(tmp, COMMAND_PATH)

    status["manual_start_requested_at"] = command["created_at"]
    status["step_details"] = "Manual Aviator confirmation requested"
    status["updated_at"] = _now_iso()
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with STATUS_PATH.open("w", encoding="utf-8") as f:
        json.dump(status, f, indent=2)

    return {"success": True, "message": "Manual Aviator confirmation sent", "status": status.get("status")}


# ── Process management ────────────────────────────────────────────────

_process: Optional[subprocess.Popen] = None


def _pid_is_alive(pid: Any) -> bool:
    try:
        pid_int = int(pid)
    except (TypeError, ValueError):
        return False
    if pid_int <= 0:
        return False
    try:
        os.kill(pid_int, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _pid_is_bot(pid: Any) -> bool:
    try:
        pid_int = int(pid)
    except (TypeError, ValueError):
        return False
    cmdline_path = Path("/proc") / str(pid_int) / "cmdline"
    if not cmdline_path.exists():
        # Process may have just exited
        return False
    try:
        cmdline = cmdline_path.read_text(encoding="utf-8", errors="replace").replace("\x00", " ")
    except OSError:
        return False
    # Accept if it's our specific bot script, OR if it's a node process that
    # was started by us (managed _process) and is still in early initialisation
    # (cmdline may not yet show the full script path on some kernels).
    if "node" in cmdline and str(BOT_SCRIPT) in cmdline:
        return True
    # Fallback: if we own the managed process and it's still alive, trust it
    global _process
    if _process is not None and _process.pid == pid_int and _process.poll() is None:
        return "node" in cmdline
    return False


def _pid_is_bot_alive(pid: Any) -> bool:
    return _pid_is_alive(pid) and _pid_is_bot(pid)


def _managed_process_alive() -> bool:
    return _process is not None and _process.poll() is None


def _status_pid(status: Dict[str, Any]) -> Optional[int]:
    try:
        pid = int(status.get("pid") or 0)
    except (TypeError, ValueError):
        return None
    return pid if pid > 0 else None


def start(phone: str, password: str, headless: bool = False) -> Dict[str, Any]:
    """Start the Node.js Playwright bot as a subprocess."""
    global _process

    current_status = _read_status({})
    status_pid = _status_pid(current_status)

    if _managed_process_alive():
        return {"success": False, "error": "Bot is already running", "status": "running"}

    if status_pid and _pid_is_bot_alive(status_pid):
        return {"success": False, "error": "Bot is already running", "status": "running", "pid": status_pid}

    if _process is not None:
        poll = _process.poll()
        if poll is None:
            return {"success": False, "error": "Bot is already running", "status": "running"}
        # Stale/exited process — clean up pipes before replacing
        _try_read_pipes()
        _process = None

    if not phone or not password:
        return {"success": False, "error": "Phone and password are required"}

    if not BOT_SCRIPT.exists():
        return {"success": False, "error": f"Bot script not found at {BOT_SCRIPT}"}

    # Write config for the Node.js bot
    _write_config(phone, password, headless)

    # Write initial status
    status = {
        "status": "starting",
        "phone": phone,
        "headless": headless,
        "pid": None,
        "started_at": _now_iso(),
        "updated_at": _now_iso(),
        "rounds_seen": 0,
        "last_round": None,
        "error": None,
    }
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with STATUS_PATH.open("w", encoding="utf-8") as f:
        json.dump(status, f, indent=2)

    env = os.environ.copy()
    env["NODE_ENV"] = "production"
    # Ensure node can find the playwright browsers
    env.setdefault("PLAYWRIGHT_BROWSERS_PATH", os.path.expanduser("~/.cache/ms-playwright"))
    # Add nvm node to PATH (node installed via nvm, not system-wide)
    nvm_node_dir = os.path.expanduser("~/.nvm/versions/node/v24.14.0/bin")
    if os.path.isdir(nvm_node_dir):
        env["PATH"] = f"{nvm_node_dir}:{env.get('PATH', '')}"

    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        log_file = LOG_PATH.open("a", encoding="utf-8")
        _process = subprocess.Popen(
            ["node", str(BOT_SCRIPT)],
            stdout=log_file,
            stderr=subprocess.STDOUT,
            env=env,
            cwd=str(BOT_DIR),
        )

        # Update status with PID
        status["pid"] = _process.pid
        status["status"] = "running"
        with STATUS_PATH.open("w", encoding="utf-8") as f:
            json.dump(status, f, indent=2)

        logger.info("Node.js bot started (PID %s)", _process.pid)
        return {
            "success": True,
            "pid": _process.pid,
            "status": "running",
            "message": f"Bot started with PID {_process.pid}",
        }

    except Exception as exc:
        logger.exception("Failed to start bot subprocess")
        status["status"] = "error"
        status["error"] = str(exc)
        status["updated_at"] = _now_iso()
        with STATUS_PATH.open("w", encoding="utf-8") as f:
            json.dump(status, f, indent=2)
        return {"success": False, "error": str(exc)}


def stop() -> Dict[str, Any]:
    """Stop the bot subprocess gracefully (SIGTERM), then SIGKILL if needed."""
    global _process

    if _process is None:
        status = _read_status({})
        pid = _status_pid(status)
        if pid and _pid_is_bot_alive(pid):
            try:
                os.kill(pid, signal.SIGTERM)
                for _ in range(20):
                    time.sleep(0.5)
                    if not _pid_is_bot_alive(pid):
                        _update_status_after_stop("stopped")
                        return {"success": True, "message": "Bot stopped gracefully", "status": "idle"}
                os.kill(pid, signal.SIGKILL)
                _update_status_after_stop("killed")
                return {"success": True, "message": "Bot was force-killed", "status": "idle"}
            except ProcessLookupError:
                _update_status_after_stop("stopped")
                return {"success": True, "message": "Bot process already exited", "status": "idle"}
            except Exception as exc:
                return {"success": False, "error": str(exc), "status": "error"}
        _update_status_after_stop("stopped" if status.get("error") else "idle")
        return {"success": False, "error": "No bot process running", "status": "idle"}

    poll = _process.poll()
    if poll is not None:
        _process = None
        _update_status_after_stop("stopped")
        return {"success": True, "message": "Bot was already stopped", "status": "idle"}

    pid = _process.pid
    logger.info("Stopping bot (PID %s)...", pid)

    # Graceful shutdown via SIGTERM
    try:
        os.kill(pid, signal.SIGTERM)
        logger.info("SIGTERM sent to PID %s", pid)

        # Wait up to 10 seconds for graceful shutdown
        for _ in range(20):
            time.sleep(0.5)
            if _process.poll() is not None:
                # Flush any remaining output before clearing
                _try_read_pipes()
                _process = None
                _update_status_after_stop("stopped")
                return {"success": True, "message": "Bot stopped gracefully", "status": "idle"}
    except ProcessLookupError:
        _process = None
        _update_status_after_stop("stopped")
        return {"success": True, "message": "Bot process already exited", "status": "idle"}
    except Exception as exc:
        logger.error("Error stopping bot: %s", exc)

    # Force kill if still alive
    try:
        _process.kill()
        _process.wait(timeout=5)
        logger.info("Bot (PID %s) force-killed", pid)
    except Exception as exc:
        logger.error("Force kill failed: %s", exc)

    _process = None
    _update_status_after_stop("killed")
    return {"success": True, "message": "Bot was force-killed", "status": "idle"}


def _try_read_pipes() -> None:
    """
    Close any open log-file handle attached to the subprocess stdout.

    The subprocess is launched with stdout redirected to a log file
    (not subprocess.PIPE), so _process.stdout is None — there is nothing
    to read.  We simply make sure the Popen object is fully cleaned up.
    """
    global _process
    if _process is None:
        return
    # stdout/stderr are file objects (or None) when launched with a file handle.
    # Calling communicate() on an already-finished process is safe and drains
    # any internal buffers without blocking.
    try:
        if _process.poll() is not None:
            # Process already finished — communicate() returns immediately.
            _process.communicate(timeout=1)
    except Exception:
        pass


def _update_status_after_stop(state: str) -> None:
    status = _read_status({"status": "idle", "updated_at": _now_iso()})
    status["status"] = state
    status["pid_alive"] = False
    status["running"] = False
    status["updated_at"] = _now_iso()
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with STATUS_PATH.open("w", encoding="utf-8") as f:
        json.dump(status, f, indent=2)


def get_status() -> Dict[str, Any]:
    """Get the current bot status from the shared status file."""
    global _process

    status = _read_status()
    managed_alive = _managed_process_alive()
    pid = _status_pid(status)
    status_pid_alive = _pid_is_bot_alive(pid) if pid else False
    process_alive = managed_alive or status_pid_alive
    status["_pid"] = (_process.pid if managed_alive else pid) if process_alive else None
    status["pid_alive"] = process_alive
    status["running"] = process_alive

    # If subprocess object exists but process died, clean up
    if _process is not None and _process.poll() is not None:
        _try_read_pipes()
        _process = None
        if status.get("status") not in ("stopped", "killed", "error"):
            status["status"] = "crashed"
            status["updated_at"] = _now_iso()
    elif process_alive and status.get("status") in (None, "", "idle", "stopped", "killed", "crashed"):
        status["status"] = "running"
        status["updated_at"] = _now_iso()

    if not process_alive and pid:
        status["_pid"] = None
        if status.get("status") in ACTIVE_STATUSES:
            status["status"] = "crashed"
            status["updated_at"] = _now_iso()

    status["display_status"] = (
        "error"
        if status.get("error") and status.get("status") in ("idle", "stopped", "killed", "crashed")
        else status.get("status", "idle")
    )

    return status


def get_logs(tail: int = 100) -> Dict[str, Any]:
    """Retrieve recent bot output logs from stderr/stdout capture."""
    global _process
    logs = {"stdout": "", "stderr": ""}
    try:
        if LOG_PATH.exists():
            lines = LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
            logs["stdout"] = "\n".join(lines[-tail:])
    except Exception:
        pass
    return logs
