<#
.SYNOPSIS
    Railway environment audit for Windows PowerShell.

.DESCRIPTION
    Validates environment variable configuration for Railway deployments.
    Equivalent to `make audit-env` for Windows environments.

    Can run in two modes:
    1. Local mode: Checks current environment variables
    2. Railway mode: Checks Railway service variables via API (requires RAILWAY_TOKEN)

.PARAMETER Check
    CI mode: fail on errors/collisions, return nonzero on warnings.

.PARAMETER Service
    Check specific service (api, ingest, enforcement).

.PARAMETER PrintContract
    Print the canonical env contract and exit.

.PARAMETER Railway
    Audit Railway service variables via API (requires RAILWAY_TOKEN).

.PARAMETER Project
    Railway project name (default: dragonfly-civil).

.PARAMETER DryRun
    Show what would be checked without calling Railway API.

.EXAMPLE
    .\scripts\audit_env.ps1
    # Runs full local audit in CI mode

.EXAMPLE
    .\scripts\audit_env.ps1 -Railway
    # Audit Railway service variables (requires RAILWAY_TOKEN)

.EXAMPLE
    .\scripts\audit_env.ps1 -Service enforcement
    # Audit only the enforcement worker locally

.EXAMPLE
    .\scripts\audit_env.ps1 -PrintContract
    # Print the canonical environment contract
#>

[CmdletBinding()]
param(
    [switch]$Check,
    [ValidateSet("api", "ingest", "enforcement")]
    [string]$Service,
    [switch]$PrintContract,
    [switch]$Railway,
    [string]$Project = "dragonfly-civil",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

# Build arguments
$pyArgs = @()

if ($PrintContract) {
    $pyArgs += "--print-contract"
}
elseif ($Railway) {
    $pyArgs += "--railway"
    $pyArgs += "--project"
    $pyArgs += $Project
    if ($DryRun) {
        $pyArgs += "--dry-run"
    }
}
else {
    if ($Check -or (-not $Service)) {
        $pyArgs += "--check"
    }
    if ($Service) {
        $pyArgs += "--service"
        $pyArgs += $Service
    }
}

# Run the Python script
$mode = if ($Railway) { "Railway API" } else { "Local" }
Write-Host "==> Running $mode environment audit" -ForegroundColor Cyan
$result = & python scripts/railway_env_audit.py @pyArgs
$exitCode = $LASTEXITCODE

# Display result
$result | ForEach-Object { Write-Host $_ }

# Interpret exit code
switch ($exitCode) {
    0 { Write-Host "`n[OK] All checks passed" -ForegroundColor Green }
    1 { Write-Host "`n[FAIL] Missing required variables" -ForegroundColor Red }
    2 { Write-Host "`n[FAIL] Deprecated keys found" -ForegroundColor Red }
    3 { Write-Host "`n[CRITICAL] Case-sensitive conflicts detected" -ForegroundColor Red }
    4 { Write-Host "`n[ERROR] Railway API error" -ForegroundColor Red }
    default { Write-Host "`n[ERROR] Unknown exit code: $exitCode" -ForegroundColor Red }
}

exit $exitCode
