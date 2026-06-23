"""
training/train_xgb.py
======================
XGBoost multi-class classifier for Aviator crash prediction.

Uses the same 72-feature vector as the RandomForest.
Outputs calibrated per-class probabilities for:
    VERY_LOW | LOW | MEDIUM | HIGH | VERY_HIGH

Saved artefacts:
    models/xgb_model.joblib   — trained XGBClassifier
    models/xgb_scaler.pkl     — StandardScaler fitted on XGB features
    logs/last_xgb_training.json

Run directly:
    cd backend && python -m training.train_xgb
"""

from __future__ import annotations

import json
import logging
import pickle
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

log = logging.getLogger(__name__)

ROOT       = Path(__file__).resolve().parent.parent.parent
MODELS_DIR = ROOT / "models"
LOGS_DIR   = Path(__file__).resolve().parent.parent / "logs"
MODELS_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)

XGB_MODEL_PATH  = MODELS_DIR / "xgb_model.joblib"
XGB_SCALER_PATH = MODELS_DIR / "xgb_scaler.pkl"

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


# ── Dataset ───────────────────────────────────────────────────────────────

def _load_data() -> Tuple[List, List]:
    from training.dataset_loader import DatasetLoader
    from training.feature_engineering import build_feature_matrix

    loader = DatasetLoader()
    loader.load()
    multipliers = [r["multiplier"] for r in loader._rounds]

    if len(multipliers) < SEQ_LEN + 10:
        raise ValueError(f"Need >= {SEQ_LEN + 10} rounds, got {len(multipliers)}.")

    log.info("Building feature matrix for %d rounds…", len(multipliers))
    X, y = build_feature_matrix(multipliers, window_size=SEQ_LEN)
    log.info("Feature matrix: %d × %d", len(X), len(X[0]) if X else 0)
    return X, y


def _oversample(X: List, y: List, min_ratio: float = 0.5) -> Tuple[List, List]:
    from collections import Counter
    import random

    counts   = Counter(y)
    majority = max(counts.values())
    target   = int(majority * min_ratio)
    X_out, y_out = list(X), list(y)

    for cls in range(NUM_CLASSES):
        current = counts.get(cls, 0)
        needed  = max(0, target - current)
        if needed == 0:
            continue
        samples = [X[i] for i in range(len(y)) if y[i] == cls]
        if not samples:
            continue
        cycle  = samples * (needed // len(samples) + 1)
        X_out += cycle[:needed]
        y_out += [cls] * needed
        log.info("Oversampled %-10s: %d → %d", CATEGORIES[cls], current, current + needed)

    combined = list(zip(X_out, y_out))
    random.shuffle(combined)
    X_out, y_out = zip(*combined)
    return list(X_out), list(y_out)


# ── Model ─────────────────────────────────────────────────────────────────

def build_xgb_model(n_rounds: int) -> "XGBClassifier":
    """
    XGBClassifier configured for multi-class probability output.

    Key settings:
      n_estimators=400        — more trees than RF for gradient boosting
      max_depth=6             — shallower trees, boosted in sequence
      learning_rate=0.05      — slow learning → better generalisation
      subsample=0.8           — row subsampling (prevents overfitting)
      colsample_bytree=0.8    — feature subsampling per tree
      use_label_encoder=False — suppress deprecation warning
      eval_metric='mlogloss'  — multi-class log loss
      tree_method='hist'      — fast histogram-based algorithm
    """
    from xgboost import XGBClassifier

    xgb = XGBClassifier(
        n_estimators=400,
        max_depth=6,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        min_child_weight=5,
        gamma=0.1,
        reg_alpha=0.1,
        reg_lambda=1.0,
        objective="multi:softprob",
        num_class=NUM_CLASSES,
        eval_metric="mlogloss",
        tree_method="hist",
        use_label_encoder=False,
        random_state=42,
        n_jobs=-1,
        verbosity=0,
    )
    return xgb


# ── Training ──────────────────────────────────────────────────────────────

def train(
    n_estimators: int = 400,
    oversample: bool = True,
    val_split: float = 0.15,
    early_stopping_rounds: int = 20,
) -> Dict:
    """
    Full XGBoost training pipeline.

    1. Load rounds via DatasetLoader
    2. Build 72-feature matrix
    3. Oversample minority classes
    4. StandardScaler
    5. Train XGBClassifier with early stopping
    6. Evaluate per-class metrics
    7. Save with joblib
    """
    _setup_logging()

    import numpy as np
    import joblib
    from collections import Counter
    from sklearn.preprocessing import StandardScaler

    # ── 1 & 2. Load + features ────────────────────────────────────────
    X_raw, y_raw = _load_data()

    # ── 3. Oversample ─────────────────────────────────────────────────
    if oversample:
        X_raw, y_raw = _oversample(X_raw, y_raw)

    # ── 4. Split + scale ──────────────────────────────────────────────
    n     = len(X_raw)
    split = max(1, int(n * (1 - val_split)))
    X_tr, X_v = X_raw[:split], X_raw[split:]
    y_tr, y_v = y_raw[:split], y_raw[split:]

    X_tr = np.array(X_tr, dtype="float32")
    X_v  = np.array(X_v,  dtype="float32")
    y_tr = np.array(y_tr, dtype="int64")
    y_v  = np.array(y_v,  dtype="int64")

    scaler  = StandardScaler()
    X_tr_s  = scaler.fit_transform(X_tr)
    X_v_s   = scaler.transform(X_v)

    with open(XGB_SCALER_PATH, "wb") as fh:
        pickle.dump(scaler, fh)
    log.info("XGB scaler saved → %s", XGB_SCALER_PATH)

    counts_raw = Counter(y_tr.tolist())
    counts     = {CATEGORIES[i]: counts_raw.get(i, 0) for i in range(NUM_CLASSES)}

    # Sample weights (inverse frequency)
    n_total = len(y_tr)
    sample_weights = np.array([
        n_total / (NUM_CLASSES * max(counts_raw.get(int(lbl), 1), 1))
        for lbl in y_tr
    ], dtype="float32")

    log.info("Train distribution: %s", counts)

    # ── 5. Train with early stopping ──────────────────────────────────
    log.info("Training XGBoost (n_estimators=%d)…", n_estimators)
    xgb = build_xgb_model(n_estimators)
    t0  = time.time()

    xgb.fit(
        X_tr_s, y_tr,
        sample_weight=sample_weights,
        eval_set=[(X_v_s, y_v)],
        verbose=False,
        early_stopping_rounds=early_stopping_rounds,
    )

    elapsed = round(time.time() - t0, 1)
    actual_trees = xgb.best_iteration + 1 if hasattr(xgb, "best_iteration") else n_estimators
    log.info("Training finished in %.1fs  (best iteration: %d)", elapsed, actual_trees)

    # ── 6. Evaluate ────────────────────────────────────────────────────
    # Train accuracy
    y_tr_pred = np.argmax(xgb.predict_proba(X_tr_s), axis=1)
    train_acc = round(float(np.mean(y_tr_pred == y_tr)) * 100, 2)

    metrics = _evaluate(xgb, X_v_s, y_v, counts)

    # Feature importances (top 15)
    importances = xgb.feature_importances_
    from training.feature_engineering import FEATURE_NAMES
    top_idx   = importances.argsort()[::-1][:15]
    top_feats = {FEATURE_NAMES[i]: round(float(importances[i]), 4) for i in top_idx}
    log.info("Top 15 XGB feature importances:")
    for name, imp in top_feats.items():
        log.info("  %-25s %.4f  %s", name, imp, "█" * int(imp * 300))

    metrics.update({
        "engine":           "xgboost",
        "n_estimators":     actual_trees,
        "training_time_s":  elapsed,
        "train_accuracy":   train_acc,
        "samples":          int(len(X_tr_s)),
        "feature_importances_top15": top_feats,
    })

    # ── 7. Save ────────────────────────────────────────────────────────
    joblib.dump(xgb, XGB_MODEL_PATH, compress=3)
    log.info("XGB model saved → %s  (%.1f KB)",
             XGB_MODEL_PATH, XGB_MODEL_PATH.stat().st_size / 1024)

    with open(LOGS_DIR / "last_xgb_training.json", "w") as fh:
        json.dump(metrics, fh, indent=2)

    return metrics


# ── Evaluation ────────────────────────────────────────────────────────────

def _evaluate(xgb, X_val, y_val, counts: Dict) -> Dict:
    import numpy as np
    from collections import Counter

    y_pred_proba = xgb.predict_proba(X_val)
    y_pred       = np.argmax(y_pred_proba, axis=1)

    dist           = Counter(y_pred.tolist())
    dominant       = max(dist, key=dist.get)
    dominant_ratio = dist[dominant] / max(len(y_pred), 1)
    bias_detected  = dominant_ratio > 0.70
    if bias_detected:
        log.warning("⚠  Bias: class '%s' = %.1f%%",
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

    log.info("XGB Validation accuracy: %.2f%%", accuracy)
    log.info("%-12s  %9s  %9s  %9s  %8s",
             "Category", "Precision", "Recall", "F1", "Support")
    for cat, m in per_class.items():
        log.info("%-12s  %9.4f  %9.4f  %9.4f  %8d",
                 cat, m["precision"], m["recall"], m["f1"], m["support"])

    return {
        "validation_accuracy": round(accuracy, 2),
        "per_class":           per_class,
        "confusion_matrix":    conf_matrix.tolist(),
        "bias_detected":       bias_detected,
    }


if __name__ == "__main__":
    metrics = train()
    print(json.dumps(metrics, indent=2))
