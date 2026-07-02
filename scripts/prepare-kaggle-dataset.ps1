param(
  [string]$InputPath = "datasets\customer_support_tickets_200k.csv",
  [string]$OutputPath = "datasets\customer_support_sentinel_5k.csv",
  [int]$Limit = 5000
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $ProjectRoot

if (-not (Test-Path $InputPath)) {
  throw "Input dataset not found: $InputPath"
}

$requiredColumns = @(
  "category",
  "issue_description",
  "resolution_notes",
  "product",
  "priority",
  "status",
  "channel",
  "region",
  "sla_breached",
  "issue_complexity_score"
)

$headers = (Get-Content -Path $InputPath -TotalCount 1) -split ","
$missing = $requiredColumns | Where-Object { $_ -notin $headers }
if ($missing) {
  throw "Missing required source columns: $($missing -join ', ')"
}

$seenPrompts = @{}
$rows = New-Object System.Collections.Generic.List[object]
$sourceRows = 0
$skipped = 0

Import-Csv -Path $InputPath | ForEach-Object {
  if ($rows.Count -ge $Limit) {
    return
  }

  $sourceRows += 1
  $prompt = [string]$_.issue_description
  $prompt = $prompt.Trim()
  $answer = [string]$_.resolution_notes
  $answer = $answer.Trim()
  $category = [string]$_.category
  $category = $category.Trim()
  if (-not $category) {
    $category = "Customer Support"
  }

  if (-not $prompt -or -not $answer -or $prompt.Length -lt 12 -or $answer.Length -lt 12) {
    $skipped += 1
    return
  }

  $enrichedPrompt = @(
    "Customer support ticket for $($_.product).",
    "Category: $category.",
    "Issue: $prompt",
    "Priority: $($_.priority).",
    "Channel: $($_.channel).",
    "Region: $($_.region).",
    "Subscription: $($_.subscription_type).",
    "Previous tickets: $($_.previous_tickets)."
  ) -join " "
  $dedupeKey = @(
    $enrichedPrompt,
    $answer,
    $_.status,
    $_.sla_breached,
    $_.issue_complexity_score,
    $_.customer_segment,
    $_.operating_system,
    $_.browser,
    $_.payment_method,
    $_.language
  ) -join "|"

  if ($seenPrompts.ContainsKey($dedupeKey)) {
    $skipped += 1
    return
  }

  $seenPrompts[$dedupeKey] = $true
  $context = @(
    "Product: $($_.product)",
    "Priority: $($_.priority)",
    "Ticket status: $($_.status)",
    "Channel: $($_.channel)",
    "Region: $($_.region)",
    "SLA breached: $($_.sla_breached)",
    "Issue complexity: $($_.issue_complexity_score)",
    "Support policy: do not request passwords, payment secrets, or unsupported guarantees; answer only from the ticket and approved resolution."
  ) -join " | "

  $rows.Add([PSCustomObject]@{
    category = $category
    prompt = $enrichedPrompt
    response = $answer
    expected_answer = $answer
    context = $context
  })
}

if ($rows.Count -eq 0) {
  throw "No valid rows were produced from $InputPath."
}

$outputDirectory = Split-Path $OutputPath -Parent
if ($outputDirectory) {
  New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null
}

$rows | Export-Csv -Path $OutputPath -NoTypeInformation -Encoding UTF8

$categoryCounts = $rows | Group-Object category | Sort-Object Count -Descending | Select-Object -First 10 Name,Count

[PSCustomObject]@{
  input = (Resolve-Path $InputPath).Path
  output = (Resolve-Path $OutputPath).Path
  requested_limit = $Limit
  produced_rows = $rows.Count
  scanned_rows = $sourceRows
  skipped_rows = $skipped
  unique_prompts = $seenPrompts.Count
  categories = $categoryCounts
}
