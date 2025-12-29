<#
.SYNOPSIS
    Generates SANITIZED Vercel environment variables for the Dragonfly Dashboard.

.DESCRIPTION
    Reads ALL values dynamically from .env.prod using regex extraction.
    No hardcoded secrets - 100% Gitleaks compliant.

.EXAMPLE
    .\scripts\generate_vercel_config.ps1

.NOTES
    Author: Dragonfly Civil Engineering Team
    Requires: .env.prod file in repository root
#>

$ErrorActionPreference = "Stop"

# ═══════════════════════════════════════════════════════════════════════════
# LOCATE .env.prod
# ═══════════════════════════════════════════════════════════════════════════

$EnvProdPath = Join-Path $PSScriptRoot "..\.env.prod"

if (-not (Test-Path $EnvProdPath)) {
    Write-Host ""
    Write-Host "ERROR: .env.prod not found at: $EnvProdPath" -ForegroundColor Red
    Write-Host "This script reads all values from .env.prod (git-ignored)." -ForegroundColor Yellow
    Write-Host ""
    exit 1
}

# ═══════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════

function Get-EnvValue {
    param(
        [string]$Content,
        [string]$Key
    )

    # Match KEY=VALUE, handling quotes and whitespace
    if ($Content -match "(?m)^${Key}=(.+)$") {
        $value = $matches[1].Trim()
        # Remove surrounding quotes if present
        $value = $value -replace '^["'']|["'']$', ''
        return $value
    }
    return $null
}

function Sanitize-EnvValue {
    param([string]$Value)

    if (-not $Value) { return "MISSING" }

    # Remove ALL whitespace including newlines, carriage returns, tabs
    $clean = $Value.Trim()
    $clean = $clean -replace '[\r\n\t]', ''

    # Remove trailing slashes from URLs
    $clean = $clean -replace '/+$', ''

    # Remove trailing /api from base URLs (frontend appends paths)
    $clean = $clean -replace '/api$', ''

    return $clean
}

# ═══════════════════════════════════════════════════════════════════════════
# READ AND EXTRACT VALUES
# ═══════════════════════════════════════════════════════════════════════════

$Content = Get-Content $EnvProdPath -Raw

# Extract required keys
$SUPABASE_URL = Get-EnvValue -Content $Content -Key "SUPABASE_URL"
$SUPABASE_ANON_KEY = Get-EnvValue -Content $Content -Key "SUPABASE_ANON_KEY"
$DRAGONFLY_API_KEY = Get-EnvValue -Content $Content -Key "DRAGONFLY_API_KEY"

# Railway URL - try multiple possible key names
$RAILWAY_URL = Get-EnvValue -Content $Content -Key "RAILWAY_URL"
if (-not $RAILWAY_URL) {
    $RAILWAY_URL = Get-EnvValue -Content $Content -Key "PROD_API_URL"
}
if (-not $RAILWAY_URL) {
    $RAILWAY_URL = Get-EnvValue -Content $Content -Key "NEXT_PUBLIC_API_URL"
}
if (-not $RAILWAY_URL) {
    $RAILWAY_URL = Get-EnvValue -Content $Content -Key "VITE_API_BASE_URL"
}
if (-not $RAILWAY_URL) {
    # Default Railway URL for Dragonfly prod
    $RAILWAY_URL = "https://dragonflycivil-production-d57a.up.railway.app"
}

# Sanitize all values
$VITE_API_BASE_URL = Sanitize-EnvValue $RAILWAY_URL
$VITE_SUPABASE_URL = Sanitize-EnvValue $SUPABASE_URL
$VITE_SUPABASE_ANON_KEY = Sanitize-EnvValue $SUPABASE_ANON_KEY
$VITE_DRAGONFLY_API_KEY = Sanitize-EnvValue $DRAGONFLY_API_KEY

# ═══════════════════════════════════════════════════════════════════════════
# OUTPUT
# ═══════════════════════════════════════════════════════════════════════════

Write-Host ""
Write-Host "═══════════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host " VERCEL ENVIRONMENT VARIABLES (SANITIZED)" -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""
Write-Host "Source: $EnvProdPath" -ForegroundColor DarkGray
Write-Host ""

# Check for missing values
$missing = @()
if ($VITE_SUPABASE_URL -eq "MISSING") { $missing += "SUPABASE_URL" }
if ($VITE_SUPABASE_ANON_KEY -eq "MISSING") { $missing += "SUPABASE_ANON_KEY" }
if ($VITE_DRAGONFLY_API_KEY -eq "MISSING") { $missing += "DRAGONFLY_API_KEY" }

if ($missing.Count -gt 0) {
    Write-Host "WARNING: Missing keys in .env.prod:" -ForegroundColor Yellow
    foreach ($key in $missing) {
        Write-Host "  - $key" -ForegroundColor Yellow
    }
    Write-Host ""
}

Write-Host "[COPY THIS BLOCK INTO VERCEL]" -ForegroundColor Green
Write-Host "────────────────────────────────────────────────────────────────────" -ForegroundColor DarkGray
Write-Host ""
Write-Host "VITE_API_BASE_URL=$VITE_API_BASE_URL"
Write-Host "VITE_SUPABASE_URL=$VITE_SUPABASE_URL"
Write-Host "VITE_SUPABASE_ANON_KEY=$VITE_SUPABASE_ANON_KEY"
Write-Host "VITE_DRAGONFLY_API_KEY=$VITE_DRAGONFLY_API_KEY"
Write-Host "VITE_DEMO_MODE=false"
Write-Host ""
Write-Host "────────────────────────────────────────────────────────────────────" -ForegroundColor DarkGray
Write-Host ""

# Validation hints
Write-Host "[VALIDATION]" -ForegroundColor Cyan
Write-Host "  API URL length:  $($VITE_API_BASE_URL.Length) chars" -ForegroundColor DarkGray
Write-Host "  Supabase URL:    $($VITE_SUPABASE_URL.Length) chars" -ForegroundColor DarkGray
Write-Host "  Anon Key:        $($VITE_SUPABASE_ANON_KEY.Length) chars (expect ~200+)" -ForegroundColor DarkGray
Write-Host "  API Key:         $($VITE_DRAGONFLY_API_KEY.Length) chars" -ForegroundColor DarkGray
Write-Host ""

if ($VITE_SUPABASE_ANON_KEY.Length -lt 100 -and $VITE_SUPABASE_ANON_KEY -ne "MISSING") {
    Write-Host "WARNING: Anon key seems too short. Verify it's the full JWT." -ForegroundColor Yellow
}

Write-Host "Done. Copy the block above into Vercel Project Settings > Environment Variables." -ForegroundColor Green
Write-Host ""
