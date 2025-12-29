<#
.SYNOPSIS
    Generates a new database password and connection strings for dragonfly_app.

.DESCRIPTION
    This script generates a strong 32-character password and outputs:
    1. The ALTER ROLE SQL command to run in Supabase
    2. The PostgreSQL connection string for Railway
    3. The PROD_DB_CONFIG JSON format (if needed)

.EXAMPLE
    .\scripts\generate_db_strings.ps1
    
    Output:
    ========================================
    DATABASE CREDENTIAL GENERATOR
    ========================================
    
    [SQL] Run this in Supabase SQL Editor:
    ALTER ROLE dragonfly_app WITH PASSWORD '<NEW_PASSWORD>';
    
    [ENV] Paste this into Railway:
    SUPABASE_DB_URL=postgresql://dragonfly_app:<PASSWORD>@db.<PROJECT_REF>.supabase.co:5432/postgres?sslmode=require

.NOTES
    Author: Dragonfly Civil Engineering Team
    Purpose: Fix "Password Authentication Failed" errors
#>

param(
    [string]$ProjectRef = "iaketsyhmqbwaabgykux",
    [string]$RoleName = "dragonfly_app",
    [int]$PasswordLength = 32
)

$ErrorActionPreference = "Stop"

# ═══════════════════════════════════════════════════════════════════════════
# Generate a strong random password (alphanumeric only to avoid URL encoding issues)
# ═══════════════════════════════════════════════════════════════════════════
function New-StrongPassword {
    param([int]$Length = 32)
    
    $chars = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
    $password = -join ((1..$Length) | ForEach-Object { $chars[(Get-Random -Maximum $chars.Length)] })
    return $password
}

# Generate the password
$NewPassword = New-StrongPassword -Length $PasswordLength

# Build connection strings
$DirectHost = "db.$ProjectRef.supabase.co"
$PoolerHost = "aws-0-us-east-1.pooler.supabase.com"
$Database = "postgres"

# Direct connection (port 5432) - for migrations
$DirectUrl = "postgresql://${RoleName}:${NewPassword}@${DirectHost}:5432/${Database}?sslmode=require"

# Pooler connection (port 6543) - for runtime (recommended)
$PoolerUrl = "postgresql://${RoleName}.${ProjectRef}:${NewPassword}@${PoolerHost}:6543/${Database}?sslmode=require"

# ═══════════════════════════════════════════════════════════════════════════
# Output
# ═══════════════════════════════════════════════════════════════════════════

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host " DATABASE CREDENTIAL GENERATOR" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Generated Password: " -NoNewline -ForegroundColor Yellow
Write-Host $NewPassword -ForegroundColor White
Write-Host ""

Write-Host "----------------------------------------" -ForegroundColor DarkGray
Write-Host "[STEP 1] Run this SQL in Supabase Dashboard -> SQL Editor:" -ForegroundColor Green
Write-Host ""
Write-Host "ALTER ROLE $RoleName WITH PASSWORD '$NewPassword';" -ForegroundColor White
Write-Host ""

Write-Host "----------------------------------------" -ForegroundColor DarkGray
Write-Host "[STEP 2] Update Railway Environment Variables:" -ForegroundColor Green
Write-Host ""
Write-Host "[OPTION A] Direct Connection (for migrations):" -ForegroundColor Yellow
Write-Host "SUPABASE_DB_URL=$DirectUrl" -ForegroundColor White
Write-Host ""
Write-Host "[OPTION B] Pooler Connection (for runtime - RECOMMENDED):" -ForegroundColor Yellow
Write-Host "SUPABASE_DB_URL=$PoolerUrl" -ForegroundColor White
Write-Host ""

Write-Host "----------------------------------------" -ForegroundColor DarkGray
Write-Host "[STEP 3] Also update SUPABASE_MIGRATE_DB_URL (always use direct):" -ForegroundColor Green
Write-Host ""
Write-Host "SUPABASE_MIGRATE_DB_URL=$DirectUrl" -ForegroundColor White
Write-Host ""

Write-Host "----------------------------------------" -ForegroundColor DarkGray
Write-Host "[OPTIONAL] PROD_DB_CONFIG JSON format:" -ForegroundColor Cyan
Write-Host ""

$JsonConfig = @{
    user     = $RoleName
    password = $NewPassword
    host     = $DirectHost
    port     = 5432
    database = $Database
    ssl      = @{ rejectUnauthorized = $false }
} | ConvertTo-Json -Compress

Write-Host "PROD_DB_CONFIG=$JsonConfig" -ForegroundColor DarkGray
Write-Host ""

Write-Host "========================================" -ForegroundColor Cyan
Write-Host " VERIFICATION" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "After updating, test with:" -ForegroundColor Yellow
Write-Host "  python -m tools.verify_db_auth `"$DirectUrl`"" -ForegroundColor White
Write-Host ""
Write-Host "Or using psql:" -ForegroundColor Yellow
Write-Host "  psql `"$DirectUrl`"" -ForegroundColor White
Write-Host ""

# Save to a temporary file for easy copy-paste
$OutputFile = "db_credentials_temp.txt"
@"
# Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
# Role: $RoleName
# Project: $ProjectRef

# SQL (run in Supabase SQL Editor)
ALTER ROLE $RoleName WITH PASSWORD '$NewPassword';

# Railway Environment Variables
SUPABASE_DB_URL=$PoolerUrl
SUPABASE_MIGRATE_DB_URL=$DirectUrl

# Direct URL (for local testing)
$DirectUrl
"@ | Out-File -FilePath $OutputFile -Encoding utf8

Write-Host "[INFO] Credentials saved to: $OutputFile" -ForegroundColor DarkGray
Write-Host "[WARNING] Delete this file after use!" -ForegroundColor Red
Write-Host ""
