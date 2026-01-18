<#
.SYNOPSIS
    Baseline Production Migrations - Mark all local migrations as applied.

.DESCRIPTION
    This script resolves "Migration Drift" by inserting records into the
    supabase_migrations.schema_migrations table for every migration file
    in the local supabase/migrations/ folder.

    After running this, `supabase migration list` should show 0 Pending.

.PARAMETER DryRun
    If specified, shows what would be inserted without making changes.

.PARAMETER Force
    Skip confirmation prompt (use with caution in prod).

.NOTES
    Author: Principal Database Reliability Engineer
    Date: 2026-01-18
    Project: Dragonfly Civil
#>

param(
    [switch]$DryRun,
    [switch]$Force
)

$ErrorActionPreference = "Stop"

# =============================================================================
# Configuration
# =============================================================================

$SCRIPT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
$PROJECT_ROOT = Split-Path -Parent $SCRIPT_DIR
$MIGRATIONS_DIR = Join-Path $PROJECT_ROOT "supabase\migrations"

# Production project ref (for validation)
$PROD_PROJECT_REF = "iaketsyhmqbwaabgykux"

# =============================================================================
# Banner
# =============================================================================

Write-Host ""
Write-Host "=" * 78 -ForegroundColor Cyan
Write-Host "  DRAGONFLY MIGRATION BASELINER" -ForegroundColor Cyan
Write-Host "  Mark all local migrations as applied in production" -ForegroundColor Gray
Write-Host "=" * 78 -ForegroundColor Cyan
Write-Host ""

# =============================================================================
# Load Environment
# =============================================================================

$envFile = Join-Path $PROJECT_ROOT ".env.prod"
if (Test-Path $envFile) {
    Write-Host "[ENV] Loading .env.prod..." -ForegroundColor Gray
    Get-Content $envFile | ForEach-Object {
        if ($_ -match "^\s*([^#][^=]+)=(.*)$") {
            $key = $matches[1].Trim()
            $val = $matches[2].Trim().Trim('"').Trim("'")
            [System.Environment]::SetEnvironmentVariable($key, $val, "Process")
        }
    }
}

# =============================================================================
# Get/Validate DSN
# =============================================================================

# Prompt for DSN if not set
$DSN = $env:DATABASE_URL
if (-not $DSN) {
    Write-Host "[INPUT] DATABASE_URL not set. Enter production DSN:" -ForegroundColor Yellow
    Write-Host "        Format: postgres[ql]://user.PROJECT_REF:PASSWORD@pooler.supabase.com:6543/postgres" -ForegroundColor Gray
    $DSN = Read-Host "DSN"
}

# Validate DSN contains prod project ref
if ($DSN -notmatch $PROD_PROJECT_REF) {
    Write-Host ""
    Write-Host "[FATAL] DSN does not contain production project ref: $PROD_PROJECT_REF" -ForegroundColor Red
    Write-Host "        This script is for PRODUCTION baselining only." -ForegroundColor Red
    Write-Host ""
    exit 1
}

# Redact DSN for display
$DSN_REDACTED = $DSN -replace "(://[^:]+:)([^@]+)(@)", '$1****$3'
Write-Host "[DSN] Target: $DSN_REDACTED" -ForegroundColor Green

# =============================================================================
# Discover Migration Files
# =============================================================================

Write-Host ""
Write-Host "[SCAN] Reading migrations from: $MIGRATIONS_DIR" -ForegroundColor Gray

if (-not (Test-Path $MIGRATIONS_DIR)) {
    Write-Host "[FATAL] Migrations directory not found: $MIGRATIONS_DIR" -ForegroundColor Red
    exit 1
}

$migrationFiles = Get-ChildItem -Path $MIGRATIONS_DIR -Filter "*.sql" | 
Sort-Object Name |
ForEach-Object { $_.Name }

$migrationCount = $migrationFiles.Count
Write-Host "[FOUND] $migrationCount migration files" -ForegroundColor Cyan

if ($migrationCount -eq 0) {
    Write-Host "[WARN] No migration files found. Nothing to baseline." -ForegroundColor Yellow
    exit 0
}

# Show first and last for sanity check
$firstMigration = $migrationFiles[0]
$lastMigration = $migrationFiles[-1]
Write-Host "        First: $firstMigration" -ForegroundColor Gray
Write-Host "        Last:  $lastMigration" -ForegroundColor Gray

# =============================================================================
# Confirmation Gate
# =============================================================================

if (-not $Force -and -not $DryRun) {
    Write-Host ""
    Write-Host "=" * 78 -ForegroundColor Yellow
    Write-Host "  ⚠️  WARNING: PRODUCTION DATABASE MODIFICATION" -ForegroundColor Yellow
    Write-Host "=" * 78 -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  This will INSERT $migrationCount records into:" -ForegroundColor White
    Write-Host "    supabase_migrations.schema_migrations" -ForegroundColor White
    Write-Host ""
    Write-Host "  This marks all local migrations as 'applied' in production." -ForegroundColor White
    Write-Host "  Only proceed if the production schema is already correct." -ForegroundColor White
    Write-Host ""
    
    $confirm = Read-Host "Type 'BASELINE' to proceed"
    if ($confirm -ne "BASELINE") {
        Write-Host "[ABORT] Confirmation not received. Exiting." -ForegroundColor Yellow
        exit 0
    }
}

# =============================================================================
# Build and Execute SQL
# =============================================================================

# The table is supabase_migrations.schema_migrations with columns:
#   version (text) - the migration version/timestamp
#   name (text) - optional descriptive name  
#   statements_applied_at (timestamp) - when it was applied

# Extract version from filename (e.g., "20251201182738" from "20251201182738_fix_dashboard_view_grants.sql")
function Get-MigrationVersion {
    param([string]$Filename)
    if ($Filename -match "^(\d+)") {
        return $matches[1]
    }
    # Fallback for non-numeric prefixed files
    return $Filename -replace "\.sql$", ""
}

# Build INSERT statements
$insertStatements = @()
foreach ($file in $migrationFiles) {
    $version = Get-MigrationVersion -Filename $file
    $name = $file -replace "\.sql$", ""
    
    # Use ON CONFLICT to be idempotent
    $sql = @"
INSERT INTO supabase_migrations.schema_migrations (version, name, statements_applied_at)
VALUES ('$version', '$name', NOW())
ON CONFLICT (version) DO NOTHING;
"@
    $insertStatements += $sql
}

$fullSQL = $insertStatements -join "`n"

# =============================================================================
# Dry Run Mode
# =============================================================================

if ($DryRun) {
    Write-Host ""
    Write-Host "[DRY-RUN] Would execute the following SQL:" -ForegroundColor Magenta
    Write-Host "-" * 78 -ForegroundColor Gray
    
    # Show first 10 and last 5
    $previewLines = $insertStatements[0..9]
    foreach ($line in $previewLines) {
        Write-Host $line -ForegroundColor Gray
    }
    
    if ($migrationCount -gt 15) {
        Write-Host "..." -ForegroundColor DarkGray
        Write-Host "  ($($migrationCount - 15) more statements)" -ForegroundColor DarkGray
        Write-Host "..." -ForegroundColor DarkGray
    }
    
    $tailLines = $insertStatements[-5..-1]
    foreach ($line in $tailLines) {
        Write-Host $line -ForegroundColor Gray
    }
    
    Write-Host "-" * 78 -ForegroundColor Gray
    Write-Host ""
    Write-Host "[DRY-RUN] No changes made. Remove -DryRun to execute." -ForegroundColor Magenta
    exit 0
}

# =============================================================================
# Execute SQL via psql
# =============================================================================

Write-Host ""
Write-Host "[EXEC] Inserting migration records..." -ForegroundColor Cyan

# Write SQL to temp file
$tempFile = [System.IO.Path]::GetTempFileName()
$fullSQL | Out-File -FilePath $tempFile -Encoding UTF8

try {
    # Execute via psql
    $env:PGPASSWORD = ($DSN -replace ".*:([^@]+)@.*", '$1')
    
    # Parse DSN components (postgres or postgresql scheme)
    if ($DSN -match "^postgres(ql)?://([^:]+):([^@]+)@([^:]+):(\d+)/([^?]+)") {
        $pgUser = $matches[2]
        $pgHost = $matches[4]
        $pgPort = $matches[5]
        $pgDB = $matches[6]
    }
    else {
        Write-Host "[FATAL] Could not parse DSN components" -ForegroundColor Red
        exit 1
    }
    
    $psqlArgs = @(
        "-h", $pgHost,
        "-p", $pgPort,
        "-U", $pgUser,
        "-d", $pgDB,
        "-f", $tempFile,
        "-v", "ON_ERROR_STOP=1"
    )
    
    $result = & psql @psqlArgs 2>&1
    $exitCode = $LASTEXITCODE
    
    if ($exitCode -ne 0) {
        Write-Host "[ERROR] psql failed with exit code $exitCode" -ForegroundColor Red
        Write-Host $result -ForegroundColor Red
        exit 1
    }
    
    Write-Host "[OK] Successfully inserted $migrationCount migration records" -ForegroundColor Green
    
}
finally {
    # Cleanup
    Remove-Item -Path $tempFile -Force -ErrorAction SilentlyContinue
    $env:PGPASSWORD = $null
}

# =============================================================================
# Verification
# =============================================================================

Write-Host ""
Write-Host "[VERIFY] Checking migration count in database..." -ForegroundColor Gray

$verifySQL = "SELECT COUNT(*) as total FROM supabase_migrations.schema_migrations;"
$countResult = & psql -h $pgHost -p $pgPort -U $pgUser -d $pgDB -t -c $verifySQL 2>&1
$dbCount = [int]($countResult.Trim())

Write-Host ""
Write-Host "=" * 78 -ForegroundColor Green
Write-Host "  ✅ BASELINE COMPLETE" -ForegroundColor Green
Write-Host "=" * 78 -ForegroundColor Green
Write-Host ""
Write-Host "  Local migrations:    $migrationCount" -ForegroundColor White
Write-Host "  Database records:    $dbCount" -ForegroundColor White
Write-Host ""
Write-Host "  Next step: Run 'supabase migration list' to verify 0 pending" -ForegroundColor Gray
Write-Host ""

exit 0
