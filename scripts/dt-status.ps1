<#
.SYNOPSIS
  Reports the status of the Digital Twin local infrastructure tracked by
  dt-start.ps1: MQTT broker (1883), REST API (8000) and MQTT subscriber.

.DESCRIPTION
  For each tracked component the running state (from its pid file) and, where
  relevant, a live probe is shown. Per-vehicle simulator subprocesses are owned
  by the API and are intentionally not listed here -- Simulation Control
  surfaces their state.

.EXAMPLE
  ./scripts/dt-status.ps1
#>
[CmdletBinding()]
param(
  [int]$ApiPort = 8000
)

$StateDir = Join-Path $env:TEMP "dtwin"

function Test-TcpPort {
  param([int]$Port)
  try {
    $client = [System.Net.Sockets.TcpClient]::new()
    $async = $client.ConnectAsync("127.0.0.1", $Port)
    $null = $async.Wait(500)
    $open = $client.Connected
    $client.Dispose()
    return $open
  } catch {
    return $false
  }
}

function Get-TrackedState {
  param([string]$Name, [string]$Label)
  $pidFile = Join-Path $StateDir "$Name.pid"
  if (-not (Test-Path -LiteralPath $pidFile)) {
    return "$Label : stopped (no pid file)"
  }
  try {
    $pidValue = [int](Get-Content -LiteralPath $pidFile)
  } catch {
    return "$Label : unknown (unreadable pid file)"
  }
  if (Get-Process -Id $pidValue -ErrorAction SilentlyContinue) {
    return "$Label : running (PID $pidValue)"
  }
  return "$Label : stopped (stale pid $pidValue)"
}

Write-Host "Default shims: venv=$env:TEMP\dtwin (state), API=http://127.0.0.1:$ApiPort" -ForegroundColor DarkGray
Write-Host ""

Get-TrackedState "mosquitto"   "MQTT broker  (1883)"
Get-TrackedState "api"         "REST API     ($ApiPort)"
Get-TrackedState "subscriber"  "MQTT subscriber"

Write-Host ""
Write-Host "Port probes:" -ForegroundColor DarkGray
$brokerOpen = Test-TcpPort 1883
$apiOpen = Test-TcpPort $ApiPort
Write-Host ("  {0,5} : {1}" -f 1883, $(if ($brokerOpen) { "open" } else { "closed" }))
Write-Host ("  {0,5} : {1}" -f $ApiPort, $(if ($apiOpen) { "open" } else { "closed" }))

if ($apiOpen) {
  try {
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:$ApiPort/api/v1/health" -TimeoutSec 3
    Write-Host ""
    Write-Host "API health : $($health.status) ($($health.service))" -ForegroundColor Green
  } catch {
    Write-Host ""
    Write-Host "API health : unreachable / unauthenticated probe failed" -ForegroundColor Yellow
  }
}