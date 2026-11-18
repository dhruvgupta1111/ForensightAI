import logging
from pathlib import Path
from typing import Any, Mapping

import joblib

from app.services.ml_experiments import normalize_features
from app.services.synthetic_dataset import FEATURE_COLUMNS

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODEL_PATH = PROJECT_ROOT / "model" / "model.joblib"
LOGGER = logging.getLogger(__name__)
EXPERIMENTAL_MODEL_DISCLAIMER = (
    "This experimental classifier was trained and evaluated using simulated "
    "examples, not observed forensic outcomes. It is not validated for real-world "
    "forensic use, does not establish contamination, and its probabilities are "
    "not calibrated real-world estimates."
)


def load_model_artifact(path: Path = MODEL_PATH) -> dict[str, Any] | None:
    if not path.is_file():
        LOGGER.warning("Experimental prediction model is missing at %s.", path)
        return None
    artifact = joblib.load(path)
    pipeline = artifact.get("pipeline") if isinstance(artifact, dict) else None
    if (
        not isinstance(artifact, dict)
        or pipeline is None
        or not hasattr(pipeline, "predict_proba")
        or artifact.get("feature_columns") != list(FEATURE_COLUMNS)
    ):
        raise ValueError(f"Invalid ForenSight model artifact: {path}")
    return artifact


def predict_with_artifact(
    artifact: Mapping[str, Any], features: Mapping[str, object]
) -> dict[str, Any]:
    normalized = normalize_features(features)
    pipeline = artifact["pipeline"]
    probabilities = pipeline.predict_proba([normalized])[0]
    prediction = str(pipeline.predict([normalized])[0])
    return {
        "prediction": prediction,
        "class_probabilities": {
            str(label): float(probability)
            for label, probability in zip(pipeline.classes_, probabilities)
        },
        "algorithm": artifact["algorithm"],
    }
