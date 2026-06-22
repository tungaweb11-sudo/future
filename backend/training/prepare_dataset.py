"""
training/prepare_dataset.py
============================
Thin shim that wraps DatasetLoader for backward compatibility.
All actual loading/cleaning/dedup logic lives in dataset_loader.py.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from training.dataset_loader import DatasetLoader

log = logging.getLogger(__name__)


def prepare(
    oversample: bool = True,
    val_split: float = 0.15,
    min_ratio: float = 0.5,
    recent_weight: float = 2.0,
    recent_minutes: int = 30,
    min_accuracy_threshold: float = 0.30,
) -> Tuple:
    """
    Full pipeline: load → clean → deduplicate → build features →
    recency-weight → filter low-accuracy slots → oversample → split.

    Parameters
    ----------
    oversample               : oversample minority classes
    val_split                : fraction of data held out for validation
    min_ratio                : minority-class oversampling ratio vs majority
    recent_weight            : weight multiplier for recent samples (last N min)
    recent_minutes           : look-back window for recency boost
    min_accuracy_threshold   : drop time slots with accuracy below this

    Returns
    -------
    X_train, X_val, y_train, y_val, class_weights, counts
    """
    loader = (
        DatasetLoader(val_split=val_split, min_ratio=min_ratio)
        .load()
        .build_features(
            oversample=oversample,
            recent_weight=recent_weight,
            recent_minutes=recent_minutes,
            min_accuracy_threshold=min_accuracy_threshold,
        )
        .fit_scaler()
    )

    loader.save_checkpoint()

    X_train, y_train = loader.get_split("train")
    X_val,   y_val   = loader.get_split("val")

    log.info("Dataset ready: train=%d  val=%d  total_rounds=%d",
             len(X_train), len(X_val), loader.total_rounds())

    return X_train, X_val, y_train, y_val, loader.class_weights(), loader._counts
