# LLM Sentinel Pro Final Demo Runbook

Use this runbook to demo or hand over the completed project.

## 1. Start The App

The local `.env` already contains a generated `SENTINEL_API_KEY`, production profile, and SQLite state.

```powershell
.\scripts\start.ps1 -Production
```

Open:

```text
http://127.0.0.1:8000
```

## 2. Unlock Protected UI Exports

Copy the key from `.env`:

```powershell
Get-Content .env
```

Do not paste the key into shared notes. In the dashboard:

```text
Settings -> Session API Key -> paste key -> Use API Key
```

## 3. Show The Final Validation

Go to:

```text
Production Readiness
```

Expected final state:

- Readiness score: `95%`
- Status: `Ready for controlled pilot`
- Latest run: `EVAL-002`
- Latest run status: `System Healthy`
- Decision: `Approved`
- Prompt marker: `support-template-1828-final`
- Dataset: `Kaggle Customer Support Tickets 5K Validation`
- Dataset rows: `5000`

## 4. Show The Dataset Work

Prepared dataset files:

- `datasets/customer_support_tickets_200k.csv`
- `datasets/customer_support_sentinel_pilot_1k.csv`
- `datasets/customer_support_sentinel_5k.csv`

Reusable commands:

```powershell
.\scripts\prepare-kaggle-dataset.ps1
.\scripts\import-sentinel-dataset.ps1 -CsvPath datasets\customer_support_sentinel_5k.csv -Name "Kaggle Customer Support Tickets 5K Validation" -Run -ApproveHealthy
```

## 5. Show The Evidence Package

Final evidence folder:

```text
release_exports
```

Evidence files:

- `release_exports/final-handoff-1828.json`
- `release_exports/final-audit-EVAL-002.json`
- `release_exports/final-readiness-1828.json`
- `release_exports/final-drift-categories.csv`
- `release_exports/final-hallucination-scoring.csv`
- `release_exports/final-root-cause.csv`

Release manifest:

```text
RELEASE_MANIFEST.md
```

## 6. Useful API Checks

Load the key:

```powershell
$key = ((Get-Content .env | Where-Object { $_ -match '^SENTINEL_API_KEY=' }) -replace '^SENTINEL_API_KEY=','').Trim()
$headers = @{ "X-Sentinel-API-Key" = $key }
```

Check readiness:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/operations/readiness -Headers $headers
```

Export handoff package:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/reports/handoff -Headers $headers
```

Export latest audit:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/reports/audit/EVAL-002 -Headers $headers
```

Open API docs:

```text
http://127.0.0.1:8000/docs
```

## 7. Final Talking Point

This is an LLM monitoring project, not a model-training project. It validates LLM outputs against expected answers and context, detects drift and hallucination risk, tracks release decisions, and exports audit-ready handoff evidence.
