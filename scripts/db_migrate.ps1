<#
.SYNOPSIS
    Canonical migration script for Dragonfly Civil's remote Supabase database.

.DESCRIPTION
    Applies pending migrations to the remote Supabase database using an explicit
    --db-url connection string. Never uses link-based connectivity or db push.
    Handles "already exists" errors by automatically marking those migrations
    as applied (self-healing).

    IMPORTANT: This script always uses explicit --db-url to avoid pooler DNS
    issues on Windows. Never use link-based Supabase commands.

.PARAMETER SupabaseEnv
    Target environment: 'dev' or 'prod'. Defaults to 'dev'.
    Alias: -Env

.PARAMETER DryRun
    If specified, lists pending migrations without applying them.

.EXAMPLE
    .\scripts\db_migrate.ps1 -SupabaseEnv dev -DryRun
    .\scripts\db_migrate.ps1 -SupabaseEnv dev
    .\scripts\db_migrate.ps1 -SupabaseEnv prod
#>

param(
    [Alias('Env')]
    [ValidateSet('dev', 'prod')]
    [string]$SupabaseEnv = 'dev',

    [switch]$DryRun
)

# ----------------------------------------------------------------------------
# CONFIGURATION
# ----------------------------------------------------------------------------

$ErrorActionPreference = 'Continue'  # We handle errors manually
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir

# Find Supabase CLI
$SupabaseCli = "$env:LOCALAPPDATA\Programs\supabase\supabase.exe"
if (-not (Test-Path $SupabaseCli)) {
    $found = Get-Command supabase -ErrorAction SilentlyContinue
    if ($found) {
        $SupabaseCli = $found.Source
    }
}

# ----------------------------------------------------------------------------
# LOGGING HELPERS (PowerShell 5.1 compatible)
# ----------------------------------------------------------------------------

function Write-Info {
    param([string]$Message)
    Write-Host "[INFO] $Message"
}

function Write-Success {
    param([string]$Message)
    Write-Host "[OK] $Message" -ForegroundColor Green
}

function Write-Warn {
    param([string]$Message)
    Write-Host "[WARN] $Message" -ForegroundColor Yellow
}

function Write-ErrorAndExit {
    param([string]$Message, [int]$ExitCode = 1)
    Write-Host "[ERROR] $Message" -ForegroundColor Red
    exit $ExitCode
}

# ----------------------------------------------------------------------------
# HELPER FUNCTIONS
# ----------------------------------------------------------------------------

function Get-PendingMigrations {
    <#
    .SYNOPSIS
        Parses `supabase migration list` output and returns IDs of pending migrations.
    .DESCRIPTION
        The CLI outputs a table like:
           Local          | Remote         | Time (UTC)
          ----------------|----------------|---------------------
           20251203150000 |                | 2025-12-03 15:00:00
           20251203120000 | 20251203120000 | 2025-12-03 12:00:00

        A migration is pending if the Remote column is empty.
    #>
    param([string]$ListOutput)

    $pending = @()

    # Split into lines and look for the pattern: ID | (empty) | timestamp
    $lines = $ListOutput -split "`r?`n"
    foreach ($line in $lines) {
        # Match: whitespace, digits, whitespace, pipe, whitespace only, pipe
        # Example: "   20251203150000 |                | 2025-12-03"
        if ($line -match '^\s*(\d{10,})\s*\|\s*\|\s*') {
            $pending += $Matches[1]
        }
    }

    return $pending
}

function Test-AlreadyExistsError {
    <#
    .SYNOPSIS
        Returns $true if the error output indicates an "already exists" condition.
    #>
    param([string]$Output)

    $patterns = @(
        'already exists',
        'SQLSTATE 42P07',   # relation already exists
        'SQLSTATE 42710',   # policy/object already exists
        'SQLSTATE 42723',   # function already exists
        'SQLSTATE 42P04'    # database already exists
    )

    foreach ($p in $patterns) {
        if ($Output -match $p) {
            return $true
        }
    }
    return $false
}

function Get-FailedMigrationId {
    <#
    .SYNOPSIS
        Extracts the migration ID from an error message like "Applying migration 20251203150000_foo.sql..."
    #>
    param([string]$Output)

    if ($Output -match 'Applying migration (\d{10,})') {
        return $Matches[1]
    }
    return $null
}

function Invoke-MigrationRepair {
    <#
    .SYNOPSIS
        Marks a migration as applied in the remote migration history.
    #>
    param(
        [string]$MigrationId,
        [string]$DbUrl
    )

    Write-Warn "Repairing migration $MigrationId (marking as applied)..."
    $output = & $SupabaseCli migration repair $MigrationId --status applied --db-url $DbUrl 2>&1 | Out-String

    if ($LASTEXITCODE -eq 0) {
        Write-Success "Migration $MigrationId marked as applied"
        return $true
    }
    else {
        Write-Host $output
        return $false
    }
}

# ----------------------------------------------------------------------------
# MAIN SCRIPT
# ----------------------------------------------------------------------------

Write-Host ""
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host " Dragonfly Civil - Database Migrations"       -ForegroundColor Cyan
Write-Host " Environment: $($SupabaseEnv.ToUpper())"      -ForegroundColor Cyan
if ($DryRun) {
    Write-Host " Mode: DRY RUN (no changes)"              -ForegroundColor Yellow
}
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host ""

# Step 1: Validate Supabase CLI exists
if (-not (Test-Path $SupabaseCli)) {
    Write-ErrorAndExit "Supabase CLI not found. Install from https://supabase.com/docs/guides/cli"
}
Write-Info "Using Supabase CLI: $SupabaseCli"

# Step 2: Load environment variables from .env
$envFile = Join-Path $RepoRoot '.env'
if (Test-Path $envFile) {
    . (Join-Path $ScriptDir 'load_env.ps1') -EnvPath $envFile
}
else {
    Write-Warn ".env file not found at $envFile"
}

# Step 3: Get the appropriate DB URL based on -SupabaseEnv
# CRITICAL: Always use explicit --db-url, never link-based commands (avoids pooler DNS issues)
$dbUrlVarName = if ($SupabaseEnv -eq 'prod') { 'SUPABASE_DB_URL_PROD' } else { 'SUPABASE_DB_URL_DEV' }
# Use $env: (process-level) since load_env.ps1 sets there, not [Environment]::GetEnvironmentVariable (system-level)
$DbUrl = (Get-Item "env:$dbUrlVarName" -ErrorAction SilentlyContinue).Value

if ([string]::IsNullOrWhiteSpace($DbUrl)) {
    Write-Host ""
    Write-ErrorAndExit @"
$dbUrlVarName is not set.

To fix this:
1. Go to Supabase Dashboard -> Settings -> Database -> Connection string
2. Copy the full URI (starts with postgresql://...)
3. Paste it into .env as:
   $dbUrlVarName=postgresql://postgres:YOUR_PASSWORD@db.YOUR_PROJECT.supabase.co:5432/postgres
4. Re-run this script.
"@
}

# Mask password in display
$displayUrl = $DbUrl -replace ':[^:@]+@', ':****@'
Write-Success "Using DB URL: $displayUrl"
Write-Info "Variable: $dbUrlVarName"

# Step 3b: Safety check for prod - require confirmation unless running in CI
if ($SupabaseEnv -eq 'prod' -and -not $env:CI -and -not $env:GITHUB_ACTIONS) {
    Write-Host ""
    Write-Host "⚠️  WARNING: You are about to apply migrations to PRODUCTION" -ForegroundColor Red
    Write-Host ""
    Write-Host "Production migrations should normally be applied via CI/CD:" -ForegroundColor Yellow
    Write-Host "  1. Push migration to main (applies to dev automatically)" -ForegroundColor Yellow
    Write-Host "  2. Go to Actions → Supabase Migrations → Run workflow" -ForegroundColor Yellow
    Write-Host "  3. Select 'prod' environment" -ForegroundColor Yellow
    Write-Host ""

    $confirmation = Read-Host "Type 'PROD' to continue, or press Enter to abort"
    if ($confirmation -ne 'PROD') {
        Write-Host "Aborted." -ForegroundColor Yellow
        exit 0
    }
}

# Step 4: List migrations and identify pending ones
Write-Host ""
Write-Info "Checking migration status..."

$listOutput = & $SupabaseCli migration list --db-url $DbUrl 2>&1 | Out-String

if ($LASTEXITCODE -ne 0) {
    Write-Host $listOutput
    Write-ErrorAndExit "Failed to list migrations. Check your database connection string."
}

$pendingIds = Get-PendingMigrations -ListOutput $listOutput

if ($pendingIds.Count -eq 0) {
    Write-Success "No pending migrations. Database is up to date."
    exit 0
}

Write-Info "Found $($pendingIds.Count) pending migration(s):"
foreach ($id in $pendingIds) {
    Write-Host "  - $id"
}

# Step 5: If dry run, stop here
if ($DryRun) {
    Write-Host ""
    Write-Host "Pending migrations: $($pendingIds -join ', ')" -ForegroundColor Yellow
    Write-Host ""
    Write-Info "Dry run complete. No migrations were applied."
    exit 0
}

# Step 6: Apply migrations with retry/repair logic
# CRITICAL: Use 'migration up', not 'db push' - db push can hang on pooler DNS issues
Write-Host ""
Write-Info "Applying migrations with 'supabase migration up --db-url'..."

$maxRetries = 5
$attempt = 0
$repairCount = 0

while ($attempt -lt $maxRetries) {
    $attempt++

    $upOutput = & $SupabaseCli migration up --db-url $DbUrl 2>&1 | Out-String

    if ($LASTEXITCODE -eq 0) {
        Write-Success "All migrations applied successfully."
        break
    }

    # Check if this is an "already exists" error we can repair
    if (Test-AlreadyExistsError -Output $upOutput) {
        $failedId = Get-FailedMigrationId -Output $upOutput

        if ($failedId) {
            Write-Warn "Migration $failedId contains objects that already exist."

            $repaired = Invoke-MigrationRepair -MigrationId $failedId -DbUrl $DbUrl
            if ($repaired) {
                $repairCount++
                Write-Info "Retrying migrations (attempt $attempt of $maxRetries)..."
                continue
            }
            else {
                Write-Host $upOutput
                Write-ErrorAndExit "Failed to repair migration $failedId."
            }
        }
        else {
            # "already exists" but couldn't determine which migration
            Write-Host $upOutput
            Write-ErrorAndExit "Migration failed with 'already exists' error but could not identify the migration ID."
        }
    }
    else {
        # Some other error
        Write-Host $upOutput
        Write-ErrorAndExit "Migration failed with an unexpected error."
    }
}

if ($attempt -ge $maxRetries -and $LASTEXITCODE -ne 0) {
    Write-ErrorAndExit "Exceeded maximum retry attempts ($maxRetries)."
}

# Step 7: Summary
Write-Host ""
Write-Host "=============================================" -ForegroundColor Green
Write-Host " Migration Complete"                          -ForegroundColor Green
Write-Host "=============================================" -ForegroundColor Green
Write-Host "  Environment:   $($SupabaseEnv.ToUpper())"
Write-Host "  Applied:       $($pendingIds.Count) migration(s)"
Write-Host "  Auto-repaired: $repairCount"
Write-Host ""

# Step 8: Show final status
Write-Info "Final migration status:"
& $SupabaseCli migration list --db-url $DbUrl 2>&1 | Select-Object -Last 15

exit 0
