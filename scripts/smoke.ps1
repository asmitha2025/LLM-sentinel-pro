param(
  [string]$BaseUrl = "http://127.0.0.1:8000",
  [string]$ApiKey = $env:SENTINEL_API_KEY
)

$ErrorActionPreference = "Stop"
$headers = @{}
if ($ApiKey) {
  $headers["X-Sentinel-API-Key"] = $ApiKey
}

$health = Invoke-RestMethod "$BaseUrl/api/health"
$readiness = Invoke-RestMethod "$BaseUrl/api/operations/readiness" -Headers $headers

[PSCustomObject]@{
  ok = $health.ok
  service = $health.service
  readiness = $readiness.status.label
  score = $readiness.status.score
  backend = $readiness.environment.state_backend
}
