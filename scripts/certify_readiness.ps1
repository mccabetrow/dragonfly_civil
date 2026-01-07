<#
.SYNOPSIS
    Dragonfly Civil - Production Readiness Certification

.DESCRIPTION
    Runs the full Go-Live Gate against production environment.
    This is the final gatekeeper before plaintiff onboarding.

.EXAMPLE
    .\scripts\certify_readiness.ps1

.EXAMPLE
    .\scripts\certify_readiness.ps1 -Env dev

.NOTES
    Exit Codes:
        0 - GO-LIVE APPROVED
        1 - GO-LIVE REJECTED
#>

param(
    [ValidateSet("dev", "prod")]
    [string]$Env = "prod"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

# ─────────────────────────────────────────────────────────────────────────────
# Environment Setup
# ─────────────────────────────────────────────────────────────────────────────

$env:DRAGONFLY_ENV = $Env
$env:SUPABASE_MODE = $Env

Write-Host ""
Write-Host "════════════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  DRAGONFLY CIVIL - PRODUCTION READINESS CERTIFICATION" -ForegroundColor Cyan
Write-Host "════════════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Environment: $($Env.ToUpper())" -ForegroundColor Yellow
Write-Host "  Timestamp:   $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss UTC')" -ForegroundColor Gray
Write-Host ""

# ─────────────────────────────────────────────────────────────────────────────
# Run Go-Live Gate
# ─────────────────────────────────────────────────────────────────────────────

Push-Location $ProjectRoot
try {
    & $PythonExe -m tools.go_live_gate --env $Env
    $ExitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}

# ─────────────────────────────────────────────────────────────────────────────
# Final Verdict
# ─────────────────────────────────────────────────────────────────────────────

Write-Host ""

if ($ExitCode -eq 0) {
    Write-Host "════════════════════════════════════════════════════════════════════" -ForegroundColor Green
    Write-Host ""
    Write-Host "  ✅ GO-LIVE APPROVED" -ForegroundColor Green
    Write-Host ""
    Write-Host "  The system is certified ready for plaintiff onboarding." -ForegroundColor Green
    Write-Host ""
    Write-Host "════════════════════════════════════════════════════════════════════" -ForegroundColor Green
}
else {
    Write-Host "════════════════════════════════════════════════════════════════════" -ForegroundColor Red
    Write-Host ""
    Write-Host "  ❌ GO-LIVE REJECTED" -ForegroundColor Red
    Write-Host ""
    Write-Host "  One or more gates failed. Review output above for details." -ForegroundColor Red
    Write-Host ""
    Write-Host "════════════════════════════════════════════════════════════════════" -ForegroundColor Red
}

Write-Host ""

exit $ExitCode
