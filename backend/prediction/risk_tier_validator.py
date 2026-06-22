"""
prediction/risk_tier_validator.py
===================================
Risk-tier validation system for MEDIUM risk recommendations.

Before approving a MEDIUM risk label the system checks three gates:

Gate 1 — Historical Accuracy
    MEDIUM predictions in the current regime must have >= 35% accuracy
    over the last 30 resolved decisions.  Below that threshold the tier
    is locked to LOW and a recalibration is triggered.

Gate 2 — Multiplier Spread
    The spread between the recommended cashout and the rolling average
    actual multiplier for recent MEDIUM predictions must be < 0.5×.
    Wide spread = the cashout target is miscalibrated.

Gate 3 — Risk Confidence Score
    Combined score = 0.6 × prediction_confidence/100 + 0.4 × historical_accuracy
    Must be >= 0.40 to approve MEDIUM risk.

Recalibration Algorithm
    When MEDIUM accuracy < 35% the validator enters MEDIUM-locked mode
    (forces LOW risk for all MEDIUM predictions) and triggers a parameter
    recalculation based on recent actual volatility:
      - Recomputes cashout base/top from recent MEDIUM actual multipliers
      - Adjusts the minimum confidence threshold for MEDIUM
    The new parameters are applied until accuracy recovers above 45%.

Thread-safe singleton exposed via get_risk_tier_validator().
"""

from __future__ import annotations

import logging
import math
import statistics
import threading
from collections import deque
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils import read_json, write_json, DECISIONS_PATH, ARTIFACT_DIR

log = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────

MEDIUM_WINDOW            = 30      # decisions window for MEDIUM accuracy check
MEDIUM_ACCURACY_FLOOR    = 0.35    # below this → lock MEDIUM to LOW
MEDIUM_ACCURACY_RECOVER  = 0.45    # above this → unlock MEDIUM
SPREAD_MAX               = 0.50    # max allowed spread (cashout vs actual mean)
RISK_CONF_MIN            = 0.40    # minimum risk confidence score

# Spread window: how many recent MEDIUM resolved decisions to average
SPREAD_WINDOW            = 15

# Default MEDIUM cashout parameters (mirror utils.py)
_DEFAULT_MEDIUM_BASE     = 1.70
_DEFAULT_MEDIUM_TOP      = 2.80
_DEFAULT_MEDIUM_MIN_CONF = 26.0    # minimum model confidence to bet MEDIUM

# Persistence
_STATE_PATH = ARTIFACT_DIR / "risk_tier_state.json"


# ── Helpers ───────────────────────────────────────────────────────────────

def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _medium_cashout(confidence: float, base: float, top: float) -> float:
    conf = _clamp(confidence, 0.0, 100.0) / 100.0
    return round(base + (top - base) * conf, 2)


# ── RiskTierValidator ────────────────────────────────────────────────────

class RiskTierValidator:
    """
    Thread-safe singleton that validates MEDIUM risk recommendations
    and recalibrates parameters when accuracy drops too low.
    """

    def __init__(self) -> None:
        self._lock             = threading.Lock()
        self._initialised      = False

        # Rolling windows (MEDIUM resolved decisions only)
        self._outcomes: deque  = deque(maxlen=MEDIUM_WINDOW)
        # Each entry: {"actual_mult": float, "cashout": float, "correct": bool}
        self._spread_data: deque = deque(maxlen=SPREAD_WINDOW)

        # Lock state
        self._locked           = False   # True when MEDIUM is forced to LOW

        # Recalibrated parameters
        self._medium_base      = _DEFAULT_MEDIUM_BASE
        self._medium_top       = _DEFAULT_MEDIUM_TOP
        self._medium_min_conf  = _DEFAULT_MEDIUM_MIN_CONF

        # Recalibration counter
        self._recal_count      = 0
        self._last_recal_accuracy: Optional[float] = None

    # ── Persistence ───────────────────────────────────────────────────

    def _ensure_initialised(self) -> None:
        if self._initialised:
            return
        self._load_state()
        self._bootstrap()
        self._initialised = True

    def _load_state(self) -> None:
        try:
            state = read_json(_STATE_PATH, {})
            if not state:
                return
            self._locked          = bool(state.get("locked", False))
            self._medium_base     = float(state.get("medium_base",     _DEFAULT_MEDIUM_BASE))
            self._medium_top      = float(state.get("medium_top",      _DEFAULT_MEDIUM_TOP))
            self._medium_min_conf = float(state.get("medium_min_conf", _DEFAULT_MEDIUM_MIN_CONF))
            self._recal_count     = int(state.get("recal_count", 0))
            self._last_recal_accuracy = state.get("last_recal_accuracy")
            log.debug("RiskTierValidator: loaded state (locked=%s)", self._locked)
        except Exception as exc:
            log.warning("RiskTierValidator: load failed: %s", exc)

    def _save_state(self) -> None:
        try:
            write_json(_STATE_PATH, {
                "locked":              self._locked,
                "medium_base":         self._medium_base,
                "medium_top":          self._medium_top,
                "medium_min_conf":     self._medium_min_conf,
                "recal_count":         self._recal_count,
                "last_recal_accuracy": self._last_recal_accuracy,
            })
        except Exception as exc:
            log.warning("RiskTierValidator: save failed: %s", exc)

    def _bootstrap(self) -> None:
        """Replay historical MEDIUM decisions to warm up outcome windows."""
        try:
            decisions = read_json(DECISIONS_PATH, [])
            if not isinstance(decisions, list):
                return
            medium = [
                d for d in decisions
                if d.get("prediction") == "MEDIUM"
                and d.get("actual_multiplier") is not None
            ]
            for d in medium[-MEDIUM_WINDOW:]:
                self._outcomes.append(bool(d.get("correct", False)))
            for d in medium[-SPREAD_WINDOW:]:
                self._spread_data.append({
                    "actual_mult": float(d["actual_multiplier"]),
                    "cashout":     float(d.get("recommended_cashout", 2.0)),
                    "correct":     bool(d.get("correct", False)),
                })
            log.debug(
                "RiskTierValidator: bootstrapped %d MEDIUM outcomes", len(self._outcomes)
            )
        except Exception as exc:
            log.warning("RiskTierValidator: bootstrap failed: %s", exc)

    # ── Metric calculations ────────────────────────────────────────────

    def _accuracy(self) -> Optional[float]:
        if not self._outcomes:
            return None
        return sum(self._outcomes) / len(self._outcomes)

    def _spread(self) -> Optional[float]:
        """
        Mean absolute spread: avg |cashout - actual_mult| over recent MEDIUM rounds.
        Returns None if insufficient data.
        """
        if len(self._spread_data) < 3:
            return None
        diffs = [abs(e["cashout"] - e["actual_mult"]) for e in self._spread_data]
        return statistics.mean(diffs)

    def _risk_confidence_score(self, prediction_confidence: float) -> float:
        """
        Combined score = 0.6 × (conf/100) + 0.4 × historical_accuracy
        Falls back to conf-only when no history.
        """
        acc = self._accuracy()
        if acc is None:
            return prediction_confidence / 100.0
        return 0.6 * (prediction_confidence / 100.0) + 0.4 * acc

    # ── Recalibration ─────────────────────────────────────────────────

    def _recalibrate(self, multipliers: Optional[List[float]] = None) -> None:
        """
        Recompute MEDIUM cashout parameters from recent actual multipliers.

        Uses multipliers from spread_data (recent MEDIUM actuals) if no
        external list is provided.
        """
        if multipliers is None:
            actuals = [e["actual_mult"] for e in self._spread_data]
        else:
            actuals = [m for m in multipliers if 2.0 <= m < 5.0]  # MEDIUM range

        if len(actuals) < 5:
            log.info("RiskTierValidator: not enough actuals for recalibration (%d)", len(actuals))
            return

        mean_a  = statistics.mean(actuals)
        std_a   = statistics.pstdev(actuals)

        # Conservative base: mean - 1 std (lower bound of typical outcomes)
        new_base = _clamp(round(mean_a - std_a * 0.8, 2),  1.50, 2.50)
        # Conservative top: mean + 0.5 std
        new_top  = _clamp(round(mean_a + std_a * 0.5, 2),  new_base + 0.20, 4.00)

        # Tighten min confidence requirement proportionally to volatility
        cv = std_a / mean_a if mean_a > 0 else 0
        new_min_conf = _clamp(_DEFAULT_MEDIUM_MIN_CONF + cv * 10.0, 24.0, 40.0)

        self._medium_base     = new_base
        self._medium_top      = new_top
        self._medium_min_conf = new_min_conf
        self._recal_count    += 1
        self._last_recal_accuracy = self._accuracy()

        log.info(
            "RiskTierValidator: recalibrated MEDIUM params — "
            "base=%.2f top=%.2f min_conf=%.1f (n_actuals=%d, mean=%.2f, std=%.2f)",
            new_base, new_top, new_min_conf, len(actuals), mean_a, std_a,
        )
        self._save_state()

    def _check_lock_state(self) -> None:
        """Toggle locked/unlocked based on current accuracy."""
        acc = self._accuracy()
        if acc is None:
            return

        if not self._locked and acc < MEDIUM_ACCURACY_FLOOR:
            self._locked = True
            log.warning(
                "RiskTierValidator: MEDIUM accuracy %.1f%% < %.0f%% — "
                "locking MEDIUM to LOW and recalibrating",
                acc * 100, MEDIUM_ACCURACY_FLOOR * 100,
            )
            self._recalibrate()

        elif self._locked and acc >= MEDIUM_ACCURACY_RECOVER:
            self._locked = False
            log.info(
                "RiskTierValidator: MEDIUM accuracy %.1f%% >= %.0f%% — "
                "unlocking MEDIUM risk tier",
                acc * 100, MEDIUM_ACCURACY_RECOVER * 100,
            )
            self._save_state()

    # ── Core API ──────────────────────────────────────────────────────

    def validate(
        self,
        risk_label:            str,
        prediction_confidence: float,
        cashout:               float,
        regime:                str = "medium",
    ) -> Dict:
        """
        Validate a risk_label recommendation.

        Returns:
            {
              "risk_level":          final risk label (may be downgraded to "LOW"),
              "risk_confidence_score": float 0-1,
              "medium_locked":       bool,
              "downgrade_reason":    str | None,
              "gates": {
                  "accuracy":  {"pass": bool, "value": float|None},
                  "spread":    {"pass": bool, "value": float|None},
                  "rcs":       {"pass": bool, "value": float},
              },
              "medium_params": {
                  "base": float, "top": float, "min_conf": float
              },
            }
        """
        with self._lock:
            self._ensure_initialised()

            # Only intercept MEDIUM risk
            if risk_label != "MEDIUM":
                rcs = self._risk_confidence_score(prediction_confidence)
                return {
                    "risk_level":            risk_label,
                    "risk_confidence_score": round(rcs, 4),
                    "medium_locked":         self._locked,
                    "downgrade_reason":      None,
                    "gates": None,
                    "medium_params": {
                        "base":     self._medium_base,
                        "top":      self._medium_top,
                        "min_conf": self._medium_min_conf,
                    },
                }

            acc    = self._accuracy()
            spread = self._spread()
            rcs    = self._risk_confidence_score(prediction_confidence)

            # Gate results
            acc_pass    = (acc is None) or (acc >= MEDIUM_ACCURACY_FLOOR)
            spread_pass = (spread is None) or (spread < SPREAD_MAX)
            rcs_pass    = rcs >= RISK_CONF_MIN

            # Lock check (may have been set by a prior record_outcome call)
            locked = self._locked

            # Collect failure reasons
            reasons: List[str] = []

            if locked:
                reasons.append(
                    f"MEDIUM locked (accuracy {acc*100:.1f}% < "
                    f"{MEDIUM_ACCURACY_FLOOR*100:.0f}% floor)"
                    if acc is not None else "MEDIUM locked (recalibrating)"
                )
            if not acc_pass:
                reasons.append(
                    f"Gate 1 fail: MEDIUM accuracy {acc*100:.1f}% "
                    f"< {MEDIUM_ACCURACY_FLOOR*100:.0f}%"
                )
            if not spread_pass:
                reasons.append(
                    f"Gate 2 fail: multiplier spread {spread:.2f}× "
                    f">= {SPREAD_MAX}× limit"
                )
            if not rcs_pass:
                reasons.append(
                    f"Gate 3 fail: risk confidence score {rcs:.2f} "
                    f"< {RISK_CONF_MIN:.2f}"
                )

            approved = not locked and acc_pass and spread_pass and rcs_pass

            final_risk      = "MEDIUM" if approved else "LOW"
            downgrade_reason = "; ".join(reasons) if reasons else None

            return {
                "risk_level":            final_risk,
                "risk_confidence_score": round(rcs, 4),
                "medium_locked":         locked,
                "downgrade_reason":      downgrade_reason,
                "gates": {
                    "accuracy": {
                        "pass":   acc_pass,
                        "value":  round(acc, 4) if acc is not None else None,
                        "window": len(self._outcomes),
                    },
                    "spread": {
                        "pass":   spread_pass,
                        "value":  round(spread, 4) if spread is not None else None,
                        "window": len(self._spread_data),
                    },
                    "rcs": {
                        "pass":  rcs_pass,
                        "value": round(rcs, 4),
                    },
                },
                "medium_params": {
                    "base":     self._medium_base,
                    "top":      self._medium_top,
                    "min_conf": self._medium_min_conf,
                },
            }

    def record_outcome(
        self,
        prediction:       str,
        actual_multiplier: float,
        cashout:          float,
        was_correct:      bool,
    ) -> None:
        """
        Feed a resolved MEDIUM decision back into the validator.
        Updates outcome windows, checks lock state, persists.
        """
        if prediction != "MEDIUM":
            return
        with self._lock:
            self._ensure_initialised()
            self._outcomes.append(was_correct)
            self._spread_data.append({
                "actual_mult": float(actual_multiplier),
                "cashout":     float(cashout),
                "correct":     was_correct,
            })
            self._check_lock_state()

    def status(self) -> Dict:
        with self._lock:
            self._ensure_initialised()
            acc    = self._accuracy()
            spread = self._spread()
            return {
                "locked":              self._locked,
                "accuracy":            round(acc, 4)    if acc    is not None else None,
                "spread":              round(spread, 4) if spread is not None else None,
                "outcomes_tracked":    len(self._outcomes),
                "spread_tracked":      len(self._spread_data),
                "recal_count":         self._recal_count,
                "last_recal_accuracy": self._last_recal_accuracy,
                "medium_params": {
                    "base":     self._medium_base,
                    "top":      self._medium_top,
                    "min_conf": self._medium_min_conf,
                },
                "thresholds": {
                    "accuracy_floor":   MEDIUM_ACCURACY_FLOOR,
                    "accuracy_recover": MEDIUM_ACCURACY_RECOVER,
                    "spread_max":       SPREAD_MAX,
                    "rcs_min":          RISK_CONF_MIN,
                },
            }


# ── Module-level singleton ────────────────────────────────────────────────

_validator: Optional[RiskTierValidator] = None
_validator_lock = threading.Lock()


def get_risk_tier_validator() -> RiskTierValidator:
    global _validator
    with _validator_lock:
        if _validator is None:
            _validator = RiskTierValidator()
    return _validator
