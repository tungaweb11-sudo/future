"""
prediction/momentum_streak.py
================================
Replaces simple consecutive-count streak logic with a weighted momentum
system plus validity checks and a streak success matrix.

Components
----------

1. MomentumCalculator
   - Assigns exponentially decaying weights to the last N rounds.
   - Produces a per-category momentum score (0-1) and a dominant trend label:
       HOT  — multipliers trending strongly above average
       WARM — mild upward momentum
       NEUTRAL — no clear direction
       COOL — mild downward momentum
       COLD — multipliers trending strongly below average

2. StreakValidityChecker
   - Tracks per-(streak_label, regime) prediction outcomes.
   - If HOT streak is failing > 60% of the time over the last 10 decisions
     in that regime, automatically downgrades: HOT→WARM, COLD→NEUTRAL.
   - Upgrades back when failure rate drops below 40%.

3. StreakSuccessMatrix
   - Tracks accuracy per (streak_type, regime) pair.
   - Persists to artifacts/streak_matrix.json.
   - Exposed for the /streak-matrix API endpoint.

4. MomentumStreakEngine  (main entry point — thread-safe singleton)
   - analyse(multipliers, regime) → full momentum + streak + validity dict
   - record_outcome(streak_label, regime, was_correct) → updates matrix
   - status() → serialisable state for API

Public API
----------
    from prediction.momentum_streak import get_momentum_engine

    engine = get_momentum_engine()
    info   = engine.analyse(multipliers, regime)
    engine.record_outcome(info["effective_trend"], regime, was_correct)
"""

from __future__ import annotations

import math
import statistics
import threading
from collections import deque
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils import read_json, write_json, ARTIFACT_DIR

# ── Constants ─────────────────────────────────────────────────────────────

CATEGORIES = ["VERY_LOW", "LOW", "MEDIUM", "HIGH", "VERY_HIGH"]

# Momentum decay base — weight of round i from the end = DECAY^i
MOMENTUM_DECAY        = 0.80      # 80% of previous weight each step back

# Number of rounds to include in momentum window
MOMENTUM_WINDOW       = 20

# Trend thresholds (momentum score relative to neutral baseline 0.5)
HOT_THRESHOLD         = 0.65
WARM_THRESHOLD        = 0.55
COOL_THRESHOLD        = 0.45
COLD_THRESHOLD        = 0.35

# Validity check window (per streak+regime combination)
VALIDITY_WINDOW       = 10        # last N outcomes to evaluate
DOWNGRADE_FAIL_RATE   = 0.60      # fail rate above this → downgrade
UPGRADE_FAIL_RATE     = 0.40      # fail rate below this → restore

# Persistence
_MATRIX_PATH = ARTIFACT_DIR / "streak_matrix.json"

# Streak labels in order (for downgrade logic)
TREND_LABELS    = ["HOT", "WARM", "NEUTRAL", "COOL", "COLD"]
TREND_DOWNGRADE = {"HOT": "WARM", "COLD": "NEUTRAL"}   # only these get downgraded
TREND_UPGRADE   = {"WARM": "HOT", "NEUTRAL": "COLD"}   # restore path


# ── Category → numeric value mapping ─────────────────────────────────────

_CAT_VALUE = {
    "VERY_LOW":  1.25,
    "LOW":       1.75,
    "MEDIUM":    3.50,
    "HIGH":      10.0,
    "VERY_HIGH": 20.0,
}


def _cat(v: float) -> str:
    if v < 1.50: return "VERY_LOW"
    if v < 2.00: return "LOW"
    if v < 5.00: return "MEDIUM"
    if v < 15.0: return "HIGH"
    return "VERY_HIGH"


# ── MomentumCalculator ────────────────────────────────────────────────────

class MomentumCalculator:
    """
    Computes exponentially weighted momentum from recent multipliers.

    The score is normalised to [0, 1]:
      0.5  = neutral (matches historical mean)
      >0.5 = recent rounds higher than average (HOT direction)
      <0.5 = recent rounds lower than average (COLD direction)
    """

    def compute(self, multipliers: List[float]) -> Dict:
        n = min(MOMENTUM_WINDOW, len(multipliers))
        if n < 3:
            return self._neutral_result()

        window = multipliers[-n:]
        # Exponential weights: most recent = highest weight
        weights = [MOMENTUM_DECAY ** i for i in range(n - 1, -1, -1)]
        w_total = sum(weights)

        w_mean = sum(w * v for w, v in zip(weights, window)) / w_total
        overall_mean = statistics.mean(multipliers)

        if overall_mean <= 0:
            return self._neutral_result()

        # Normalise: ratio of weighted recent mean to overall mean
        ratio = w_mean / overall_mean

        # Map ratio to a 0-1 momentum score via sigmoid-like clamp
        # ratio=1.0 → score=0.5; ratio=1.5 → ~0.75; ratio=0.67 → ~0.25
        score = 0.5 + (ratio - 1.0) * 0.5
        score = max(0.0, min(1.0, score))

        # Per-category momentum scores (weighted frequency)
        cat_weights: Dict[str, float] = {c: 0.0 for c in CATEGORIES}
        for w, v in zip(weights, window):
            cat_weights[_cat(v)] += w
        cat_scores = {c: round(cat_weights[c] / w_total, 4) for c in CATEGORIES}

        # Trend label
        if score >= HOT_THRESHOLD:
            trend = "HOT"
        elif score >= WARM_THRESHOLD:
            trend = "WARM"
        elif score <= COLD_THRESHOLD:
            trend = "COLD"
        elif score <= COOL_THRESHOLD:
            trend = "COOL"
        else:
            trend = "NEUTRAL"

        # Magnitude: how strong is the momentum (0-1)
        magnitude = abs(score - 0.5) * 2.0

        # Category-level momentum (which category dominates recent rounds)
        dominant_cat = max(cat_scores, key=cat_scores.get)

        return {
            "momentum_score":   round(score, 4),
            "trend":            trend,
            "magnitude":        round(magnitude, 4),
            "weighted_mean":    round(w_mean, 4),
            "overall_mean":     round(overall_mean, 4),
            "category_scores":  cat_scores,
            "dominant_category": dominant_cat,
            "window_size":      n,
        }

    @staticmethod
    def _neutral_result() -> Dict:
        return {
            "momentum_score":    0.5,
            "trend":             "NEUTRAL",
            "magnitude":         0.0,
            "weighted_mean":     0.0,
            "overall_mean":      0.0,
            "category_scores":   {c: 0.0 for c in CATEGORIES},
            "dominant_category": "MEDIUM",
            "window_size":       0,
        }


# ── StreakSuccessMatrix ───────────────────────────────────────────────────

class StreakSuccessMatrix:
    """
    Tracks prediction accuracy per (streak_label, regime) pair.

    Matrix cell: {"total": int, "correct": int}

    Supports the /streak-matrix API endpoint and the validity checker.
    """

    def __init__(self) -> None:
        # matrix[(trend, regime)] = {"total": 0, "correct": 0}
        self._matrix: Dict[Tuple[str, str], Dict[str, int]] = {}
        self._loaded = False

    def _key(self, trend: str, regime: str) -> Tuple[str, str]:
        return (trend, regime)

    def record(self, trend: str, regime: str, was_correct: bool) -> None:
        key = self._key(trend, regime)
        if key not in self._matrix:
            self._matrix[key] = {"total": 0, "correct": 0}
        self._matrix[key]["total"] += 1
        if was_correct:
            self._matrix[key]["correct"] += 1

    def accuracy(self, trend: str, regime: str) -> Optional[float]:
        cell = self._matrix.get(self._key(trend, regime))
        if not cell or cell["total"] == 0:
            return None
        return cell["correct"] / cell["total"]

    def to_dict(self) -> Dict:
        result = {}
        for (trend, regime), cell in self._matrix.items():
            if trend not in result:
                result[trend] = {}
            acc = cell["correct"] / cell["total"] if cell["total"] else None
            result[trend][regime] = {
                "total":    cell["total"],
                "correct":  cell["correct"],
                "accuracy": round(acc, 4) if acc is not None else None,
            }
        return result

    def load(self, data: Dict) -> None:
        for trend, regimes in data.items():
            for regime, cell in regimes.items():
                key = (trend, regime)
                self._matrix[key] = {
                    "total":   int(cell.get("total", 0)),
                    "correct": int(cell.get("correct", 0)),
                }


# ── StreakValidityChecker ─────────────────────────────────────────────────

class StreakValidityChecker:
    """
    Monitors per-(trend, regime) failure rates using a rolling window.
    Downgrades HOT→WARM or COLD→NEUTRAL when failure rate > 60%.
    Restores when failure rate drops below 40%.
    """

    def __init__(self) -> None:
        # rolling windows: (trend, regime) → deque of booleans (True=correct)
        self._windows: Dict[Tuple[str, str], deque] = {}
        # current effective trend overrides: (original_trend, regime) → effective_trend
        self._overrides: Dict[Tuple[str, str], str] = {}

    def _window(self, trend: str, regime: str) -> deque:
        key = (trend, regime)
        if key not in self._windows:
            self._windows[key] = deque(maxlen=VALIDITY_WINDOW)
        return self._windows[key]

    def record(self, trend: str, regime: str, was_correct: bool) -> None:
        self._window(trend, regime).append(was_correct)
        self._recheck(trend, regime)

    def _recheck(self, trend: str, regime: str) -> None:
        win = self._window(trend, regime)
        if len(win) < max(3, VALIDITY_WINDOW // 2):
            return  # not enough data

        fail_rate = sum(1 for x in win if not x) / len(win)
        key       = (trend, regime)
        current   = self._overrides.get(key, trend)

        if trend in TREND_DOWNGRADE and fail_rate > DOWNGRADE_FAIL_RATE:
            downgraded = TREND_DOWNGRADE[trend]
            if current != downgraded:
                self._overrides[key] = downgraded

        elif trend in TREND_UPGRADE:
            # Check if original had been downgraded and should be restored
            if current != trend and fail_rate < UPGRADE_FAIL_RATE:
                self._overrides.pop(key, None)

    def effective_trend(self, trend: str, regime: str) -> Tuple[str, Optional[str]]:
        """
        Returns (effective_trend, downgrade_reason | None).
        effective_trend may differ from trend if a downgrade is active.
        """
        key      = (trend, regime)
        override = self._overrides.get(key)
        if override and override != trend:
            win       = self._window(trend, regime)
            fail_rate = sum(1 for x in win if not x) / len(win) if win else 0
            reason    = (
                f"{trend} downgraded to {override}: "
                f"fail rate {fail_rate*100:.1f}% > {DOWNGRADE_FAIL_RATE*100:.0f}% "
                f"over last {len(win)} predictions in {regime} regime"
            )
            return override, reason
        return trend, None

    def state(self) -> Dict:
        out = {}
        for (trend, regime), win in self._windows.items():
            fail_rate = sum(1 for x in win if not x) / len(win) if win else None
            eff, _    = self.effective_trend(trend, regime)
            out[f"{trend}|{regime}"] = {
                "samples":        len(win),
                "fail_rate":      round(fail_rate, 4) if fail_rate is not None else None,
                "effective_trend": eff,
                "downgraded":     eff != trend,
            }
        return out


# ── Momentum adjustment map for the statistical predictor ────────────────

def momentum_to_category_adj(
    trend: str,
    magnitude: float,
    dominant_cat: str,
) -> Dict[str, float]:
    """
    Convert momentum info into a per-category probability adjustment dict.
    Returns multipliers (not deltas) — multiply into combined probs.

    Diminishing returns: adjustment magnitude scales with `magnitude`
    so a weak signal barely moves probabilities.
    """
    adj = {c: 1.0 for c in CATEGORIES}
    strength = 0.5 + magnitude * 0.5   # maps [0,1] → [0.5, 1.0]

    if trend == "HOT":
        # Favour higher categories, suppress lower
        adj["HIGH"]      = 1.0 + 0.12 * strength
        adj["VERY_HIGH"] = 1.0 + 0.08 * strength
        adj["MEDIUM"]    = 1.0 + 0.04 * strength
        adj["LOW"]       = 1.0 - 0.06 * strength
        adj["VERY_LOW"]  = 1.0 - 0.10 * strength
    elif trend == "WARM":
        adj["MEDIUM"]    = 1.0 + 0.08 * strength
        adj["HIGH"]      = 1.0 + 0.05 * strength
        adj["VERY_LOW"]  = 1.0 - 0.05 * strength
    elif trend == "COLD":
        adj["VERY_LOW"]  = 1.0 + 0.12 * strength
        adj["LOW"]       = 1.0 + 0.08 * strength
        adj["MEDIUM"]    = 1.0 - 0.06 * strength
        adj["HIGH"]      = 1.0 - 0.10 * strength
        adj["VERY_HIGH"] = 1.0 - 0.12 * strength
    elif trend == "COOL":
        adj["VERY_LOW"]  = 1.0 + 0.08 * strength
        adj["LOW"]       = 1.0 + 0.05 * strength
        adj["HIGH"]      = 1.0 - 0.05 * strength

    # Clamp to reasonable range — prevent runaway adjustments
    for c in adj:
        adj[c] = max(0.50, min(2.0, adj[c]))

    return adj


# ── MomentumStreakEngine ─────────────────────────────────────────────────

class MomentumStreakEngine:
    """
    Thread-safe singleton combining all momentum/streak components.
    """

    def __init__(self) -> None:
        self._lock      = threading.Lock()
        self._calc      = MomentumCalculator()
        self._matrix    = StreakSuccessMatrix()
        self._validity  = StreakValidityChecker()
        self._loaded    = False

    # ── Persistence ───────────────────────────────────────────────────

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        try:
            state = read_json(_MATRIX_PATH, {})
            if "matrix" in state:
                self._matrix.load(state["matrix"])
        except Exception:
            pass
        self._loaded = True

    def _save(self) -> None:
        try:
            write_json(_MATRIX_PATH, {"matrix": self._matrix.to_dict()})
        except Exception:
            pass

    # ── Core API ──────────────────────────────────────────────────────

    def analyse(self, multipliers: List[float], regime: str = "medium") -> Dict:
        """
        Compute full momentum + streak analysis for the current round sequence.

        Returns dict containing:
          momentum_score, trend, magnitude, effective_trend,
          downgrade_reason, category_adj, category_scores,
          dominant_category
        """
        with self._lock:
            self._ensure_loaded()

            momentum = self._calc.compute(multipliers)
            raw_trend = momentum["trend"]
            magnitude = momentum["magnitude"]
            dom_cat   = momentum["dominant_category"]

            # Apply validity check (may downgrade HOT/COLD)
            eff_trend, downgrade_reason = self._validity.effective_trend(raw_trend, regime)

            # Category adjustment multipliers with diminishing returns
            cat_adj = momentum_to_category_adj(eff_trend, magnitude, dom_cat)

            return {
                "momentum_score":    momentum["momentum_score"],
                "raw_trend":         raw_trend,
                "effective_trend":   eff_trend,
                "magnitude":         magnitude,
                "dominant_category": dom_cat,
                "category_scores":   momentum["category_scores"],
                "weighted_mean":     momentum["weighted_mean"],
                "overall_mean":      momentum["overall_mean"],
                "category_adj":      cat_adj,
                "downgrade_reason":  downgrade_reason,
                "window_size":       momentum["window_size"],
            }

    def record_outcome(
        self,
        trend: str,
        regime: str,
        was_correct: bool,
    ) -> None:
        """Feed a resolved prediction outcome back into the matrix + validity checker."""
        with self._lock:
            self._ensure_loaded()
            self._matrix.record(trend, regime, was_correct)
            self._validity.record(trend, regime, was_correct)
            self._save()

    def status(self) -> Dict:
        with self._lock:
            self._ensure_loaded()
            return {
                "matrix":   self._matrix.to_dict(),
                "validity": self._validity.state(),
            }


# ── Module-level singleton ────────────────────────────────────────────────

_engine: Optional[MomentumStreakEngine] = None
_engine_lock = threading.Lock()


def get_momentum_engine() -> MomentumStreakEngine:
    global _engine
    with _engine_lock:
        if _engine is None:
            _engine = MomentumStreakEngine()
    return _engine
