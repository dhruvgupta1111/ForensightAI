from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.auth import get_current_user
from app.config import PREDICTION_LOG_PATH
from app.schemas import PredictionRequest
from app.services.model_runtime import (
    EXPERIMENTAL_MODEL_DISCLAIMER,
    predict_with_artifact,
)
from app.services.prediction_logging import append_prediction_log

router = APIRouter()


@router.post("/predict")
def predict(
    data: PredictionRequest,
    request: Request,
    _: Any = Depends(get_current_user),
) -> dict[str, Any]:
    artifact = getattr(request.app.state, "model_artifact", None)
    if artifact is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The experimental model artifact is not available.",
        )

    features = data.model_dump()
    result = predict_with_artifact(artifact, features)
    append_prediction_log(
        PREDICTION_LOG_PATH,
        features,
        result["prediction"],
    )
    return {
        **result,
        "dataset_type": "synthetic",
        "disclaimer": EXPERIMENTAL_MODEL_DISCLAIMER,
    }
