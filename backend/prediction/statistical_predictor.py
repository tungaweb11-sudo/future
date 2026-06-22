"""
prediction/statistical_predictor.py
=====================================
Pure-Python sequence predictor for Aviator crash games.
No TensorFlow required — uses only the standard library + numpy if available.

Architecture:
  1. SEQUENCE MEMORY (10 rounds) — learns patterns in recent 10-round windows
  2. RISK MANAGEMENT LAYER — maps raw prediction + regime → bet sizing/action
  3. CONFIDENCE CALIBRATION — realistic confidence that avoids false precision

The key insight: instead of always predicting from the full history distribution
(which locks on VERY_LOW), we learn which SEQUENCES of 10 rounds tend to be
followed by which outcome. This gives real sequential memory like an LSTM.

When TensorFlow is installed and model is trained, this falls back automatically
and the engine switches to "tensorflow_lstm_v2".
"""

from __future__ import annotations

import math
import statistics
from collections import Counter, defaultdict
from typing import Dict, List, Optional, Tuple

CATEGORIES  = ["VERY_LOW", "LOW", "MEDIUM", "HIGH", "VERY_HIGH"]
NUM_CLASSES = len(CATEGORIES)
SEQ_LEN     = 10   # sequence memory window (like LSTM hidden state)


# ── Category helpers ──────────────────────────────────────────────────────

def _cat(v: float) -> str:
    if v < 1.50: return "VERY_LOW"
    if v < 2.00: return "LOW"
    if v < 5.00: return "MEDIUM"
    if v < 15.0: return "HIGH"
    return "VERY_HIGH"


def _cat_short(v: float) -> str:
    return {"VERY_LOW":"VL","LOW":"L","MEDIUM":"M","HIGH":"H","VERY_HIGH":"VH"}.get(_cat(v), "?")


def _entropy(probs: Dict[str, float]) -> float:
    return -sum(p * math.log(p + 1e-12) for p in probs.values())


# ── Volatility regime ─────────────────────────────────────────────────────

def _vol_regime(window: List[float]) -> str:
    if len(window) < 5:
        return "medium"
    recent = window[-min(20, len(window)):]
    try:
        std = statistics.pstdev(recent)
        mn  = statistics.mean(recent)
        cv  = std / mn if mn > 0 else 0.0
    except statistics.StatisticsError:
        return "medium"
    if cv < 0.45:  return "low"
    if cv > 0.85:  return "high"
    return "medium"


# ── Volatility normaliser ─────────────────────────────────────────────────

def _volatility_stats(multipliers: List[float]) -> Dict[str, float]:
    """
    Compute std-dev over last 100 rounds plus a volatility adjustment factor.

    Returns:
        std          — population std-dev of last 100 rounds
        high_vol     — True if std > 3.0
        vaf          — volatility adjustment factor applied to confidence
                       1.0 = neutral; >1.0 = increase sensitivity (high vol)
    """
    window = multipliers[-100:] if len(multipliers) >= 100 else multipliers
    if len(window) < 5:
        return {"std": 0.0, "high_vol": False, "vaf": 1.0}
    std = statistics.pstdev(window)
    high_vol = std > 3.0
    # VAF: scales linearly from 1.0 at std=0 to 1.30 at std=6.0 (caps there)
    vaf = min(1.30, 1.0 + (std / 6.0) * 0.30) if high_vol else 1.0
    return {"std": round(std, 4), "high_vol": high_vol, "vaf": round(vaf, 4)}


# ── High-volatility prediction rules ─────────────────────────────────────

def _high_vol_probs(
    multipliers: List[float],
    base_probs: Dict[str, float],
) -> Dict[str, float]:
    """
    Separate probability adjustments for high-volatility market conditions
    (last multiplier > 5.0× OR std > 3.0).

    Strategy:
    - Increase probability mass on HIGH + VERY_HIGH (tails are fatter)
    - Widen confidence interval by redistributing from MEDIUM
    - If last 3 multipliers are all > 5.0×, additionally boost VERY_HIGH
    """
    # Check if last multiplier is extreme
    last_mult = multipliers[-1] if multipliers else 1.0
    extreme_last = last_mult > 5.0

    # Count recent extreme events (last 10 rounds)
    recent = multipliers[-10:] if len(multipliers) >= 10 else multipliers
    extreme_count = sum(1 for m in recent if m > 5.0)
    extreme_ratio = extreme_count / len(recent) if recent else 0.0

    adj = dict(base_probs)

    if extreme_last:
        # Last round was extreme — model the aftermath
        # After a big crash, very_low/low are more likely (regression to mean)
        adj["VERY_LOW"]  = adj.get("VERY_LOW",  0) * 1.15
        adj["LOW"]       = adj.get("LOW",        0) * 1.10
        adj["HIGH"]      = adj.get("HIGH",       0) * 1.08
        adj["VERY_HIGH"] = adj.get("VERY_HIGH",  0) * 0.85
        adj["MEDIUM"]    = adj.get("MEDIUM",     0) * 0.90
    else:
        # High-vol regime but last was not extreme — tails more likely next
        adj["HIGH"]      = adj.get("HIGH",       0) * 1.18
        adj["VERY_HIGH"] = adj.get("VERY_HIGH",  0) * 1.12
        adj["MEDIUM"]    = adj.get("MEDIUM",     0) * 0.92

    # If extreme events are frequent recently, boost HIGH further
    if extreme_ratio > 0.3:
        adj["HIGH"]      = adj.get("HIGH",      0) * (1.0 + extreme_ratio * 0.20)
        adj["VERY_HIGH"] = adj.get("VERY_HIGH", 0) * (1.0 + extreme_ratio * 0.15)

    # Re-normalise
    total = sum(adj.values())
    if total > 0:
        adj = {c: adj[c] / total for c in CATEGORIES}

    return adj


# ── Streak detector ───────────────────────────────────────────────────────

def _streak(cats: List[str]) -> Tuple[str, int]:
    if not cats:
        return ("VERY_LOW", 0)
    cur    = cats[-1]
    length = 0
    for c in reversed(cats):
        if c == cur:
            length += 1
        else:
            break
    return (cur, length)


def _recent_trend(multipliers: List[float]) -> str:
    if len(multipliers) < 30:
        return "neutral"
    m10 = statistics.mean(multipliers[-10:])
    m30 = statistics.mean(multipliers[-30:])
    if m10 > m30 * 1.3:  return "hot"
    if m10 < m30 * 0.75: return "cold"
    return "neutral"


# ── Risk management layer ─────────────────────────────────────────────────

# Maps (prediction_category, regime) → (min_confidence_to_bet, bet_fraction_base)
# Higher min_confidence for risky categories = fewer but higher-quality BETs
_RISK_TABLE: Dict[Tuple[str, str], Tuple[float, float]] = {
    # (category,  regime): (min_conf, bet_frac)
    ("VERY_LOW",  "low"):    (24.0, 0.06),
    ("VERY_LOW",  "medium"): (26.0, 0.05),
    ("VERY_LOW",  "high"):   (28.0, 0.04),
    ("LOW",       "low"):    (25.0, 0.07),
    ("LOW",       "medium"): (27.0, 0.06),
    ("LOW",       "high"):   (29.0, 0.05),
    ("MEDIUM",    "low"):    (26.0, 0.05),
    ("MEDIUM",    "medium"): (28.0, 0.05),
    ("MEDIUM",    "high"):   (30.0, 0.04),
    ("HIGH",      "low"):    (32.0, 0.03),
    ("HIGH",      "medium"): (34.0, 0.03),
    ("HIGH",      "high"):   (36.0, 0.02),
    ("VERY_HIGH", "low"):    (36.0, 0.02),
    ("VERY_HIGH", "medium"): (38.0, 0.02),
    ("VERY_HIGH", "high"):   (40.0, 0.01),
}


def get_risk_params(category: str, regime: str) -> Tuple[float, float]:
    return _RISK_TABLE.get((category, regime), (28.0, 0.04))


# ── Sequence memory model ─────────────────────────────────────────────────

class SequenceMemoryModel:
    """
    Learns which 10-round sequences tend to precede which outcomes.
    This is the pure-Python equivalent of an LSTM's sequential memory.

    For each unique 10-category sequence seen in training, records what
    category came next. At prediction time, finds the closest matching
    sequence and uses its outcome distribution.
    """

    def __init__(self, seq_len: int = SEQ_LEN) -> None:
        self.seq_len  = seq_len
        # seq_memory[(c1,c2,...,c10)] → Counter({next_cat: count})
        self.seq_memory: Dict[Tuple, Counter] = defaultdict(Counter)
        # Shorter sequences for fallback
        self.seq5_memory: Dict[Tuple, Counter] = defaultdict(Counter)
        self.seq3_memory: Dict[Tuple, Counter] = defaultdict(Counter)
        self._fitted  = False
        self._n_seqs  = 0

    def fit(self, multipliers: List[float]) -> None:
        cats = [_cat(v) for v in multipliers]
        n    = len(cats)
        if n < self.seq_len + 1:
            return

        for i in range(self.seq_len, n):
            seq10 = tuple(cats[i - self.seq_len : i])
            seq5  = seq10[-5:]
            seq3  = seq10[-3:]
            nxt   = cats[i]
            self.seq_memory[seq10][nxt]  += 1
            self.seq5_memory[seq5][nxt]  += 1
            self.seq3_memory[seq3][nxt]  += 1

        self._fitted = True
        self._n_seqs = n - self.seq_len

    def lookup(self, recent_cats: List[str]) -> Optional[Dict[str, float]]:
        """
        Look up the outcome distribution for the current sequence.
        Tries seq10 → seq5 → seq3, falling back to None if no match.
        """
        if len(recent_cats) >= self.seq_len:
            key10 = tuple(recent_cats[-self.seq_len:])
            if key10 in self.seq_memory and sum(self.seq_memory[key10].values()) >= 3:
                return self._normalise(self.seq_memory[key10])

        if len(recent_cats) >= 5:
            key5 = tuple(recent_cats[-5:])
            if key5 in self.seq5_memory and sum(self.seq5_memory[key5].values()) >= 3:
                return self._normalise(self.seq5_memory[key5])

        if len(recent_cats) >= 3:
            key3 = tuple(recent_cats[-3:])
            if key3 in self.seq3_memory and sum(self.seq3_memory[key3].values()) >= 3:
                return self._normalise(self.seq3_memory[key3])

        return None   # no match → caller uses regime model

    def _normalise(self, counter: Counter) -> Dict[str, float]:
        total = sum(counter.values())
        return {c: counter.get(c, 0) / total for c in CATEGORIES}


# ── Main predictor ────────────────────────────────────────────────────────

class StatisticalPredictor:
    """
    Multi-layer predictor:
      Layer 1: Sequence memory (10-round patterns)  — like LSTM
      Layer 2: Regime detection (volatility state)  — risk management
      Layer 3: Streak/momentum signals              — pattern completion
      Layer 4: Risk management table                — BET/SKIP thresholds
    """

    def __init__(self) -> None:
        self._seq_model   = SequenceMemoryModel(SEQ_LEN)
        self._base_counts: Dict[str, float] = {c: 1.0 for c in CATEGORIES}
        self._fitted      = False
        self._global_mean = 2.5
        self._total       = 0

    def fit(self, multipliers: List[float]) -> None:
        if len(multipliers) < SEQ_LEN + 5:
            return

        cats = [_cat(v) for v in multipliers]
        for c in cats:
            self._base_counts[c] += 1.0

        self._seq_model.fit(multipliers)
        self._fitted      = True
        self._global_mean = statistics.mean(multipliers)
        self._total       = len(multipliers)
        return self

    def predict(self, multipliers: List[float]) -> Dict:
        if not self._fitted:
            self.fit(multipliers)

        cats      = [_cat(v) for v in multipliers]
        regime    = _vol_regime(multipliers)

        # ── Volatility normaliser ──────────────────────────────────────
        vol_stats   = _volatility_stats(multipliers)
        high_vol    = vol_stats["high_vol"]
        vaf         = vol_stats["vaf"]    # volatility adjustment factor
        last_extreme = (multipliers[-1] if multipliers else 1.0) > 5.0

        # ── Momentum-based streak (replaces simple consecutive count) ──
        from prediction.momentum_streak import get_momentum_engine
        _meng    = get_momentum_engine()
        momentum = _meng.analyse(multipliers, regime)
        trend    = momentum["effective_trend"].lower()   # keep hot/warm/neutral/cool/cold
        # Keep legacy streak fields for compatibility (use dominant category + momentum window)
        streak_cat = momentum["dominant_category"]
        streak_len = momentum["window_size"]             # reflects momentum window size
        cat_adj_momentum = momentum["category_adj"]

        # ── Layer 1: sequence memory lookup ───────────────────────────
        seq_probs = self._seq_model.lookup(cats)
        seq_hit   = seq_probs is not None

        # ── Layer 2: regime base distribution ─────────────────────────
        # In low regime: LOW/MEDIUM more likely; high regime: anything
        regime_probs = {c: 1.0 / NUM_CLASSES for c in CATEGORIES}
        if regime == "low":
            regime_probs.update({"VERY_LOW": 0.16, "LOW": 0.25,
                                  "MEDIUM": 0.30, "HIGH": 0.18, "VERY_HIGH": 0.11})
        elif regime == "high":
            regime_probs.update({"VERY_LOW": 0.24, "LOW": 0.18,
                                  "MEDIUM": 0.22, "HIGH": 0.20, "VERY_HIGH": 0.16})
        else:  # medium
            regime_probs.update({"VERY_LOW": 0.20, "LOW": 0.19,
                                  "MEDIUM": 0.26, "HIGH": 0.21, "VERY_HIGH": 0.14})

        # ── Layer 3: momentum adjustment (replaces streak + trend) ────
        # cat_adj_momentum already applies diminishing returns, validity checks,
        # and covers both streak exhaustion and trend direction in one pass.
        # We use it directly instead of the old streak_adj * trend_adj product.
        streak_adj = cat_adj_momentum
        trend_adj  = {c: 1.0 for c in CATEGORIES}   # absorbed into momentum

        # ── Combine all layers ─────────────────────────────────────────
        if seq_hit:
            # Sequence match: heavily weight the sequence signal
            # W = 55% seq, 30% regime, 15% streak/trend
            combined = {}
            for c in CATEGORIES:
                combined[c] = (
                    0.55 * seq_probs[c] +
                    0.30 * regime_probs[c] +
                    0.15 * regime_probs[c] * streak_adj[c] * trend_adj[c]
                )
        else:
            # No sequence match: regime + streak/trend only
            # W = 60% regime, 40% streak/trend adjustments
            combined = {}
            for c in CATEGORIES:
                combined[c] = regime_probs[c] * streak_adj[c] * trend_adj[c]

        # ── Recent 5-round momentum nudge ──────────────────────────────
        recent5 = cats[-5:]
        freq5   = Counter(recent5)
        for c, cnt in freq5.items():
            combined[c] = combined.get(c, 0) * (1.0 + cnt * 0.025)

        # ── High-volatility probability adjustment ─────────────────────
        # When last multiplier > 5.0× OR std > 3.0, blend in separate rules
        if high_vol or last_extreme:
            total_pre = sum(combined.values())
            base_norm = {c: combined[c] / total_pre for c in CATEGORIES} if total_pre else {c: 1/NUM_CLASSES for c in CATEGORIES}
            hv_probs  = _high_vol_probs(multipliers, base_norm)
            # Blend 40% high-vol rules into combined probabilities
            hv_weight = 0.40 if last_extreme else 0.25
            for c in CATEGORIES:
                combined[c] = (1.0 - hv_weight) * combined[c] + hv_weight * hv_probs[c] * total_pre

        # ── Normalise ─────────────────────────────────────────────────
        total     = sum(combined.values())
        probs_raw = {c: combined[c] / total for c in CATEGORIES}

        # Round to percentages
        probs = {c: round(probs_raw[c] * 100, 2) for c in CATEGORIES}
        diff  = round(100.0 - sum(probs.values()), 2)
        top_c = max(probs, key=probs.get)
        probs[top_c] = round(probs[top_c] + diff, 2)

        prediction = max(probs, key=probs.get)

        # ── Confidence calibration ────────────────────────────────────
        raw_top   = probs[prediction]
        ent       = _entropy(probs_raw)
        max_ent   = math.log(NUM_CLASSES)
        certainty = 1.0 - (ent / max_ent)
        uniform   = 100.0 / NUM_CLASSES

        # Base confidence from how far top prob is above uniform
        base_conf = uniform + (raw_top - uniform) * (0.5 + 0.5 * certainty)

        # Boost from signal quality
        boost = 1.0
        if seq_hit:                           boost += 0.20
        if momentum["magnitude"] >= 0.6:      boost += 0.12
        elif momentum["magnitude"] >= 0.3:    boost += 0.04
        if regime != "medium":                boost += 0.06
        if momentum["effective_trend"] != "NEUTRAL": boost += 0.05

        confidence = round(min(68.0, base_conf * boost), 2)
        confidence = max(uniform, confidence)

        # ── Volatility adjustment factor ──────────────────────────────
        # VAF > 1.0 during high-vol: increases sensitivity (widens confidence)
        if high_vol and vaf > 1.0:
            confidence = round(min(68.0, confidence * vaf), 2)

        # ── 20% confidence buffer for extreme last multiplier (> 5.0×) ──
        # Predictions after an extreme event are inherently less certain —
        # reduce confidence by 20% to reflect higher uncertainty.
        if last_extreme:
            confidence = round(confidence * 0.80, 2)

        # ── Risk management ───────────────────────────────────────────
        min_conf, bet_frac_base = get_risk_params(prediction, regime)
        # Scale bet fraction by how much confidence exceeds the threshold
        if confidence >= min_conf:
            excess     = (confidence - min_conf) / max(100.0 - min_conf, 1.0)
            bet_frac   = round(bet_frac_base * (0.6 + 0.4 * excess), 4)
            rec_action = "BET"
        else:
            bet_frac   = 0.0
            rec_action = "SKIP"

        return {
            "probs":        probs,
            "prediction":   prediction,
            "confidence":   confidence,
            "regime":       regime,
            "streak":       {
                "category":          streak_cat,
                "length":            streak_len,
                "trend":             momentum["effective_trend"],
                "raw_trend":         momentum["raw_trend"],
                "momentum_score":    momentum["momentum_score"],
                "magnitude":         momentum["magnitude"],
                "downgrade_reason":  momentum["downgrade_reason"],
            },
            "trend":            momentum["effective_trend"].lower(),
            "entropy":          round(ent, 4),
            "certainty":        round(certainty, 4),
            "seq_hit":          seq_hit,
            "bet_fraction":     bet_frac,
            "action":           rec_action,
            # Volatility metadata
            "volatility_std":   vol_stats["std"],
            "high_volatility":  high_vol,
            "volatility_adj_factor": vaf,
            "last_extreme":     last_extreme,
        }


# ── module-level singleton ────────────────────────────────────────────────

_model:     Optional[StatisticalPredictor] = None
_fitted_on: int = 0


def get_statistical_predictor(multipliers: List[float]) -> StatisticalPredictor:
    global _model, _fitted_on
    if _model is None or len(multipliers) - _fitted_on >= 50:
        _model = StatisticalPredictor()
        _model.fit(multipliers)
        _fitted_on = len(multipliers)
    return _model
