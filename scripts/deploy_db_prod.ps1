<#
.SYNOPSIS
    B3 Production Database Rollout - Zero-tolerance deployment script.

.DESCRIPTION
    Orchestrates Phase 1 (Database Rollout) of the B3 Deployment Control protocol.
    
    This script enforces the principle: "One button can kill the system."
    It requires explicit human confirmation before touching production.

    Steps:
    1. Safety stop confirmation (workers scaled to 0)
    2. Load prod environment (.env.prod)
    3. Apply migrations via supabase db push
    4. Verify contract truth (SQL introspection)
    5. Show evidence for manual verification

.EXAMPLE
    .\scripts\deploy_db_prod.ps1

.NOTES
    NEVER run this while workers are active in Railway.
    ALWAYS run gate_preflight.ps1 first.
#>

param(
    [switch]$SkipConfirmation,  # FOR TESTING ONLY - never use in production
    [switch]$DryRun             # Show what would be done without doing it
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

function Write-Banner {
    param([string]$Message, [string]$Color = "Cyan")
    Write-Host ""
    Write-Host ("=" * 70) -ForegroundColor $Color
    Write-Host "  $Message" -ForegroundColor $Color
    Write-Host ("=" * 70) -ForegroundColor $Color
    Write-Host ""
}

function Write-Warn {
    param([string]$Message)
    Write-Host "[!] $Message" -ForegroundColor Yellow
}

function Write-Step {
    param([int]$Number, [string]$Description)
    Write-Host ""
    Write-Host "[$Number] $Description" -ForegroundColor Cyan
    Write-Host ("-" * 50) -ForegroundColor DarkGray
}

function Invoke-AbortDeploy {
    param([string]$Reason)
    Write-Host ""
    Write-Host ("=" * 70) -ForegroundColor Red
    Write-Host "  [X] DEPLOYMENT ABORTED" -ForegroundColor Red
    Write-Host "  $Reason" -ForegroundColor Red
    Write-Host ("=" * 70) -ForegroundColor Red
    Write-Host ""
    exit 1
}

# ============================================================================
# MAIN EXECUTION
# ============================================================================

Write-Banner "B3 PRODUCTION DATABASE ROLLOUT" "Magenta"

# ----------------------------------------------------------------------------
# STEP 1: Safety Stop Confirmation
# ----------------------------------------------------------------------------
Write-Step 1 "SAFETY STOP CONFIRMATION"

Write-Host ""
Write-Host "+----------------------------------------------------------------------+" -ForegroundColor Red
Write-Host "|                                                                      |" -ForegroundColor Red
Write-Host "|  [!] STOP: HAVE YOU SCALED WORKERS TO 0 IN RAILWAY?                  |" -ForegroundColor Red
Write-Host "|                                                                      |" -ForegroundColor Red
Write-Host "|  Database migrations MUST NOT run while workers are active.         |" -ForegroundColor Red
Write-Host "|  Old worker code may crash or corrupt data.                         |" -ForegroundColor Red
Write-Host "|                                                                      |" -ForegroundColor Red
Write-Host "|  Go to Railway -> Worker Service -> Scale to 0                      |" -ForegroundColor Red
Write-Host "|                                                                      |" -ForegroundColor Red
Write-Host "+----------------------------------------------------------------------+" -ForegroundColor Red
Write-Host ""

if (-not $SkipConfirmation) {
    $confirmation = Read-Host "Type 'YES' to confirm workers are scaled to 0"
    
    if ($confirmation -ne "YES") {
        Invoke-AbortDeploy "User did not confirm workers are stopped. Deploy cancelled."
    }
    
    Write-Host "[OK] User confirmed workers are stopped." -ForegroundColor Green
}

if ($DryRun) {
    Write-Host "[DRY RUN] Would proceed with deployment" -ForegroundColor Yellow
}

# ----------------------------------------------------------------------------
# STEP 2: Load Production Environment
# ----------------------------------------------------------------------------
Write-Step 2 "LOADING PRODUCTION ENVIRONMENT"

$envFile = Join-Path $RepoRoot ".env.prod"
if (-not (Test-Path $envFile)) {
    Invoke-AbortDeploy ".env.prod not found. Cannot deploy to production."
}

# Set SUPABASE_MODE to prod
$env:SUPABASE_MODE = "prod"
$env:ENV_FILE = $envFile

# Load env vars from file
$loadedVars = @()
Get-Content $envFile | ForEach-Object {
    if ($_ -match '^\s*#') { return }
    if ($_ -match '^\s*$') { return }
    if ($_ -match '^([^=]+)=(.*)$') {
        $key = $matches[1].Trim()
        $value = $matches[2].Trim().Trim('"').Trim("'")
        Set-Item -Path "Env:$key" -Value $value
        $loadedVars += $key
    }
}

Write-Host "Loaded $($loadedVars.Count) environment variables from .env.prod" -ForegroundColor Green
Write-Host "SUPABASE_MODE = prod" -ForegroundColor Green

# Get the database URL using a helper script
$pythonExe = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$getUrlScript = 'from src.supabase_client import get_supabase_db_url; print(get_supabase_db_url())'
try {
    $dbUrl = & $pythonExe -c $getUrlScript 2>&1 | Select-Object -Last 1
    if (-not $dbUrl -or $LASTEXITCODE -ne 0) {
        if ($DryRun) {
            Write-Warn "Could not get database URL (dry run continues)"
            $dbUrl = "postgresql://[not-resolved]"
        }
        else {
            Invoke-AbortDeploy "Failed to get database URL from supabase_client"
        }
    }
}
catch {
    if ($DryRun) {
        Write-Warn "Could not get database URL (dry run continues): $_"
        $dbUrl = "postgresql://[not-resolved]"
    }
    else {
        Invoke-AbortDeploy "Failed to get database URL: $_"
    }
}

# Mask the password for display
$maskedUrl = $dbUrl -replace ':[^:@]+@', ':****@'
Write-Host "Database URL: $maskedUrl" -ForegroundColor Gray

# ----------------------------------------------------------------------------
# STEP 3: Apply Migrations
# ----------------------------------------------------------------------------
Write-Step 3 "APPLYING MIGRATIONS"

if ($DryRun) {
    Write-Host "[DRY RUN] Would run: supabase db push --include-all" -ForegroundColor Yellow
}
else {
    Write-Host "Running: supabase db push --include-all" -ForegroundColor White
    
    try {
        $pushResult = & supabase db push --include-all --db-url $dbUrl 2>&1
        $exitCode = $LASTEXITCODE
        
        # Show output
        $pushResult | ForEach-Object { Write-Host $_ }
        
        if ($exitCode -ne 0) {
            Invoke-AbortDeploy "supabase db push failed with exit code $exitCode"
        }
        
        Write-Host ""
        Write-Host "[OK] Migrations applied successfully" -ForegroundColor Green
    }
    catch {
        Invoke-AbortDeploy "Migration failed: $_"
    }
}

# ----------------------------------------------------------------------------
# STEP 4: Contract Truth Verification
# ----------------------------------------------------------------------------
Write-Step 4 "CONTRACT TRUTH VERIFICATION"

Write-Host "Querying current RPC signatures from production database..." -ForegroundColor White
Write-Host ""

if ($DryRun) {
    Write-Host "[DRY RUN] Would query contract truth" -ForegroundColor Yellow
}
else {
    try {
        # Use a separate Python script file to avoid here-string parsing issues
        $scriptPath = Join-Path $RepoRoot "scripts\query_contract.py"
        
        if (Test-Path $scriptPath) {
            & $pythonExe $scriptPath
            $exitCode = $LASTEXITCODE
            
            if ($exitCode -ne 0) {
                Write-Warn "Contract truth query had issues (exit code $exitCode)"
            }
        }
        else {
            Write-Warn "Contract query script not found: $scriptPath"
            Write-Host "Run manually: python scripts/query_contract.py" -ForegroundColor Gray
        }
    }
    catch {
        Write-Warn "Failed to query contract truth: $_"
    }
}

# ----------------------------------------------------------------------------
# STEP 5: Next Steps
# ----------------------------------------------------------------------------
Write-Host ""
Write-Host ("=" * 70) -ForegroundColor Green
Write-Host "  DATABASE ROLLOUT COMPLETE" -ForegroundColor Green
Write-Host ("=" * 70) -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  1. VERIFY the Contract Truth output above" -ForegroundColor White
Write-Host "     - Each RPC should have exactly 1 overload" -ForegroundColor Gray
Write-Host "     - All should be SECURITY DEFINER" -ForegroundColor Gray
Write-Host "  2. Deploy new worker code to Railway" -ForegroundColor White
Write-Host "  3. Scale workers back to 1" -ForegroundColor White
Write-Host "  4. Run smoke test: .\scripts\smoke_full_cycle.ps1 -Env prod" -ForegroundColor White
Write-Host ""

if (-not $DryRun) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Write-Host "Timestamp: $ts" -ForegroundColor Gray
}

exit 0
