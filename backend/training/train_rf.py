"""
training/train_rf.py
=====================
RandomForest classifier for Aviator crash prediction.

Uses the same 72-feature engineering pipeline as the LSTM model.
Outputs per-class probabilities for:
    VERY_LOW | LOW | MEDIUM | HIGH | VERY_HIGH

Saved artefacts:
    models/rf_model.joblib   — trained RandomForestClassifier
    models/rf_scaler.pkl     — StandardScaler fitted on RF features
    logs/last_rf_training.json

Run directly:
    cd backend && python -m training.train_rf
"""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

log = logging.getLogger(__name__)

ROOT       = Path(__file__).resolve().parent.parent.parent
MODELS_DIR = ROOT / "models"
LOGS_DIR   = Path(__file__).resolve().parent.parent / "logs"
MODELS_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)

RF_MODEL_PATH  = MODELS_DIR / "rf_model.joblib"
RF_SCALER_PATH = MODELS_DIR / "rf_scaler.pkl"

CATEGORIES  = ["VERY_LOW", "LOW", "MEDIUM", "HIGH", "VERY_HIGH"]
NUM_CLASSES = len(CATEGORIES)
SEQ_LEN     = 20


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(LOGS_DIR / "training.log"),
        ],
    )


# ── Dataset preparation ───────────────────────────────────────────────────

def _load_data() -> Tuple[List, List]:
    """
    Load multipliers from all sources and build the flat 72-feature matrix.
    Returns (X, y) lists.
    """
    from training.dataset_loader import DatasetLoader
    from training.feature_engineering import build_feature_matrix

    loader = DatasetLoader()
    loader.load()
    multipliers = [r["multiplier"] for r in loader._rounds]

    if len(multipliers) < SEQ_LEN + 10:
        raise ValueError(f"Need at least {SEQ_LEN + 10} rounds, got {len(multipliers)}.")

    log.info("Building feature matrix for %d rounds…", len(multipliers))
    X, y = build_feature_matrix(multipliers, window_size=SEQ_LEN)
    log.info("Feature matrix: %d samples × %d features", len(X), len(X[0]) if X else 0)
    return X, y


def _oversample(
    X: List, y: List, min_ratio: float = 0.5
) -> Tuple[List, List]:
    """Duplicate minority classes to min_ratio × majority count."""
    from collections import Counter
    import random

    counts   = Counter(y)
    majority = max(counts.values())
    target   = int(majority * min_ratio)

    X_out, y_out = list(X), list(y)
    for cls_idx in range(NUM_CLASSES):
        current = counts.get(cls_idx, 0)
        needed  = max(0, target - current)
        if needed == 0:
            continue
        samples = [X[i] for i in range(len(y)) if y[i] == cls_idx]
        if not samples:
            continue
        cycle = samples * (needed // len(samples) + 1)
        X_out += cycle[:needed]
        y_out += [cls_idx] * needed
        log.info("Oversampled %-10s: %d → %d",
                 CATEGORIES[cls_idx], current, current + needed)

    # Shuffle
    combined = list(zip(X_out, y_out))
    random.shuffle(combined)
    X_out, y_out = zip(*combined)
    return list(X_out), list(y_out)


# ── Model building ────────────────────────────────────────────────────────

def build_rf_model(n_estimators: int = 300) -> "RandomForestClassifier":
    """
    Build a RandomForestClassifier configured for imbalanced multi-class
    prediction with probability output.

    Key settings:
      n_estimators=300   — enough trees for stable probability estimates
      max_depth=12        — prevents overfitting on a small dataset
      min_samples_leaf=5  — smooths probability estimates
      class_weight='balanced_subsample' — per-tree class balancing
      n_jobs=-1           — parallel on all cores
    """
    from sklearn.ensemble import RandomForestClassifier

    rf = RandomForestClassifier(
        n_estimators=300,
        max_depth=12,
        min_samples_split=10,
        min_samples_leaf=5,
        max_features="sqrt",       # sqrt(72) ≈ 8 features per split
        class_weight="balanced_subsample",
        random_state=42,
        n_jobs=-1,
        oob_score=True,            # out-of-bag accuracy estimate
        verbose=0,
    )
    return rf


# ── Training ──────────────────────────────────────────────────────────────

def train(
    n_estimators: int = 300,
    oversample: bool = True,
    val_split: float = 0.15,
) -> Dict:
    """
    Full RandomForest training pipeline.

    Steps:
      1. Load rounds via DatasetLoader
      2. Build 72-feature matrix
      3. Oversample minority classes
      4. StandardScaler fit+transform
      5. Train RandomForestClassifier
      6. Evaluate with per-class metrics + OOB score
      7. Save model + scaler with joblib

    Returns a metrics dict.
    """
    _setup_logging()

    import numpy as np
    import pickle
    import joblib
    from collections import Counter
    from sklearn.preprocessing import StandardScaler

    # ── 1. Load data ───────────────────────────────────────────────────
    X_raw, y_raw = _load_data()

    # ── 2. Oversample ──────────────────────────────────────────────────
    if oversample:
        X_raw, y_raw = _oversample(X_raw, y_raw)

    # ── 3. Train / val split ───────────────────────────────────────────
    n     = len(X_raw)
    split = max(1, int(n * (1 - val_split)))
    X_tr, X_v = X_raw[:split], X_raw[split:]
    y_tr, y_v = y_raw[:split], y_raw[split:]

    X_tr = np.array(X_tr, dtype="float32")
    X_v  = np.array(X_v,  dtype="float32")
    y_tr = np.array(y_tr, dtype="int64")
    y_v  = np.array(y_v,  dtype="int64")

    # ── 4. Scale ───────────────────────────────────────────────────────
    scaler  = StandardScaler()
    X_tr_s  = scaler.fit_transform(X_tr)
    X_v_s   = scaler.transform(X_v)

    with open(RF_SCALER_PATH, "wb") as fh:
        pickle.dump(scaler, fh)
    log.info("RF scaler saved → %s", RF_SCALER_PATH)

    # Distribution
    counts_raw = Counter(y_tr.tolist())
    counts     = {CATEGORIES[i]: counts_raw.get(i, 0) for i in range(NUM_CLASSES)}
    log.info("Train distribution: %s", counts)

    # ── 5. Train ────────────────────────────────────────────────────────
    log.info("Training RandomForest (n_estimators=%d)…", n_estimators)
    rf = build_rf_model(n_estimators=n_estimators)
    t0 = time.time()
    rf.fit(X_tr_s, y_tr)
    elapsed = round(time.time() - t0, 1)
    log.info("Training finished in %.1fs", elapsed)

    # ── 6. Evaluate ─────────────────────────────────────────────────────
    oob_acc = round(rf.oob_score_ * 100, 2) if hasattr(rf, "oob_score_") else None
    metrics = _evaluate(rf, X_v_s, y_v, counts)

    # Feature importances (top 15)
    importances = rf.feature_importances_
    from training.feature_engineering import FEATURE_NAMES
    top_idx  = importances.argsort()[::-1][:15]
    top_feats = {FEATURE_NAMES[i]: round(float(importances[i]), 4) for i in top_idx}
    log.info("Top 15 feature importances:")
    for name, imp in top_feats.items():
        bar = "█" * int(imp * 200)
        log.info("  %-25s %.4f  %s", name, imp, bar)

    metrics.update({
        "engine":          "random_forest",
        "n_estimators":    n_estimators,
        "training_time_s": elapsed,
        "oob_accuracy":    oob_acc,
        "samples":         int(len(X_tr_s)),
        "feature_importances_top15": top_feats,
    })

    # ── 7. Save model ────────────────────────────────────────────────────
    joblib.dump(rf, RF_MODEL_PATH, compress=3)
    log.info("RF model saved → %s  (%.1f KB)",
             RF_MODEL_PATH, RF_MODEL_PATH.stat().st_size / 1024)

    with open(LOGS_DIR / "last_rf_training.json", "w") as fh:
        json.dump(metrics, fh, indent=2)

    return metrics


# ── Evaluation ────────────────────────────────────────────────────────────

def _evaluate(rf, X_val, y_val, counts: Dict) -> Dict:
    import numpy as np
    from collections import Counter

    y_pred_proba = rf.predict_proba(X_val)       # (N, 5)  probabilities
    y_pred       = np.argmax(y_pred_proba, axis=1)

    # Bias check
    dist           = Counter(y_pred.tolist())
    dominant       = max(dist, key=dist.get)
    dominant_ratio = dist[dominant] / max(len(y_pred), 1)
    bias_detected  = dominant_ratio > 0.70
    if bias_detected:
        log.warning("⚠  Bias: class '%s' = %.1f%% of predictions.",
                    CATEGORIES[dominant], dominant_ratio * 100)

    accuracy = float(np.mean(y_pred == y_val)) * 100

    per_class = {}
    for i, cat in enumerate(CATEGORIES):
        tp     = int(np.sum((y_pred == i) & (y_val == i)))
        fp     = int(np.sum((y_pred == i) & (y_val != i)))
        fn     = int(np.sum((y_pred != i) & (y_val == i)))
        prec   = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1     = 2 * prec * recall / (prec + recall) if (prec + recall) else 0.0
        per_class[cat] = {
            "precision": round(prec,   4),
            "recall":    round(recall, 4),
            "f1":        round(f1,     4),
            "support":   counts.get(cat, 0),
        }

    conf_matrix = np.zeros((NUM_CLASSES, NUM_CLASSES), dtype=int)
    for true, pred in zip(y_val, y_pred):
        conf_matrix[true][pred] += 1

    log.info("Validation accuracy: %.2f%%", accuracy)
    log.info("%-12s  %9s  %9s  %9s  %8s",
             "Category", "Precision", "Recall", "F1", "Support")
    for cat, m in per_class.items():
        log.info("%-12s  %9.4f  %9.4f  %9.4f  %8d",
                 cat, m["precision"], m["recall"], m["f1"], m["support"])
    log.info("Confusion matrix:")
    log.info("         " + "  ".join(f"{c[:5]:>5}" for c in CATEGORIES))
    for i, row in enumerate(conf_matrix.tolist()):
        log.info("%-9s %s", CATEGORIES[i][:9], "  ".join(f"{v:5d}" for v in row))

    return {
        "validation_accuracy": round(accuracy, 2),
        "train_accuracy":      round(accuracy, 2),  # updated by caller
        "per_class":           per_class,
        "confusion_matrix":    conf_matrix.tolist(),
        "bias_detected":       bias_detected,
    }


# ── CLI ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    metrics = train()
    print(json.dumps(metrics, indent=2))
