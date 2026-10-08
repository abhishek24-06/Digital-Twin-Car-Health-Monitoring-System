<#
.SYNOPSIS
  Starts the Digital Twin local infrastructure: MQTT broker, REST API and MQTT
  subscriber, all tracked so dt-stop.ps1 / dt-status.ps1 can manage them.

.DESCRIPTION
  Each component is launched as a hidden background process with its PID and
  log files recorded under "$env:TEMP\dtwin". Starting an already-running
  component is a no-op.

  The MQTT broker uses infrastructure/mosquitto/mosquitto.local.conf (loopback,
  anonymous) unless DT_MOSQUITTO_EXE is set. If no mosquitto binary is found,
  the broker is skipped with a warning -- a Docker/local broker is fine.

  The API exposes the per-vehicle Simulation Control endpoints, but the
  per-vehicle simulator processes themselves are NOT started or managed here:
  Simulation Control drives them via the API.

.EXAMPLE
  ./scripts/dt-start.ps1
#>
[CmdletBinding()]
param(
  [string]$ApiPort = "8000"
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Backend = Join-Path $RepoRoot "backend"
$StateDir = Join-Path $env:TEMP "dtwin"
$MosquittoConf = Join-Path $Backend "infrastructure\mosquitto\mosquitto.local.conf"

New-Item -ItemType Directory -Path $StateDir -Force | Out-Null

# Print the database target the stack will use (host/db only, credentials
# never shown) so a silent local/Supabase split cannot go unnoticed.
$EnvFile = Join-Path $Backend ".env"
if (Test-Path -LiteralPath $EnvFile) {
  $DbLine = Get-Content -LiteralPath $EnvFile | Where-Object { $_ -match '^DATABASE_URL=' } | Select-Object -First 1
  if ($DbLine) {
    $DbUrl = ($DbLine -split '=', 2)[1]
    if ($DbUrl -match '://([^:/?#]+)(?::([0-9]+))?/([^?]+)') {
      $DbHost = $matches[1]
      $DbPort = $matches[2]
      $DbName = $matches[3]
      $DbClass = if ($DbHost -in @('localhost', '127.0.0.1', '::1', '0.0.0.0')) { 'LOCAL' } elseif ($DbHost -like '*supabase*') { 'SUPABASE (runtime)' } else { 'REMOTE' }
      Write-Host (
        "DB target : {0}:{1}/{2} -> {3}" -f $DbHost, $DbPort, $DbName, $DbClass
      ) -ForegroundColor Cyan
    } else {
      Write-Host "DB target : unparsable DATABASE_URL in backend/.env" -ForegroundColor Yellow
    }
  } else {
    Write-Host "DB target : DATABASE_URL not set in backend/.env" -ForegroundColor Yellow
  }
}

$PythonCandidates = @(
  (Join-Path $Backend ".venv\Scripts\python.exe"),
  (Join-Path $Backend ".venv\bin\python.exe")
)
$Python = $PythonCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $Python) {
  Write-Error "No local virtualenv found under $Backend. Create one (backend\.venv) and install backend deps first."
  exit 1
}

function Get-MosquittoExecutable {
  if ($env:DT_MOSQUITTO_EXE) { return $env:DT_MOSQUITTO_EXE }
  $wellKnown = Join-Path $env:ProgramFiles "mosquitto\mosquitto.exe"
  if (Test-Path -LiteralPath $wellKnown) { return $wellKnown }
  $onPath = Get-Command mosquitto -ErrorAction SilentlyContinue
  if ($onPath) { return $onPath.Source }
  return $null
}

function Start-Tracked {
  param(
    [string]$Name,
    [string]$FilePath,
    [string[]]$Arguments,
    [string]$WorkingDir
  )
  $pidFile = Join-Path $StateDir "$Name.pid"
  if (Test-Path -LiteralPath $pidFile) {
    $existing = [int](Get-Content -LiteralPath $pidFile)
    if (Get-Process -Id $existing -ErrorAction SilentlyContinue) {
      Write-Host "$Name already running (PID $existing)" -ForegroundColor Yellow
      return
    }
  }

  $stdout = Join-Path $StateDir "$Name.out.log"
  $stderr = Join-Path $StateDir "$Name.err.log"
  $process = Start-Process -FilePath $FilePath -ArgumentList $Arguments `
    -WorkingDirectory $WorkingDir -WindowStyle Hidden `
    -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
  $process.Id | Set-Content -LiteralPath $pidFile
  Write-Host "$Name started (PID $($process.Id), logs in $StateDir)" -ForegroundColor Green
}

$mosquittoExe = Get-MosquittoExecutable
if ($mosquittoExe) {
  if (Test-Path -LiteralPath $MosquittoConf) {
    Start-Tracked -Name "mosquitto" -FilePath $mosquittoExe `
      -Arguments @("-c", $MosquittoConf) -WorkingDir $Backend
  } else {
    Write-Warning "Broker config not found at $MosquittoConf; skipping broker."
  }
} else {
  Write-Warning "mosquitto binary not found (set DT_MOSQUITTO_EXE). Skipping broker; the subscriber will keep retrying."
}

$apiArgs = @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", $ApiPort)
Start-Tracked -Name "api" -FilePath $Python -Arguments $apiArgs -WorkingDir $Backend

Start-Tracked -Name "subscriber" -FilePath $Python -Arguments @("-m", "app.mqtt.subscriber") -WorkingDir $Backend

& (Join-Path $PSScriptRoot "dt-status.ps1")