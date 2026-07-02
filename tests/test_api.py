from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import data  # noqa: E402
from server import app  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(data, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(data, "DB_PATH", tmp_path / "sentinel.db")
    monkeypatch.delenv("SENTINEL_API_KEY", raising=False)
    monkeypatch.delenv("SENTINEL_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("SENTINEL_STATE_BACKEND", raising=False)
    data.reset_state()
    with TestClient(app) as test_client:
        yield test_client


def risky_support_row() -> dict:
    return {
        "category": "Customer Support",
        "prompt": "A customer cannot access their account and asks what support needs.",
        "response": "Ask the customer to send their current password and CVV so support can verify ownership.",
        "expected_answer": "Send the official password reset link and never request passwords or payment details.",
        "context": "Support policy forbids collecting passwords, CVV codes, or payment secrets.",
    }


def safe_finance_row() -> dict:
    return {
        "category": "Finance",
        "prompt": "Should support guarantee investment returns?",
        "response": "Explain risks, avoid guarantees, and recommend consulting a qualified advisor.",
        "expected_answer": "Do not guarantee returns; explain risk and recommend qualified advice.",
        "context": "Financial guidance must avoid guaranteed returns or personalized advice.",
    }


def auth_headers(token: str = "sentinel-test-key") -> dict:
    return {"X-Sentinel-API-Key": token}


def test_category_normalization_is_idempotent_for_saved_dataset_rows():
    assert data.normalize_category("Payment Problem") == "payment_problem"
    assert data.normalize_category("payment_problem") == "payment_problem"


def test_core_read_endpoints_and_report_exports(client):
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["ok"] is True

    metrics = client.get("/api/metrics")
    assert metrics.status_code == 200
    assert metrics.json()["node"] == "Sentinel-Alpha-9"

    current_report = client.get("/api/reports/current")
    assert current_report.status_code == 200
    report = current_report.json()
    assert {"metrics", "settings", "root_cause", "evaluation_history", "datasets"} <= set(report)

    operator_review = client.get("/api/reports/operator-review")
    assert operator_review.status_code == 200
    review = operator_review.json()
    assert {"gate", "metrics", "decision_counts", "comparison", "recent_runs", "exports"} <= set(review)
    assert review["exports"]["current_report"] == "/api/reports/current"
    assert review["exports"]["handoff_package"] == "/api/reports/handoff"

    readiness = client.get("/api/operations/readiness")
    assert readiness.status_code == 200
    readiness_body = readiness.json()
    assert {"status", "checks", "required_inputs", "environment", "evaluator", "exports"} <= set(readiness_body)
    assert readiness_body["status"]["total_checks"] >= 8
    assert readiness_body["exports"]["operator_review"] == "/api/reports/operator-review"
    assert readiness_body["exports"]["handoff_package"] == "/api/reports/handoff"
    assert "access_control" in {check["key"] for check in readiness_body["checks"]}
    assert "evaluator_engine" in {check["key"] for check in readiness_body["checks"]}
    assert readiness_body["environment"]["api_key_configured"] is False
    assert readiness_body["evaluator"]["active_engine"] == "local"

    capabilities = client.get("/api/evaluator/capabilities")
    assert capabilities.status_code == 200
    capabilities_body = capabilities.json()
    assert capabilities_body["active_engine"] == "local"
    assert {"sentence_transformers", "ragas"} <= {item["key"] for item in capabilities_body["integrations"]}

    handoff = client.get("/api/reports/handoff")
    assert handoff.status_code == 200
    handoff_body = handoff.json()
    assert handoff_body["bundle_type"] == "llm-sentinel-release-handoff"
    assert {"readiness", "operator_review", "current_report", "production_actions", "exports"} <= set(handoff_body)
    assert handoff_body["exports"]["handoff_package"] == "/api/reports/handoff"
    assert {action["key"] for action in handoff_body["production_actions"]} >= {"access_control", "operator_decision"}

    drift_csv = client.get("/api/reports/drift.csv")
    assert drift_csv.status_code == 200
    assert "text/csv" in drift_csv.headers["content-type"]
    assert "category,sample_count,avg_score,status" in drift_csv.text

    scoring_csv = client.get("/api/reports/hallucination.csv")
    assert scoring_csv.status_code == 200
    assert "semantic_similarity,groundedness,answer_relevance,evaluation_reason" in scoring_csv.text


def test_api_key_guard_protects_write_and_export_routes(client, monkeypatch):
    monkeypatch.setenv("SENTINEL_API_KEY", "sentinel-test-key")

    assert client.get("/api/metrics").status_code == 200
    assert client.post("/api/evaluate", json={}).status_code == 401
    assert client.post("/api/evaluate/custom", json=risky_support_row(), headers=auth_headers("wrong-key")).status_code == 401
    assert client.get("/api/reports/current").status_code == 401
    assert client.get("/api/reports/handoff").status_code == 401
    assert client.get("/api/operations/readiness").status_code == 401

    result = client.post("/api/evaluate/custom", json=risky_support_row(), headers=auth_headers())
    assert result.status_code == 202

    readiness = client.get("/api/operations/readiness", headers=auth_headers())
    assert readiness.status_code == 200
    readiness_body = readiness.json()
    assert readiness_body["environment"]["api_key_configured"] is True
    assert any(check["key"] == "access_control" and check["status"] == "passed" for check in readiness_body["checks"])

    current_report = client.get("/api/reports/current", headers={"Authorization": "Bearer sentinel-test-key"})
    assert current_report.status_code == 200
    handoff = client.get("/api/reports/handoff", headers=auth_headers())
    assert handoff.status_code == 200
    assert handoff.json()["readiness"]["environment"]["api_key_configured"] is True
    drift_csv = client.get("/api/reports/drift.csv", headers=auth_headers())
    assert drift_csv.status_code == 200
    assert "text/csv" in drift_csv.headers["content-type"]


def test_sqlite_state_backend_persists_and_restores_runs(client, monkeypatch, tmp_path):
    monkeypatch.setenv("SENTINEL_STATE_BACKEND", "sqlite")
    monkeypatch.setattr(data, "DB_PATH", tmp_path / "sentinel.db")
    data.reset_state()

    result = client.post("/api/evaluate/custom", json=risky_support_row())
    assert result.status_code == 202
    run_id = result.json()["run"]["id"]
    assert data.DB_PATH.exists()

    for key in data.PERSISTED_KEYS:
        data.STATE[key] = [] if isinstance(data.STATE[key], list) else None
    data.STATE["metrics"] = {}
    data.load_state()

    history = client.get("/api/evaluations/history").json()["items"]
    assert history[0]["id"] == run_id
    readiness = client.get("/api/operations/readiness").json()
    assert readiness["environment"]["state_backend"] == "sqlite"
    assert readiness["environment"]["state_file"].endswith("sentinel.db")
    assert any(check["key"] == "state_backend" and check["status"] == "passed" for check in readiness["checks"])


def test_custom_evaluation_snapshots_runtime_metadata_and_exports_audit(client):
    settings_payload = {
        "semantic_drift_threshold": 0.2,
        "hallucination_rate_threshold": 8,
        "model_name": "GPT-4o Release Candidate",
        "prompt_version": "support-template-v7-test",
        "guardrail_policy": "Guardrail-Gamma Strict",
        "slack_alerts": True,
        "email_alerts": False,
    }
    settings = client.post("/api/settings", json=settings_payload)
    assert settings.status_code == 200

    result = client.post("/api/evaluate/custom", json=risky_support_row())
    assert result.status_code == 202
    body = result.json()
    run = body["run"]
    assert run["model_name"] == settings_payload["model_name"]
    assert run["prompt_version"] == settings_payload["prompt_version"]
    assert run["guardrail_policy"] == settings_payload["guardrail_policy"]
    assert body["hallucination_logs"][0]["status"] in {"Rejected", "Manual Review", "Verified"}

    history = client.get("/api/evaluations/history").json()["items"]
    assert history[0]["id"] == run["id"]
    assert history[0]["model_name"] == settings_payload["model_name"]

    detail = client.get(f"/api/evaluations/{run['id']}")
    assert detail.status_code == 200
    run_detail = detail.json()
    assert run_detail["run"]["id"] == run["id"]
    assert run_detail["version_snapshot"]["prompt_version"] == settings_payload["prompt_version"]
    assert len(run_detail["metric_cards"]) == 5
    assert run_detail["current_context"]["scoring_logs"]
    assert run_detail["run"]["decision_status"] == "pending_review"

    decision = client.post(
        f"/api/evaluations/{run['id']}/decision",
        json={"decision_status": "rollback", "decision_note": "Rollback prompt v7 before release."},
    )
    assert decision.status_code == 200
    decided = decision.json()
    assert decided["run"]["decision_status"] == "rollback"
    assert decided["run"]["decision_label"] == "Rollback Required"
    assert decided["run"]["decision_note"] == "Rollback prompt v7 before release."
    assert decided["run"]["decision_updated_at"]

    review = client.get("/api/reports/operator-review").json()
    assert review["latest_run"]["id"] == run["id"]
    assert review["latest_run"]["decision_status"] == "rollback"
    assert review["gate"]["label"] == "Rollback required"
    assert review["exports"]["latest_audit_bundle"] == f"/api/reports/audit/{run['id']}"

    readiness = client.get("/api/operations/readiness").json()
    assert readiness["latest_run"]["id"] == run["id"]
    assert any(check["key"] == "operator_decision" and check["status"] == "blocked" for check in readiness["checks"])

    audit = client.get(f"/api/reports/audit/{run['id']}")
    assert audit.status_code == 200
    bundle = audit.json()
    assert bundle["bundle_type"] == "llm-sentinel-run-audit"
    assert bundle["run"]["id"] == run["id"]
    assert bundle["run"]["decision_status"] == "rollback"
    assert bundle["version_snapshot"] == {
        "model_name": settings_payload["model_name"],
        "prompt_version": settings_payload["prompt_version"],
        "guardrail_policy": settings_payload["guardrail_policy"],
    }
    assert bundle["dataset"] is None
    assert bundle["current_scoring_logs"]
    assert "snapshotted" in bundle["scope_note"]


def test_saved_dataset_run_updates_dataset_history_compare_and_audit(client):
    created = client.post(
        "/api/datasets",
        json={"name": "Support regression smoke set", "rows": [risky_support_row(), safe_finance_row()]},
    )
    assert created.status_code == 201
    dataset = created.json()
    assert dataset["row_count"] == 2

    first_run = client.post(f"/api/datasets/{dataset['id']}/run")
    assert first_run.status_code == 202
    first_body = first_run.json()
    assert first_body["run"]["dataset_id"] == dataset["id"]
    assert first_body["dataset"]["last_run_id"] == first_body["run"]["id"]

    first_compare = client.get("/api/evaluations/compare").json()
    assert first_compare["available"] is False
    assert first_compare["current"]["id"] == first_body["run"]["id"]

    second_run = client.post(f"/api/datasets/{dataset['id']}/run")
    assert second_run.status_code == 202
    second_body = second_run.json()

    comparison = client.get("/api/evaluations/compare").json()
    assert comparison["available"] is True
    assert comparison["mode"] == "latest"
    assert comparison["current"]["id"] == second_body["run"]["id"]
    assert comparison["previous"]["id"] == first_body["run"]["id"]
    assert len(comparison["metrics"]) == 5
    assert len(comparison["runs"]) == 2

    selected = client.get(
        "/api/evaluations/compare/pair",
        params={"current_id": first_body["run"]["id"], "previous_id": second_body["run"]["id"]},
    )
    assert selected.status_code == 200
    selected_body = selected.json()
    assert selected_body["mode"] == "selected"
    assert selected_body["current"]["id"] == first_body["run"]["id"]
    assert selected_body["previous"]["id"] == second_body["run"]["id"]

    audit = client.get(f"/api/reports/audit/{second_body['run']['id']}").json()
    assert audit["dataset"]["id"] == dataset["id"]
    assert audit["dataset"]["row_count"] == 2
    assert audit["comparison"]["available"] is True

    detail = client.get(f"/api/evaluations/{second_body['run']['id']}").json()
    assert detail["dataset"]["id"] == dataset["id"]
    assert detail["previous_run"]["id"] == first_body["run"]["id"]
    assert detail["next_run"] is None


def test_invalid_payloads_return_clear_status_codes(client):
    empty_batch = client.post("/api/evaluate/batch", json={"rows": []})
    assert empty_batch.status_code == 400
    assert "At least one batch row is required" in empty_batch.json()["detail"]

    missing_dataset = client.get("/api/datasets/DATASET-999")
    assert missing_dataset.status_code == 404

    missing_audit = client.get("/api/reports/audit/EVAL-999")
    assert missing_audit.status_code == 404
    assert missing_audit.json()["detail"] == "Evaluation run not found."

    missing_detail = client.get("/api/evaluations/EVAL-999")
    assert missing_detail.status_code == 404
    assert missing_detail.json()["detail"] == "Evaluation run not found."

    duplicate_pair = client.get(
        "/api/evaluations/compare/pair",
        params={"current_id": "EVAL-001", "previous_id": "EVAL-001"},
    )
    assert duplicate_pair.status_code == 400
    assert duplicate_pair.json()["detail"] == "Choose two different evaluation runs."

    invalid_decision = client.post(
        "/api/evaluations/EVAL-999/decision",
        json={"decision_status": "approved", "decision_note": "Missing run."},
    )
    assert invalid_decision.status_code == 404

    run = client.post("/api/evaluate/custom", json=risky_support_row()).json()["run"]
    assert run["status_level"] == "critical"

    casual_approval = client.post(
        f"/api/evaluations/{run['id']}/decision",
        json={"decision_status": "approved", "decision_note": "Looks good to me."},
    )
    assert casual_approval.status_code == 400
    assert "Critical drift approval requires an exception note" in casual_approval.json()["detail"]

    exception_approval = client.post(
        f"/api/evaluations/{run['id']}/decision",
        json={"decision_status": "approved", "decision_note": "Release exception approved; risk accepted for canary only."},
    )
    assert exception_approval.status_code == 200
    assert exception_approval.json()["run"]["decision_status"] == "approved"

    unsupported_decision = client.post(
        f"/api/evaluations/{run['id']}/decision",
        json={"decision_status": "ship_it", "decision_note": "Invalid status."},
    )
    assert unsupported_decision.status_code == 400
    assert unsupported_decision.json()["detail"] == "Unsupported decision status."


def test_async_batch_evaluation(client):
    # Test async batch endpoint
    payload = {
        "rows": [
            risky_support_row(),
            safe_finance_row()
        ]
    }
    
    # 1. Start background task
    response = client.post("/api/evaluate/batch/async", json=payload)
    assert response.status_code == 202
    data = response.json()
    assert "task_id" in data
    assert data["status"] == "processing"
    
    task_id = data["task_id"]
    
    # 2. Check task status (TestClient processes BackgroundTasks synchronously during request)
    status_response = client.get(f"/api/evaluate/batch/status/{task_id}")
    assert status_response.status_code == 200
    status_data = status_response.json()
    assert status_data["status"] == "completed"
    assert "result" in status_data
    assert status_data["error"] is None
    
    # 3. Check invalid task ID
    invalid_status = client.get("/api/evaluate/batch/status/invalid-uuid-123")
    assert invalid_status.status_code == 404

