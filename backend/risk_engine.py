import statistics
"""
Professional Aviator Risk Management Engine.

Calculates risk metrics from crash history:
  - Risk level (LOW / MEDIUM / HIGH)
  - Volatility score
  - Streak detection (consecutive patterns)
  - Moving averages (SMA, EMA)
  - Composite risk index
"""

import math
import risk_statistics
from typing import Any, Dict, List, Tuple


# ── Helpers ──────────────────────────────────────────────────────────

def _ema(data: List[float], period: int) -> float:
    """Exponential Moving Average – last value of the EMA series."""
    if not data:
        return 0.0
    k = 2.0 / (period + 1)
    ema = data[0]
    for price in data[1:]:
        ema = price * k + ema * (1 - k)
    return ema


def _sma(data: List[float], period: int) -> float:
    """Simple Moving Average over the last `period` values."""
    if not data or period == 0:
        return 0.0
    window = data[-period:]
    return sum(window) / len(window)


def _category(multiplier: float) -> str:
    if multiplier < 1.5:
        return "VERY_LOW"
    if multiplier < 2.0:
        return "LOW"
    if multiplier < 5.0:
        return "MEDIUM"
    if multiplier < 15.0:
        return "HIGH"
    return "VERY_HIGH"


# ── Public API ───────────────────────────────────────────────────────

def compute_volatility(multipliers: List[float]) -> Dict[str, float]:
    """
    Volatility metrics based on recent multipliers.

    Returns:
        raw_std: population standard deviation of the sample
        cv: coefficient of variation (std / mean) – scale-independent
        recent_std: standard deviation of the last 20 rounds
    """
    if len(multipliers) < 2:
        return {"raw_std": 0.0, "cv": 0.0, "recent_std": 0.0}

    mean = statistics.mean(multipliers)
    raw_std = statistics.stdev(multipliers) if len(multipliers) > 1 else 0.0
    cv = (raw_std / mean) if mean > 0 else 0.0

    recent = multipliers[-20:] if len(multipliers) >= 20 else multipliers
    recent_std = statistics.stdev(recent) if len(recent) > 1 else 0.0

    return {
        "raw_std": round(raw_std, 4),
        "cv": round(cv, 4),
        "recent_std": round(recent_std, 4),
    }


def detect_streaks(multipliers: List[float]) -> Dict[str, Any]:
    """
    Detect runs of consecutive same-category crashes.

    Returns:
        current_streak: {category, length, active}
        longest_streaks: {LOW: N, MEDIUM: N, HIGH: N}
        recent_streaks: list of streak objects for the last 100 rounds
    """
    if not multipliers:
        return {
            "current_streak": {"category": None, "length": 0, "active": False},
            "longest_streaks": {"VERY_LOW": 0, "LOW": 0, "MEDIUM": 0, "HIGH": 0, "VERY_HIGH": 0},
            "recent_streaks": [],
        }

    categories = [_category(m) for m in multipliers]

    # ── full-history streaks ──
    longest: Dict[str, int] = {"VERY_LOW": 0, "LOW": 0, "MEDIUM": 0, "HIGH": 0, "VERY_HIGH": 0}
    all_streaks: List[Dict[str, Any]] = []
    current_cat = categories[0]
    current_len = 1

    for cat in categories[1:]:
        if cat == current_cat:
            current_len += 1
        else:
            all_streaks.append({"category": current_cat, "length": current_len})
            longest[current_cat] = max(longest[current_cat], current_len)
            current_cat = cat
            current_len = 1
    all_streaks.append({"category": current_cat, "length": current_len})
    longest[current_cat] = max(longest[current_cat], current_len)

    # current active streak
    current_streak = {
        "category": current_cat,
        "length": current_len,
        "active": current_len >= 2,
    }

    # recent streaks (last 100 rounds)
    recent_categories = categories[-100:]
    recent_streaks: List[Dict[str, Any]] = []
    if recent_categories:
        rc = recent_categories[0]
        rl = 1
        for cat in recent_categories[1:]:
            if cat == rc:
                rl += 1
            else:
                recent_streaks.append({"category": rc, "length": rl})
                rc = cat
                rl = 1
        recent_streaks.append({"category": rc, "length": rl})

    return {
        "current_streak": current_streak,
        "longest_streaks": longest,
        "recent_streaks": recent_streaks[-20:],
    }


def compute_moving_averages(multipliers: List[float]) -> Dict[str, float]:
    """
    Short, medium, and long-term moving averages.

    Returns:
        sma_5:  simple MA over 5  rounds
        sma_10: simple MA over 10 rounds
        sma_20: simple MA over 20 rounds
        ema_12: exponential MA over 12 rounds
        ema_26: exponential MA over 26 rounds
    """
    return {
        "sma_5": round(_sma(multipliers, 5), 4),
        "sma_10": round(_sma(multipliers, 10), 4),
        "sma_20": round(_sma(multipliers, 20), 4),
        "ema_12": round(_ema(multipliers, 12), 4),
        "ema_26": round(_ema(multipliers, 26), 4),
    }


def compute_risk_index(
    multipliers: List[float],
) -> Dict[str, Any]:
    """
    Composite risk assessment.

    Factors weighted into a 0-100 score:
      - Volatility (30 %): higher CV = more risk
      - Streak (25 %): active streak of HIGH or long LOW streak
      - Moving-average trend (25 %): short-term vs long-term
      - Frequency of high crashes (20 %): proportion of HIGH outcomes

    Returns:
        risk_score: 0-100 numeric score
        risk_level: LOW / MEDIUM / HIGH
        factors: breakdown of each contributing factor
    """
    if len(multipliers) < 5:
        return {
            "risk_score": 0,
            "risk_level": "LOW",
            "factors": {},
        }

    volatility = compute_volatility(multipliers)
    streaks = detect_streaks(multipliers)
    mas = compute_moving_averages(multipliers)

    recent = multipliers[-50:] if len(multipliers) >= 50 else multipliers
    high_count = sum(1 for m in recent if _category(m) in ("HIGH", "VERY_HIGH"))
    high_ratio = high_count / len(recent)

    # ── factor scores (each 0-100) ──
    # 1. Volatility factor
    cv = volatility["cv"]
    volatility_factor = min(100, cv * 100)

    # 2. Streak factor
    cs = streaks["current_streak"]
    if cs["category"] in ("HIGH", "VERY_HIGH") and cs["active"]:
        streak_factor = min(100, 40 + cs["length"] * 10)
    elif cs["category"] in ("VERY_LOW", "LOW") and cs["length"] > 5:
        streak_factor = min(100, 30 + (cs["length"] - 5) * 8)
    elif cs["category"] == "MEDIUM" and cs["length"] > 4:
        streak_factor = min(100, 25 + (cs["length"] - 4) * 10)
    else:
        streak_factor = 10

    # 3. MA trend factor: if sma_5 > sma_20 * 1.15 → upward momentum (risk)
    sma_5 = mas["sma_5"]
    sma_20 = mas["sma_20"]
    if sma_20 > 0:
        trend_ratio = sma_5 / sma_20
        if trend_ratio > 1.2:
            trend_factor = 80
        elif trend_ratio > 1.1:
            trend_factor = 60
        elif trend_ratio > 1.0:
            trend_factor = 40
        elif trend_ratio < 0.85:
            trend_factor = 30
        else:
            trend_factor = 20
    else:
        trend_factor = 20

    # 4. High-crash frequency factor
    high_factor = high_ratio * 100

    # ── weighted composite ──
    risk_score = (
        volatility_factor * 0.30
        + streak_factor * 0.25
        + trend_factor * 0.25
        + high_factor * 0.20
    )
    risk_score = round(min(100, max(0, risk_score)), 1)

    if risk_score >= 65:
        risk_level = "HIGH"
    elif risk_score >= 35:
        risk_level = "MEDIUM"
    else:
        risk_level = "LOW"

    return {
        "risk_score": risk_score,
        "risk_level": risk_level,
        "factors": {
            "volatility_factor": round(volatility_factor, 1),
            "streak_factor": round(streak_factor, 1),
            "trend_factor": round(trend_factor, 1),
            "high_frequency_factor": round(high_factor, 1),
        },
        "volatility": volatility,
        "streaks": streaks,
        "moving_averages": mas,
        "high_ratio": round(high_ratio, 4),
    }


def compute_round_summary(rounds: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    High-level summary of the entire round history for dashboard display.
    """
    multipliers = [r["multiplier"] for r in rounds]

    total = len(multipliers)
    if total == 0:
        return {
            "total_rounds": 0,
            "avg_multiplier": 0,
            "max_multiplier": 0,
            "min_multiplier": 0,
            "category_counts": {"LOW": 0, "MEDIUM": 0, "HIGH": 0},
            "recent_trend": "stable",
        }

    cats = [_category(m) for m in multipliers]
    counts = {
        "VERY_LOW":  cats.count("VERY_LOW"),
        "LOW":       cats.count("LOW"),
        "MEDIUM":    cats.count("MEDIUM"),
        "HIGH":      cats.count("HIGH"),
        "VERY_HIGH": cats.count("VERY_HIGH"),
    }

    # Recent trend: compare last 10 vs previous 10
    if total >= 20:
        recent_10 = statistics.mean(multipliers[-10:])
        prior_10 = statistics.mean(multipliers[-20:-10])
    elif total >= 10:
        recent_10 = statistics.mean(multipliers[-10:])
        prior_10 = statistics.mean(multipliers[: max(1, total - 10)])
    else:
        recent_10 = statistics.mean(multipliers)
        prior_10 = statistics.mean(multipliers)

    diff = recent_10 - prior_10
    if diff > 0.5:
        trend = "increasing"
    elif diff < -0.5:
        trend = "decreasing"
    else:
        trend = "stable"

    return {
        "total_rounds": total,
        "avg_multiplier": round(statistics.mean(multipliers), 2),
        "max_multiplier": round(max(multipliers), 2),
        "min_multiplier": round(min(multipliers), 2),
        "category_counts": counts,
        "recent_trend": trend,
    }

