<#
.SYNOPSIS
    Railway environment audit for Windows PowerShell.

.DESCRIPTION
    Validates environment variable configuration for Railway deployments.
    Equivalent to `make audit-env` for Windows environments.

.PARAMETER Check
    CI mode: fail on errors/collisions, return nonzero on warnings.

.PARAMETER Service
    Check specific service (api, ingest, enforcement, simplicity).

.PARAMETER PrintContract
    Print the canonical env contract and exit.

.EXAMPLE
    .\scripts\audit_env.ps1
    # Runs full audit in CI mode

.EXAMPLE
    .\scripts\audit_env.ps1 -Service enforcement
    # Audit only the enforcement worker

.EXAMPLE
    .\scripts\audit_env.ps1 -PrintContract
    # Print the canonical environment contract
#>

[CmdletBinding()]
param(
    [switch]$Check,
    [ValidateSet("api", "ingest", "enforcement", "simplicity")]
    [string]$Service,
    [switch]$PrintContract
)

$ErrorActionPreference = "Stop"

# Build arguments
$args = @()

if ($Check -or (-not $Service -and -not $PrintContract)) {
    $args += "--check"
}

if ($Service) {
    $args += "--service"
    $args += $Service
}

if ($PrintContract) {
    $args += "--print-contract"
}

# Run the Python script
Write-Host "==> Running Railway environment audit" -ForegroundColor Cyan
$result = & python scripts/railway_env_audit.py @args
$exitCode = $LASTEXITCODE

# Display result
$result | ForEach-Object { Write-Host $_ }

# Interpret exit code
switch ($exitCode) {
    0 { Write-Host "`n[OK] All checks passed" -ForegroundColor Green }
    1 { Write-Host "`n[WARN] Passed with warnings (deprecated keys or missing recommended vars)" -ForegroundColor Yellow }
    2 { Write-Host "`n[ERROR] Deprecated key collisions detected" -ForegroundColor Red }
    3 { Write-Host "`n[CRITICAL] Case-sensitive conflicts detected" -ForegroundColor Red }
    default { Write-Host "`n[ERROR] Unknown exit code: $exitCode" -ForegroundColor Red }
}

exit $exitCode
