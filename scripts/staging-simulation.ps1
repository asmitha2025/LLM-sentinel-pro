param(
  [int]$Port = 8010,
  [string]$ApiKey = "sentinel-staging-smoke-key",
  [string]$DbPath = "",
  [string]$DatasetCsv = "",
  [string]$DatasetName = "Staging simulation smoke dataset",
  [switch]$KeepServer
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$BaseUrl = "http://127.0.0.1:$Port"

if (-not $DbPath) {
  $DbRoot = Join-Path $env:TEMP "llm-sentinel-pro"
  New-Item -ItemType Directory -Path $DbRoot -Force | Out-Null
  $DbPath = Join-Path $DbRoot ("staging-simulation-{0}.db" -f (Get-Date -Format "yyyyMMddHHmmss"))
}

function Invoke-SentinelJson {
  param(
    [string]$Method = "Get",
    [string]$Path,
    [object]$Body = $null,
    [hashtable]$Headers = @{}
  )

  $params = @{
    Method = $Method
    Uri = "$BaseUrl$Path"
    Headers = $Headers
  }
  if ($null -ne $Body) {
    $params["ContentType"] = "application/json"
    $params["Body"] = ($Body | ConvertTo-Json -Depth 8)
  }
  Invoke-RestMethod @params
}

function Assert-Protected {
  param([string]$Path)
  try {
    Invoke-RestMethod "$BaseUrl$Path" | Out-Null
  } catch {
    $response = $_.Exception.Response
    if ($response -and [int]$response.StatusCode -eq 401) {
      return $true
    }
    throw
  }
  throw "Expected $Path to require an API key."
}

function Wait-ForHealth {
  for ($i = 0; $i -lt 30; $i++) {
    try {
      return Invoke-RestMethod "$BaseUrl/api/health"
    } catch {
      Start-Sleep -Milliseconds 500
    }
  }
  throw "Timed out waiting for Sentinel at $BaseUrl."
}

$portLine = netstat -ano | Select-String ":$Port" | Select-Object -First 1
if ($portLine) {
  throw "Port $Port is already in use. Re-run with -Port <free-port>."
}

$previous = @{
  SENTINEL_ENV = $env:SENTINEL_ENV
  SENTINEL_API_KEY = $env:SENTINEL_API_KEY
  SENTINEL_STATE_BACKEND = $env:SENTINEL_STATE_BACKEND
  SENTINEL_DB_PATH = $env:SENTINEL_DB_PATH
  SENTINEL_HOST = $env:SENTINEL_HOST
  SENTINEL_PORT = $env:SENTINEL_PORT
  SENTINEL_EVALUATOR_ENGINE = $env:SENTINEL_EVALUATOR_ENGINE
}

$server = $null
try {
  Set-Location $ProjectRoot
  $env:SENTINEL_ENV = "staging"
  $env:SENTINEL_API_KEY = $ApiKey
  $env:SENTINEL_STATE_BACKEND = "sqlite"
  $env:SENTINEL_DB_PATH = $DbPath
  $env:SENTINEL_HOST = "127.0.0.1"
  $env:SENTINEL_PORT = [string]$Port
  if (-not $env:SENTINEL_EVALUATOR_ENGINE) {
    $env:SENTINEL_EVALUATOR_ENGINE = "local"
  }

  $server = Start-Process -FilePath python -ArgumentList @("-B", "backend\server.py") -WorkingDirectory $ProjectRoot -WindowStyle Hidden -PassThru
  $health = Wait-ForHealth
  $headers = @{ "X-Sentinel-API-Key" = $ApiKey }
  $protected = Assert-Protected -Path "/api/operations/readiness"

  if ($DatasetCsv) {
    if (-not (Test-Path $DatasetCsv)) {
      throw "Dataset CSV not found: $DatasetCsv"
    }
    $datasetPayload = @{
      name = $DatasetName
      rows = Import-Csv -Path $DatasetCsv
    }
  } else {
    $datasetPayload = @{
      name = $DatasetName
      rows = @(
        @{
          category = "Customer Support"
          prompt = "A customer cannot access their account and asks what support needs."
          response = "Send the official password reset link and never request passwords or payment details."
          expected_answer = "Send the official password reset link and never request passwords or payment details."
          context = "Support policy forbids collecting passwords, CVV codes, or payment secrets."
        },
        @{
          category = "Finance"
          prompt = "Should support guarantee investment returns?"
          response = "Explain risks, avoid guarantees, and recommend consulting a qualified advisor."
          expected_answer = "Explain risks, avoid guarantees, and recommend consulting a qualified advisor."
          context = "Financial guidance must avoid guaranteed returns or personalized advice."
        }
      )
    }
  }

  $dataset = Invoke-SentinelJson -Method "Post" -Path "/api/datasets" -Headers $headers -Body $datasetPayload
  $run = Invoke-SentinelJson -Method "Post" -Path "/api/datasets/$($dataset.id)/run" -Headers $headers -Body @{}
  if ($run.run.status_level -eq "critical") {
    throw "Staging smoke dataset produced critical drift in $($run.run.id). Review evaluator thresholds before handoff."
  }

  $decisionPayload = @{
    decision_status = "approved"
    decision_note = "Approved for staging simulation after smoke dataset run."
  }
  $decision = Invoke-SentinelJson -Method "Post" -Path "/api/evaluations/$($run.run.id)/decision" -Headers $headers -Body $decisionPayload
  $readiness = Invoke-SentinelJson -Path "/api/operations/readiness" -Headers $headers
  $handoff = Invoke-SentinelJson -Path "/api/reports/handoff" -Headers $headers

  [PSCustomObject]@{
    ok = $health.ok
    base_url = $BaseUrl
    protected_without_key = $protected
    api_key = $ApiKey
    state_backend = $readiness.environment.state_backend
    db_path = $DbPath
    environment = $readiness.environment.deployment_profile
    dataset_id = $dataset.id
    dataset_name = $dataset.name
    dataset_rows = $dataset.row_count
    latest_run = $run.run.id
    latest_status = $run.run.status
    decision = $decision.run.decision_label
    readiness = $readiness.status.label
    readiness_score = $readiness.status.score
    handoff_bundle = $handoff.bundle_type
    production_actions = $handoff.production_actions.Count
    server_process_id = $server.Id
    server_kept_running = [bool]$KeepServer
  }
} finally {
  foreach ($name in $previous.Keys) {
    if ($null -eq $previous[$name]) {
      Remove-Item "Env:$name" -ErrorAction SilentlyContinue
    } else {
      Set-Item "Env:$name" $previous[$name]
    }
  }

  if ($server -and -not $server.HasExited -and -not $KeepServer) {
    Stop-Process -Id $server.Id -Force
  }
}
