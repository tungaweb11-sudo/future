"""
prediction/confidence_calibrator.py
=====================================
Thread-safe singleton ConfidenceCalibrator.

Provides confidence calibration via:
  1. Confidence bins (0-20, 20-40, 40-60, 60-80, 80-100) tracking
  2. Inversion detection — if high-confidence bins are consistently wrong,
     flip: new_conf = 100 - old_conf
  3. Isotonic-regression-style correction factor per bin (Platt scaling lite)
  4. Rolling audit log (max 200 entries)
  5. Persistence to artifacts/confidence_calibration.json
  6. Bootstrap from data/decisions.json on first init

Public API
----------
    calibrate(raw_confidence) -> dict
    record_outcome(raw_confidence, was_correct) -> None
    status() -> dict
    get_audit_log(limit=50) -> list
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils import read_json, write_json, utc_now, ARTIFACT_DIR, DECISIONS_PATH

log = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────

# Bin definitions: (label, lo_inclusive, hi_exclusive)
# The last bin is hi-inclusive (catches 100.0)
_BINS: List[Tuple[str, float, float]] = [
    ("0-20",   0.0,   20.0),
    ("20-40",  20.0,  40.0),
    ("40-60",  40.0,  60.0),
    ("60-80",  60.0,  80.0),
    ("80-100", 80.0,  100.001),   # 100.001 so 100.0 is captured
]

# Minimum resolved predictions in high-confidence bins before inversion check
INVERSION_MIN_SAMPLES = 15

# High-confidence bins are those with lo >= 50
HIGH_CONF_BIN_LABELS = {"60-80", "80-100"}

# Accuracy thresholds for inversion toggle
INVERSION_BAD_THRESHOLD  = 0.30   # < 30% → invert
INVERSION_GOOD_THRESHOLD = 0.50   # > 50% → clear inversion

# Isotonic correction limits (clamped)
CORRECTION_MIN = 0.5
CORRECTION_MAX = 2.0

# Minimum resolved predictions before computing correction factors
CORRECTION_MIN_SAMPLES = 20

# Audit log size
AUDIT_LOG_MAX = 200

# Persistence path
_CALIBRATION_STATE_PATH = ARTIFACT_DIR / "confidence_calibration.json"


# ── Helpers ───────────────────────────────────────────────────────────────

def _find_bin(confidence: float) -> str:
    """Return the bin label for a given confidence value."""
    for label, lo, hi in _BINS:
        if lo <= confidence < hi:
            return label
    # Clamp: below 0 → first bin, above 100 → last bin
    if confidence < 0.0:
        return _BINS[0][0]
    return _BINS[-1][0]


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


# ── ConfidenceCalibrator ──────────────────────────────────────────────────

class ConfidenceCalibrator:
    """
    Thread-safe confidence calibration system.

    Lifecycle:
        1. __init__ — creates empty state
        2. _ensure_initialised (lazy) — loads persisted state, then bootstraps
           from decisions.json so history is preserved across restarts
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._initialised = False

        # Per-bin stats: label → {"total": int, "correct": int, "conf_sum": float}
        self._bins: Dict[str, Dict] = {
            label: {"total": 0, "correct": 0, "conf_sum": 0.0}
            for label, _, _ in _BINS
        }

        # Inversion flag
        self._inverted: bool = False

        # Correction factors per bin (computed lazily)
        self._correction: Dict[str, float] = {label: 1.0 for label, _, _ in _BINS}

        # Rolling audit log
        self._audit: deque = deque(maxlen=AUDIT_LOG_MAX)

        # Summary counters
        self._summary: Dict[str, int] = {
            "over_confidence_events": 0,
            "under_confidence_events": 0,
            "inversions_applied": 0,
            "total_calibrated": 0,
        }

    # ── Initialisation / Persistence ─────────────────────────────────

    def _ensure_initialised(self) -> None:
        """Lazy init: load persisted state, then bootstrap from decisions.json."""
        if self._initialised:
            return
        self._load_state()
        self._bootstrap_from_decisions()
        self._initialised = True

    def _load_state(self) -> None:
        try:
            state = read_json(_CALIBRATION_STATE_PATH, {})
            if not state:
                return
            # Bins
            for label in self._bins:
                if label in state.get("bins", {}):
                    b = state["bins"][label]
                    self._bins[label]["total"]    = int(b.get("total", 0))
                    self._bins[label]["correct"]  = int(b.get("correct", 0))
                    self._bins[label]["conf_sum"] = float(b.get("conf_sum", 0.0))
            # Inversion
            self._inverted = bool(state.get("inverted", False))
            # Correction factors
            for label in self._correction:
                if label in state.get("correction", {}):
                    self._correction[label] = float(state["correction"][label])
            # Summary
            for k in self._summary:
                if k in state.get("summary", {}):
                    self._summary[k] = int(state["summary"][k])
            # Audit log (last AUDIT_LOG_MAX entries only)
            for entry in state.get("audit", []):
                self._audit.append(entry)
            log.debug("ConfidenceCalibrator: loaded state from disk")
        except Exception as exc:
            log.warning("ConfidenceCalibrator: failed to load state: %s", exc)

    def _save_state(self) -> None:
        try:
            write_json(_CALIBRATION_STATE_PATH, {
                "bins":       {
                    label: dict(stats)
                    for label, stats in self._bins.items()
                },
                "inverted":   self._inverted,
                "correction": dict(self._correction),
                "summary":    dict(self._summary),
                "audit":      list(self._audit),
            })
        except Exception as exc:
            log.warning("ConfidenceCalibrator: failed to save state: %s", exc)

    def _bootstrap_from_decisions(self) -> None:
        """
        On first init (no saved state or empty bins), replay resolved
        decisions from decisions.json to warm up bin stats.
        """
        total_existing = sum(b["total"] for b in self._bins.values())
        if total_existing > 0:
            # Already have data — skip bootstrap to avoid double-counting
            return
        try:
            decisions = read_json(DECISIONS_PATH, [])
            if not isinstance(decisions, list):
                return
            count = 0
            for d in decisions:
                if d.get("actual_multiplier") is None:
                    continue
                raw_conf = float(d.get("raw_confidence", d.get("confidence", 0.0)))
                was_correct = bool(d.get("correct", False))
                label = _find_bin(raw_conf)
                self._bins[label]["total"]    += 1
                self._bins[label]["conf_sum"] += raw_conf
                if was_correct:
                    self._bins[label]["correct"] += 1
                count += 1
            if count:
                self._recompute_correction()
                self._check_inversion(reason="bootstrap")
                log.debug(
                    "ConfidenceCalibrator: bootstrapped %d resolved decisions", count
                )
        except Exception as exc:
            log.warning("ConfidenceCalibrator: bootstrap failed: %s", exc)

    # ── Bin accuracy helpers ──────────────────────────────────────────

    def _bin_accuracy(self, label: str) -> Optional[float]:
        """Actual accuracy for a bin, or None if no data."""
        b = self._bins[label]
        if b["total"] == 0:
            return None
        return b["correct"] / b["total"]

    def _bin_mean_conf(self, label: str) -> Optional[float]:
        """Mean predicted confidence for a bin, or None if no data."""
        b = self._bins[label]
        if b["total"] == 0:
            return None
        return b["conf_sum"] / b["total"]

    # ── Inversion detection ────────────────────────────────────────────

    def _check_inversion(self, reason: str = "") -> None:
        """
        Evaluate high-confidence bins and update the inversion flag.
        Logs every state change.
        """
        high_total   = sum(self._bins[l]["total"]   for l in HIGH_CONF_BIN_LABELS)
        high_correct = sum(self._bins[l]["correct"] for l in HIGH_CONF_BIN_LABELS)

        if high_total < INVERSION_MIN_SAMPLES:
            return  # not enough data yet

        accuracy = high_correct / high_total

        if not self._inverted and accuracy < INVERSION_BAD_THRESHOLD:
            self._inverted = True
            self._summary["inversions_applied"] += 1
            log.warning(
                "ConfidenceCalibrator: INVERSION ACTIVATED — "
                "high-conf accuracy %.1f%% < %.0f%% (n=%d) reason=%s",
                accuracy * 100, INVERSION_BAD_THRESHOLD * 100, high_total, reason,
            )
        elif self._inverted and accuracy > INVERSION_GOOD_THRESHOLD:
            self._inverted = False
            log.info(
                "ConfidenceCalibrator: inversion CLEARED — "
                "high-conf accuracy %.1f%% > %.0f%% (n=%d) reason=%s",
                accuracy * 100, INVERSION_GOOD_THRESHOLD * 100, high_total, reason,
            )

    # ── Correction factor computation ─────────────────────────────────

    def _recompute_correction(self) -> None:
        """
        Compute per-bin correction factor after at least CORRECTION_MIN_SAMPLES
        total resolved predictions exist.

            correction[bin] = actual_accuracy[bin] / mean_predicted_confidence[bin]
                              (clamped to [CORRECTION_MIN, CORRECTION_MAX])
        """
        total_resolved = sum(b["total"] for b in self._bins.values())
        if total_resolved < CORRECTION_MIN_SAMPLES:
            return

        for label in self._correction:
            acc  = self._bin_accuracy(label)
            mean = self._bin_mean_conf(label)

            if acc is None or mean is None or mean == 0.0:
                self._correction[label] = 1.0
                continue

            # mean is in [0, 100], acc is in [0, 1] — normalise mean
            mean_norm = mean / 100.0
            raw_factor = acc / mean_norm
            self._correction[label] = _clamp(raw_factor, CORRECTION_MIN, CORRECTION_MAX)

    # ── Public API ────────────────────────────────────────────────────

    def calibrate(self, raw_confidence: float) -> Dict:
        """
        Apply calibration to a raw confidence value.

        Pipeline:
          1. Clamp input to [0, 100]
          2. If inverted: apply inversion (100 - conf)
          3. Apply per-bin correction factor
          4. Clamp output to [0, 100]
          5. Append audit entry
          6. Return rich result dict

        Returns:
            {
              "calibrated_conf":   float,
              "correction_factor": float,
              "inverted":          bool,
              "bin":               str,
              "reason":            str,
            }
        """
        with self._lock:
            self._ensure_initialised()

            raw_conf = _clamp(float(raw_confidence), 0.0, 100.0)
            bin_label = _find_bin(raw_conf)
            correction = self._correction[bin_label]
            inverted   = self._inverted

            steps = []
            working = raw_conf

            # Step 1 — inversion
            if inverted:
                working = 100.0 - working
                steps.append(
                    f"inversion applied ({raw_conf:.1f}%→{working:.1f}%)"
                )

            # Step 2 — correction factor (applied to post-inversion value,
            # but bin is always derived from the original raw_conf)
            pre_correction = working
            working = _clamp(working * correction, 0.0, 100.0)
            if abs(correction - 1.0) > 0.005:
                direction = "over" if correction < 1.0 else "under"
                steps.append(
                    f"correction ×{correction:.3f} ({direction}-confidence; "
                    f"{pre_correction:.1f}%→{working:.1f}%)"
                )
                if correction < 1.0:
                    self._summary["over_confidence_events"] += 1
                else:
                    self._summary["under_confidence_events"] += 1

            calibrated_conf = round(working, 2)

            if not steps:
                reason = "no correction applied (factors at baseline)"
            else:
                reason = "; ".join(steps)

            self._summary["total_calibrated"] += 1

            entry = {
                "ts":               utc_now(),
                "raw_conf":         round(raw_conf, 2),
                "calibrated_conf":  calibrated_conf,
                "correction_factor": round(correction, 4),
                "inverted":         inverted,
                "bin":              bin_label,
                "reason":           reason,
            }
            self._audit.append(entry)

            return {
                "calibrated_conf":   calibrated_conf,
                "correction_factor": round(correction, 4),
                "inverted":          inverted,
                "bin":               bin_label,
                "reason":            reason,
            }

    def record_outcome(self, raw_confidence: float, was_correct: bool) -> None:
        """
        Record a resolved prediction outcome.

        Updates bin stats, re-evaluates inversion flag, recomputes correction
        factors, and persists state.
        """
        with self._lock:
            self._ensure_initialised()

            raw_conf  = _clamp(float(raw_confidence), 0.0, 100.0)
            bin_label = _find_bin(raw_conf)

            self._bins[bin_label]["total"]    += 1
            self._bins[bin_label]["conf_sum"] += raw_conf
            if was_correct:
                self._bins[bin_label]["correct"] += 1

            # Re-evaluate inversion and correction after every update
            self._check_inversion(reason="record_outcome")
            self._recompute_correction()
            self._save_state()

    def status(self) -> Dict:
        """Return full calibrator state."""
        with self._lock:
            self._ensure_initialised()

            bin_stats = {}
            for label in [b[0] for b in _BINS]:
                b   = self._bins[label]
                acc = self._bin_accuracy(label)
                mean_conf = self._bin_mean_conf(label)
                bin_stats[label] = {
                    "total":               b["total"],
                    "correct":             b["correct"],
                    "accuracy":            round(acc, 4) if acc is not None else None,
                    "mean_predicted_conf": round(mean_conf, 2) if mean_conf is not None else None,
                    "correction_factor":   round(self._correction[label], 4),
                }

            return {
                "bins":         bin_stats,
                "inverted":     self._inverted,
                "correction":   {l: round(v, 4) for l, v in self._correction.items()},
                "summary":      dict(self._summary),
                "last_20_audit": list(self._audit)[-20:],
            }

    def get_audit_log(self, limit: int = 50) -> List[Dict]:
        """Return last `limit` audit entries."""
        with self._lock:
            self._ensure_initialised()
            return list(self._audit)[-limit:]


# ── Module-level singleton ────────────────────────────────────────────────

_calibrator: Optional[ConfidenceCalibrator] = None
_calibrator_lock = threading.Lock()


def get_confidence_calibrator() -> ConfidenceCalibrator:
    global _calibrator
    with _calibrator_lock:
        if _calibrator is None:
            _calibrator = ConfidenceCalibrator()
    return _calibrator
