"""
training/feature_engineering.py
================================
72-feature engineering module for the Aviator LSTM classifier.

Feature groups (72 total)
--------------------------
Group A — Raw log-scaled windows (35)
  last_5_multipliers   [0–4]    log-scaled, padded
  last_10_multipliers  [5–14]   log-scaled, padded
  last_20_multipliers  [15–34]  log-scaled, padded

Group B — Moving averages (3)
  moving_average_5, moving_average_10, moving_average_20

Group C — Spread & shape (9)
  standard_deviation_5, standard_deviation_10, standard_deviation_20
  variance_20, max_20, min_20, median_20
  volatility  (CV = std / mean)
  range_20    (max − min)

Group D — Distributional moments (3)
  skewness, kurtosis, entropy

Group E — Category counts in last 10 rounds (5)
  very_low_count_10, low_count_10, medium_count_10,
  high_count_10, very_high_count_10

Group F — Category frequencies in full window (5)
  freq_very_low, freq_low, freq_medium, freq_high, freq_very_high

Group G — Streaks & gap indicators (6)
  streak_low, streak_high
  time_since_high      (rounds since last HIGH/VERY_HIGH)
  time_since_very_high (rounds since last VERY_HIGH)
  streak_medium        (consecutive MEDIUM at end)
  streak_very_low      (consecutive VERY_LOW at end)

Group H — Momentum & trend (6)
  momentum_5   (mean_5 / mean_20 — 1)
  momentum_10  (mean_10 / mean_20 — 1)
  ema_5, ema_10         exponential MAs
  slope_5               linear regression slope over last 5
  slope_10              linear regression slope over last 10

FEATURE_DIM = 35 + 3 + 9 + 3 + 5 + 5 + 6 + 6 = 72
"""

from __future__ import annotations

import csv
import math
import statistics
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ── Constants ─────────────────────────────────────────────────────────────

_THRESHOLDS = [1.50, 2.00, 5.00, 15.0]

CATEGORIES = ["VERY_LOW", "LOW", "MEDIUM", "HIGH", "VERY_HIGH"]

# Feature names in the exact order returned by compute_features()
FEATURE_NAMES: List[str] = (
    [f"last_5_mult_{i+1}"  for i in range(5)]   +  #  0– 4
    [f"last_10_mult_{i+1}" for i in range(10)]  +  #  5–14
    [f"last_20_mult_{i+1}" for i in range(20)]  +  # 15–34
    ["moving_average_5", "moving_average_10", "moving_average_20",  # 35–37
     "standard_deviation_5", "standard_deviation_10", "standard_deviation_20",  # 38–40
     "variance_20", "max_20", "min_20", "median_20",  # 41–44
     "volatility", "range_20",  # 45–46
     "skewness", "kurtosis", "entropy",  # 47–49
     "very_low_count_10", "low_count_10", "medium_count_10",  # 50–52
     "high_count_10", "very_high_count_10",  # 53–54
     "freq_very_low", "freq_low", "freq_medium",  # 55–57
     "freq_high", "freq_very_high",  # 58–59
     "streak_low", "streak_high",  # 60–61
     "time_since_high", "time_since_very_high",  # 62–63
     "streak_medium", "streak_very_low",  # 64–65
     "momentum_5", "momentum_10",  # 66–67
     "ema_5", "ema_10",  # 68–69
     "slope_5", "slope_10",  # 70–71
    ]
)

FEATURE_DIM = len(FEATURE_NAMES)   # 72
assert FEATURE_DIM == 72, f"Expected 72, got {FEATURE_DIM}"


# ── Low-level helpers ─────────────────────────────────────────────────────

def _log_scale(v: float) -> float:
    """Map multiplier → [0, 1] via log(v) / log(100)."""
    return math.log(min(max(float(v), 1.0), 100.0)) / math.log(100.0)


def _category(v: float) -> int:
    """0=VERY_LOW … 4=VERY_HIGH."""
    for i, t in enumerate(_THRESHOLDS):
        if v < t:
            return i
    return len(_THRESHOLDS)


def _norm(x: float, cap: float = 100.0) -> float:
    """Soft-cap normalisation to [0, 1]."""
    return min(abs(x) / cap, 1.0)


def _norm_signed(x: float, cap: float = 5.0) -> float:
    """Normalise signed value to [-1, 1]."""
    return max(-1.0, min(1.0, x / cap))


def _ema(values: List[float], period: int) -> float:
    """Exponential moving average — last value of the series."""
    if not values:
        return 0.0
    k   = 2.0 / (period + 1)
    ema = values[0]
    for v in values[1:]:
        ema = v * k + ema * (1 - k)
    return ema


def _linear_slope(values: List[float]) -> float:
    """Ordinary least squares slope over the values."""
    n = len(values)
    if n < 2:
        return 0.0
    xs  = list(range(n))
    xm  = (n - 1) / 2.0
    ym  = sum(values) / n
    num = sum((x - xm) * (y - ym) for x, y in zip(xs, values))
    den = sum((x - xm) ** 2 for x in xs)
    return num / den if den else 0.0


def _skewness(values: List[float], mean: float, std: float) -> float:
    """Pearson sample skewness."""
    n = len(values)
    if n < 3 or std == 0:
        return 0.0
    return sum(((v - mean) / std) ** 3 for v in values) * n / ((n - 1) * (n - 2))


def _kurtosis(values: List[float], mean: float, std: float) -> float:
    """Excess kurtosis (Fisher definition)."""
    n = len(values)
    if n < 4 or std == 0:
        return 0.0
    raw = sum(((v - mean) / std) ** 4 for v in values) / n
    return raw - 3.0


def _entropy(cats: List[int]) -> float:
    """Shannon entropy of category distribution (normalised 0-1)."""
    n   = len(cats)
    if n == 0:
        return 0.0
    max_entropy = math.log(len(CATEGORIES))
    if max_entropy == 0:
        return 0.0
    counts = [cats.count(i) for i in range(len(CATEGORIES))]
    ent    = -sum((c / n) * math.log(c / n + 1e-12) for c in counts if c > 0)
    return ent / max_entropy


def _streak_of(values: List[float], predicate) -> int:
    """Count consecutive values from the end satisfying predicate."""
    count = 0
    for v in reversed(values):
        if predicate(v):
            count += 1
        else:
            break
    return count


def _time_since(values: List[float], predicate) -> int:
    """
    Rounds since the most recent value satisfying predicate.
    Returns len(window) if predicate never matched.
    """
    for i, v in enumerate(reversed(values)):
        if predicate(v):
            return i
    return len(values)


# ── Main feature extractor ────────────────────────────────────────────────

def compute_features(window: List[float]) -> List[float]:
    """
    Compute the full 72-feature vector from a multiplier window.

    Parameters
    ----------
    window : list of raw multiplier floats, length >= 20 recommended.

    Returns
    -------
    List of 72 float values, all normalised to roughly [0, 1] or [-1, 1].
    """
    n = len(window)
    if n == 0:
        raise ValueError("window must not be empty")

    vals = [float(v) for v in window]

    # ── Sub-windows ───────────────────────────────────────────────────
    w5  = vals[-5:]  if n >= 5  else vals
    w10 = vals[-10:] if n >= 10 else vals
    w20 = vals[-20:] if n >= 20 else vals

    pad5  = _log_scale(vals[0])
    pad10 = _log_scale(vals[0])
    pad20 = _log_scale(vals[0])

    # ── Group A: raw log-scaled windows (35) ─────────────────────────
    scaled5  = [pad5]  * (5  - len(w5))  + [_log_scale(v) for v in w5]
    scaled10 = [pad10] * (10 - len(w10)) + [_log_scale(v) for v in w10]
    scaled20 = [pad20] * (20 - len(w20)) + [_log_scale(v) for v in w20]

    # ── Group B: moving averages (3) ─────────────────────────────────
    mean5  = statistics.mean(w5)
    mean10 = statistics.mean(w10)
    mean20 = statistics.mean(w20)

    # ── Group C: spread & shape (9) ──────────────────────────────────
    std5   = statistics.pstdev(w5)  if len(w5)  > 1 else 0.0
    std10  = statistics.pstdev(w10) if len(w10) > 1 else 0.0
    std20  = statistics.pstdev(w20) if len(w20) > 1 else 0.0
    var20  = std20 ** 2
    mx20   = max(w20)
    mn20   = min(w20)
    med20  = statistics.median(w20)
    vol    = std20 / mean20 if mean20 > 0 else 0.0
    rng20  = mx20 - mn20

    # ── Group D: distributional moments (3) ──────────────────────────
    skew  = _skewness(w20, mean20, std20)
    kurt  = _kurtosis(w20, mean20, std20)
    cats20 = [_category(v) for v in w20]
    ent   = _entropy(cats20)

    # ── Group E: category counts in last 10 (5) ──────────────────────
    cats10 = [_category(v) for v in w10]
    n10    = len(cats10)
    vl10   = cats10.count(0) / n10
    l10    = cats10.count(1) / n10
    m10    = cats10.count(2) / n10
    h10    = cats10.count(3) / n10
    vh10   = cats10.count(4) / n10

    # ── Group F: category frequencies in full window (5) ─────────────
    cats_all  = [_category(v) for v in vals]
    n_all     = len(cats_all)
    freq_vl   = cats_all.count(0) / n_all
    freq_l    = cats_all.count(1) / n_all
    freq_m    = cats_all.count(2) / n_all
    freq_h    = cats_all.count(3) / n_all
    freq_vh   = cats_all.count(4) / n_all

    # ── Group G: streaks & gap indicators (6) ────────────────────────
    streak_low     = _streak_of(vals, lambda v: v < 2.0)
    streak_high    = _streak_of(vals, lambda v: v >= 5.0)
    streak_medium  = _streak_of(vals, lambda v: 2.0 <= v < 5.0)
    streak_vl      = _streak_of(vals, lambda v: v < 1.5)
    time_since_h   = _time_since(vals, lambda v: v >= 5.0)
    time_since_vh  = _time_since(vals, lambda v: v >= 15.0)

    # ── Group H: momentum & trend (6) ────────────────────────────────
    mom5  = (mean5  / mean20 - 1.0) if mean20 > 0 else 0.0
    mom10 = (mean10 / mean20 - 1.0) if mean20 > 0 else 0.0
    ema5  = _ema(vals[-5:],  5)
    ema10 = _ema(vals[-10:], 10)
    slope5  = _linear_slope(vals[-5:])
    slope10 = _linear_slope(vals[-10:])

    # ── Normalise all non-log-scaled features ─────────────────────────
    # Cap values into sensible [0,1] or [-1,1] ranges.
    MAX_MULT   = 100.0
    MAX_STD    = 20.0
    MAX_VAR    = 400.0
    MAX_STREAK = 20.0
    MAX_TIME   = float(n)        # max possible "time since" is window length
    MAX_SLOPE  = 5.0

    features: List[float] = (
        # Group A (already [0,1])
        scaled5 + scaled10 + scaled20
        +
        # Group B
        [_norm(mean5, MAX_MULT), _norm(mean10, MAX_MULT), _norm(mean20, MAX_MULT)]
        +
        # Group C
        [
            _norm(std5,  MAX_STD),
            _norm(std10, MAX_STD),
            _norm(std20, MAX_STD),
            _norm(var20, MAX_VAR),
            _norm(mx20,  MAX_MULT),
            _norm(mn20,  MAX_MULT),
            _norm(med20, MAX_MULT),
            _norm(vol,   5.0),
            _norm(rng20, MAX_MULT),
        ]
        +
        # Group D — skewness/kurtosis are signed
        [
            _norm_signed(skew,  3.0),   # typical range ±3
            _norm_signed(kurt, 10.0),   # typical range ±10
            ent,                        # already [0,1]
        ]
        +
        # Group E (already [0,1] as fractions)
        [vl10, l10, m10, h10, vh10]
        +
        # Group F (already [0,1])
        [freq_vl, freq_l, freq_m, freq_h, freq_vh]
        +
        # Group G
        [
            _norm(streak_low,    MAX_STREAK),
            _norm(streak_high,   MAX_STREAK),
            _norm(time_since_h,  MAX_TIME),
            _norm(time_since_vh, MAX_TIME),
            _norm(streak_medium, MAX_STREAK),
            _norm(streak_vl,     MAX_STREAK),
        ]
        +
        # Group H — momentum is signed
        [
            _norm_signed(mom5,   1.0),
            _norm_signed(mom10,  1.0),
            _norm(ema5,  MAX_MULT),
            _norm(ema10, MAX_MULT),
            _norm_signed(slope5,  MAX_SLOPE),
            _norm_signed(slope10, MAX_SLOPE),
        ]
    )

    assert len(features) == FEATURE_DIM, \
        f"Expected {FEATURE_DIM} features, got {len(features)}"

    return features


def compute_features_named(window: List[float]) -> Dict[str, float]:
    """Return features as an ordered dict {name: value}."""
    return dict(zip(FEATURE_NAMES, compute_features(window)))


# ── Feature matrix builder ────────────────────────────────────────────────

def build_feature_matrix(
    multipliers: List[float],
    window_size: int = 20,
) -> Tuple[List[List[float]], List[int]]:
    """
    Slide a window over the full multiplier history and produce
    feature matrix X and label vector y.

    Returns
    -------
    X : list of 72-feature vectors  (len = len(multipliers) - window_size)
    y : list of int labels           (category of the *next* round)
    """
    X, y = [], []
    for i in range(window_size, len(multipliers)):
        window = multipliers[i - window_size: i]
        X.append(compute_features(window))
        y.append(_category(multipliers[i]))
    return X, y


# ── CSV export ────────────────────────────────────────────────────────────

def export_features_csv(
    multipliers: List[float],
    output_path: Optional[Path] = None,
    window_size: int = 20,
    include_label: bool = True,
) -> Path:
    """
    Build the feature matrix and save it to a CSV file.

    The CSV has one row per sample with columns:
        sample_index, <72 feature names>, [label, category]

    Parameters
    ----------
    multipliers  : raw multiplier history
    output_path  : destination file (default: data/features.csv)
    window_size  : sliding window size
    include_label: whether to append label + category name columns

    Returns
    -------
    Path to the written CSV file.
    """
    if output_path is None:
        output_path = Path(__file__).resolve().parent.parent.parent / "data" / "features.csv"

    output_path.parent.mkdir(parents=True, exist_ok=True)

    X, y = build_feature_matrix(multipliers, window_size=window_size)

    header = ["sample_index"] + FEATURE_NAMES
    if include_label:
        header += ["label", "category"]

    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        for i, (features, label) in enumerate(zip(X, y)):
            row = [i] + [round(v, 6) for v in features]
            if include_label:
                row += [label, CATEGORIES[label]]
            writer.writerow(row)

    import logging
    logging.getLogger(__name__).info(
        "Features exported: %d samples × %d features → %s",
        len(X), FEATURE_DIM, output_path,
    )
    return output_path


# ── TensorFlow dataset helper ─────────────────────────────────────────────

def make_tf_dataset(
    multipliers: List[float],
    window_size: int = 20,
    batch_size: int = 256,
    shuffle: bool = True,
    shuffle_buffer: int = 10_000,
):
    """
    Build a tf.data.Dataset ready for model.fit().

    Returns a batched, prefetched dataset of (features, labels) pairs.
    Requires TensorFlow to be installed.
    """
    try:
        import tensorflow as tf
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("TensorFlow is required for make_tf_dataset()") from exc

    X, y = build_feature_matrix(multipliers, window_size=window_size)
    X_np = np.array(X, dtype="float32")
    y_np = np.array(y, dtype="int64")

    ds = tf.data.Dataset.from_tensor_slices((X_np, y_np))
    if shuffle:
        ds = ds.shuffle(buffer_size=min(shuffle_buffer, len(X_np)), reshuffle_each_iteration=True)
    ds = ds.batch(batch_size).prefetch(tf.data.AUTOTUNE)
    return ds


# ── CLI entry point ───────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys, json, logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
    log = logging.getLogger(__name__)

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

    # Load data
    from round_logger import get_all_rounds
    from utils import load_round_history

    rounds = get_all_rounds()
    if len(rounds) < 25:
        rounds = load_round_history()
    multipliers = [r["multiplier"] for r in rounds]

    log.info("Loaded %d rounds", len(multipliers))
    log.info("FEATURE_DIM = %d", FEATURE_DIM)
    log.info("Features: %s", FEATURE_NAMES)

    # Show one sample
    if len(multipliers) >= 20:
        sample = compute_features_named(multipliers[-20:])
        log.info("\nSample feature vector (last 20 rounds):")
        for name, val in sample.items():
            log.info("  %-25s = %.6f", name, val)

    # Export CSV
    out = export_features_csv(multipliers)
    log.info("CSV saved to: %s", out)
    print(f"\nDone. {len(multipliers) - 20} samples exported to {out}")
