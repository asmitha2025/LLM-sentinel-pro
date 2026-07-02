param(
  [string]$CsvPath = "datasets\customer_support_sentinel_pilot_1k.csv",
  [string]$Name = "Kaggle Customer Support Tickets Pilot 1K",
  [string]$BaseUrl = "http://127.0.0.1:8000",
  [string]$ApiKey = $env:SENTINEL_API_KEY,
  [switch]$Run,
  [switch]$ApproveHealthy
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $ProjectRoot

if (-not (Test-Path $CsvPath)) {
  throw "CSV not found: $CsvPath"
}

$required = @("category", "prompt", "response", "expected_answer", "context")
$headers = (Get-Content -Path $CsvPath -TotalCount 1) -replace '"', '' -split ","
$missing = $required | Where-Object { $_ -notin $headers }
if ($missing) {
  throw "CSV is missing Sentinel columns: $($missing -join ', ')"
}

$headersMap = @{}
if ($ApiKey) {
  $headersMap["X-Sentinel-API-Key"] = $ApiKey
}

function Invoke-SentinelJson {
  param(
    [string]$Method = "Get",
    [string]$Path,
    [object]$Body = $null
  )

  $params = @{
    Method = $Method
    Uri = "$BaseUrl$Path"
    Headers = $headersMap
  }
  if ($null -ne $Body) {
    $params["ContentType"] = "application/json"
    $params["Body"] = ($Body | ConvertTo-Json -Depth 8)
  }
  Invoke-RestMethod @params
}

$rows = Import-Csv -Path $CsvPath
if (-not $rows.Count) {
  throw "CSV has no data rows."
}

$dataset = Invoke-SentinelJson -Method "Post" -Path "/api/datasets" -Body @{
  name = $Name
  rows = $rows
}

$runResult = $null
$decision = $null
if ($Run) {
  $runResult = Invoke-SentinelJson -Method "Post" -Path "/api/datasets/$($dataset.id)/run" -Body @{}
  if ($ApproveHealthy -and $runResult.run.status_level -ne "critical") {
    $decision = Invoke-SentinelJson -Method "Post" -Path "/api/evaluations/$($runResult.run.id)/decision" -Body @{
      decision_status = "approved"
      decision_note = "Approved after imported Sentinel dataset validation run."
    }
  }
}

$readiness = Invoke-SentinelJson -Path "/api/operations/readiness"

[PSCustomObject]@{
  dataset_id = $dataset.id
  dataset_name = $dataset.name
  row_count = $dataset.row_count
  run_id = if ($runResult) { $runResult.run.id } else { $null }
  run_status = if ($runResult) { $runResult.run.status } else { $null }
  run_level = if ($runResult) { $runResult.run.status_level } else { $null }
  hallucination_rate = if ($runResult) { $runResult.run.hallucination_rate } else { $null }
  semantic_drift = if ($runResult) { $runResult.run.semantic_drift } else { $null }
  decision = if ($decision) { $decision.run.decision_label } else { $null }
  readiness = $readiness.status.label
  readiness_score = $readiness.status.score
}
