"""
prediction/calibration_engine.py
==================================
Weighted probability model with Bayesian updating, hit-rate optimizer,
and recalibration mode.

Components
----------
1. BayesianCategoryEstimator
   - Maintains Dirichlet priors per category, updated from real outcomes.
   - Computes posterior-weighted probabilities that blend model output
     with empirically observed category frequencies.

2. HitRateOptimizer
   - Every OPTIMIZER_WINDOW resolved predictions, evaluates accuracy per
     category and nudges boundary thresholds to maximise overall hit rate.
   - Boundaries are stored as (lo, hi) multiplier ranges for each category.

3. RecalibrationMode
   - If rolling hit rate over the last RECAL_WINDOW predictions drops
     below RECAL_THRESHOLD (45%), enters recalibration mode:
       * action overridden to SKIP on all predictions
       * collects RECAL_COLLECT data points
       * exits automatically once enough data is gathered

4. CalibrationEngine (main entry point)
   - Thread-safe singleton.
   - apply(prediction_result, resolved_decisions) → enriched result.
   - record_outcome(decision) → feeds Bayesian updater + recal mode.
   - status() → full state for the /calibration endpoint.
"""

from __future__ import annotations

import logging
import math
import threading
from collections import deque
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils import CATEGORIES, read_json, write_json, DECISIONS_PATH

log = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────

OPTIMIZER_WINDOW   = 50    # run boundary optimisation every N resolved predictions
RECAL_WINDOW       = 20    # rolling window for hit-rate check
RECAL_THRESHOLD    = 0.45  # hit rate floor before recalibration triggers
RECAL_COLLECT      = 20    # data points to collect before exiting recal mode
BAYES_PRIOR_WEIGHT = 5.0   # pseudo-count strength for Dirichlet prior (higher = slower update)

# Default category boundaries (multiplier ranges) — same as utils.py at start
_DEFAULT_BOUNDARIES: Dict[str, Tuple[float, float]] = {
    "VERY_LOW":  (1.00, 1.50),
    "LOW":       (1.50, 2.00),
    "MEDIUM":    (2.00, 5.00),
    "HIGH":      (5.00, 15.0),
    "VERY_HIGH": (15.0, 9999.0),
}

# Boundary adjustment step size (in multiplier units)
_BOUNDARY_STEP = 0.10
# Maximum drift from default per boundary
_BOUNDARY_MAX_DRIFT = 1.0


# ── Helpers ───────────────────────────────────────────────────────────────

def _boundaries_to_category(mult: float, boundaries: Dict[str, Tuple[float, float]]) -> str:
    """Classify a multiplier using the current (possibly adjusted) boundaries."""
    for cat in CATEGORIES:
        lo, hi = boundaries.get(cat, (0, 9999))
        if lo <= mult < hi:
            return cat
    return CATEGORIES[-1]


def _dirichlet_mean(counts: Dict[str, float]) -> Dict[str, float]:
    """Normalised posterior mean of a Dirichlet distribution."""
    total = sum(counts.values())
    if total <= 0:
        uniform = 1.0 / len(counts)
        return {c: uniform for c in counts}
    return {c: v / total for c, v in counts.items()}


# ── Bayesian Category Estimator ───────────────────────────────────────────

class BayesianCategoryEstimator:
    """
    Dirichlet-Multinomial model for category probability estimation.

    Prior: uniform Dirichlet with concentration BAYES_PRIOR_WEIGHT per category.
    Posterior: updated each time a resolved decision arrives.

    Usage:
        posterior = estimator.posterior_probs()   # Dict[cat, float] summing to 1
        blended   = estimator.blend(model_probs)  # weighted mix
    """

    def __init__(self) -> None:
        # alpha_i = prior + observed counts
        self._alpha: Dict[str, float] = {c: BAYES_PRIOR_WEIGHT for c in CATEGORIES}
        self._n_updates = 0

    def update(self, actual_category: str) -> None:
        """Increment the count for the observed category (Bayesian update)."""
        if actual_category in self._alpha:
            self._alpha[actual_category] += 1.0
            self._n_updates += 1

    def posterior_probs(self) -> Dict[str, float]:
        """Posterior mean probabilities (sum to 1.0)."""
        return _dirichlet_mean(self._alpha)

    def blend(self, model_probs: Dict[str, float], weight: float = 0.35) -> Dict[str, float]:
        """
        Blend posterior with model probabilities.

        weight: fraction attributed to the Bayesian posterior (0-1).
                Remainder goes to the model's raw probabilities.
        """
        posterior = self.posterior_probs()
        blended = {}
        for cat in CATEGORIES:
            m = model_probs.get(cat, 0.0) / 100.0   # model gives percentages
            p = posterior.get(cat, 0.0)
            blended[cat] = (1.0 - weight) * m + weight * p

        # Renormalise and convert back to percentages
        total = sum(blended.values())
        if total <= 0:
            return {c: round(100.0 / len(CATEGORIES), 2) for c in CATEGORIES}
        result = {c: round(blended[c] / total * 100, 2) for c in CATEGORIES}

        # Fix rounding error
        diff = round(100.0 - sum(result.values()), 2)
        top  = max(result, key=result.get)
        result[top] = round(result[top] + diff, 2)
        return result

    def state(self) -> Dict:
        posterior = self.posterior_probs()
        return {
            "alpha":       {c: round(v, 3) for c, v in self._alpha.items()},
            "posterior":   {c: round(v, 4) for c, v in posterior.items()},
            "n_updates":   self._n_updates,
        }

    def load_state(self, state: Dict) -> None:
        if "alpha" in state:
            for c in CATEGORIES:
                if c in state["alpha"]:
                    self._alpha[c] = float(state["alpha"][c])
        self._n_updates = state.get("n_updates", 0)


# ── Hit Rate Optimizer ────────────────────────────────────────────────────

class HitRateOptimizer:
    """
    Automatically adjusts category boundaries to maximise hit rate.

    Every OPTIMIZER_WINDOW resolved predictions it:
      1. Evaluates hit rate per category.
      2. For each boundary (shared edge between two adjacent categories):
         - If the lower category has lower accuracy, shifts the boundary
           slightly up (shrinking the lower category's range, pushing
           borderline cases into the next category up).
         - Capped at _BOUNDARY_MAX_DRIFT from the default.
      3. Saves the adjusted boundaries for future classification.
    """

    def __init__(self) -> None:
        self._boundaries: Dict[str, Tuple[float, float]] = dict(_DEFAULT_BOUNDARIES)
        self._resolved_since_last: int = 0
        self._optimisation_count:  int = 0
        self._last_adjustments:    List[str] = []

    def current_boundaries(self) -> Dict[str, Tuple[float, float]]:
        return dict(self._boundaries)

    def classify(self, multiplier: float) -> str:
        return _boundaries_to_category(multiplier, self._boundaries)

    def record_and_maybe_optimise(
        self,
        resolved_window: List[Dict],
    ) -> bool:
        """
        Increment counter and run optimisation if threshold reached.
        Returns True if optimisation ran this call.
        """
        self._resolved_since_last += 1
        if self._resolved_since_last < OPTIMIZER_WINDOW:
            return False

        self._resolved_since_last = 0
        self._run_optimisation(resolved_window)
        return True

    def _run_optimisation(self, resolved: List[Dict]) -> None:
        """
        Core boundary adjustment algorithm.
        Evaluates accuracy per category and nudges boundaries.
        """
        if len(resolved) < OPTIMIZER_WINDOW:
            return

        # Count correct / total per category (using current boundaries)
        cat_correct: Dict[str, int] = {c: 0 for c in CATEGORIES}
        cat_total:   Dict[str, int] = {c: 0 for c in CATEGORIES}

        for d in resolved[-OPTIMIZER_WINDOW:]:
            pred   = d.get("prediction")
            actual = d.get("actual_multiplier")
            if pred not in CATEGORIES or actual is None:
                continue
            actual_cat = self.classify(float(actual))
            cat_total[pred]   += 1
            if actual_cat == pred:
                cat_correct[pred] += 1

        adjustments = []
        # Ordered boundary edges: [VL|L, L|M, M|H, H|VH]
        boundary_edges = [
            ("VERY_LOW", "LOW"),
            ("LOW",      "MEDIUM"),
            ("MEDIUM",   "HIGH"),
            ("HIGH",     "VERY_HIGH"),
        ]

        for lower_cat, upper_cat in boundary_edges:
            lo_acc = (cat_correct[lower_cat] / cat_total[lower_cat]
                      if cat_total[lower_cat] > 0 else 0.5)
            up_acc = (cat_correct[upper_cat] / cat_total[upper_cat]
                      if cat_total[upper_cat] > 0 else 0.5)

            current_edge  = self._boundaries[lower_cat][1]  # == upper_cat[0]
            default_edge  = _DEFAULT_BOUNDARIES[lower_cat][1]
            max_edge      = default_edge + _BOUNDARY_MAX_DRIFT
            min_edge      = default_edge - _BOUNDARY_MAX_DRIFT

            if lo_acc < up_acc - 0.10 and current_edge < max_edge:
                # Lower category is less accurate — raise the boundary
                new_edge = round(min(max_edge, current_edge + _BOUNDARY_STEP), 2)
                direction = "↑"
            elif up_acc < lo_acc - 0.10 and current_edge > min_edge:
                # Upper category is less accurate — lower the boundary
                new_edge = round(max(min_edge, current_edge - _BOUNDARY_STEP), 2)
                direction = "↓"
            else:
                continue  # no adjustment needed

            # Apply the boundary change
            lo_lo, _ = self._boundaries[lower_cat]
            _, up_hi  = self._boundaries[upper_cat]
            self._boundaries[lower_cat] = (lo_lo,    new_edge)
            self._boundaries[upper_cat] = (new_edge, up_hi)
            adjustments.append(
                f"{lower_cat}|{upper_cat}: {current_edge}→{new_edge} {direction} "
                f"(acc {lo_acc:.2f} vs {up_acc:.2f})"
            )

        self._optimisation_count += 1
        self._last_adjustments = adjustments
        if adjustments:
            log.info("HitRateOptimizer: %d adjustments — %s", len(adjustments), adjustments)
        else:
            log.debug("HitRateOptimizer: no boundary changes needed")

    def state(self) -> Dict:
        return {
            "boundaries":           {c: list(v) for c, v in self._boundaries.items()},
            "default_boundaries":   {c: list(v) for c, v in _DEFAULT_BOUNDARIES.items()},
            "resolved_since_last":  self._resolved_since_last,
            "optimisation_count":   self._optimisation_count,
            "last_adjustments":     self._last_adjustments,
        }

    def load_state(self, state: Dict) -> None:
        if "boundaries" in state:
            for c in CATEGORIES:
                if c in state["boundaries"]:
                    v = state["boundaries"][c]
                    self._boundaries[c] = (float(v[0]), float(v[1]))
        self._resolved_since_last = state.get("resolved_since_last", 0)
        self._optimisation_count  = state.get("optimisation_count", 0)
        self._last_adjustments    = state.get("last_adjustments", [])


# ── Recalibration Mode ────────────────────────────────────────────────────

class RecalibrationMode:
    """
    Monitors rolling hit rate and triggers a betting pause when it
    drops below RECAL_THRESHOLD (45%).

    While active:
      - All action recommendations are overridden to SKIP.
      - Each incoming resolved decision counts toward RECAL_COLLECT.
      - After RECAL_COLLECT data points, mode deactivates automatically.
    """

    def __init__(self) -> None:
        self._active:          bool  = False
        self._collected:       int   = 0
        self._trigger_hit_rate: Optional[float] = None
        # Rolling window of correct/incorrect outcomes (booleans)
        self._outcomes: deque = deque(maxlen=RECAL_WINDOW)

    def record_outcome(self, was_correct: bool) -> None:
        self._outcomes.append(was_correct)
        if self._active:
            self._collected += 1
            if self._collected >= RECAL_COLLECT:
                self._active   = False
                self._collected = 0
                log.info(
                    "RecalibrationMode: collected %d data points — resuming normal operation",
                    RECAL_COLLECT,
                )
            return

        # Check whether we should enter recalibration
        if len(self._outcomes) >= RECAL_WINDOW:
            hit_rate = sum(self._outcomes) / len(self._outcomes)
            if hit_rate < RECAL_THRESHOLD:
                self._active           = True
                self._collected        = 0
                self._trigger_hit_rate = round(hit_rate, 4)
                log.warning(
                    "RecalibrationMode ACTIVATED: hit rate %.1f%% < %.0f%% — "
                    "pausing bets for %d data points",
                    hit_rate * 100, RECAL_THRESHOLD * 100, RECAL_COLLECT,
                )

    @property
    def active(self) -> bool:
        return self._active

    def current_hit_rate(self) -> Optional[float]:
        if not self._outcomes:
            return None
        return round(sum(self._outcomes) / len(self._outcomes), 4)

    def state(self) -> Dict:
        return {
            "active":             self._active,
            "collected":          self._collected,
            "collect_target":     RECAL_COLLECT,
            "remaining":          max(0, RECAL_COLLECT - self._collected) if self._active else 0,
            "trigger_hit_rate":   self._trigger_hit_rate,
            "current_hit_rate":   self.current_hit_rate(),
            "window_size":        len(self._outcomes),
        }

    def load_state(self, state: Dict) -> None:
        self._active            = bool(state.get("active", False))
        self._collected         = int(state.get("collected", 0))
        self._trigger_hit_rate  = state.get("trigger_hit_rate")


# ── Calibration Engine ────────────────────────────────────────────────────

_STATE_PATH = Path(__file__).resolve().parent.parent / "artifacts" / "calibration_state.json"


class CalibrationEngine:
    """
    Thread-safe singleton that wraps all calibration components.

    Call flow:
        1. apply(result)           — before returning a prediction to the client
        2. record_outcome(decision) — after backfill resolves a decision
    """

    def __init__(self) -> None:
        self._lock       = threading.Lock()
        self._bayes      = BayesianCategoryEstimator()
        self._optimizer  = HitRateOptimizer()
        self._recal      = RecalibrationMode()
        self._initialised = False

    # ── Persistence ───────────────────────────────────────────────────

    def _load_state(self) -> None:
        try:
            state = read_json(_STATE_PATH, {})
            if state:
                if "bayes" in state:
                    self._bayes.load_state(state["bayes"])
                if "optimizer" in state:
                    self._optimizer.load_state(state["optimizer"])
                if "recal" in state:
                    self._recal.load_state(state["recal"])
                log.debug("CalibrationEngine state loaded from disk")
        except Exception as exc:
            log.warning("CalibrationEngine: failed to load state: %s", exc)

    def _save_state(self) -> None:
        try:
            write_json(_STATE_PATH, {
                "bayes":     self._bayes.state(),
                "optimizer": self._optimizer.state(),
                "recal":     self._recal.state(),
            })
        except Exception as exc:
            log.warning("CalibrationEngine: failed to save state: %s", exc)

    def _ensure_initialised(self) -> None:
        if self._initialised:
            return
        self._load_state()
        # Bootstrap Bayesian prior from historical decisions if available
        try:
            decisions = read_json(DECISIONS_PATH, [])
            if isinstance(decisions, list):
                for d in decisions:
                    actual_mult = d.get("actual_multiplier")
                    if actual_mult is not None:
                        cat = self._optimizer.classify(float(actual_mult))
                        self._bayes.update(cat)
                log.debug(
                    "CalibrationEngine bootstrapped with %d resolved decisions",
                    sum(1 for d in decisions if d.get("actual_multiplier") is not None),
                )
        except Exception as exc:
            log.warning("CalibrationEngine bootstrap failed: %s", exc)
        self._initialised = True

    # ── Core API ──────────────────────────────────────────────────────

    def apply(self, prediction_result: Dict) -> Dict:
        """
        Enrich a prediction result with:
          - Bayesian-weighted probabilities
          - Recalibration mode override (if active)
          - Current boundary state
        """
        with self._lock:
            self._ensure_initialised()

            # ── Sanitize incoming probabilities — guard against NaN/Inf ──
            raw_probs = prediction_result.get("probabilities", {})
            import math as _math

            def _is_bad(v) -> bool:
                try:
                    return not _math.isfinite(float(v))
                except (TypeError, ValueError):
                    return True

            # If any probability is bad, fall back to uniform distribution
            if any(_is_bad(v) for v in raw_probs.values()) or not raw_probs:
                uniform = round(100.0 / len(CATEGORIES), 2)
                model_probs = {c: uniform for c in CATEGORIES}
                # Fix rounding so they sum to exactly 100
                model_probs[CATEGORIES[0]] = round(
                    100.0 - uniform * (len(CATEGORIES) - 1), 2
                )
            else:
                model_probs = {c: float(raw_probs.get(c, 0.0)) for c in CATEGORIES}

            bayes_weight = min(0.35, 0.05 + self._bayes._n_updates * 0.002)
            blended_probs = self._bayes.blend(model_probs, weight=bayes_weight)

            # Sanitize blended output too
            if any(_is_bad(v) for v in blended_probs.values()):
                blended_probs = model_probs

            # Re-derive prediction from blended probs
            blended_prediction = max(blended_probs, key=blended_probs.get)
            blended_confidence = round(blended_probs[blended_prediction], 2)

            recal_active  = self._recal.active
            recal_override = None
            if recal_active:
                recal_override = (
                    f"Recalibration mode active — collecting data point "
                    f"{self._recal._collected + 1}/{RECAL_COLLECT} "
                    f"(triggered at {self._recal._trigger_hit_rate*100:.1f}% hit rate)"
                )

            return {
                **prediction_result,
                # Overwrite probs and top prediction with Bayesian blend
                "probabilities":        blended_probs,
                "prediction":           blended_prediction,
                "confidence":           blended_confidence,
                "bayes_weight":         round(bayes_weight, 4),
                "raw_prediction":       prediction_result.get("prediction"),
                "raw_probabilities":    model_probs,  # sanitized
                # Recalibration state
                "recalibration_active": recal_active,
                "recalibration_reason": recal_override,
                # Current optimised boundaries
                "category_boundaries":  {
                    c: list(v) for c, v in self._optimizer.current_boundaries().items()
                },
            }

    def record_outcome(self, decision: Dict) -> None:
        """
        Feed a resolved decision back into all calibration components.
        Call this after actual_multiplier is known.
        """
        actual_mult = decision.get("actual_multiplier")
        was_correct = decision.get("correct")
        if actual_mult is None or was_correct is None:
            return

        with self._lock:
            self._ensure_initialised()

            actual_cat = self._optimizer.classify(float(actual_mult))
            self._bayes.update(actual_cat)
            self._recal.record_outcome(bool(was_correct))

            # Collect resolved decisions for the optimizer
            try:
                decisions = read_json(DECISIONS_PATH, [])
                if isinstance(decisions, list):
                    resolved = [d for d in decisions if d.get("actual_multiplier") is not None]
                    self._optimizer.record_and_maybe_optimise(resolved)
            except Exception:
                pass

            self._save_state()

    def status(self) -> Dict:
        with self._lock:
            self._ensure_initialised()
            return {
                "bayesian":     self._bayes.state(),
                "optimizer":    self._optimizer.state(),
                "recalibration": self._recal.state(),
            }

    def force_reset(self) -> None:
        """Reset all state (for testing / manual override)."""
        with self._lock:
            self._bayes     = BayesianCategoryEstimator()
            self._optimizer = HitRateOptimizer()
            self._recal     = RecalibrationMode()
            self._save_state()
            log.info("CalibrationEngine: full state reset")


# ── Module-level singleton ────────────────────────────────────────────────

_engine: Optional[CalibrationEngine] = None
_engine_lock = threading.Lock()


def get_calibration_engine() -> CalibrationEngine:
    global _engine
    with _engine_lock:
        if _engine is None:
            _engine = CalibrationEngine()
    return _engine
