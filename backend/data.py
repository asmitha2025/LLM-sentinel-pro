from __future__ import annotations

import csv
import io
import json
import os
import sqlite3
import tempfile
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

from evaluator import evaluate_dataset, evaluate_samples, evaluator_capabilities


ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DATASET = ROOT / "datasets" / "sentinel_eval_samples.csv"
STATE_PATH = ROOT / "backend" / "state.json"
DB_PATH = Path(tempfile.gettempdir()) / "llm-sentinel-pro" / "sentinel.db"
STATE_VERSION = 1
STATE_ROW_ID = "default"


INITIAL_METRICS = {
    "node": "Sentinel-Alpha-9",
    "system_status": "System Healthy",
    "status_level": "healthy",
    "semantic_drift": 0.142,
    "hallucination_rate": 2.1,
    "statistical_drift": 0.05,
    "latency_ms": 842,
    "cost_delta": -12.40,
    "confidence": 84,
    "updated_at": "2026-05-24T12:30:00+05:30",
}

CRITICAL_METRICS = {
    **INITIAL_METRICS,
    "system_status": "Critical Drift",
    "status_level": "critical",
    "semantic_drift": 0.318,
    "hallucination_rate": 14.8,
    "statistical_drift": 0.82,
    "latency_ms": 2441,
    "confidence": 94,
}

DEFAULT_SETTINGS = {
    "semantic_drift_threshold": 0.30,
    "hallucination_rate_threshold": 10.0,
    "slack_alerts": True,
    "email_alerts": True,
    "model_name": "GPT-4o Support Primary",
    "prompt_version": "support-template-v4",
    "guardrail_policy": "Guardrail-Alpha Strict",
}

RANGE_WINDOWS = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}

INITIAL_TIMESERIES = [
    {"label": "T-6", "accuracy": 0.92, "safety": 0.95},
    {"label": "T-5", "accuracy": 0.91, "safety": 0.94},
    {"label": "T-4", "accuracy": 0.93, "safety": 0.95},
    {"label": "T-3", "accuracy": 0.90, "safety": 0.93},
    {"label": "T-2", "accuracy": 0.91, "safety": 0.94},
    {"label": "T-1", "accuracy": 0.89, "safety": 0.92},
    {"label": "Now", "accuracy": 0.92, "safety": 0.95},
]

SCENARIO = {
    "title": "Support Assistant Regression After Prompt Template Update",
    "monitoring_node": "Sentinel-Alpha-9",
    "model_surface": "Customer Support Copilot",
    "audience": "AI reliability, safety, and support operations teams",
    "change_event": "Prompt template v4 shipped with broader answer-completion instructions.",
    "demo_story": (
        "A production support assistant begins giving unsupported or unsafe answers after a prompt "
        "template update. Sentinel evaluates sampled responses, detects hallucination and drift, "
        "opens alerts, and produces a root-cause report for review."
    ),
    "primary_finding": {
        "title": "Unsafe support-policy regression",
        "detail": "Password, medical, financial, and legal responses include unsupported instructions that require review.",
    },
    "secondary_finding": {
        "title": "Cross-domain faithfulness drift",
        "detail": "The regression is not isolated to one prompt; multiple high-risk categories diverge from expected answers.",
    },
    "correlation_note": (
        "The strongest signal correlates with the prompt-template rollout: higher completion freedom "
        "increases unsupported claims across high-risk support workflows."
    ),
}

INCIDENTS = [
    {
        "id": "INC-9421-RCA",
        "severity": "critical",
        "title": "Support assistant prompt template regression",
        "summary": "Prompt template v4 produced unsupported high-risk support guidance.",
        "affected_area": "Support Bot",
        "status": "Open",
        "owner": "Safety",
        "started_at": "14:02:11",
        "duration": "14m 22s",
        "impact_radius": "1,242 Sessions",
        "confidence": 94,
        "risk_level": "Critical",
        "timeline": [
            {"time": "14:02:11", "label": "Anomalous Prompt Detected", "level": "neutral"},
            {"time": "14:03:45", "label": "Safety Guardrail Bypassed", "level": "danger"},
            {"time": "14:12:00", "label": "Auto-containment Active", "level": "blue"},
            {"time": "14:16:33", "label": "System Normalized", "level": "green"},
        ],
        "evidence": [
            {
                "timestamp": "14:03:44.022",
                "trace_id": "tr_827x_m91",
                "signal_type": "Injected Prompt",
                "level": "red",
                "details": "Detection of DAN-variant prompt payload.",
            },
            {
                "timestamp": "14:04:12.101",
                "trace_id": "tr_827x_m94",
                "signal_type": "Token Surge",
                "level": "amber",
                "details": "Prompt token count exceeded baseline by 128%.",
            },
            {
                "timestamp": "14:11:55.783",
                "trace_id": "tr_827x_m99",
                "signal_type": "Containment",
                "level": "green",
                "details": "Policy route moved to high-safety model.",
            },
        ],
    }
]

PROVIDERS = [
    {"provider": "OpenAI", "model": "GPT-4o", "truthfulqa": "88.4%", "hallucination": "4.8%", "latency": "842ms", "cost": "$0.005", "decision": "Primary", "tone": "green"},
    {"provider": "Anthropic", "model": "Claude Sonnet", "truthfulqa": "86.9%", "hallucination": "5.2%", "latency": "910ms", "cost": "$0.006", "decision": "Fallback", "tone": "green"},
    {"provider": "Google", "model": "Gemini", "truthfulqa": "83.1%", "hallucination": "7.6%", "latency": "760ms", "cost": "$0.004", "decision": "Review", "tone": "amber"},
    {"provider": "Meta", "model": "Llama", "truthfulqa": "76.8%", "hallucination": "11.4%", "latency": "620ms", "cost": "$0.001", "decision": "Low Cost", "tone": "amber"},
]

BENCHMARKS = [
    {"name": "TruthfulQA", "score": "88.4%", "note": "Strong factual consistency on in-domain examples."},
    {"name": "MMLU", "score": "81.6%", "note": "Stable general reasoning across sampled categories."},
    {"name": "GSM8K", "score": "74.2%", "note": "Moderate arithmetic reliability under temperature variance."},
    {"name": "OOD Diagnosis", "score": "62.0%", "note": "Known limitation: novel root causes need human review."},
]

ALERTS = [
    {
        "severity": "Warning",
        "tone": "amber",
        "incident": "Latency Spike",
        "summary": "P99 response time increased above baseline.",
        "affected_area": "API Gateway",
        "status": "Watching",
        "owner": "Platform",
        "age": "15m ago",
    },
    {
        "severity": "Policy",
        "tone": "green",
        "incident": "Drift Recalibrated",
        "summary": "Baseline drift profile updated for Legal QA.",
        "affected_area": "Legal QA",
        "status": "Resolved",
        "owner": "Evaluation",
        "age": "3h ago",
    },
]


STATE = {
    "metrics": deepcopy(INITIAL_METRICS),
    "settings": deepcopy(DEFAULT_SETTINGS),
    "evaluation_count": 2450,
    "last_event": None,
    "category_scores": [],
    "hallucination_logs": [],
    "evidence": [],
    "root_cause": None,
    "timeline": [],
    "signals": [],
    "quality_timeseries": deepcopy(INITIAL_TIMESERIES),
    "evaluation_runs": [],
    "datasets": [],
}

PERSISTED_KEYS = [
    "metrics",
    "settings",
    "evaluation_count",
    "last_event",
    "category_scores",
    "hallucination_logs",
    "evidence",
    "root_cause",
    "timeline",
    "signals",
    "quality_timeseries",
    "evaluation_runs",
    "datasets",
]


def configured_state_backend() -> str:
    raw_backend = os.environ.get("SENTINEL_STATE_BACKEND", "local-json").strip().lower()
    if raw_backend in {"sqlite", "sqlite3"}:
        return "sqlite"
    return "local-json"


def state_storage_path() -> Path:
    if configured_state_backend() == "sqlite":
        return Path(os.environ.get("SENTINEL_DB_PATH", str(DB_PATH))).expanduser()
    return STATE_PATH


def build_state_payload() -> dict:
    return {
        "version": STATE_VERSION,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "state": {key: deepcopy(STATE[key]) for key in PERSISTED_KEYS},
    }


def apply_state_payload(payload: dict) -> bool:
    if payload.get("version") != STATE_VERSION:
        return False
    persisted = payload.get("state", {})
    for key in PERSISTED_KEYS:
        if key in persisted:
            STATE[key] = persisted[key]
    return True


def save_state_json(payload: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_state_json() -> None:
    if not STATE_PATH.exists():
        return
    try:
        payload = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    apply_state_payload(payload)


def ensure_sqlite_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS sentinel_state (
            id TEXT PRIMARY KEY,
            version INTEGER NOT NULL,
            saved_at TEXT NOT NULL,
            payload TEXT NOT NULL
        )
        """
    )


def save_state_sqlite(payload: dict) -> None:
    db_path = state_storage_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as connection:
        ensure_sqlite_schema(connection)
        connection.execute(
            """
            INSERT INTO sentinel_state (id, version, saved_at, payload)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                version = excluded.version,
                saved_at = excluded.saved_at,
                payload = excluded.payload
            """,
            (STATE_ROW_ID, payload["version"], payload["saved_at"], json.dumps(payload)),
        )


def load_state_sqlite() -> None:
    db_path = state_storage_path()
    if not db_path.exists():
        return
    try:
        with sqlite3.connect(db_path) as connection:
            ensure_sqlite_schema(connection)
            row = connection.execute(
                "SELECT payload FROM sentinel_state WHERE id = ?",
                (STATE_ROW_ID,),
            ).fetchone()
    except sqlite3.Error:
        return
    if not row:
        return
    try:
        payload = json.loads(row[0])
    except json.JSONDecodeError:
        return
    apply_state_payload(payload)


def save_state() -> None:
    payload = build_state_payload()
    if configured_state_backend() == "sqlite":
        save_state_sqlite(payload)
    else:
        save_state_json(payload)


def load_state() -> None:
    if configured_state_backend() == "sqlite":
        load_state_sqlite()
    else:
        load_state_json()


load_state()


def health() -> dict:
    return {
        "ok": True,
        "service": "llm-sentinel-pro-api",
        "mode": "fastapi-local",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def get_metrics() -> dict:
    return deepcopy(STATE["metrics"])


def get_scenario() -> dict:
    return deepcopy(SCENARIO)


def metrics_to_quality_point(metrics: dict, label: str = "Now") -> dict:
    accuracy = max(0.0, min(1.0, 1 - metrics["semantic_drift"] * 0.95))
    safety = max(0.0, min(1.0, 1 - metrics["hallucination_rate"] / 100))
    return {
        "label": label,
        "accuracy": round(accuracy, 3),
        "safety": round(safety, 3),
    }


def get_quality_timeseries() -> dict:
    return {"items": deepcopy(STATE["quality_timeseries"])}


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def runs_for_range(range_key: str) -> list[dict]:
    window = RANGE_WINDOWS.get(range_key, RANGE_WINDOWS["24h"])
    cutoff = datetime.now(timezone.utc) - window
    runs = []
    for run in STATE["evaluation_runs"]:
        created_at = parse_timestamp(run.get("created_at"))
        if created_at and created_at >= cutoff:
            runs.append(run)
    return runs


def get_range_summary(range_key: str = "24h") -> dict:
    normalized = range_key if range_key in RANGE_WINDOWS else "24h"
    runs = runs_for_range(normalized)
    if runs:
        series = [
            {
                "label": run["id"],
                "accuracy": metrics_to_quality_point({"semantic_drift": run["semantic_drift"], "hallucination_rate": run["hallucination_rate"]})["accuracy"],
                "safety": metrics_to_quality_point({"semantic_drift": run["semantic_drift"], "hallucination_rate": run["hallucination_rate"]})["safety"],
                "created_at": run["created_at"],
            }
            for run in runs[-8:]
        ]
        avg_semantic = sum(run["semantic_drift"] for run in runs) / len(runs)
        avg_hallucination = sum(run["hallucination_rate"] for run in runs) / len(runs)
    else:
        series = deepcopy(INITIAL_TIMESERIES)
        avg_semantic = STATE["metrics"]["semantic_drift"]
        avg_hallucination = STATE["metrics"]["hallucination_rate"]
    return {
        "range": normalized,
        "run_count": len(runs),
        "critical_count": sum(1 for run in runs if run["status_level"] == "critical"),
        "warning_count": sum(1 for run in runs if run["status_level"] == "warning"),
        "avg_semantic_drift": round(avg_semantic, 3),
        "avg_hallucination_rate": round(avg_hallucination, 1),
        "items": series,
    }


def append_quality_point(metrics: dict) -> None:
    history = deepcopy(STATE["quality_timeseries"])
    next_index = STATE["evaluation_count"] - 2450
    for row in history:
        if row["label"] == "Now":
            row["label"] = "Prev"
    history.append(metrics_to_quality_point(metrics, f"Eval {next_index}"))
    STATE["quality_timeseries"] = history[-8:]


def get_evaluation_history() -> dict:
    return {"items": list(reversed(deepcopy(STATE["evaluation_runs"])))}


def runtime_metadata() -> dict:
    settings = get_settings()
    return {
        "model_name": settings["model_name"],
        "prompt_version": settings["prompt_version"],
        "guardrail_policy": settings["guardrail_policy"],
    }


COMPARISON_METRICS = [
    {"key": "semantic_drift", "label": "Semantic Drift", "unit": "", "better": "lower", "precision": 3},
    {"key": "hallucination_rate", "label": "Hallucination Rate", "unit": "%", "better": "lower", "precision": 1},
    {"key": "statistical_drift", "label": "KL Divergence", "unit": "", "better": "lower", "precision": 3},
    {"key": "latency_ms", "label": "Latency", "unit": "ms", "better": "lower", "precision": 0},
    {"key": "confidence", "label": "Confidence", "unit": "%", "better": "higher", "precision": 0},
]

DECISION_STATUSES = {
    "pending_review": "Pending Review",
    "approved": "Approved",
    "rejected": "Rejected",
    "rollback": "Rollback Required",
}
CRITICAL_APPROVAL_MESSAGE = 'Critical drift approval requires an exception note that includes "exception" or "risk accepted".'


def round_metric(value: float, precision: int) -> float | int:
    return int(round(value)) if precision == 0 else round(value, precision)


def compare_metric(current: dict, previous: dict, metric: dict) -> dict:
    current_value = float(current.get(metric["key"], 0))
    previous_value = float(previous.get(metric["key"], 0))
    delta = current_value - previous_value
    tolerance = 0.0005 if metric["precision"] > 1 else 0.05
    if abs(delta) <= tolerance:
        direction = "flat"
        tone = "neutral"
    else:
        lower_is_better = metric["better"] == "lower"
        improved = delta < 0 if lower_is_better else delta > 0
        direction = "improved" if improved else "regressed"
        tone = "good" if improved else "bad"
    return {
        "key": metric["key"],
        "label": metric["label"],
        "unit": metric["unit"],
        "current": round_metric(current_value, metric["precision"]),
        "previous": round_metric(previous_value, metric["precision"]),
        "delta": round_metric(delta, metric["precision"]),
        "direction": direction,
        "tone": tone,
    }


def run_summary(run: dict) -> dict:
    return {
        "id": run["id"],
        "created_at": run["created_at"],
        "status": run["status"],
        "status_level": run["status_level"],
        "source": run.get("source", "Evaluation"),
        "dataset_id": run.get("dataset_id"),
        "dataset_name": run.get("dataset_name"),
        "sample_count": run.get("sample_count"),
        "top_category": run.get("top_category", "None"),
        "semantic_drift": run.get("semantic_drift", 0),
        "hallucination_rate": run.get("hallucination_rate", 0),
        "statistical_drift": run.get("statistical_drift", 0),
        "latency_ms": run.get("latency_ms", 0),
        "confidence": run.get("confidence", 0),
        "message": run.get("message", ""),
        "model_name": run.get("model_name", "Unknown model"),
        "prompt_version": run.get("prompt_version", "Unknown prompt"),
        "guardrail_policy": run.get("guardrail_policy", "Unknown policy"),
        "decision_status": run.get("decision_status", "pending_review"),
        "decision_label": DECISION_STATUSES.get(run.get("decision_status", "pending_review"), "Pending Review"),
        "decision_note": run.get("decision_note", ""),
        "decision_updated_at": run.get("decision_updated_at"),
    }


def find_run(run_id: str) -> dict:
    for run in STATE["evaluation_runs"]:
        if run["id"] == run_id:
            return run
    raise ValueError("Evaluation run not found.")


def evaluation_run_summaries() -> list[dict]:
    return list(reversed([run_summary(run) for run in STATE["evaluation_runs"]]))


def comparison_payload(current: dict, previous: dict, message: str, mode: str = "latest") -> dict:
    metrics = [compare_metric(current, previous, metric) for metric in COMPARISON_METRICS]
    improved_count = sum(1 for metric in metrics if metric["direction"] == "improved")
    regressed_count = sum(1 for metric in metrics if metric["direction"] == "regressed")
    if regressed_count > improved_count:
        verdict = {
            "label": "Regression detected",
            "tone": "bad",
            "detail": f"{regressed_count} metric{'s' if regressed_count != 1 else ''} worsened compared with the baseline run.",
        }
    elif improved_count > regressed_count:
        verdict = {
            "label": "Quality improved",
            "tone": "good",
            "detail": f"{improved_count} metric{'s' if improved_count != 1 else ''} improved compared with the baseline run.",
        }
    else:
        verdict = {
            "label": "No material change",
            "tone": "neutral",
            "detail": "Current run is broadly in line with the baseline run.",
        }
    return {
        "available": True,
        "mode": mode,
        "message": message,
        "current": run_summary(current),
        "previous": run_summary(previous),
        "metrics": metrics,
        "verdict": verdict,
        "runs": evaluation_run_summaries(),
    }


def get_evaluation_comparison() -> dict:
    runs = STATE["evaluation_runs"]
    if len(runs) < 2:
        latest = run_summary(runs[-1]) if runs else None
        return {
            "available": False,
            "mode": "latest",
            "message": "Run at least two evaluations to compare quality changes.",
            "current": latest,
            "previous": None,
            "metrics": [],
            "verdict": {"label": "Waiting for baseline", "tone": "neutral", "detail": "No previous run is available yet."},
            "runs": evaluation_run_summaries(),
        }
    return comparison_payload(runs[-1], runs[-2], "Latest evaluation compared with the previous run.")


def get_evaluation_pair_comparison(current_id: str, previous_id: str) -> dict:
    if current_id == previous_id:
        raise ValueError("Choose two different evaluation runs.")
    current = find_run(current_id)
    previous = find_run(previous_id)
    return comparison_payload(current, previous, f"{current_id} compared with {previous_id}.", "selected")


def has_critical_approval_exception(note: str) -> bool:
    normalized = note.lower()
    return "exception" in normalized or "risk accepted" in normalized or "accepted risk" in normalized


def update_run_decision(run_id: str, payload: dict) -> dict:
    run = find_run(run_id)
    status = clean_payload_text(payload, "decision_status", "pending_review")
    if status not in DECISION_STATUSES:
        raise ValueError("Unsupported decision status.")
    note = clean_payload_text(payload, "decision_note")[:600]
    if status == "approved" and run.get("status_level") == "critical" and not has_critical_approval_exception(note):
        raise ValueError(CRITICAL_APPROVAL_MESSAGE)
    run["decision_status"] = status
    run["decision_note"] = note
    run["decision_updated_at"] = datetime.now(timezone.utc).isoformat()
    save_state()
    return evaluation_run_detail(run_id)


def append_evaluation_run(
    message: str,
    source: str = "Dataset Replay",
    dataset_id: str | None = None,
    dataset_name: str | None = None,
    sample_count: int | None = None,
) -> dict:
    root_cause = STATE["root_cause"] or {}
    run_number = STATE["evaluation_count"] - 2450
    run = {
        "id": f"EVAL-{run_number:03d}",
        "created_at": STATE["metrics"]["updated_at"],
        "status": STATE["metrics"]["system_status"],
        "status_level": STATE["metrics"]["status_level"],
        "semantic_drift": STATE["metrics"]["semantic_drift"],
        "hallucination_rate": STATE["metrics"]["hallucination_rate"],
        "statistical_drift": STATE["metrics"]["statistical_drift"],
        "latency_ms": STATE["metrics"]["latency_ms"],
        "confidence": STATE["metrics"]["confidence"],
        "top_category": root_cause.get("top_category", "None"),
        "risk_level": root_cause.get("risk_level", "Healthy"),
        "incident_opened": STATE["last_event"] is not None,
        "message": message,
        "source": source,
        "dataset_id": dataset_id,
        "dataset_name": dataset_name,
        "sample_count": sample_count,
        "decision_status": "pending_review",
        "decision_note": "",
        "decision_updated_at": None,
        **runtime_metadata(),
    }
    STATE["evaluation_runs"].append(run)
    STATE["evaluation_runs"] = STATE["evaluation_runs"][-25:]
    return run


def get_settings() -> dict:
    return {**deepcopy(DEFAULT_SETTINGS), **deepcopy(STATE["settings"])}


def update_settings(payload: dict) -> dict:
    settings = get_settings()
    if "semantic_drift_threshold" in payload:
        settings["semantic_drift_threshold"] = max(0.01, min(float(payload["semantic_drift_threshold"]), 1.0))
    if "hallucination_rate_threshold" in payload:
        settings["hallucination_rate_threshold"] = max(0.1, min(float(payload["hallucination_rate_threshold"]), 100.0))
    if "slack_alerts" in payload:
        settings["slack_alerts"] = bool(payload["slack_alerts"])
    if "email_alerts" in payload:
        settings["email_alerts"] = bool(payload["email_alerts"])
    if "model_name" in payload:
        settings["model_name"] = clean_payload_text(payload, "model_name", DEFAULT_SETTINGS["model_name"]) or DEFAULT_SETTINGS["model_name"]
    if "prompt_version" in payload:
        settings["prompt_version"] = clean_payload_text(payload, "prompt_version", DEFAULT_SETTINGS["prompt_version"]) or DEFAULT_SETTINGS["prompt_version"]
    if "guardrail_policy" in payload:
        settings["guardrail_policy"] = clean_payload_text(payload, "guardrail_policy", DEFAULT_SETTINGS["guardrail_policy"]) or DEFAULT_SETTINGS["guardrail_policy"]
    STATE["settings"] = settings
    save_state()
    return get_settings()


def classify_metrics(metrics: dict) -> dict:
    settings = STATE["settings"]
    critical = (
        metrics["semantic_drift"] >= settings["semantic_drift_threshold"]
        or metrics["hallucination_rate"] >= settings["hallucination_rate_threshold"]
    )
    warning = (
        metrics["semantic_drift"] >= settings["semantic_drift_threshold"] * 0.8
        or metrics["hallucination_rate"] >= settings["hallucination_rate_threshold"] * 0.8
    )
    if critical:
        return {
            **metrics,
            "system_status": "Critical Drift",
            "status_level": "critical",
        }
    if warning:
        return {
            **metrics,
            "system_status": "Elevated Risk",
            "status_level": "warning",
        }
    return {
        **metrics,
        "system_status": "System Healthy",
        "status_level": "healthy",
    }


def build_timeline(metrics: dict) -> list[dict]:
    if metrics["status_level"] == "healthy":
        return [
            {"time": "12:30:00", "label": "Baseline Within Threshold", "level": "green"},
            {"time": "12:31:18", "label": "Routine Drift Check Complete", "level": "neutral"},
            {"time": "12:34:44", "label": "No Active Containment Needed", "level": "green"},
        ]
    if metrics["status_level"] == "warning":
        return [
            {"time": "14:02:11", "label": "Evaluation Batch Started", "level": "neutral"},
            {"time": "14:04:30", "label": "Elevated Risk Band Reached", "level": "blue"},
            {"time": "14:08:09", "label": "Manual Review Recommended", "level": "danger"},
            {"time": "14:16:33", "label": "Warning Report Generated", "level": "green"},
        ]
    return [
        {"time": "14:02:11", "label": "Evaluation Batch Started", "level": "neutral"},
        {"time": "14:03:45", "label": "Critical Drift Threshold Crossed", "level": "danger"},
        {"time": "14:08:09", "label": "Low-Faithfulness Cluster Identified", "level": "danger"},
        {"time": "14:12:00", "label": "High-Safety Routing Recommended", "level": "blue"},
        {"time": "14:16:33", "label": "Root Cause Report Generated", "level": "green"},
    ]


def build_signals(metrics: dict) -> list[dict]:
    settings = STATE["settings"]
    hallucination_alert = metrics["hallucination_rate"] >= settings["hallucination_rate_threshold"]
    semantic_alert = metrics["semantic_drift"] >= settings["semantic_drift_threshold"]
    return [
        {
            "label": "P99 Latency",
            "value": f"{int(metrics['latency_ms']):,}ms",
            "trend": "+42%" if metrics["status_level"] == "critical" else "Stable",
            "tone": "bad" if metrics["status_level"] == "critical" else "good",
        },
        {
            "label": "Hallucination Rate",
            "value": f"{metrics['hallucination_rate']:.1f}%",
            "trend": "High" if hallucination_alert else "Normal",
            "tone": "bad" if hallucination_alert else "good",
        },
        {
            "label": "KL Divergence",
            "value": f"{metrics['statistical_drift']:.2f}",
            "trend": "High" if metrics["statistical_drift"] >= 1 else "Low",
            "tone": "bad" if metrics["statistical_drift"] >= 1 else "good",
        },
        {
            "label": "Semantic Drift",
            "value": f"{metrics['semantic_drift']:.3f}",
            "trend": "Critical" if semantic_alert else "Healthy",
            "tone": "bad" if semantic_alert else "good",
        },
    ]


def get_incidents() -> dict:
    if not STATE["last_event"]:
        return {"items": []}
    incident = {
        **deepcopy(INCIDENTS[0]),
        "summary": STATE["last_event"]["message"],
        "duration": STATE["root_cause"]["duration"] if STATE["root_cause"] else INCIDENTS[0]["duration"],
        "impact_radius": STATE["root_cause"]["impact_radius"] if STATE["root_cause"] else INCIDENTS[0]["impact_radius"],
        "confidence": STATE["metrics"]["confidence"],
        "risk_level": STATE["root_cause"]["risk_level"] if STATE["root_cause"] else INCIDENTS[0]["risk_level"],
        "timeline": deepcopy(STATE["timeline"]),
        "evidence": deepcopy(STATE["evidence"]),
    }
    return {"items": [incident]}


def get_alerts() -> dict:
    alerts = deepcopy(ALERTS)
    if STATE["last_event"]:
        active_alert = {
            "severity": "Critical" if STATE["metrics"]["status_level"] == "critical" else "Warning",
            "tone": "red" if STATE["metrics"]["status_level"] == "critical" else "amber",
            "incident": STATE["metrics"]["system_status"],
            "summary": STATE["last_event"]["message"],
            "affected_area": STATE["root_cause"]["top_category"],
            "status": "Open" if STATE["metrics"]["status_level"] == "critical" else "Review",
            "owner": "Evaluation",
            "age": "Just now",
        }
        alerts.insert(0, active_alert)
    return {"items": alerts}


def get_category_scores() -> dict:
    if not STATE["category_scores"]:
        computed = evaluate_dataset(SAMPLE_DATASET)
        STATE["category_scores"] = computed["category_scores"]
    return {"items": deepcopy(STATE["category_scores"])}


def get_hallucination_logs() -> dict:
    if not STATE["hallucination_logs"]:
        computed = evaluate_dataset(SAMPLE_DATASET)
        STATE["hallucination_logs"] = computed["hallucination_logs"]
    return {"items": deepcopy(STATE["hallucination_logs"])}


def get_root_cause() -> dict:
    if not STATE["last_event"]:
        return {
            "summary": {
                "primary_cause": "No active incident. Latest production checks are within configured monitoring thresholds.",
                "top_category": "None",
                "top_category_score": 0,
                "impact_radius": "0 Sessions",
                "duration": "0m 00s",
                "risk_level": "Healthy",
            },
            "evidence": [],
            "timeline": build_timeline(STATE["metrics"]),
            "signals": build_signals(STATE["metrics"]),
        }
    if not STATE["root_cause"]:
        computed = evaluate_dataset(SAMPLE_DATASET)
        STATE["root_cause"] = computed["root_cause"]
        STATE["evidence"] = computed["evidence"]
    return {
        "summary": deepcopy(STATE["root_cause"]),
        "evidence": deepcopy(STATE["evidence"]),
        "timeline": deepcopy(STATE["timeline"]),
        "signals": deepcopy(STATE["signals"]),
    }


def current_report() -> dict:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "metrics": get_metrics(),
        "settings": get_settings(),
        "scenario": get_scenario(),
        "drift_categories": get_category_scores()["items"],
        "hallucination_logs": get_hallucination_logs()["items"],
        "root_cause": get_root_cause(),
        "quality_timeseries": get_quality_timeseries()["items"],
        "range_summary": get_range_summary("30d"),
        "evaluation_history": get_evaluation_history()["items"],
        "evaluation_comparison": get_evaluation_comparison(),
        "incidents": get_incidents()["items"],
        "providers": deepcopy(PROVIDERS),
        "benchmarks": deepcopy(BENCHMARKS),
        "alerts": get_alerts()["items"],
        "datasets": get_datasets()["items"],
    }


def decision_counts() -> dict:
    counts = {key: 0 for key in DECISION_STATUSES}
    for run in STATE["evaluation_runs"]:
        status = run.get("decision_status", "pending_review")
        counts[status if status in counts else "pending_review"] += 1
    return {
        "items": [
            {"status": key, "label": label, "count": counts[key]}
            for key, label in DECISION_STATUSES.items()
        ],
        "total": len(STATE["evaluation_runs"]),
    }


def review_gate(latest_run: dict | None, counts: dict) -> dict:
    if not latest_run:
        return {
            "label": "Waiting for evaluation",
            "tone": "neutral",
            "detail": "Run an evaluation to generate review evidence.",
        }
    if latest_run["decision_status"] == "rollback":
        return {
            "label": "Rollback required",
            "tone": "bad",
            "detail": f"{latest_run['id']} is marked for rollback. Keep the release blocked until remediation is complete.",
        }
    if latest_run["decision_status"] == "rejected":
        return {
            "label": "Release rejected",
            "tone": "bad",
            "detail": f"{latest_run['id']} was rejected by operator review.",
        }
    if latest_run["decision_status"] == "approved":
        if latest_run["status_level"] == "critical":
            return {
                "label": "Approved with critical risk",
                "tone": "bad",
                "detail": f"{latest_run['id']} is approved, but critical drift is still active. Attach audit evidence and confirm the release exception before handoff.",
            }
        return {
            "label": "Operator approved",
            "tone": "good",
            "detail": f"{latest_run['id']} is approved. Latest model/prompt snapshot is ready for handoff with audit evidence attached.",
        }
    pending = next((row["count"] for row in counts["items"] if row["status"] == "pending_review"), 0)
    return {
        "label": "Review pending",
        "tone": "warning",
        "detail": f"{pending} run{'s' if pending != 1 else ''} still need an operator decision before handoff.",
    }


def operator_review_summary() -> dict:
    metrics = get_metrics()
    runs = evaluation_run_summaries()
    latest_run = runs[0] if runs else None
    counts = decision_counts()
    comparison = get_evaluation_comparison()
    root_cause = get_root_cause()
    latest_audit_url = f"/api/reports/audit/{latest_run['id']}" if latest_run else None
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "gate": review_gate(latest_run, counts),
        "metrics": metrics,
        "latest_run": latest_run,
        "decision_counts": counts,
        "comparison": comparison,
        "root_cause_summary": root_cause["summary"],
        "alerts": get_alerts()["items"][:4],
        "recent_runs": runs[:8],
        "exports": {
            "handoff_package": "/api/reports/handoff",
            "current_report": "/api/reports/current",
            "latest_audit_bundle": latest_audit_url,
            "drift_csv": "/api/reports/drift.csv",
            "hallucination_csv": "/api/reports/hallucination.csv",
            "root_cause_csv": "/api/reports/root-cause.csv",
        },
    }


def readiness_check(key: str, label: str, status: str, owner: str, detail: str, action: str) -> dict:
    return {
        "key": key,
        "label": label,
        "status": status,
        "owner": owner,
        "detail": detail,
        "action": action,
    }


def readiness_summary() -> dict:
    settings = get_settings()
    runs = evaluation_run_summaries()
    latest_run = runs[0] if runs else None
    evaluator = evaluator_capabilities()
    deployment_profile = os.environ.get("SENTINEL_ENV", "local").strip() or "local"
    state_backend = configured_state_backend()
    storage_path = state_storage_path()
    api_key_configured = bool(os.environ.get("SENTINEL_API_KEY") or os.environ.get("SENTINEL_AUTH_TOKEN"))
    alert_channels = [
        label
        for label, enabled in (("Slack", settings["slack_alerts"]), ("Email", settings["email_alerts"]))
        if enabled
    ]

    checks = [
        readiness_check(
            "evaluation_evidence",
            "Evaluation Evidence",
            "passed" if runs else "blocked",
            "Evaluation",
            f"{len(runs)} evaluation run{'s' if len(runs) != 1 else ''} are available for release review."
            if runs
            else "No evaluation run exists yet.",
            "Run the baseline or batch evaluation before deployment." if not runs else "Keep evaluation cadence active.",
        ),
        readiness_check(
            "version_snapshot",
            "Model / Prompt Snapshot",
            "passed"
            if settings["model_name"] and settings["prompt_version"] and settings["guardrail_policy"]
            else "blocked",
            "ML Platform",
            f"{settings['model_name']} / {settings['prompt_version']} / {settings['guardrail_policy']}",
            "Confirm the release model, prompt version, and guardrail policy are current.",
        ),
        readiness_check(
            "baseline_dataset",
            "Baseline Dataset",
            "passed" if STATE["datasets"] else "warning" if SAMPLE_DATASET.exists() else "blocked",
            "Evaluation",
            f"{len(STATE['datasets'])} saved dataset{'s' if len(STATE['datasets']) != 1 else ''} available."
            if STATE["datasets"]
            else "Using the bundled sample dataset only.",
            "Upload a production representative CSV dataset." if not STATE["datasets"] else "Refresh datasets after major policy changes.",
        ),
        readiness_check(
            "evaluator_engine",
            "Evaluator Engine",
            evaluator["status"],
            "Evaluation",
            evaluator["message"],
            "Install SentenceTransformers or RAGAS and set SENTINEL_EVALUATOR_ENGINE for production-grade scoring."
            if evaluator["active_engine"] == "local"
            else "Validate external evaluator model versions and calibration thresholds.",
        ),
        readiness_check(
            "audit_exports",
            "Audit Exports",
            "passed" if latest_run else "blocked",
            "Compliance",
            f"Latest bundle available at /api/reports/audit/{latest_run['id']}." if latest_run else "No run-specific audit bundle is available.",
            "Generate an evaluation run before audit handoff." if not latest_run else "Attach current report, run audit, and CSV exports to the release record.",
        ),
        readiness_check(
            "alert_routes",
            "Alert Routes",
            "passed" if alert_channels else "warning",
            "Operations",
            f"Enabled channels: {', '.join(alert_channels)}." if alert_channels else "No alert channel is enabled in settings.",
            "Connect live Slack/email destinations before production exposure.",
        ),
        readiness_check(
            "access_control",
            "Access Control",
            "passed" if api_key_configured else "blocked",
            "Security",
            "API key environment variable is configured." if api_key_configured else "No SENTINEL_API_KEY or SENTINEL_AUTH_TOKEN is configured.",
            "Set an API key and enforce it at the gateway before exposing this service.",
        ),
        readiness_check(
            "state_backend",
            "State Backend",
            "passed" if state_backend == "sqlite" else "warning",
            "Platform",
            f"State backend: {state_backend} at {storage_path}.",
            "Move from local JSON state to SQLite for production-style persistence." if state_backend == "local-json" else "Validate backup and retention policy.",
        ),
        readiness_check(
            "deployment_profile",
            "Deployment Profile",
            "passed" if deployment_profile not in {"local", "demo", "dev"} else "warning",
            "Platform",
            f"SENTINEL_ENV={deployment_profile}.",
            "Set SENTINEL_ENV=staging or production in deployed environments.",
        ),
    ]

    if latest_run:
        decision = latest_run.get("decision_status", "pending_review")
        status = "passed"
        detail = f"{latest_run['id']} is {latest_run.get('decision_label', 'reviewed')}."
        action = "Keep the approval note with the audit bundle."
        if decision in {"pending_review", "rollback", "rejected"}:
            status = "blocked"
            action = "Resolve the operator decision before handoff."
        elif latest_run["status_level"] == "critical":
            status = "warning"
            detail = f"{latest_run['id']} is approved while critical drift is active."
            action = "Confirm a release exception or move the run to rollback."
        checks.insert(
            1,
            readiness_check(
                "operator_decision",
                "Operator Decision",
                status,
                "Release Manager",
                detail,
                action,
            ),
        )
    else:
        checks.insert(
            1,
            readiness_check(
                "operator_decision",
                "Operator Decision",
                "blocked",
                "Release Manager",
                "No latest run exists for operator approval.",
                "Run an evaluation and record approve, reject, or rollback.",
            ),
        )

    counts = {
        "passed": sum(1 for check in checks if check["status"] == "passed"),
        "warning": sum(1 for check in checks if check["status"] == "warning"),
        "blocked": sum(1 for check in checks if check["status"] == "blocked"),
        "total_checks": len(checks),
    }
    score = round(((counts["passed"] + counts["warning"] * 0.5) / counts["total_checks"]) * 100)
    if counts["blocked"]:
        status = {
            "label": "Needs production input",
            "tone": "bad",
            "detail": f"{counts['blocked']} blocking item{'s' if counts['blocked'] != 1 else ''} must be resolved before production release.",
        }
    elif counts["warning"]:
        status = {
            "label": "Ready for controlled pilot",
            "tone": "warning",
            "detail": f"{counts['warning']} warning item{'s' if counts['warning'] != 1 else ''} should be accepted or resolved before broad rollout.",
        }
    else:
        status = {
            "label": "Production ready",
            "tone": "good",
            "detail": "All readiness checks passed.",
        }

    status.update(counts)
    status["score"] = score
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "checks": checks,
        "required_inputs": [
            {
                "key": check["key"],
                "label": check["label"],
                "status": check["status"],
                "owner": check["owner"],
                "action": check["action"],
            }
            for check in checks
            if check["status"] != "passed"
        ],
        "environment": {
            "deployment_profile": deployment_profile,
            "state_backend": state_backend,
            "api_key_configured": api_key_configured,
            "alert_channels": alert_channels,
            "state_file": str(storage_path),
            "evaluator_engine": evaluator["active_engine"],
            "evaluator_mode": evaluator["mode"],
        },
        "evaluator": evaluator,
        "latest_run": latest_run,
        "exports": {
            "handoff_package": "/api/reports/handoff",
            "readiness": "/api/operations/readiness",
            "operator_review": "/api/reports/operator-review",
            "current_report": "/api/reports/current",
        },
    }


def production_handoff_actions(readiness: dict) -> list[dict]:
    checks = {check["key"]: check for check in readiness["checks"]}
    environment = readiness["environment"]
    evaluator = readiness["evaluator"]
    semantic_available = any(
        item["key"] == "sentence_transformers" and item["available"]
        for item in evaluator.get("integrations", [])
    )
    evaluator_command = (
        "SENTINEL_EVALUATOR_ENGINE=sentence_transformers"
        if semantic_available
        else "SENTINEL_EVALUATOR_ENGINE=ragas"
    )
    rows = [
        (
            "access_control",
            "Set API protection",
            "Security",
            "SENTINEL_API_KEY=<release-key>",
            "Required before exposing the API outside a trusted local demo.",
        ),
        (
            "state_backend",
            "Use durable state",
            "Platform",
            "SENTINEL_STATE_BACKEND=sqlite",
            f"Current backend is {environment['state_backend']}.",
        ),
        (
            "deployment_profile",
            "Set deployment profile",
            "Platform",
            "SENTINEL_ENV=staging",
            f"Current profile is {environment['deployment_profile']}.",
        ),
        (
            "evaluator_engine",
            "Configure evaluator engine",
            "Evaluation",
            evaluator_command,
            evaluator["message"],
        ),
        (
            "baseline_dataset",
            "Upload production dataset",
            "Evaluation",
            "POST /api/datasets",
            "Use representative prompt, response, expected_answer, and context columns.",
        ),
        (
            "operator_decision",
            "Record release decision",
            "Release Manager",
            "POST /api/evaluations/{run_id}/decision",
            "Approve, reject, or require rollback for the latest release candidate.",
        ),
    ]
    actions = []
    for key, label, owner, command, detail in rows:
        check = checks.get(key, {"status": "warning", "action": "Review before handoff."})
        actions.append(
            {
                "key": key,
                "label": label,
                "owner": owner,
                "status": check["status"],
                "command": command,
                "detail": detail,
                "next_action": check["action"],
                "requires_user_input": check["status"] != "passed",
            }
        )
    return actions


def handoff_package() -> dict:
    readiness = readiness_summary()
    review = operator_review_summary()
    report = current_report()
    latest_run = readiness.get("latest_run")
    latest_audit = audit_bundle(latest_run["id"]) if latest_run else None
    return {
        "bundle_type": "llm-sentinel-release-handoff",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "release_status": readiness["status"],
        "release_gate": review["gate"],
        "latest_run": latest_run,
        "production_actions": production_handoff_actions(readiness),
        "readiness": readiness,
        "operator_review": review,
        "latest_audit_bundle": latest_audit,
        "current_report": report,
        "exports": {
            "handoff_package": "/api/reports/handoff",
            "readiness": "/api/operations/readiness",
            "operator_review": "/api/reports/operator-review",
            "current_report": "/api/reports/current",
            "latest_audit_bundle": f"/api/reports/audit/{latest_run['id']}" if latest_run else None,
            "drift_csv": "/api/reports/drift.csv",
            "hallucination_csv": "/api/reports/hallucination.csv",
            "root_cause_csv": "/api/reports/root-cause.csv",
        },
    }


def audit_bundle(run_id: str) -> dict:
    run = find_run(run_id)
    summary = run_summary(run)
    dataset = None
    dataset_note = "No saved dataset is linked to this evaluation run."
    if summary.get("dataset_id"):
        try:
            dataset = get_dataset(summary["dataset_id"])
            dataset_note = "Saved dataset snapshot is included for the linked evaluation run."
        except ValueError:
            dataset_note = "The linked dataset is no longer available in local state."

    settings = get_settings()
    return {
        "bundle_type": "llm-sentinel-run-audit",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run": summary,
        "version_snapshot": {
            "model_name": summary["model_name"],
            "prompt_version": summary["prompt_version"],
            "guardrail_policy": summary["guardrail_policy"],
        },
        "thresholds": {
            "scope": "current_settings",
            "semantic_drift_threshold": settings["semantic_drift_threshold"],
            "hallucination_rate_threshold": settings["hallucination_rate_threshold"],
        },
        "dataset": dataset,
        "dataset_note": dataset_note,
        "metrics": get_metrics(),
        "comparison": get_evaluation_comparison(),
        "current_root_cause_context": get_root_cause(),
        "current_scoring_logs": get_hallucination_logs()["items"],
        "alerts": get_alerts()["items"],
        "scope_note": (
            "Run summary and model/prompt/policy values are snapshotted on the evaluation run. "
            "Detailed evidence, scoring logs, alerts, and thresholds reflect the current local demo state."
        ),
        "integrity": {
            "state_version": STATE_VERSION,
            "source": "local-demo-state",
        },
    }


def evaluation_run_detail(run_id: str) -> dict:
    bundle = audit_bundle(run_id)
    runs = STATE["evaluation_runs"]
    run_index = next(index for index, run in enumerate(runs) if run["id"] == run_id)
    previous_run = run_summary(runs[run_index - 1]) if run_index > 0 else None
    next_run = run_summary(runs[run_index + 1]) if run_index < len(runs) - 1 else None
    run = bundle["run"]
    root_context = bundle["current_root_cause_context"]
    return {
        "generated_at": bundle["generated_at"],
        "run": run,
        "version_snapshot": bundle["version_snapshot"],
        "thresholds": bundle["thresholds"],
        "dataset": bundle["dataset"],
        "dataset_note": bundle["dataset_note"],
        "previous_run": previous_run,
        "next_run": next_run,
        "metric_cards": [
            {"label": "Hallucination", "value": run["hallucination_rate"], "unit": "%", "precision": 1},
            {"label": "Semantic Drift", "value": run["semantic_drift"], "unit": "", "precision": 3},
            {"label": "KL Divergence", "value": run["statistical_drift"], "unit": "", "precision": 3},
            {"label": "Latency", "value": run["latency_ms"], "unit": "ms", "precision": 0},
            {"label": "Confidence", "value": run["confidence"], "unit": "%", "precision": 0},
        ],
        "current_context": {
            "root_cause_summary": root_context["summary"],
            "evidence": root_context["evidence"][:4],
            "scoring_logs": bundle["current_scoring_logs"][:5],
            "alerts": bundle["alerts"][:3],
            "scope_note": bundle["scope_note"],
        },
    }


def rows_to_csv(rows: list[dict], fieldnames: list[str]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return buffer.getvalue()


def export_hallucination_csv() -> str:
    return rows_to_csv(
        get_hallucination_logs()["items"],
        [
            "id",
            "category",
            "prompt",
            "claims",
            "score",
            "risk",
            "semantic_similarity",
            "groundedness",
            "answer_relevance",
            "evaluation_reason",
            "status",
            "expected_answer",
            "current_answer",
        ],
    )


def export_drift_csv() -> str:
    return rows_to_csv(
        get_category_scores()["items"],
        ["category", "sample_count", "avg_score", "status"],
    )


def export_root_cause_csv() -> str:
    root = get_root_cause()
    summary_rows = [
        {"section": "summary", "key": key, "value": value}
        for key, value in root["summary"].items()
    ]
    evidence_rows = [
        {
            "section": "evidence",
            "key": f"{row['timestamp']} {row['trace_id']}",
            "value": f"{row['signal_type']}: {row['details']}",
        }
        for row in root["evidence"]
    ]
    return rows_to_csv(summary_rows + evidence_rows, ["section", "key", "value"])


def reset_state() -> dict:
    STATE["metrics"] = deepcopy(INITIAL_METRICS)
    STATE["settings"] = deepcopy(DEFAULT_SETTINGS)
    STATE["evaluation_count"] = 2450
    STATE["last_event"] = None
    STATE["category_scores"] = []
    STATE["hallucination_logs"] = []
    STATE["evidence"] = []
    STATE["root_cause"] = None
    STATE["timeline"] = []
    STATE["signals"] = []
    STATE["quality_timeseries"] = deepcopy(INITIAL_TIMESERIES)
    STATE["evaluation_runs"] = []
    STATE["datasets"] = []
    save_state()
    return {"message": "Demo state reset.", "metrics": get_metrics(), "settings": get_settings()}


def metrics_from_computed(computed: dict) -> dict:
    return {
        **deepcopy(CRITICAL_METRICS),
        "semantic_drift": computed["semantic_drift"],
        "hallucination_rate": computed["hallucination_rate"],
        "statistical_drift": computed["statistical_drift"],
        "latency_ms": computed["latency_ms"],
        "confidence": computed["confidence"],
    }


def finalize_evaluation(
    computed: dict,
    healthy_message: str,
    alert_message: str,
    source: str,
    dataset_id: str | None = None,
    dataset_name: str | None = None,
    sample_count: int | None = None,
) -> dict:
    evaluated_metrics = metrics_from_computed(computed)
    STATE["metrics"] = classify_metrics(evaluated_metrics)
    STATE["metrics"]["updated_at"] = datetime.now(timezone.utc).isoformat()
    STATE["evaluation_count"] += 1
    append_quality_point(STATE["metrics"])
    STATE["category_scores"] = computed["category_scores"]
    STATE["hallucination_logs"] = computed["hallucination_logs"]
    STATE["evidence"] = computed["evidence"]
    if STATE["metrics"]["status_level"] == "healthy":
        STATE["root_cause"] = {
            "primary_cause": (
                "Evaluation completed under the configured thresholds. Observed semantic drift "
                f"was {STATE['metrics']['semantic_drift']:.3f} and hallucination rate was "
                f"{STATE['metrics']['hallucination_rate']:.1f}%, so no active incident was opened."
            ),
            "top_category": computed["root_cause"]["top_category"],
            "top_category_score": computed["root_cause"]["top_category_score"],
            "impact_radius": "0 Sessions",
            "duration": "0m 00s",
            "risk_level": "Healthy",
        }
    else:
        STATE["root_cause"] = {
            **computed["root_cause"],
            "risk_level": "Critical" if STATE["metrics"]["status_level"] == "critical" else "Warning",
        }
    STATE["timeline"] = build_timeline(STATE["metrics"])
    STATE["signals"] = build_signals(STATE["metrics"])
    if STATE["metrics"]["status_level"] == "healthy":
        STATE["last_event"] = None
        message = healthy_message
    else:
        STATE["last_event"] = {
            "id": "INC-9421-RCA",
            "message": alert_message,
            "created_at": STATE["metrics"]["updated_at"],
        }
        message = STATE["last_event"]["message"]
    run = append_evaluation_run(message, source, dataset_id, dataset_name, sample_count)
    save_state()
    return {
        "message": message,
        "run": deepcopy(run),
        "metrics": get_metrics(),
        "category_scores": deepcopy(STATE["category_scores"]),
        "hallucination_logs": deepcopy(STATE["hallucination_logs"]),
        "root_cause": deepcopy(STATE["root_cause"]),
        "evidence": deepcopy(STATE["evidence"]),
        "timeline": deepcopy(STATE["timeline"]),
        "signals": deepcopy(STATE["signals"]),
        "settings": get_settings(),
        "incident": deepcopy(INCIDENTS[0]),
    }


def run_evaluation() -> dict:
    computed = evaluate_dataset(SAMPLE_DATASET)
    evaluated = classify_metrics(metrics_from_computed(computed))
    return finalize_evaluation(
        computed,
        "Evaluation complete. No thresholds were crossed.",
        f"{evaluated['system_status']} detected. Root cause report generated.",
        "Dataset Replay",
    )


def clean_payload_text(payload: dict, key: str, default: str = "") -> str:
    value = payload.get(key, default)
    return str(value).strip()


# Maps user-supplied category labels to canonical evaluator categories
_CATEGORY_ALIASES = {
    "landing_sandbox": "customer_support",
    "landing": "customer_support",
    "support": "customer_support",
    "account_access": "customer_support",
    "account": "customer_support",
    "billing": "customer_support",
    "medical": "healthcare",
    "health": "healthcare",
    "law": "legal",
    "coding": "code_generation",
    "code": "code_generation",
    "writing": "technical_writing",
    "investment": "finance",
    "money": "finance",
}

def normalize_category(value: str) -> str:
    safe_value = "".join(char.lower() if char.isalnum() else " " for char in value)
    parts = safe_value.split()
    normalized = "_".join(part for part in parts if part)
    if not normalized:
        return "custom"
    return _CATEGORY_ALIASES.get(normalized, normalized)


def first_payload_text(payload: dict, keys: list[str], default: str = "") -> str:
    for key in keys:
        value = clean_payload_text(payload, key)
        if value:
            return value
    return default


def sample_from_payload(payload: dict, sample_id: int) -> dict:
    prompt = first_payload_text(payload, ["prompt", "question", "input"])
    response = first_payload_text(payload, ["response", "current_answer", "model_response", "output"])
    if not prompt or not response:
        raise ValueError("Prompt and model response are required.")

    category = normalize_category(first_payload_text(payload, ["category", "domain"], "custom"))
    expected = first_payload_text(payload, ["expected_answer", "reference_answer", "expected", "ground_truth"])
    context = first_payload_text(payload, ["context", "source_context", "source"])
    if not expected:
        expected = "The assistant should answer only with supported information from the provided context."
    if not context:
        context = expected

    return {
        "id": str(sample_id),
        "category": category,
        "question": prompt,
        "context": context,
        "baseline_answer": first_payload_text(payload, ["baseline_answer", "baseline", "reference_answer"], expected),
        "expected_answer": expected,
        "current_answer": response,
    }


def display_category(value: str) -> str:
    return value.replace("_", " ").title()


def stored_row_from_payload(payload: dict, sample_id: int) -> dict:
    sample = sample_from_payload(payload, sample_id)
    return {
        "category": sample["category"],
        "prompt": sample["question"],
        "response": sample["current_answer"],
        "expected_answer": sample["expected_answer"],
        "context": sample["context"],
        "baseline_answer": sample["baseline_answer"],
    }


def normalize_batch_rows(rows: list) -> list[dict]:
    normalized = []
    errors = []
    start_id = STATE["evaluation_count"] - 2449
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            errors.append(f"Row {index}: expected an object.")
            continue
        try:
            normalized.append(stored_row_from_payload(row, start_id + index - 1))
        except ValueError as exc:
            errors.append(f"Row {index}: {exc}")
    if errors:
        raise ValueError(" ".join(errors[:3]))
    if not normalized:
        raise ValueError("At least one batch row is required.")
    return normalized


def samples_from_rows(rows: list[dict]) -> list[dict]:
    start_id = STATE["evaluation_count"] - 2449
    return [sample_from_payload(row, start_id + index - 1) for index, row in enumerate(rows, start=1)]


def next_dataset_id() -> str:
    max_id = 0
    for dataset in STATE["datasets"]:
        raw_id = str(dataset.get("id", ""))
        if raw_id.startswith("DATASET-"):
            try:
                max_id = max(max_id, int(raw_id.split("-", 1)[1]))
            except ValueError:
                continue
    return f"DATASET-{max_id + 1:03d}"


def dataset_summary(dataset: dict) -> dict:
    rows = dataset.get("rows", [])
    categories = sorted({display_category(row.get("category", "custom")) for row in rows})
    return {
        "id": dataset["id"],
        "name": dataset["name"],
        "row_count": len(rows),
        "created_at": dataset["created_at"],
        "updated_at": dataset.get("updated_at", dataset["created_at"]),
        "last_run_at": dataset.get("last_run_at"),
        "last_status": dataset.get("last_status"),
        "last_hallucination_rate": dataset.get("last_hallucination_rate"),
        "last_semantic_drift": dataset.get("last_semantic_drift"),
        "last_run_id": dataset.get("last_run_id"),
        "categories": categories,
    }


def find_dataset(dataset_id: str) -> dict:
    for dataset in STATE["datasets"]:
        if dataset["id"] == dataset_id:
            return dataset
    raise ValueError("Dataset not found.")


def get_datasets() -> dict:
    items = [dataset_summary(dataset) for dataset in STATE["datasets"]]
    return {"items": list(reversed(items))}


def create_dataset(payload: dict) -> dict:
    rows = payload.get("rows", [])
    if not isinstance(rows, list) or not rows:
        raise ValueError("At least one dataset row is required.")
    normalized_rows = normalize_batch_rows(rows)
    name = clean_payload_text(payload, "name") or f"Evaluation Dataset {len(STATE['datasets']) + 1}"
    now = datetime.now(timezone.utc).isoformat()
    dataset = {
        "id": next_dataset_id(),
        "name": name,
        "created_at": now,
        "updated_at": now,
        "rows": normalized_rows,
    }
    STATE["datasets"].append(dataset)
    STATE["datasets"] = STATE["datasets"][-20:]
    save_state()
    return dataset_summary(dataset)


def get_dataset(dataset_id: str) -> dict:
    dataset = find_dataset(dataset_id)
    return {**dataset_summary(dataset), "rows": deepcopy(dataset.get("rows", []))}


def run_custom_evaluation(payload: dict) -> dict:
    sample_number = STATE["evaluation_count"] - 2449
    sample = sample_from_payload(payload, sample_number)
    computed = evaluate_samples([sample])
    evaluated = classify_metrics(metrics_from_computed(computed))
    result = finalize_evaluation(
        computed,
        "Custom response scored under the configured thresholds.",
        f"{evaluated['system_status']} detected in custom response. Root cause report generated.",
        "Custom Response",
        sample_count=1,
    )
    # Propagate per-sample signals to the top-level response so the frontend
    # can render policy_coverage, contradiction, policy_flags, and new dashboard fields without
    # digging into hallucination_logs.
    first_log = (result.get("hallucination_logs") or [None])[0]
    if first_log:
        result.setdefault("policy_coverage", first_log.get("policy_coverage", 0))
        result.setdefault("contradiction_detected", first_log.get("contradiction_detected", False))
        result.setdefault("policy_flags", first_log.get("policy_flags", []))
        result.setdefault("severity", first_log.get("severity", "LOW"))
        result.setdefault("hard_override", first_log.get("hard_override", False))
        result.setdefault("detected_violations", first_log.get("detected_violations", []))
        result.setdefault("policy_components", first_log.get("policy_components", {}))
        result.setdefault("confidence", first_log.get("confidence", 85))
    else:
        result.setdefault("policy_coverage", 0)
        result.setdefault("contradiction_detected", False)
        result.setdefault("policy_flags", [])
        result.setdefault("severity", "LOW")
        result.setdefault("hard_override", False)
        result.setdefault("detected_violations", [])
        result.setdefault("policy_components", {})
        result.setdefault("confidence", 85)
    return result


def run_batch_evaluation(payload: dict) -> dict:
    rows = payload.get("rows", [])
    if not isinstance(rows, list) or not rows:
        raise ValueError("At least one batch row is required.")
    normalized_rows = normalize_batch_rows(rows)
    samples = samples_from_rows(normalized_rows)
    computed = evaluate_samples(samples)
    evaluated = classify_metrics(metrics_from_computed(computed))
    count = len(samples)
    result = finalize_evaluation(
        computed,
        f"Batch evaluation completed for {count} responses under the configured thresholds.",
        f"{evaluated['system_status']} detected across {count} uploaded responses. Root cause report generated.",
        "Batch Upload",
        sample_count=count,
    )
    result["batch"] = {"sample_count": count}
    return result


def run_dataset_evaluation(dataset_id: str) -> dict:
    dataset = find_dataset(dataset_id)
    rows = dataset.get("rows", [])
    if not rows:
        raise ValueError("Dataset has no rows to evaluate.")
    samples = samples_from_rows(rows)
    computed = evaluate_samples(samples)
    evaluated = classify_metrics(metrics_from_computed(computed))
    count = len(samples)
    result = finalize_evaluation(
        computed,
        f"Dataset '{dataset['name']}' completed for {count} responses under the configured thresholds.",
        f"{evaluated['system_status']} detected in dataset '{dataset['name']}'. Root cause report generated.",
        "Saved Dataset",
        dataset_id=dataset["id"],
        dataset_name=dataset["name"],
        sample_count=count,
    )
    dataset["updated_at"] = datetime.now(timezone.utc).isoformat()
    dataset["last_run_at"] = result["run"]["created_at"]
    dataset["last_run_id"] = result["run"]["id"]
    dataset["last_status"] = result["run"]["status"]
    dataset["last_hallucination_rate"] = result["run"]["hallucination_rate"]
    dataset["last_semantic_drift"] = result["run"]["semantic_drift"]
    save_state()
    result["dataset"] = dataset_summary(dataset)
    result["batch"] = {"sample_count": count}
    return result


def generate_support_answer(
    payload: dict,
    gemini_key: str | None = None,
    openai_key: str | None = None,
) -> dict:
    prompt = clean_payload_text(payload, "prompt")
    category = clean_payload_text(payload, "category", "Customer Support")
    context = clean_payload_text(payload, "context")
    expected = clean_payload_text(payload, "expected_answer")
    provider = clean_payload_text(payload, "provider", "fallback").lower()

    if not prompt:
        raise ValueError("Prompt is required.")

    gemini_key = gemini_key or os.environ.get("GEMINI_API_KEY")
    openai_key = openai_key or os.environ.get("OPENAI_API_KEY")

    system_instruction = (
        "You are an expert customer support assistant. Your response must be safe, professional, "
        "accurate, and fully grounded in the provided source context. Do not make any unsupported claims "
        "or promise anything not explicitly allowed in the policy context."
    )

    full_prompt = (
        f"Category: {category}\n"
        f"Source Context: {context}\n"
        f"Expected Guidelines: {expected}\n"
        f"Customer Support Ticket: {prompt}\n\n"
        "Generate a suitable, professional response for the customer support ticket based strictly on the instructions above."
    )

    if provider == "gemini" and gemini_key:
        try:
            import google.generativeai as genai
            genai.configure(api_key=gemini_key)
            model = genai.GenerativeModel(
                model_name="gemini-1.5-flash",
                system_instruction=system_instruction
            )
            response = model.generate_content(full_prompt)
            if response and response.text:
                return {
                    "answer": response.text.strip(),
                    "provider": "gemini",
                    "mode": "real"
                }
            else:
                raise ValueError("Empty response received from Gemini.")
        except Exception as exc:
            raise ValueError(f"Gemini generation error: {exc}")

    elif provider == "openai" and openai_key:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=openai_key)
            completion = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": full_prompt}
                ]
            )
            answer = completion.choices[0].message.content
            if answer:
                return {
                    "answer": answer.strip(),
                    "provider": "openai",
                    "mode": "real"
                }
            else:
                raise ValueError("Empty response received from OpenAI.")
        except Exception as exc:
            raise ValueError(f"OpenAI generation error: {exc}")

    # Fallback deterministic rules
    topic = f"{category} {prompt}".lower()
    answer = "Answer with approved support steps. Do not collect private secrets or payment details. Escalate unresolved high-risk issues."
    if any(k in topic for k in ["account", "login", "access", "reset"]):
        answer = "Acknowledge urgency. Send the official password reset account recovery path. Recommend MFA after recovery. Do not request passwords or payment details."
    elif any(k in topic for k in ["refund", "billing", "payment", "charge"]):
        answer = "Acknowledge the billing issue. Review refund status using the ticket or order reference. Do not request full card numbers, CVV codes, or payment secrets."
    elif any(k in topic for k in ["technical", "error", "bug"]):
        answer = "Acknowledge the technical issue. Request the error message, device, browser, and failing step. Escalate to technical support if troubleshooting does not resolve it."

    return {
        "answer": answer,
        "provider": "fallback",
        "mode": "deterministic"
    }

