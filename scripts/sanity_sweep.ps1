<#
.SYNOPSIS
    Dragonfly Civil - Sanity Sweep

.DESCRIPTION
    Fast local sanity check before touching production.
    Performs: compile check, import validation, and silent Go-Live Gate.

.EXAMPLE
    .\scripts\sanity_sweep.ps1

.EXAMPLE
    .\scripts\sanity_sweep.ps1 -Env prod

.NOTES
    Exit Codes:
        0 - All checks passed
        1 - One or more checks failed
#>

param(
    [ValidateSet("dev", "prod")]
    [string]$Env = "dev"
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

$env:SUPABASE_MODE = $Env

Write-Host ""
Write-Host "════════════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  DRAGONFLY CIVIL - SANITY SWEEP" -ForegroundColor Cyan
Write-Host "════════════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Environment: $($Env.ToUpper())" -ForegroundColor Yellow
Write-Host "  Timestamp:   $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor Gray
Write-Host ""

Push-Location $ProjectRoot
$OverallSuccess = $true

# ─────────────────────────────────────────────────────────────────────────────
# Step 1: Compile Check (Syntax Errors)
# ─────────────────────────────────────────────────────────────────────────────

Write-Host "────────────────────────────────────────────────────────────────────" -ForegroundColor DarkGray
Write-Host "[Step 1/3] Compile Check" -ForegroundColor White
Write-Host "────────────────────────────────────────────────────────────────────" -ForegroundColor DarkGray

try {
    & $PythonExe -m py_compile tools/go_live_gate.py backend/core/bootstrap.py src/supabase_client.py 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  ✅ No syntax errors detected" -ForegroundColor Green
    }
    else {
        Write-Host "  ❌ Syntax errors found!" -ForegroundColor Red
        $OverallSuccess = $false
    }
}
catch {
    Write-Host "  ❌ Compile check failed: $_" -ForegroundColor Red
    $OverallSuccess = $false
}

Write-Host ""

# ─────────────────────────────────────────────────────────────────────────────
# Step 2: Import Check (Circular Dependencies)
# ─────────────────────────────────────────────────────────────────────────────

Write-Host "────────────────────────────────────────────────────────────────────" -ForegroundColor DarkGray
Write-Host "[Step 2/3] Import Check" -ForegroundColor White
Write-Host "────────────────────────────────────────────────────────────────────" -ForegroundColor DarkGray

try {
    & $PythonExe -c "import tools.go_live_gate; import backend.core.bootstrap; import src.supabase_client; print('  Imports OK')" 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  ✅ No circular imports detected" -ForegroundColor Green
    }
    else {
        Write-Host "  ❌ Import errors found!" -ForegroundColor Red
        $OverallSuccess = $false
    }
}
catch {
    Write-Host "  ❌ Import check failed: $_" -ForegroundColor Red
    $OverallSuccess = $false
}

Write-Host ""

# ─────────────────────────────────────────────────────────────────────────────
# Step 3: Go-Live Gate (Silent Mode)
# ─────────────────────────────────────────────────────────────────────────────

Write-Host "────────────────────────────────────────────────────────────────────" -ForegroundColor DarkGray
Write-Host "[Step 3/3] Go-Live Gate (Silent Mode)" -ForegroundColor White
Write-Host "────────────────────────────────────────────────────────────────────" -ForegroundColor DarkGray

try {
    & $PythonExe -m tools.go_live_gate --env $Env --skip-discord
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  ✅ Go-Live Gate passed" -ForegroundColor Green
    }
    else {
        Write-Host "  ❌ Go-Live Gate failed (exit $LASTEXITCODE)" -ForegroundColor Red
        $OverallSuccess = $false
    }
}
catch {
    Write-Host "  ❌ Go-Live Gate error: $_" -ForegroundColor Red
    $OverallSuccess = $false
}
finally {
    Pop-Location
}

# ─────────────────────────────────────────────────────────────────────────────
# Final Summary
# ─────────────────────────────────────────────────────────────────────────────

Write-Host ""
Write-Host "════════════════════════════════════════════════════════════════════" -ForegroundColor Cyan

if ($OverallSuccess) {
    Write-Host ""
    Write-Host "  ✅ SANITY SWEEP PASSED" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Codebase is structurally sound. Safe to push to main." -ForegroundColor Green
    Write-Host ""
    Write-Host "════════════════════════════════════════════════════════════════════" -ForegroundColor Green
    exit 0
}
else {
    Write-Host ""
    Write-Host "  ❌ SANITY SWEEP FAILED" -ForegroundColor Red
    Write-Host ""
    Write-Host "  Review errors above before pushing." -ForegroundColor Red
    Write-Host ""
    Write-Host "════════════════════════════════════════════════════════════════════" -ForegroundColor Red
    exit 1
}
