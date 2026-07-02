# LLM Sentinel Pro Release Manifest

Generated: 2026-05-24

## Current Release Candidate

- Latest secured production-style run: `EVAL-002`
- Status: `System Healthy`
- Decision: `Approved`
- Dataset: `Kaggle Customer Support Tickets 5K Validation`
- Sample count: `5000`
- Hallucination rate: `0.0%`
- Semantic drift: `0.0`
- Model snapshot: `GPT-4o Support Primary`
- Prompt snapshot: `support-template-1828-final`
- Guardrail policy: `Guardrail-Alpha Strict`

## Dataset Artifacts

- Raw Kaggle file: `datasets/customer_support_tickets_200k.csv`
- Sentinel 5K validation file: `datasets/customer_support_sentinel_5k.csv`
- Sentinel 1K pilot file: `datasets/customer_support_sentinel_pilot_1k.csv`
- Converter script: `scripts/prepare-kaggle-dataset.ps1`
- Import/run script: `scripts/import-sentinel-dataset.ps1`

The raw Kaggle file has many repeated issue templates, so the converter enriches prompts with non-PII ticket metadata and excludes customer names and emails.

## Validation Completed

- 1K local pilot run: `EVAL-006`, healthy, approved
- 5K local validation run: `EVAL-007`, healthy, approved
- 5K secured production-style run: `EVAL-001`, healthy, approved
- 5K secured production-style marker run: `EVAL-002`, healthy, approved, prompt marker `1828`
- Handoff package endpoint: `/api/reports/handoff`
- Latest audit bundle: `/api/reports/audit/EVAL-002`
- Secured production-style readiness score: `95%`
- Local development readiness score before API key: `75%`
- Staging rehearsal score: `95%`

## Staging Rehearsal Command

```powershell
.\scripts\staging-simulation.ps1 -DatasetCsv datasets\customer_support_sentinel_5k.csv -DatasetName "Kaggle Customer Support Tickets 5K Validation"
```

Verified staging behavior:

- API key protection enabled
- SQLite backend enabled
- `SENTINEL_ENV=staging`
- 5K dataset imported and evaluated
- Healthy run approved
- Handoff package generated

## Production Start

```powershell
Copy-Item .env.production.example .env
notepad .env
.\scripts\start.ps1 -Production
```

A strong local `SENTINEL_API_KEY` has been generated in `.env`, which is ignored by git. Do not commit or paste the key into shared notes. Rotate it before any public deployment if this machine has been shared.

## Remaining Production Inputs

- Completed: `SENTINEL_API_KEY` configured locally
- Completed: running with `SENTINEL_STATE_BACKEND=sqlite`
- Completed: running with `SENTINEL_ENV=production`
- Optional: configure `SENTINEL_EVALUATOR_ENGINE=sentence_transformers`

## Final Handoff Status

The core app, dataset conversion, 5K validation, staging rehearsal, secured production-style start, audit export, readiness export, and release handoff package are working. The remaining work is optional external evaluator configuration and deployment to the target host.
