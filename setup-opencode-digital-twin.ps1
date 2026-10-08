$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host " Digital Twin - OpenCode Skill Setup"
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""

# --------------------------------------------------
# Verify project root
# --------------------------------------------------

if (-not (Test-Path ".git")) {
    Write-Host "ERROR: .git directory not found." -ForegroundColor Red
    Write-Host ""
    Write-Host "Run this script from:"
    Write-Host "C:\Users\Abhishek\Desktop\Digital Twin"
    exit 1
}

Write-Host "Project root:"
Write-Host (Get-Location)
Write-Host ""

# --------------------------------------------------
# Create OpenCode directories
# --------------------------------------------------

Write-Host "[1/4] Creating OpenCode directories..." -ForegroundColor Yellow

New-Item -ItemType Directory -Force -Path ".opencode\skills" | Out-Null
New-Item -ItemType Directory -Force -Path ".opencode\commands" | Out-Null

Write-Host "  OK .opencode\skills"
Write-Host "  OK .opencode\commands"
Write-Host ""

# --------------------------------------------------
# Engineering skills
# --------------------------------------------------

$skills = @(
    "spec-driven-development",
    "planning-and-task-breakdown",
    "incremental-implementation",
    "test-driven-development",
    "code-review-and-quality",
    "debugging-and-error-recovery",
    "api-and-interface-design",
    "security-and-hardening"
)

Write-Host "[2/4] Installing engineering skills..." -ForegroundColor Yellow
Write-Host ""

foreach ($skill in $skills) {

    Write-Host "Installing $skill..." -ForegroundColor Cyan

    npx skills add addyosmani/agent-skills `
        --skill $skill `
        --agent opencode `
        --yes

    if ($LASTEXITCODE -ne 0) {
        Write-Host "FAILED: $skill" -ForegroundColor Red
        exit 1
    }

    Write-Host "  OK $skill" -ForegroundColor Green
}

Write-Host ""

# --------------------------------------------------
# UI UX Pro Max
# --------------------------------------------------

Write-Host "[3/4] Installing UI UX Pro Max..." -ForegroundColor Yellow
Write-Host ""

npx ui-ux-pro-max-cli init --ai opencode

if ($LASTEXITCODE -ne 0) {
    Write-Host "UI UX Pro Max installation failed." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "  OK UI UX Pro Max" -ForegroundColor Green
Write-Host ""

# --------------------------------------------------
# Superpowers configuration
# --------------------------------------------------

Write-Host "[4/4] Configuring Superpowers..." -ForegroundColor Yellow

$opencodeConfig = "opencode.json"

if (Test-Path $opencodeConfig) {

    $config = Get-Content $opencodeConfig -Raw | ConvertFrom-Json

} else {

    $config = [PSCustomObject]@{
        '$schema' = "https://opencode.ai/config.json"
        plugins = @()
    }
}

if (-not $config.plugins) {
    $config | Add-Member -MemberType NoteProperty -Name plugins -Value @()
}

$plugin = "superpowers@git+https://github.com/obra/superpowers.git"

if ($config.plugins -notcontains $plugin) {
    $config.plugins += $plugin
    Write-Host "  OK Superpowers added" -ForegroundColor Green
} else {
    Write-Host "  OK Superpowers already configured" -ForegroundColor Green
}

$config | ConvertTo-Json -Depth 10 | Set-Content $opencodeConfig

Write-Host ""
Write-Host "==================================================" -ForegroundColor Green
Write-Host " Setup Complete"
Write-Host "==================================================" -ForegroundColor Green
Write-Host ""

Write-Host "Installed:"
foreach ($skill in $skills) {
    Write-Host "  OK $skill"
}

Write-Host "  OK UI UX Pro Max"
Write-Host "  OK Superpowers"
Write-Host ""

Write-Host "Restart OpenCode before testing the skills." -ForegroundColor Yellow
Write-Host ""