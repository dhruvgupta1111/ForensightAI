import hashlib
import json
import logging
import secrets
import sqlite3
from datetime import datetime, timezone
from typing import Annotated, Literal

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from pwdlib.exceptions import UnknownHashError

from app.auth import (
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)
from app.config import COOKIE_SECURE, JWT_EXPIRE_MINUTES, PREDICTION_LOG_PATH
from app.database import get_db
from app.schemas import (
    AssessmentRequest,
    AssessmentResponse,
    AssessmentWorkflowResponse,
    Credentials,
    SignupRequest,
)
from app.services.logistic_regression import get_model_evaluation
from app.services.model_runtime import (
    EXPERIMENTAL_MODEL_DISCLAIMER,
    predict_with_artifact,
)
from app.services.prediction_logging import append_prediction_log
from app.services.risk_assessment import PreliminaryRuleBasedService
from app.services.synthetic_dataset import FEATURE_COLUMNS

router = APIRouter(prefix="/api")
risk_service = PreliminaryRuleBasedService()
LOGGER = logging.getLogger(__name__)
CSRF_COOKIE = "forensight_csrf"
AUTH_COOKIE = "access_token"
EVIDENCE_TYPES = ("Biological", "Trace", "Digital", "Firearms", "Document", "Other")
EXPERIMENTAL_RETRY_MESSAGE = (
    "The experimental classifier could not complete. You can retry it."
)


def _set_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        AUTH_COOKIE,
        token,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="strict",
        max_age=JWT_EXPIRE_MINUTES * 60,
        path="/",
    )


def _set_csrf_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        CSRF_COOKIE,
        token,
        httponly=False,
        secure=COOKIE_SECURE,
        samesite="strict",
        max_age=JWT_EXPIRE_MINUTES * 60,
        path="/",
    )


def _user_payload(user) -> dict[str, int | str]:
    return {"id": user["id"], "full_name": user["full_name"], "email": user["email"]}


def _assessment_payload(record) -> dict:
    return {
        "id": record["id"],
        "evidence_ref": record["evidence_ref"],
        "evidence_type": record["evidence_type"],
        "collection_conditions": record["collection_conditions"],
        "ppe_compliant": bool(record["ppe_compliant"]),
        "tool_condition": record["tool_condition"],
        "packaging_condition": record["packaging_condition"],
        "storage_condition": record["storage_condition"],
        "separately_packaged": bool(record["separately_packaged"]),
        "chain_of_custody_documented": bool(record["chain_of_custody_documented"]),
        "risk_category": record["risk_category"],
        "risk_score": record["risk_score"],
        "risk_factors": json.loads(record["risk_factors"]),
        "recommendations": json.loads(record["recommendations"]),
        "created_at": record["created_at"],
    }


def _insert_assessment_record(db, user_id, data, assessment, created_at):
    cursor = db.execute(
        """
        INSERT INTO assessments (
            user_id, evidence_ref, evidence_type, collection_conditions,
            ppe_compliant, tool_condition, packaging_condition, storage_condition,
            separately_packaged, chain_of_custody_documented, risk_category,
            risk_score, risk_factors, recommendations, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            data.evidence_ref,
            data.evidence_type,
            data.collection_conditions,
            int(data.ppe_compliant),
            data.tool_condition,
            data.packaging_condition,
            data.storage_condition,
            int(data.separately_packaged),
            int(data.chain_of_custody_documented),
            assessment.category,
            assessment.score,
            json.dumps(assessment.factors),
            json.dumps(assessment.recommendations),
            created_at,
        ),
    )
    return cursor.lastrowid


def _experimental_execution(request: Request, features: dict) -> dict:
    artifact = getattr(request.app.state, "model_artifact", None)
    if artifact is None:
        return {
            "status": "failed",
            "result": None,
            "message": "The experimental classifier is unavailable. You can retry it.",
        }

    try:
        result = predict_with_artifact(artifact, features)
    except (AttributeError, KeyError, TypeError, ValueError):
        LOGGER.exception("The experimental classifier failed during an assessment.")
        return {
            "status": "failed",
            "result": None,
            "message": EXPERIMENTAL_RETRY_MESSAGE,
        }

    return {
        "status": "succeeded",
        "result": {
            **result,
            "dataset_type": "synthetic",
            "disclaimer": EXPERIMENTAL_MODEL_DISCLAIMER,
        },
        "message": None,
    }


def _workflow_response(db, user_id: int, assessment_id: int):
    record = db.execute(
        "SELECT * FROM assessments WHERE id = ? AND user_id = ?",
        (assessment_id, user_id),
    ).fetchone()
    if record is None:
        raise HTTPException(status_code=404, detail="Assessment not found.")

    execution = db.execute(
        "SELECT * FROM assessment_workflow_results WHERE assessment_id = ?",
        (assessment_id,),
    ).fetchone()
    if execution is None:
        raise HTTPException(
            status_code=404,
            detail="No combined workflow results are available for this assessment.",
        )

    experimental_result = (
        json.loads(execution["experimental_result"])
        if execution["experimental_result"]
        else None
    )
    assessment_payload = _assessment_payload(record)
    return {
        "assessment": assessment_payload,
        "primary_screen": {
            "status": "succeeded",
            "method": "preliminary_rule_based",
            "risk_category": assessment_payload["risk_category"],
            "risk_score": assessment_payload["risk_score"],
            "risk_factors": assessment_payload["risk_factors"],
            "recommendations": assessment_payload["recommendations"],
        },
        "experimental_classifier": {
            "status": execution["experimental_status"],
            "result": experimental_result,
            "message": execution["error_message"],
        },
    }


def _assessment_features(record) -> dict[str, object]:
    stored_values = {
        "evidence_type": record["evidence_type"],
        "collection_conditions": record["collection_conditions"],
        "ppe_compliant": bool(record["ppe_compliant"]),
        "tool_condition": record["tool_condition"],
        "packaging_condition": record["packaging_condition"],
        "storage_condition": record["storage_condition"],
        "separately_packaged": bool(record["separately_packaged"]),
        "chain_of_custody_documented": bool(record["chain_of_custody_documented"]),
    }
    return {column: stored_values[column] for column in FEATURE_COLUMNS}


@router.get("/auth/csrf")
def issue_csrf_token(response: Response):
    token = secrets.token_urlsafe(32)
    _set_csrf_cookie(response, token)
    return {"csrf_token": token}


@router.post("/auth/signup", status_code=status.HTTP_201_CREATED)
def signup(
    data: SignupRequest,
    response: Response,
    db=Depends(get_db),
):
    try:
        cursor = db.execute(
            "INSERT INTO users (full_name, email, password_hash, created_at) "
            "VALUES (?, ?, ?, ?)",
            (
                data.full_name,
                data.email.lower(),
                hash_password(data.password),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        db.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        ) from None

    token = create_access_token(cursor.lastrowid)
    _set_auth_cookie(response, token)
    return {
        "user": {
            "id": cursor.lastrowid,
            "full_name": data.full_name,
            "email": data.email.lower(),
        }
    }


@router.post("/auth/login")
def login(data: Credentials, response: Response, db=Depends(get_db)):
    user = db.execute(
        "SELECT id, full_name, email, password_hash FROM users WHERE email = ?",
        (data.email.lower(),),
    ).fetchone()
    try:
        valid_password = user is not None and verify_password(
            data.password, user["password_hash"]
        )
    except UnknownHashError:
        valid_password = False
    if not valid_password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email or password is incorrect.",
        )

    _set_auth_cookie(response, create_access_token(user["id"]))
    return {"user": _user_payload(user)}


@router.post("/auth/logout")
def logout(response: Response):
    response.delete_cookie(AUTH_COOKIE, path="/", secure=COOKIE_SECURE, samesite="strict")
    response.delete_cookie(CSRF_COOKIE, path="/", secure=COOKIE_SECURE, samesite="strict")
    return {"message": "Signed out."}


@router.get("/auth/me")
def current_user(user=Depends(get_current_user)):
    return {"user": _user_payload(user)}


@router.get("/dashboard")
def dashboard(
    request: Request,
    user=Depends(get_current_user),
    db=Depends(get_db),
):
    counts = db.execute(
        """
        SELECT COUNT(*) AS total,
            SUM(CASE WHEN risk_category = 'low' THEN 1 ELSE 0 END) AS low,
            SUM(CASE WHEN risk_category = 'medium' THEN 1 ELSE 0 END) AS medium,
            SUM(CASE WHEN risk_category = 'high' THEN 1 ELSE 0 END) AS high
        FROM assessments WHERE user_id = ?
        """,
        (user["id"],),
    ).fetchone()
    recent = db.execute(
        "SELECT * FROM assessments WHERE user_id = ? "
        "ORDER BY created_at DESC, id DESC LIMIT 6",
        (user["id"],),
    ).fetchall()
    evidence_type_rows = db.execute(
        "SELECT evidence_type, COUNT(*) AS count FROM assessments "
        "WHERE user_id = ? GROUP BY evidence_type",
        (user["id"],),
    ).fetchall()
    evidence_type_counts = {evidence_type: 0 for evidence_type in EVIDENCE_TYPES}
    evidence_type_counts.update(
        {row["evidence_type"]: row["count"] for row in evidence_type_rows}
    )
    indicators = db.execute(
        """
        SELECT
            COALESCE(SUM(CASE WHEN ppe_compliant = 0 THEN 1 ELSE 0 END), 0) AS ppe,
            COALESCE(SUM(CASE WHEN collection_conditions != 'controlled' THEN 1 ELSE 0 END), 0) AS collection,
            COALESCE(SUM(CASE WHEN packaging_condition IN ('compromised', 'unknown') THEN 1 ELSE 0 END), 0) AS packaging,
            COALESCE(SUM(CASE WHEN separately_packaged = 0 THEN 1 ELSE 0 END), 0) AS separate_packaging,
            COALESCE(SUM(CASE WHEN storage_condition != 'controlled' THEN 1 ELSE 0 END), 0) AS storage,
            COALESCE(SUM(CASE WHEN chain_of_custody_documented = 0 THEN 1 ELSE 0 END), 0) AS custody
        FROM assessments WHERE user_id = ?
        """,
        (user["id"],),
    ).fetchone()
    monthly_rows = db.execute(
        """
        SELECT substr(created_at, 1, 7) AS month, COUNT(*) AS count
        FROM assessments
        WHERE user_id = ?
        GROUP BY substr(created_at, 1, 7)
        ORDER BY month
        """,
        (user["id"],),
    ).fetchall()
    high_risk = db.execute(
        "SELECT * FROM assessments WHERE user_id = ? AND risk_category = 'high' "
        "ORDER BY created_at DESC, id DESC LIMIT 10",
        (user["id"],),
    ).fetchall()
    return {
        "total": counts["total"],
        "low": counts["low"] or 0,
        "medium": counts["medium"] or 0,
        "high": counts["high"] or 0,
        "recent": [_assessment_payload(row) for row in recent],
        "evidence_types": [
            {"evidence_type": evidence_type, "count": count}
            for evidence_type, count in evidence_type_counts.items()
        ],
        "indicators": [
            {"key": "ppe", "label": "PPE not confirmed", "count": indicators["ppe"]},
            {
                "key": "collection",
                "label": "Collection not controlled",
                "count": indicators["collection"],
            },
            {
                "key": "packaging",
                "label": "Packaging compromised or unknown",
                "count": indicators["packaging"],
            },
            {
                "key": "separate_packaging",
                "label": "Not separately packaged",
                "count": indicators["separate_packaging"],
            },
            {
                "key": "storage",
                "label": "Storage not controlled",
                "count": indicators["storage"],
            },
            {
                "key": "custody",
                "label": "Custody documentation incomplete",
                "count": indicators["custody"],
            },
        ],
        "monthly_trend": [
            {"month": row["month"], "count": row["count"]} for row in monthly_rows
        ],
        "high_risk_assessments": [_assessment_payload(row) for row in high_risk],
        "model_evaluation": get_model_evaluation(),
        "model_comparison": (
            request.app.state.model_artifact.get("experiment_comparison", [])
            if getattr(request.app.state, "model_artifact", None) is not None
            else []
        ),
    }


@router.post(
    "/assessments",
    status_code=status.HTTP_201_CREATED,
    response_model=AssessmentResponse,
)
def create_assessment(
    data: AssessmentRequest,
    user=Depends(get_current_user),
    db=Depends(get_db),
):
    assessment = risk_service.assess(data)
    created_at = datetime.now(timezone.utc).isoformat()
    try:
        assessment_id = _insert_assessment_record(
            db, user["id"], data, assessment, created_at
        )
        db.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This evidence reference already has an assessment.",
        ) from None

    record = db.execute(
        "SELECT * FROM assessments WHERE id = ? AND user_id = ?",
        (assessment_id, user["id"]),
    ).fetchone()
    return _assessment_payload(record)


@router.post(
    "/assessments/workflow",
    status_code=status.HTTP_201_CREATED,
    response_model=AssessmentWorkflowResponse,
)
def create_assessment_workflow(
    data: AssessmentRequest,
    request: Request,
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=16, max_length=128)
    ],
    user=Depends(get_current_user),
    db=Depends(get_db),
):
    payload = data.model_dump(mode="json")
    request_hash = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    existing = db.execute(
        """
        SELECT request_hash, assessment_id
        FROM assessment_idempotency_keys
        WHERE user_id = ? AND idempotency_key = ?
        """,
        (user["id"], idempotency_key),
    ).fetchone()
    if existing is not None:
        if existing["request_hash"] != request_hash:
            raise HTTPException(
                status_code=409,
                detail="This submission key was already used with different assessment data.",
            )
        return _workflow_response(db, user["id"], existing["assessment_id"])

    assessment = risk_service.assess(data)
    features = {column: payload[column] for column in FEATURE_COLUMNS}
    execution = _experimental_execution(request, features)
    created_at = datetime.now(timezone.utc).isoformat()

    try:
        db.execute("BEGIN IMMEDIATE")
        existing = db.execute(
            """
            SELECT request_hash, assessment_id
            FROM assessment_idempotency_keys
            WHERE user_id = ? AND idempotency_key = ?
            """,
            (user["id"], idempotency_key),
        ).fetchone()
        if existing is not None:
            if existing["request_hash"] != request_hash:
                db.rollback()
                raise HTTPException(
                    status_code=409,
                    detail="This submission key was already used with different assessment data.",
                )
            db.commit()
            return _workflow_response(db, user["id"], existing["assessment_id"])

        assessment_id = _insert_assessment_record(
            db, user["id"], data, assessment, created_at
        )
        db.execute(
            """
            INSERT INTO assessment_workflow_results (
                assessment_id, experimental_status, experimental_result,
                error_message, updated_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                assessment_id,
                execution["status"],
                json.dumps(execution["result"], sort_keys=True)
                if execution["result"] is not None
                else None,
                execution["message"],
                created_at,
            ),
        )
        db.execute(
            """
            INSERT INTO assessment_idempotency_keys (
                user_id, idempotency_key, request_hash, assessment_id, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (user["id"], idempotency_key, request_hash, assessment_id, created_at),
        )
        db.commit()
    except sqlite3.IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This evidence reference already has an assessment.",
        ) from None

    if execution["result"] is not None:
        append_prediction_log(
            PREDICTION_LOG_PATH,
            features,
            execution["result"]["prediction"],
        )
    return _workflow_response(db, user["id"], assessment_id)


@router.get(
    "/assessments/{assessment_id}/workflow",
    response_model=AssessmentWorkflowResponse,
)
def get_assessment_workflow(
    assessment_id: int,
    user=Depends(get_current_user),
    db=Depends(get_db),
):
    return _workflow_response(db, user["id"], assessment_id)


@router.post(
    "/assessments/{assessment_id}/workflow/retry",
    response_model=AssessmentWorkflowResponse,
)
def retry_assessment_classifier(
    assessment_id: int,
    request: Request,
    user=Depends(get_current_user),
    db=Depends(get_db),
):
    db.execute("BEGIN IMMEDIATE")
    record = db.execute(
        "SELECT * FROM assessments WHERE id = ? AND user_id = ?",
        (assessment_id, user["id"]),
    ).fetchone()
    if record is None:
        db.rollback()
        raise HTTPException(status_code=404, detail="Assessment not found.")

    execution = db.execute(
        "SELECT * FROM assessment_workflow_results WHERE assessment_id = ?",
        (assessment_id,),
    ).fetchone()
    if execution is None:
        db.rollback()
        raise HTTPException(
            status_code=404,
            detail="No experimental classifier result exists for this assessment.",
        )
    if execution["experimental_status"] == "succeeded":
        db.commit()
        return _workflow_response(db, user["id"], assessment_id)

    features = _assessment_features(record)
    result = _experimental_execution(request, features)
    db.execute(
        """
        UPDATE assessment_workflow_results
        SET experimental_status = ?, experimental_result = ?,
            error_message = ?, updated_at = ?
        WHERE assessment_id = ?
        """,
        (
            result["status"],
            json.dumps(result["result"], sort_keys=True)
            if result["result"] is not None
            else None,
            result["message"],
            datetime.now(timezone.utc).isoformat(),
            assessment_id,
        ),
    )
    db.commit()

    if result["result"] is not None:
        append_prediction_log(
            PREDICTION_LOG_PATH,
            features,
            result["result"]["prediction"],
        )
    return _workflow_response(db, user["id"], assessment_id)


@router.get("/assessments", response_model=list[AssessmentResponse])
def assessment_history(
    user=Depends(get_current_user),
    db=Depends(get_db),
    risk: Annotated[Literal["low", "medium", "high"] | None, Query()] = None,
):
    if risk:
        rows = db.execute(
            "SELECT * FROM assessments WHERE user_id = ? AND risk_category = ? "
            "ORDER BY created_at DESC, id DESC",
            (user["id"], risk),
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT * FROM assessments WHERE user_id = ? "
            "ORDER BY created_at DESC, id DESC",
            (user["id"],),
        ).fetchall()
    return [_assessment_payload(row) for row in rows]


@router.get("/assessments/{assessment_id}", response_model=AssessmentResponse)
def get_assessment(
    assessment_id: int,
    user=Depends(get_current_user),
    db=Depends(get_db),
):
    record = db.execute(
        "SELECT * FROM assessments WHERE id = ? AND user_id = ?",
        (assessment_id, user["id"]),
    ).fetchone()
    if record is None:
        raise HTTPException(status_code=404, detail="Assessment not found.")
    return _assessment_payload(record)
