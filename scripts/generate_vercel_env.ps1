<#
.SYNOPSIS
    Generates Vercel environment variables for the Dragonfly Dashboard.

.DESCRIPTION
    This script reads from .env.prod and outputs the exact environment variables
    needed for Vercel deployment. Copy/paste these into Vercel Project Settings.

.PARAMETER EnvFile
    Path to the production env file. Defaults to .env.prod in the repo root.

.EXAMPLE
    .\scripts\generate_vercel_env.ps1
    
    Output:
    ========================================
    VERCEL ENVIRONMENT VARIABLES
    ========================================
    
    NEXT_PUBLIC_API_URL=https://dragonflycivil-production-d57a.up.railway.app/api
    NEXT_PUBLIC_API_KEY=df_prod_xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
    ...

.NOTES
    Author: Dragonfly Civil Engineering Team
    Purpose: Go-Live Vercel <-> Railway connectivity
#>

param(
    [string]$EnvFile = ".env.prod"
)

$ErrorActionPreference = "Stop"

# Header
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host " VERCEL ENVIRONMENT VARIABLES" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Copy these into Vercel -> Project Settings -> Environment Variables" -ForegroundColor Yellow
Write-Host "Target: Production (and optionally Preview)" -ForegroundColor Yellow
Write-Host ""
Write-Host "----------------------------------------" -ForegroundColor DarkGray

# Check if env file exists
if (-not (Test-Path $EnvFile)) {
    Write-Host "[ERROR] Environment file not found: $EnvFile" -ForegroundColor Red
    Write-Host "Make sure you have a .env.prod file in the repo root." -ForegroundColor Yellow
    exit 1
}

# Read env file and parse key-value pairs
$envVars = @{}
Get-Content $EnvFile | ForEach-Object {
    $line = $_.Trim()
    # Skip comments and empty lines
    if ($line -and -not $line.StartsWith("#")) {
        if ($line -match "^([^=]+)=(.*)$") {
            $key = $matches[1].Trim()
            $value = $matches[2].Trim()
            $envVars[$key] = $value
        }
    }
}

# Railway Backend URL (hardcoded since it's not in .env.prod)
$railwayUrl = "https://dragonflycivil-production-d57a.up.railway.app"

# Extract values
$supabaseUrl = $envVars["SUPABASE_URL"]
$supabaseServiceKey = $envVars["SUPABASE_SERVICE_ROLE_KEY"]
$dragonflyApiKey = $envVars["DRAGONFLY_API_KEY"]

# Note: We need to find the anon key - it's different from service role key
# For now, we'll generate a placeholder and note it needs to be updated

Write-Host ""
Write-Host "[REQUIRED] Backend API Connection:" -ForegroundColor Green
Write-Host ""

# VITE_API_BASE_URL - Railway backend with /api suffix
Write-Host "VITE_API_BASE_URL=$railwayUrl/api" -ForegroundColor White

# VITE_DRAGONFLY_API_KEY - API key for X-DRAGONFLY-API-KEY header
Write-Host "VITE_DRAGONFLY_API_KEY=$dragonflyApiKey" -ForegroundColor White

Write-Host ""
Write-Host "[REQUIRED] Supabase Direct Access:" -ForegroundColor Green
Write-Host ""

# VITE_SUPABASE_URL
Write-Host "VITE_SUPABASE_URL=$supabaseUrl" -ForegroundColor White

# VITE_SUPABASE_ANON_KEY - Note: This is different from service role key
# The anon key is safe for frontend use, service role is NOT
Write-Host ""
Write-Host "[IMPORTANT] VITE_SUPABASE_ANON_KEY:" -ForegroundColor Yellow
Write-Host "  Get from: Supabase Dashboard -> Settings -> API -> anon/public key" -ForegroundColor DarkGray
Write-Host "  Project: $supabaseUrl" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  DO NOT use the service role key on the frontend!" -ForegroundColor Red

Write-Host ""
Write-Host "----------------------------------------" -ForegroundColor DarkGray
Write-Host ""
Write-Host "[OPTIONAL] Demo Mode (disable for production):" -ForegroundColor Cyan
Write-Host ""
Write-Host "VITE_DEMO_MODE=false" -ForegroundColor DarkGray

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host " COPY-PASTE BLOCK" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Generate clean copy-paste block
$copyBlock = @"
VITE_API_BASE_URL=$railwayUrl/api
VITE_DRAGONFLY_API_KEY=$dragonflyApiKey
VITE_SUPABASE_URL=$supabaseUrl
VITE_SUPABASE_ANON_KEY=<GET FROM SUPABASE DASHBOARD>
VITE_DEMO_MODE=false
"@

Write-Host $copyBlock -ForegroundColor White

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "[NEXT STEPS]" -ForegroundColor Green
Write-Host "1. Go to Vercel -> dragonfly-dashboard -> Settings -> Environment Variables" -ForegroundColor White
Write-Host "2. Add each variable above (Environment: Production)" -ForegroundColor White
Write-Host "3. Get the anon key from Supabase Dashboard -> Settings -> API" -ForegroundColor White
Write-Host "4. Redeploy: vercel --prod" -ForegroundColor White
Write-Host ""

# Also output to a file for convenience
$outputFile = "vercel_env_vars.txt"
$copyBlock | Out-File -FilePath $outputFile -Encoding utf8
Write-Host "[INFO] Variables also saved to: $outputFile" -ForegroundColor DarkGray
Write-Host ""
