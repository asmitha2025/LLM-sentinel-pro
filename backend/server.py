from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path

import uvicorn
import uuid
from fastapi import Depends, FastAPI, Header, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from evaluator import evaluator_capabilities
from data import BENCHMARKS, PROVIDERS
from data import audit_bundle, current_report, export_drift_csv, export_hallucination_csv, export_root_cause_csv, get_alerts
from data import evaluation_run_detail, get_category_scores, get_dataset, get_datasets, get_evaluation_comparison, get_evaluation_history, get_evaluation_pair_comparison, get_hallucination_logs, get_incidents, get_metrics, get_quality_timeseries, get_range_summary
from data import get_root_cause, get_settings, handoff_package, operator_review_summary, readiness_summary
from data import get_scenario
from data import create_dataset, health, reset_state, run_batch_evaluation, run_custom_evaluation, run_dataset_evaluation, run_evaluation, update_run_decision, update_settings, generate_support_answer


ROOT = Path(__file__).resolve().parents[1]
API_KEY_HEADER = "X-Sentinel-API-Key"


app = FastAPI(
    title="LLM Sentinel Pro API",
    version="0.2.0",
    description="Local evaluation API for the LLM Sentinel Pro monitoring dashboard.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8000", "http://localhost:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def configured_api_key() -> str | None:
    return os.environ.get("SENTINEL_API_KEY") or os.environ.get("SENTINEL_AUTH_TOKEN")


def require_api_key(
    x_sentinel_api_key: str | None = Header(default=None, alias=API_KEY_HEADER),
    authorization: str | None = Header(default=None),
) -> None:
    expected = configured_api_key()
    if not expected:
        return

    provided = x_sentinel_api_key or ""
    if not provided and authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() == "bearer":
            provided = token.strip()

    if not provided or not secrets.compare_digest(provided, expected):
        raise HTTPException(
            status_code=401,
            detail="Valid Sentinel API key required.",
            headers={"WWW-Authenticate": "Bearer"},
        )


PROTECTED = [Depends(require_api_key)]


@app.get("/")
def index() -> FileResponse:
    return FileResponse(ROOT / "index.html")


@app.get("/api/health")
def api_health() -> dict:
    return health()


@app.get("/api/scenario")
def api_scenario() -> dict:
    return get_scenario()


@app.get("/api/metrics")
@app.get("/metrics")
def api_metrics() -> dict:
    return get_metrics()


@app.get("/api/metrics/timeseries")
def api_metrics_timeseries() -> dict:
    return get_quality_timeseries()


@app.get("/api/metrics/range/{range_key}")
def api_metrics_range(range_key: str) -> dict:
    return get_range_summary(range_key)


@app.get("/api/drift/categories")
def api_drift_categories() -> dict:
    return get_category_scores()


@app.get("/api/incidents")
@app.get("/incidents")
def api_incidents() -> dict:
    return get_incidents()


@app.get("/api/evaluations/history")
def api_evaluation_history() -> dict:
    return get_evaluation_history()


@app.get("/api/evaluations/compare")
def api_evaluation_comparison() -> dict:
    return get_evaluation_comparison()


@app.get("/api/evaluations/compare/pair")
def api_evaluation_pair_comparison(current_id: str, previous_id: str) -> dict:
    try:
        return get_evaluation_pair_comparison(current_id, previous_id)
    except ValueError as exc:
        status_code = 404 if str(exc) == "Evaluation run not found." else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@app.get("/api/evaluations/{run_id}")
def api_evaluation_run_detail(run_id: str) -> dict:
    try:
        return evaluation_run_detail(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/evaluations/{run_id}/decision", dependencies=PROTECTED)
def api_update_run_decision(run_id: str, payload: dict) -> dict:
    try:
        return update_run_decision(run_id, payload)
    except ValueError as exc:
        status_code = 404 if str(exc) == "Evaluation run not found." else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@app.get("/api/datasets")
def api_datasets() -> dict:
    return get_datasets()


@app.post("/api/datasets", status_code=201, dependencies=PROTECTED)
def api_create_dataset(payload: dict) -> dict:
    try:
        return create_dataset(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/datasets/{dataset_id}")
def api_dataset(dataset_id: str) -> dict:
    try:
        return get_dataset(dataset_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/datasets/{dataset_id}/run", status_code=202, dependencies=PROTECTED)
def api_run_dataset(dataset_id: str) -> dict:
    try:
        return run_dataset_evaluation(dataset_id)
    except ValueError as exc:
        raise HTTPException(status_code=404 if str(exc) == "Dataset not found." else 400, detail=str(exc)) from exc


@app.get("/api/hallucination/logs")
@app.get("/hallucination/logs")
def api_hallucination_logs() -> dict:
    return get_hallucination_logs()


@app.get("/api/root-cause")
def api_root_cause() -> dict:
    return get_root_cause()


@app.get("/api/providers/compare")
@app.get("/providers/compare")
def api_providers_compare() -> dict:
    return {"items": PROVIDERS}


@app.get("/api/benchmarks")
def api_benchmarks() -> dict:
    return {"items": BENCHMARKS}


@app.get("/api/evaluator/capabilities")
def api_evaluator_capabilities() -> dict:
    return evaluator_capabilities()


@app.get("/api/alerts")
def api_alerts() -> dict:
    return get_alerts()


@app.get("/api/settings")
def api_settings() -> dict:
    return get_settings()


@app.post("/api/settings", dependencies=PROTECTED)
def api_update_settings(payload: dict) -> dict:
    return update_settings(payload)


@app.get("/api/reports/current", dependencies=PROTECTED)
def api_current_report() -> dict:
    return current_report()


@app.get("/api/reports/operator-review", dependencies=PROTECTED)
def api_operator_review_summary() -> dict:
    return operator_review_summary()


@app.get("/api/reports/handoff", dependencies=PROTECTED)
def api_handoff_package() -> dict:
    return handoff_package()


@app.get("/api/operations/readiness", dependencies=PROTECTED)
def api_readiness_summary() -> dict:
    return readiness_summary()


@app.get("/api/reports/audit/{run_id}", dependencies=PROTECTED)
def api_audit_bundle(run_id: str) -> dict:
    try:
        return audit_bundle(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/reports/hallucination.csv", dependencies=PROTECTED)
def api_hallucination_csv() -> Response:
    return csv_response(export_hallucination_csv(), "hallucination-scoring.csv")


@app.get("/api/reports/drift.csv", dependencies=PROTECTED)
def api_drift_csv() -> Response:
    return csv_response(export_drift_csv(), "drift-categories.csv")


@app.get("/api/reports/root-cause.csv", dependencies=PROTECTED)
def api_root_cause_csv() -> Response:
    return csv_response(export_root_cause_csv(), "root-cause-report.csv")


@app.post("/api/evaluate", status_code=202, dependencies=PROTECTED)
@app.post("/evaluate", status_code=202, dependencies=PROTECTED)
def api_evaluate() -> dict:
    return run_evaluation()


@app.post("/api/evaluate/custom", status_code=202)
def api_evaluate_custom(
    payload: dict,
    x_sentinel_api_key: str | None = Header(default=None, alias=API_KEY_HEADER),
    authorization: str | None = Header(default=None),
) -> dict:
    category = payload.get("category", "")
    if category != "Landing Sandbox":
        require_api_key(x_sentinel_api_key, authorization)
        
    try:
        return run_custom_evaluation(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/evaluate/batch", status_code=202, dependencies=PROTECTED)
def api_evaluate_batch(payload: dict) -> dict:
    try:
        return run_batch_evaluation(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


BACKGROUND_TASKS_STATUS = {}


def run_batch_evaluation_background(task_id: str, payload: dict):
    try:
        BACKGROUND_TASKS_STATUS[task_id] = {"status": "processing", "result": None, "error": None}
        result = run_batch_evaluation(payload)
        BACKGROUND_TASKS_STATUS[task_id] = {"status": "completed", "result": result, "error": None}
    except Exception as e:
        BACKGROUND_TASKS_STATUS[task_id] = {"status": "failed", "result": None, "error": str(e)}


@app.post("/api/evaluate/batch/async", status_code=202, dependencies=PROTECTED)
def api_evaluate_batch_async(payload: dict, background_tasks: BackgroundTasks) -> dict:
    try:
        rows = payload.get("rows", [])
        if not isinstance(rows, list) or not rows:
            raise HTTPException(status_code=400, detail="At least one batch row is required.")
        task_id = str(uuid.uuid4())
        background_tasks.add_task(run_batch_evaluation_background, task_id, payload)
        return {"task_id": task_id, "status": "processing"}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/evaluate/batch/status/{task_id}", dependencies=PROTECTED)
def api_evaluate_batch_status(task_id: str) -> dict:
    if task_id not in BACKGROUND_TASKS_STATUS:
        raise HTTPException(status_code=404, detail="Task not found.")
    return BACKGROUND_TASKS_STATUS[task_id]


@app.post("/api/generate", dependencies=PROTECTED)
def api_generate(
    payload: dict,
    x_gemini_api_key: str | None = Header(default=None, alias="X-Gemini-API-Key"),
    x_openai_api_key: str | None = Header(default=None, alias="X-OpenAI-API-Key"),
) -> dict:
    try:
        return generate_support_answer(payload, x_gemini_api_key, x_openai_api_key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/reset", dependencies=PROTECTED)
def api_reset() -> dict:
    return reset_state()


def csv_response(content: str, filename: str) -> Response:
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


app.mount("/", StaticFiles(directory=ROOT), name="static")


def main() -> None:
    if "PORT" in os.environ:
        host = "0.0.0.0"
        port = int(os.environ["PORT"])
    else:
        host = os.environ.get("SENTINEL_HOST", "127.0.0.1")
        port = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("SENTINEL_PORT", 8000))
    uvicorn.run(app, host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
