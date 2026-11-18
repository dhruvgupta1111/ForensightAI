from datetime import datetime, timezone
import json

from fastapi.testclient import TestClient
import pytest

from app import database
from app.main import app

def csrf_headers(client):
    response = client.get("/api/auth/csrf")
    assert response.status_code == 200
    return {"X-CSRF-Token": response.json()["csrf_token"]}


def signup(client, email="analyst@example.org"):
    return client.post(
        "/api/auth/signup",
        headers=csrf_headers(client),
        json={
            "full_name": "Case Analyst",
            "email": email,
            "password": "Secure-Example-Passphrase-4",
        },
    )


def test_dashboard_requires_authentication_and_starts_empty(client):
    assert client.get("/api/dashboard").status_code == 401
    created = signup(client)
    assert created.status_code == 201

    dashboard = client.get("/api/dashboard")
    assert dashboard.status_code == 200
    assert dashboard.json()["total"] == 0

    other_client = TestClient(client.app)
    assert other_client.get("/api/dashboard").status_code == 401


def test_dashboard_analytics_are_empty_without_saved_assessments(client):
    assert signup(client).status_code == 201

    dashboard = client.get("/api/dashboard").json()

    assert dashboard["total"] == 0
    assert dashboard["evidence_types"] == [
        {"evidence_type": evidence_type, "count": 0}
        for evidence_type in ("Biological", "Trace", "Digital", "Firearms", "Document", "Other")
    ]
    assert all(indicator["count"] == 0 for indicator in dashboard["indicators"])
    assert dashboard["monthly_trend"] == []
    assert dashboard["high_risk_assessments"] == []
    assert len(dashboard["model_comparison"]) == 4
    assert {run["algorithm"] for run in dashboard["model_comparison"]} == {
        "Logistic Regression",
        "Decision Tree",
    }
    selected_run = next(
        run for run in dashboard["model_comparison"] if run["selected"]
    )
    assert selected_run["algorithm"] == "Decision Tree"
    assert sum(map(sum, selected_run["confusion_matrix"]["counts"])) == 375
    assert len(selected_run["class_metrics"]) == 2
    assert dashboard["model_evaluation"]["status"] == "experimental"
    assert dashboard["model_evaluation"]["dataset_type"] == "synthetic"
    assert dashboard["model_evaluation"]["accuracy"] is not None


def test_dashboard_analytics_aggregate_only_saved_user_assessments(client):
    assert signup(client).status_code == 201
    common = {
        "evidence_type": "Trace",
        "collection_conditions": "controlled",
        "ppe_compliant": True,
        "tool_condition": "clean",
        "packaging_condition": "intact",
        "storage_condition": "controlled",
        "separately_packaged": True,
        "chain_of_custody_documented": True,
    }
    assessments = [
        {**common, "evidence_ref": "ANALYTICS-LOW"},
        {
            **common,
            "evidence_ref": "ANALYTICS-MEDIUM",
            "evidence_type": "Digital",
            "collection_conditions": "challenging",
            "storage_condition": "uncontrolled",
        },
        {
            **common,
            "evidence_ref": "ANALYTICS-HIGH",
            "evidence_type": "Biological",
            "collection_conditions": "challenging",
            "ppe_compliant": False,
            "tool_condition": "compromised",
            "packaging_condition": "compromised",
            "storage_condition": "uncontrolled",
            "separately_packaged": False,
            "chain_of_custody_documented": False,
        },
    ]
    for assessment in assessments:
        response = client.post(
            "/api/assessments",
            headers=csrf_headers(client),
            json=assessment,
        )
        assert response.status_code == 201

    dashboard = client.get("/api/dashboard").json()
    evidence_types = {
        item["evidence_type"]: item["count"] for item in dashboard["evidence_types"]
    }
    indicators = {item["key"]: item["count"] for item in dashboard["indicators"]}

    assert (dashboard["total"], dashboard["low"], dashboard["medium"], dashboard["high"]) == (3, 1, 1, 1)
    assert evidence_types == {
        "Biological": 1,
        "Trace": 1,
        "Digital": 1,
        "Firearms": 0,
        "Document": 0,
        "Other": 0,
    }
    assert indicators == {
        "ppe": 1,
        "collection": 2,
        "packaging": 1,
        "separate_packaging": 1,
        "storage": 2,
        "custody": 1,
    }
    assert dashboard["monthly_trend"] == [
        {"month": datetime.now(timezone.utc).strftime("%Y-%m"), "count": 3}
    ]
    assert len(dashboard["high_risk_assessments"]) == 1
    assert dashboard["high_risk_assessments"][0]["evidence_ref"] == "ANALYTICS-HIGH"
    assert dashboard["high_risk_assessments"][0]["risk_score"] == 14

    second_client = TestClient(client.app)
    second_client.post(
        "/api/auth/signup",
        headers=csrf_headers(second_client),
        json={
            "full_name": "Second Analyst",
            "email": "second@example.org",
            "password": "Another-Secure-Passphrase-5",
        },
    )
    second_dashboard = second_client.get("/api/dashboard").json()
    assert second_dashboard["total"] == 0
    assert second_dashboard["monthly_trend"] == []
    assert second_dashboard["high_risk_assessments"] == []


def test_login_logout_and_user_scoped_assessments(client):
    assert signup(client).status_code == 201
    own_assessment = {
        "evidence_ref": "OWNER-ONLY-001",
        "evidence_type": "Trace",
        "collection_conditions": "controlled",
        "ppe_compliant": True,
        "tool_condition": "clean",
        "packaging_condition": "intact",
        "storage_condition": "controlled",
        "separately_packaged": True,
        "chain_of_custody_documented": True,
    }
    assert client.post(
        "/api/assessments",
        headers=csrf_headers(client),
        json=own_assessment,
    ).status_code == 201
    assert client.post(
        "/api/auth/logout", headers=csrf_headers(client)
    ).status_code == 200
    assert client.get("/api/dashboard").status_code == 401

    login = client.post(
        "/api/auth/login",
        headers=csrf_headers(client),
        json={
            "email": "analyst@example.org",
            "password": "Secure-Example-Passphrase-4",
        },
    )
    assert login.status_code == 200
    assert client.get("/api/auth/me").json()["user"]["email"] == "analyst@example.org"
    assert client.get("/api/dashboard").json()["total"] == 1

    second_client = TestClient(client.app)
    second_client.post(
        "/api/auth/signup",
        headers=csrf_headers(second_client),
        json={
            "full_name": "Second Analyst",
            "email": "second@example.org",
            "password": "Another-Secure-Passphrase-5",
        },
    )
    assert second_client.get("/api/dashboard").json()["total"] == 0
    assert second_client.get("/api/assessments").json() == []
    assert len(client.get("/api/assessments").json()) == 1


def test_assessment_is_saved_explained_and_filterable(client):
    assert signup(client).status_code == 201
    assessment = {
        "evidence_ref": "FS-2026-0042",
        "evidence_type": "Biological",
        "collection_conditions": "challenging",
        "ppe_compliant": False,
        "tool_condition": "clean",
        "packaging_condition": "intact",
        "storage_condition": "controlled",
        "separately_packaged": True,
        "chain_of_custody_documented": False,
    }
    response = client.post(
        "/api/assessments",
        headers=csrf_headers(client),
        json=assessment,
    )
    assert response.status_code == 201
    result = response.json()
    assert result["risk_category"] == "high"
    assert result["risk_score"] == 6
    assert result["risk_factors"]
    assert result["recommendations"]
    assert result["evidence_ref"] == assessment["evidence_ref"]

    assert client.get("/api/assessments?risk=high").json()[0]["id"] == result["id"]
    assert client.get("/api/assessments?risk=low").json() == []
    assert client.get("/api/dashboard").json()["high"] == 1


def test_rejects_bad_credentials_validation_and_missing_csrf(client):
    blocked = client.post(
        "/api/auth/signup",
        json={"full_name": "A", "email": "not-an-email", "password": "short"},
    )
    assert blocked.status_code == 403
    assert blocked.headers["x-content-type-options"] == "nosniff"

    cross_origin = client.post(
        "/api/auth/signup",
        headers={**csrf_headers(client), "Origin": "https://untrusted.example"},
        json={
            "full_name": "Case Analyst",
            "email": "analyst@example.org",
            "password": "Secure-Example-Passphrase-4",
        },
    )
    assert cross_origin.status_code == 403

    assert signup(client).status_code == 201
    login = client.post(
        "/api/auth/login",
        headers=csrf_headers(client),
        json={"email": "analyst@example.org", "password": "incorrect-password"},
    )
    assert login.status_code == 401
    duplicate = signup(client)
    assert duplicate.status_code == 409


def test_health_and_existing_web_interface_load(client):
    health = client.get("/health")
    interface = client.get("/")

    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert health.json()["experimental_model_loaded"] is True
    assert interface.status_code == 200
    assert "ForenSight AI" in interface.text
    assert client.get("/docs").status_code == 200


def test_prediction_is_authenticated_validated_and_logged(client, tmp_path, monkeypatch):
    from app import prediction_routes

    log_path = tmp_path / "logs" / "predictions.jsonl"
    monkeypatch.setattr(prediction_routes, "PREDICTION_LOG_PATH", log_path)
    assert signup(client).status_code == 201
    request_data = {
        "evidence_type": "Trace",
        "collection_conditions": "controlled",
        "ppe_compliant": True,
        "tool_condition": "clean",
        "packaging_condition": "intact",
        "storage_condition": "controlled",
        "separately_packaged": True,
        "chain_of_custody_documented": True,
    }

    response = client.post(
        "/predict",
        headers=csrf_headers(client),
        json=request_data,
    )
    result = response.json()

    assert response.status_code == 200
    assert result["prediction"] in {"synthetic_lower_risk", "synthetic_higher_risk"}
    assert result["dataset_type"] == "synthetic"
    assert "not validated for real-world forensic use" in result["disclaimer"]
    assert "simulated examples" in result["disclaimer"]
    assert sum(result["class_probabilities"].values()) == pytest.approx(1.0)
    assert log_path.is_file()
    entry = json.loads(log_path.read_text(encoding="utf-8").splitlines()[0])
    assert entry["features"] == request_data
    assert "timestamp" in entry
    assert "analyst@example.org" not in log_path.read_text(encoding="utf-8")

    invalid_requests = [
        {**request_data, "evidence_type": "unknown-kind"},
        {key: value for key, value in request_data.items() if key != "storage_condition"},
        {**request_data, "ppe_compliant": "true"},
        {**request_data, "extra_field": "not-allowed"},
    ]
    for invalid_request in invalid_requests:
        rejected = client.post(
            "/predict",
            headers=csrf_headers(client),
            json=invalid_request,
        )
        assert rejected.status_code == 422
    assert len(log_path.read_text(encoding="utf-8").splitlines()) == 1


def test_prediction_endpoint_requires_auth_and_handles_missing_model(client):
    request_data = {
        "evidence_type": "Trace",
        "collection_conditions": "controlled",
        "ppe_compliant": True,
        "tool_condition": "clean",
        "packaging_condition": "intact",
        "storage_condition": "controlled",
        "separately_packaged": True,
        "chain_of_custody_documented": True,
    }
    unauthorized = client.post(
        "/predict",
        headers=csrf_headers(client),
        json=request_data,
    )
    assert unauthorized.status_code == 401

    assert signup(client).status_code == 201
    client.app.state.model_artifact = None
    unavailable = client.post(
        "/predict",
        headers=csrf_headers(client),
        json=request_data,
    )
    assert unavailable.status_code == 503


def test_combined_workflow_is_idempotent_and_persists_both_results(
    client, tmp_path, monkeypatch
):
    import app.routes as routes_module
    from app.services.model_runtime import predict_with_artifact

    log_path = tmp_path / "predictions.jsonl"
    monkeypatch.setattr(routes_module, "PREDICTION_LOG_PATH", log_path)
    assert signup(client).status_code == 201
    assessment = {
        "evidence_ref": "WORKFLOW-001",
        "evidence_type": "Trace",
        "collection_conditions": "controlled",
        "ppe_compliant": True,
        "tool_condition": "clean",
        "packaging_condition": "intact",
        "storage_condition": "controlled",
        "separately_packaged": True,
        "chain_of_custody_documented": True,
    }
    key = "workflow-request-key-001"
    headers = {
        **csrf_headers(client),
        "Idempotency-Key": key,
    }

    response = client.post(
        "/api/assessments/workflow",
        headers=headers,
        json=assessment,
    )
    assert response.status_code == 201
    result = response.json()
    assert result["primary_screen"]["status"] == "succeeded"
    assert result["primary_screen"]["method"] == "preliminary_rule_based"
    assert result["assessment"]["risk_category"] == "low"
    assert result["experimental_classifier"]["status"] == "succeeded"
    prediction = result["experimental_classifier"]["result"]
    expected_prediction = predict_with_artifact(
        client.app.state.model_artifact,
        {
            key: value
            for key, value in assessment.items()
            if key != "evidence_ref"
        },
    )
    assert prediction["prediction"] in {
        "synthetic_lower_risk",
        "synthetic_higher_risk",
    }
    assert prediction["prediction"] == expected_prediction["prediction"]
    assert prediction["class_probabilities"] == pytest.approx(
        expected_prediction["class_probabilities"]
    )
    assert prediction["algorithm"] == expected_prediction["algorithm"]
    assert sum(prediction["class_probabilities"].values()) == pytest.approx(1.0)

    repeated = client.post(
        "/api/assessments/workflow",
        headers={**csrf_headers(client), "Idempotency-Key": key},
        json=assessment,
    )
    assert repeated.status_code == 201
    assert repeated.json() == result
    assert client.get(
        f"/api/assessments/{result['assessment']['id']}/workflow"
    ).json() == result

    changed_payload = {**assessment, "evidence_type": "Digital"}
    key_reuse = client.post(
        "/api/assessments/workflow",
        headers={**csrf_headers(client), "Idempotency-Key": key},
        json=changed_payload,
    )
    duplicate_reference = client.post(
        "/api/assessments/workflow",
        headers={
            **csrf_headers(client),
            "Idempotency-Key": "workflow-request-key-002",
        },
        json=assessment,
    )
    assert key_reuse.status_code == 409
    assert duplicate_reference.status_code == 409

    connection = database.connect()
    try:
        assert connection.execute("SELECT COUNT(*) FROM assessments").fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM assessment_workflow_results"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM assessment_idempotency_keys"
        ).fetchone()[0] == 1
    finally:
        connection.close()
    assert len(log_path.read_text(encoding="utf-8").splitlines()) == 1

    database.initialize_database()
    connection = database.connect()
    try:
        assert connection.execute("SELECT COUNT(*) FROM assessments").fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM assessment_workflow_results"
        ).fetchone()[0] == 1
    finally:
        connection.close()


def test_failed_classifier_can_be_retried_without_duplicate_assessment(
    client, tmp_path, monkeypatch
):
    import app.routes as routes_module

    monkeypatch.setattr(
        routes_module, "PREDICTION_LOG_PATH", tmp_path / "predictions.jsonl"
    )
    assert signup(client).status_code == 201
    artifact = client.app.state.model_artifact
    client.app.state.model_artifact = None
    assessment = {
        "evidence_ref": "WORKFLOW-RETRY-001",
        "evidence_type": "Biological",
        "collection_conditions": "challenging",
        "ppe_compliant": False,
        "tool_condition": "clean",
        "packaging_condition": "intact",
        "storage_condition": "controlled",
        "separately_packaged": True,
        "chain_of_custody_documented": False,
    }

    response = client.post(
        "/api/assessments/workflow",
        headers={
            **csrf_headers(client),
            "Idempotency-Key": "workflow-retry-request-001",
        },
        json=assessment,
    )
    assert response.status_code == 201
    failed = response.json()
    assert failed["assessment"]["risk_category"] == "high"
    assert failed["experimental_classifier"]["status"] == "failed"
    assert failed["experimental_classifier"]["result"] is None

    client.app.state.model_artifact = artifact
    retried = client.post(
        f"/api/assessments/{failed['assessment']['id']}/workflow/retry",
        headers=csrf_headers(client),
    )
    assert retried.status_code == 200
    completed = retried.json()
    assert completed["assessment"]["id"] == failed["assessment"]["id"]
    assert completed["experimental_classifier"]["status"] == "succeeded"
    assert len(client.get("/api/assessments").json()) == 1


def test_workspace_removes_model_insights_and_prediction_preview(client):
    page = client.get("/").text
    workspace = page.split('<div id="workspace"', maxsplit=1)[1]

    assert 'data-view="model"' not in workspace
    assert 'id="view-model"' not in workspace
    assert "Synthetic model preview" not in workspace
    assert "Synthetic" not in workspace
    assert 'id="run-experimental-prediction"' not in workspace
    assert "Submit evidence" in workspace


def test_experimental_model_is_loaded_once_during_application_startup(
    tmp_path, monkeypatch
):
    import app.main as main_module

    monkeypatch.setattr(database, "DATABASE_PATH", tmp_path / "startup.sqlite3")
    load_count = 0

    def fake_load():
        nonlocal load_count
        load_count += 1
        return {"test_model": True}

    monkeypatch.setattr(main_module, "load_model_artifact", fake_load)
    with TestClient(app) as test_client:
        assert test_client.get("/health").json()["experimental_model_loaded"] is True
        assert test_client.get("/health").json()["experimental_model_loaded"] is True
        assert load_count == 1


def test_assessment_reference_cannot_be_reused(client):
    assert signup(client).status_code == 201
    payload = {
        "evidence_ref": "ITEM-001",
        "evidence_type": "Trace",
        "collection_conditions": "controlled",
        "ppe_compliant": True,
        "tool_condition": "clean",
        "packaging_condition": "intact",
        "storage_condition": "controlled",
        "separately_packaged": True,
        "chain_of_custody_documented": True,
    }
    first = client.post(
        "/api/assessments", headers=csrf_headers(client), json=payload
    )
    second = client.post(
        "/api/assessments", headers=csrf_headers(client), json=payload
    )
    assert first.status_code == 201
    assert second.status_code == 409
    assert first.json()["risk_category"] == "low"
