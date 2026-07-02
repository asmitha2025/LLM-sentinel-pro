param(
  [string]$EnvFile = ".env",
  [switch]$Production
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $ProjectRoot

function Import-EnvFile {
  param([string]$Path)
  if (-not (Test-Path $Path)) {
    return
  }

  foreach ($rawLine in Get-Content $Path) {
    $line = $rawLine.Trim()
    if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) {
      continue
    }

    $parts = $line -split "=", 2
    $name = $parts[0].Trim()
    $value = $parts[1].Trim().Trim('"').Trim("'")
    if ($name) {
      Set-Item -Path "Env:$name" -Value $value
    }
  }
}

Import-EnvFile -Path $EnvFile

if ($Production) {
  if (-not $env:SENTINEL_ENV) { $env:SENTINEL_ENV = "production" }
  if (-not $env:SENTINEL_STATE_BACKEND) { $env:SENTINEL_STATE_BACKEND = "sqlite" }
  if (-not $env:SENTINEL_API_KEY) {
    throw "SENTINEL_API_KEY is required for -Production mode. Set it in .env or the current shell."
  }
}

if (-not $env:SENTINEL_PORT) { $env:SENTINEL_PORT = "8000" }
if (-not $env:SENTINEL_HOST) { $env:SENTINEL_HOST = "127.0.0.1" }

Write-Host "Starting LLM Sentinel Pro on http://$($env:SENTINEL_HOST):$($env:SENTINEL_PORT)"
python -B backend\server.py
