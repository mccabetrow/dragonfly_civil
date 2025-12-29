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

# Get the MIGRATION-SPECIFIC database URL (Port 5432 Direct Connection)
# CRITICAL: Migrations MUST use the direct connection, NOT the transaction pooler.
$pythonExe = Join-Path $RepoRoot ".venv\Scripts\python.exe"

# Check for SUPABASE_MIGRATE_DB_URL in environment
$migrateUrl = $env:SUPABASE_MIGRATE_DB_URL
if (-not $migrateUrl) {
    Invoke-AbortDeploy "Missing SUPABASE_MIGRATE_DB_URL. This env var is required for migrations."
}

# Parse and validate the port - MUST be 5432 (Direct), NOT 6543 (Pooler)
try {
    $uri = [System.Uri]$migrateUrl.Replace("postgresql://", "http://")
    $port = $uri.Port
    
    if ($port -eq 6543) {
        Write-Host ""
        Write-Host "+----------------------------------------------------------------------+" -ForegroundColor Red
        Write-Host "|  [X] FATAL: Cannot run migrations via Transaction Pooler (6543)     |" -ForegroundColor Red
        Write-Host "|                                                                      |" -ForegroundColor Red
        Write-Host "|  Migrations require prepared statements and transaction control     |" -ForegroundColor Red
        Write-Host "|  that are incompatible with PgBouncer's transaction pooling.        |" -ForegroundColor Red
        Write-Host "|                                                                      |" -ForegroundColor Red
        Write-Host "|  ACTION: Use SUPABASE_MIGRATE_DB_URL with port 5432 (Direct).       |" -ForegroundColor Red
        Write-Host "+----------------------------------------------------------------------+" -ForegroundColor Red
        Invoke-AbortDeploy "SUPABASE_MIGRATE_DB_URL uses port 6543 (Pooler). Must use port 5432 (Direct)."
    }
    
    if ($port -ne 5432) {
        Invoke-AbortDeploy "SUPABASE_MIGRATE_DB_URL uses unexpected port $port. Expected port 5432 (Direct)."
    }
    
    Write-Host "[OK] Migration URL validated: Port 5432 (Direct Connection)" -ForegroundColor Green
}
catch {
    Invoke-AbortDeploy "Failed to parse SUPABASE_MIGRATE_DB_URL: $_"
}

$dbUrl = $migrateUrl

# Mask the password for display
$maskedUrl = $dbUrl -replace ':[^:@]+@', ':****@'
Write-Host "Migration DB URL: $maskedUrl" -ForegroundColor Gray

# ----------------------------------------------------------------------------
# STEP 3: Apply Migrations (using --db-url for explicit connection control)
# ----------------------------------------------------------------------------
Write-Step 3 "APPLYING MIGRATIONS"

if ($DryRun) {
    Write-Host "[DRY RUN] Would run: supabase db push --db-url <MIGRATE_URL>" -ForegroundColor Yellow
}
else {
    Write-Host "Running: supabase db push --db-url <MIGRATE_URL>" -ForegroundColor White
    Write-Host "(Using explicit SUPABASE_MIGRATE_DB_URL for direct connection)" -ForegroundColor Gray
    
    try {
        $pushResult = & supabase db push --db-url $dbUrl 2>&1
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
# STEP 3.5: Verify Database Connection Post-Push
# ----------------------------------------------------------------------------
Write-Host ""
Write-Host "Verifying database connectivity post-migration..." -ForegroundColor White

if ($DryRun) {
    Write-Host "[DRY RUN] Would run: python -m tools.test_db_connection" -ForegroundColor Yellow
}
else {
    try {
        & $pythonExe -m tools.test_db_connection
        $exitCode = $LASTEXITCODE
        
        if ($exitCode -ne 0) {
            Write-Warn "Database connection verification failed (exit code $exitCode)"
            Write-Host "Migrations were applied, but post-verification failed." -ForegroundColor Yellow
        }
        else {
            Write-Host "[OK] Database connectivity verified" -ForegroundColor Green
        }
    }
    catch {
        Write-Warn "Failed to verify database connection: $_"
    }
}

# ----------------------------------------------------------------------------
# STEP 3.6: Refresh PostgREST Schema Cache
# ----------------------------------------------------------------------------
Write-Host ""
Write-Host "Refreshing PostgREST schema cache..." -ForegroundColor White

if ($DryRun) {
    Write-Host "[DRY RUN] Would run: python -m tools.pgrst_reload" -ForegroundColor Yellow
}
else {
    try {
        & $pythonExe -m tools.pgrst_reload
        $exitCode = $LASTEXITCODE
        
        if ($exitCode -ne 0) {
            Write-Warn "PostgREST schema cache reload failed (exit code $exitCode)"
            Write-Host "Migrations were applied, but REST API may need manual refresh." -ForegroundColor Yellow
        }
        else {
            Write-Host "[OK] PostgREST schema cache refreshed" -ForegroundColor Green
        }
    }
    catch {
        Write-Warn "Failed to refresh schema cache: $_"
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
