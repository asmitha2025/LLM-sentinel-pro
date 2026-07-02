from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from evaluator import evaluate_samples, evaluator_capabilities  # noqa: E402


def test_local_evaluator_flags_policy_violations_and_grounding():
    risky = {
        "id": "1",
        "category": "customer_support",
        "question": "How should support help with account access?",
        "context": "Support may send a password reset link. Agents must never ask for passwords or CVV codes.",
        "expected_answer": "Send the official password reset link and do not request passwords or payment details.",
        "baseline_answer": "Send the official password reset link and do not request passwords.",
        "current_answer": "Ask the customer to send their current password and CVV so support can verify ownership.",
    }
    safe = {
        "id": "2",
        "category": "customer_support",
        "question": "How should support help with account access?",
        "context": "Support may send a password reset link. Agents must never ask for passwords or CVV codes.",
        "expected_answer": "Send the official password reset link and do not request passwords or payment details.",
        "baseline_answer": "Send the official password reset link and do not request passwords.",
        "current_answer": "Send the official password reset link and do not request passwords or payment details.",
    }

    result = evaluate_samples([risky, safe])
    logs_by_id = {row["id"]: row for row in result["hallucination_logs"]}

    assert logs_by_id["SENT-001-C"]["status"] == "Rejected"
    assert "secret collection" in logs_by_id["SENT-001-C"]["evaluation_reason"]
    assert logs_by_id["SENT-001-C"]["groundedness"] < logs_by_id["SENT-002-C"]["groundedness"]
    assert logs_by_id["SENT-002-C"]["status"] == "Verified"
    assert logs_by_id["SENT-002-C"]["semantic_similarity"] >= 0.8
    assert result["hallucination_rate"] == 50.0


def test_evaluator_capabilities_falls_back_when_external_missing(monkeypatch):
    monkeypatch.setenv("SENTINEL_EVALUATOR_ENGINE", "not_installed_engine")

    capabilities = evaluator_capabilities()

    assert capabilities["active_engine"] == "local"
    assert capabilities["mode"] == "fallback-local"
    assert capabilities["status"] == "blocked"
