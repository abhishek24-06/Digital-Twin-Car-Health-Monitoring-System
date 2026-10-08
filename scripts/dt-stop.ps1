<#
.SYNOPSIS
  Stops the Digital Twin local infrastructure started by dt-start.ps1: MQTT
  broker, REST API and MQTT subscriber. Only tracked components are stopped;
  per-vehicle simulator subprocesses are owned by the API and are not touched.

.EXAMPLE
  ./scripts/dt-stop.ps1
#>
[CmdletBinding()]

$ErrorActionPreference = "Stop"

$StateDir = Join-Path $env:TEMP "dtwin"
if (-not (Test-Path -LiteralPath $StateDir)) {
  Write-Host "Nothing tracked under $StateDir; nothing to stop." -ForegroundColor Yellow
  exit 0
}

$stopped = @()
Get-ChildItem -LiteralPath $StateDir -Filter "*.pid" | ForEach-Object {
  $name = $_.BaseName
  try {
    $pidValue = [int](Get-Content -LiteralPath $_.FullName)
  } catch {
    Write-Warning "$name pid file unreadable; leaving it in place."
    return
  }
  $process = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
  if ($process) {
    Stop-Process -Id $pidValue -Force -ErrorAction SilentlyContinue
    Write-Host "$name stopped (PID $pidValue)" -ForegroundColor Green
    $stopped += $name
  } else {
    Write-Host "$name was not running (stale pid $pidValue)" -ForegroundColor DarkGray
  }
  Remove-Item -LiteralPath $_.FullName -Force -ErrorAction SilentlyContinue
}

if ($stopped.Count -eq 0) {
  Write-Host "No tracked infrastructure was running." -ForegroundColor Yellow
}