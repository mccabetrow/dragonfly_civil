<#
.SYNOPSIS
    Generates SANITIZED Vercel environment variables for the Dragonfly Dashboard.

.DESCRIPTION
    This script outputs clean, copy-pasteable environment variables for Vercel.
    All values are sanitized with .Trim() to remove hidden whitespace/newlines
    that can cause "Backend Disconnected" or auth failures.

.EXAMPLE
    .\scripts\generate_vercel_config.ps1
    
    Then copy the output block directly into Vercel Project Settings.

.NOTES
    Author: Dragonfly Civil Engineering Team
    Purpose: Eliminate invisible whitespace issues in Vercel env vars
#>

$ErrorActionPreference = "Stop"

# ═══════════════════════════════════════════════════════════════════════════
# CONFIGURATION - Edit these values as needed
# ═══════════════════════════════════════════════════════════════════════════

# Railway Backend URL (root domain only - frontend appends /api/...)
$RAILWAY_URL = "https://dragonflycivil-production-d57a.up.railway.app"

# Supabase Project URL
$SUPABASE_URL = "https://iaketsyhmqbwaabgykux.supabase.co"

# Supabase Anon Key (public, safe for frontend - NOT service role!)
# Get from: Supabase Dashboard -> Settings -> API -> anon/public key
# NOTE: Read from .env.prod if available, otherwise use placeholder
$EnvProdPath = Join-Path $PSScriptRoot "..\\.env.prod"
if (Test-Path $EnvProdPath) {
    # Try to read anon key from env file (not committed)
    $content = Get-Content $EnvProdPath -Raw
    if ($content -match 'SUPABASE_ANON_KEY=(.+)') {
        $SUPABASE_ANON_KEY = $matches[1].Trim()
    }
    else {
        $SUPABASE_ANON_KEY = "<GET FROM SUPABASE DASHBOARD - Settings -> API -> anon/public key>"
    }
}
else {
    $SUPABASE_ANON_KEY = "<GET FROM SUPABASE DASHBOARD - Settings -> API -> anon/public key>"
}

# Dragonfly API Key (for X-DRAGONFLY-API-KEY header)
# NOTE: Read from .env.prod if available
if (Test-Path $EnvProdPath) {
    $content = Get-Content $EnvProdPath -Raw
    if ($content -match 'DRAGONFLY_API_KEY=(.+)') {
        $DRAGONFLY_API_KEY = $matches[1].Trim()
    }
    else {
        $DRAGONFLY_API_KEY = "<GET FROM .env.prod>"
    }
}
else {
    $DRAGONFLY_API_KEY = "<GET FROM .env.prod>"
}

# ═══════════════════════════════════════════════════════════════════════════
# SANITIZATION - Remove ALL hidden whitespace/newlines
# ═══════════════════════════════════════════════════════════════════════════

function Sanitize-EnvValue {
    param([string]$Value)
    
    if (-not $Value) { return "" }
    
    # Remove ALL whitespace including newlines, carriage returns, tabs
    $clean = $Value.Trim()
    $clean = $clean -replace '[\r\n\t]', ''
    
    # Remove trailing slashes from URLs
    $clean = $clean -replace '/+$', ''
    
    # Remove trailing /api from base URLs (frontend appends paths)
    $clean = $clean -replace '/api$', ''
    
    return $clean
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
Write-Host "Copy this block into Vercel -> Project Settings -> Environment Variables" -ForegroundColor Yellow
Write-Host "Target Environment: Production (and optionally Preview)" -ForegroundColor Yellow
Write-Host ""

# Validation checks
$errors = @()
if (-not $VITE_API_BASE_URL) { $errors += "VITE_API_BASE_URL is empty" }
if (-not $VITE_SUPABASE_URL) { $errors += "VITE_SUPABASE_URL is empty" }
if (-not $VITE_SUPABASE_ANON_KEY) { $errors += "VITE_SUPABASE_ANON_KEY is empty" }
if (-not $VITE_DRAGONFLY_API_KEY) { $errors += "VITE_DRAGONFLY_API_KEY is empty" }

if ($VITE_SUPABASE_ANON_KEY -match "service_role") {
    $errors += "WARNING: VITE_SUPABASE_ANON_KEY looks like a service role key! Use anon key instead."
}

if ($errors.Count -gt 0) {
    Write-Host "[ERRORS]" -ForegroundColor Red
    foreach ($err in $errors) {
        Write-Host "  ❌ $err" -ForegroundColor Red
    }
    Write-Host ""
}

# Character count validation
Write-Host "[VALIDATION]" -ForegroundColor Green
Write-Host "  VITE_API_BASE_URL      : $($VITE_API_BASE_URL.Length) chars" -ForegroundColor DarkGray
Write-Host "  VITE_SUPABASE_URL      : $($VITE_SUPABASE_URL.Length) chars" -ForegroundColor DarkGray
Write-Host "  VITE_SUPABASE_ANON_KEY : $($VITE_SUPABASE_ANON_KEY.Length) chars (JWT ~200+ expected)" -ForegroundColor DarkGray
Write-Host "  VITE_DRAGONFLY_API_KEY : $($VITE_DRAGONFLY_API_KEY.Length) chars" -ForegroundColor DarkGray
Write-Host ""

Write-Host "───────────────────────────────────────────────────────────────────" -ForegroundColor DarkGray
Write-Host ""

# Output the clean values
Write-Host "VITE_API_BASE_URL=$VITE_API_BASE_URL" -ForegroundColor White
Write-Host "VITE_DRAGONFLY_API_KEY=$VITE_DRAGONFLY_API_KEY" -ForegroundColor White
Write-Host "VITE_SUPABASE_URL=$VITE_SUPABASE_URL" -ForegroundColor White
Write-Host "VITE_SUPABASE_ANON_KEY=$VITE_SUPABASE_ANON_KEY" -ForegroundColor White
Write-Host "VITE_DEMO_MODE=false" -ForegroundColor White

Write-Host ""
Write-Host "───────────────────────────────────────────────────────────────────" -ForegroundColor DarkGray
Write-Host ""

Write-Host "[NEXT STEPS]" -ForegroundColor Green
Write-Host "  1. Go to: https://vercel.com/[your-team]/dragonfly-dashboard/settings/environment-variables" -ForegroundColor White
Write-Host "  2. Add each variable above (Environment: Production)" -ForegroundColor White
Write-Host "  3. Redeploy: Deployments -> ... -> Redeploy" -ForegroundColor White
Write-Host ""

Write-Host "[DEBUG TIP]" -ForegroundColor Cyan
Write-Host "  After deploy, open browser console and look for:" -ForegroundColor DarkGray
Write-Host "    [Dragonfly] API Target: $VITE_API_BASE_URL" -ForegroundColor DarkGray
Write-Host "    [Dragonfly] Health OK from /api/health" -ForegroundColor DarkGray
Write-Host ""

# Also save to file for convenience
$outputFile = "vercel_config.txt"
$content = @"
# Vercel Environment Variables for Dragonfly Dashboard
# Generated: $(Get-Date -Format "yyyy-MM-dd HH:mm:ss")
# Copy each line into Vercel Project Settings

VITE_API_BASE_URL=$VITE_API_BASE_URL
VITE_DRAGONFLY_API_KEY=$VITE_DRAGONFLY_API_KEY
VITE_SUPABASE_URL=$VITE_SUPABASE_URL
VITE_SUPABASE_ANON_KEY=$VITE_SUPABASE_ANON_KEY
VITE_DEMO_MODE=false
"@

$content | Out-File -FilePath $outputFile -Encoding utf8 -NoNewline
Write-Host "[INFO] Also saved to: $outputFile" -ForegroundColor DarkGray
Write-Host ""
