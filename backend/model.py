import logging
import math
from typing import Dict, List, Tuple

from utils import ARTIFACT_DIR, CATEGORIES, read_json, write_json, category_to_recommended_cashout, risk_level


MODEL_PATH = ARTIFACT_DIR / "aviator_lstm.keras"
FALLBACK_MODEL_PATH = ARTIFACT_DIR / "fallback_model.json"
SEQUENCE_LENGTH = 12


class TensorFlowUnavailable(RuntimeError):
    pass


class AviatorPredictor:
    def __init__(self, sequence_length: int = SEQUENCE_LENGTH) -> None:
        self.sequence_length = sequence_length
        self.model = None
        self.logger = logging.getLogger(self.__class__.__name__)

    def _keras(self):
        try:
            from tensorflow import keras
        except ImportError as exc:
            raise TensorFlowUnavailable(
                "TensorFlow is not installed. Run `pip install -r backend/requirements.txt`."
            ) from exc
        return keras

    def normalize(self, values: List[float]) -> List[float]:
        # log-scale normalisation capped at 100× — maps 1.0→0, 100×→1
        return [math.log(min(max(float(v), 1.0), 100.0)) / math.log(100.0) for v in values]

    def create_sequences(self, multipliers: List[float]) -> Tuple[List[List[float]], List[int]]:
        if len(multipliers) <= self.sequence_length:
            return [], []

        normalized = self.normalize(multipliers)
        labels = [self.category_index(value) for value in multipliers]

        x, y = [], []
        for index in range(self.sequence_length, len(normalized)):
            x.append(normalized[index - self.sequence_length:index])
            y.append(labels[index])
        return x, y

    def build_model(self):
        keras = self._keras()
        model = keras.Sequential(
            [
                keras.layers.Input(shape=(self.sequence_length, 1)),
                keras.layers.LSTM(128, return_sequences=True),
                keras.layers.Dropout(0.25),
                keras.layers.LSTM(64),
                keras.layers.Dense(64, activation="relu"),
                keras.layers.Dropout(0.2),
                keras.layers.Dense(len(CATEGORIES), activation="softmax"),
            ]
        )
        model.compile(
            optimizer=keras.optimizers.Adam(learning_rate=0.001),
            loss="sparse_categorical_crossentropy",
            metrics=["accuracy"],
        )
        return model

    def load(self) -> bool:
        if not MODEL_PATH.exists():
            return False
        keras = self._keras()
        self.model = keras.models.load_model(MODEL_PATH)
        return True

    def save(self) -> None:
        if self.model is None:
            raise RuntimeError("Cannot save before a model has been trained.")
        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        self.model.save(MODEL_PATH)

    def train(self, multipliers: List[float], epochs: int = 30) -> Dict[str, float]:
        x, y = self.create_sequences(multipliers)
        if len(x) < 10:
            raise ValueError("At least 23 valid rounds are recommended for training.")

        try:
            import numpy as np
        except ImportError:
            return self.train_fallback(multipliers)

        try:
            self.model = self.build_model()
        except TensorFlowUnavailable:
            return self.train_fallback(multipliers)

        x_np = np.array(x, dtype="float32").reshape(-1, self.sequence_length, 1)
        y_np = np.array(y, dtype="int64")
        split = max(1, int(len(x_np) * 0.8))
        x_train, x_test = x_np[:split], x_np[split:]
        y_train, y_test = y_np[:split], y_np[split:]

        keras = self._keras()
        callbacks = [keras.callbacks.EarlyStopping(monitor="loss", patience=5, restore_best_weights=True)]

        history = self.model.fit(
            x_train,
            y_train,
            validation_data=(x_test, y_test) if len(x_test) else None,
            epochs=epochs,
            batch_size=16,
            verbose=0,
            callbacks=callbacks,
        )
        self.save()

        train_accuracy = float(history.history.get("accuracy", [0])[-1]) * 100
        validation_accuracy = float(history.history.get("val_accuracy", [train_accuracy / 100])[-1]) * 100
        return {
            "train_accuracy": round(train_accuracy, 2),
            "validation_accuracy": round(validation_accuracy, 2),
            "samples": int(len(x)),
            "engine": "tensorflow_lstm",
        }

    def train_fallback(self, multipliers: List[float]) -> Dict[str, float]:
        labels = [self.category_index(value) for value in multipliers]
        # Laplace-smoothed counts
        counts = {cat: 2 for cat in CATEGORIES}
        transitions = {cat: {nxt: 1 for nxt in CATEGORIES} for cat in CATEGORIES}

        for index, label in enumerate(labels):
            category = CATEGORIES[label]
            counts[category] += 1
            if index:
                previous = CATEGORIES[labels[index - 1]]
                transitions[previous][category] += 1

        write_json(
            FALLBACK_MODEL_PATH,
            {
                "counts": counts,
                "transitions": transitions,
                "sequence_length": self.sequence_length,
            },
        )

        total = sum(counts.values())
        baseline = max(counts.values()) / total * 100
        return {
            "train_accuracy": round(baseline, 2),
            "validation_accuracy": round(baseline, 2),
            "samples": max(0, len(multipliers) - self.sequence_length),
            "engine": "stdlib_fallback",
        }

    def predict(self, multipliers: List[float]) -> Dict[str, object]:
        if len(multipliers) < self.sequence_length:
            raise ValueError(f"Need at least {self.sequence_length} rounds to predict.")
        if self.model is None and MODEL_PATH.exists():
            try:
                self.load()
            except TensorFlowUnavailable:
                self.model = None
        if self.model is None:
            if not FALLBACK_MODEL_PATH.exists():
                self.train_fallback(multipliers)
            return self.predict_fallback(multipliers)

        import numpy as np

        sequence = np.array(self.normalize(multipliers[-self.sequence_length:]), dtype="float32").reshape(1, self.sequence_length, 1)
        probabilities = self.model.predict(sequence, verbose=0)[0]
        class_index = int(np.argmax(probabilities))
        prediction = CATEGORIES[class_index]
        confidence = round(float(probabilities[class_index]) * 100, 2)
        return {
            "prediction": prediction,
            "confidence": confidence,
            "recommended_cashout": category_to_recommended_cashout(prediction, confidence),
            "risk_level": risk_level(prediction, confidence),
            "probabilities": {
                category: round(float(probabilities[index]) * 100, 2)
                for index, category in enumerate(CATEGORIES)
            },
        }

    def predict_fallback(self, multipliers: List[float]) -> Dict[str, object]:
        payload = read_json(FALLBACK_MODEL_PATH, {})
        counts      = payload.get("counts",      {cat: 2 for cat in CATEGORIES})
        transitions = payload.get("transitions", {})

        # Last round category drives transition signal
        last_cat  = CATEGORIES[self.category_index(multipliers[-1])]
        trans     = transitions.get(last_cat, counts)

        # Recent window (last 5 rounds) for momentum
        recent = [CATEGORIES[self.category_index(v)] for v in multipliers[-5:]]
        recent_counts = {cat: recent.count(cat) for cat in CATEGORIES}

        total_counts  = max(sum(counts.values()), 1)
        total_trans   = max(sum(trans.values()), 1)
        total_recent  = max(sum(recent_counts.values()), 1)

        # Weights: 25% base freq, 50% transition from last round, 25% recent momentum
        scores = {
            cat: (
                (counts.get(cat, 1) / total_counts)        * 25.0 +
                (trans.get(cat, 1)  / total_trans)         * 50.0 +
                (recent_counts.get(cat, 0) / total_recent) * 25.0
            )
            for cat in CATEGORIES
        }

        total_score = sum(scores.values()) or 1.0
        raw = {cat: scores[cat] / total_score * 100 for cat in CATEGORIES}

        # Force probabilities to sum exactly to 100.0
        rounded = {cat: round(raw[cat], 2) for cat in CATEGORIES}
        diff = round(100.0 - sum(rounded.values()), 2)
        top  = max(rounded, key=rounded.get)
        rounded[top] = round(rounded[top] + diff, 2)

        prediction = max(rounded, key=rounded.get)
        confidence  = rounded[prediction]

        return {
            "prediction":          prediction,
            "confidence":          confidence,
            "recommended_cashout": category_to_recommended_cashout(prediction, confidence),
            "risk_level":          risk_level(prediction, confidence),
            "probabilities":       rounded,
            "engine":              "stdlib_fallback",
        }

    @staticmethod
    def category_index(multiplier: float) -> int:
        if multiplier < 1.50:
            return 0   # VERY_LOW
        if multiplier < 2.00:
            return 1   # LOW
        if multiplier < 5.00:
            return 2   # MEDIUM
        if multiplier < 15.0:
            return 3   # HIGH
        return 4       # VERY_HIGH
