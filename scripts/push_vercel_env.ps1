<#
.SYNOPSIS
    Push clean environment variables to Vercel from .env.prod

.DESCRIPTION
    Reads .env.prod, sanitizes values (trims whitespace, removes trailing slashes),
    and pushes them to Vercel using the Vercel CLI.

.PARAMETER DryRun
    Preview the commands without executing them.

.PARAMETER Project
    Vercel project name (uses current directory project if not specified).

.EXAMPLE
    .\scripts\push_vercel_env.ps1 -DryRun
    .\scripts\push_vercel_env.ps1 -Project dragonfly-dashboard
#>
param(
    [switch]$DryRun,
    [string]$Project,
    [string]$EnvFile = ".env.prod"
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path $PSScriptRoot -Parent
$EnvPath = Join-Path $RepoRoot $EnvFile

if (-not (Test-Path $EnvPath)) {
    Write-Host "ERROR: File not found: $EnvPath" -ForegroundColor Red
    exit 1
}

# Check for Vercel CLI
$vercel = Get-Command vercel -ErrorAction SilentlyContinue
if (-not $vercel) {
    Write-Host "ERROR: Vercel CLI not found. Install with: npm i -g vercel" -ForegroundColor Red
    exit 1
}

# URL keys that should have trailing slashes removed
$UrlKeys = @(
    "VITE_API_BASE_URL",
    "VITE_SUPABASE_URL",
    "API_BASE_URL",
    "SUPABASE_URL"
)

# Parse and sanitize env file
$vars = @{}
Get-Content $EnvPath | ForEach-Object {
    if ($_ -match '^\s*#' -or $_ -match '^\s*$') { return }
    
    $parts = $_ -split '=', 2
    if ($parts.Count -eq 2) {
        $key = $parts[0].Trim()
        $value = $parts[1].Trim()
        
        # Remove internal newlines
        $value = $value -replace '[\r\n]+', ''
        
        # Remove trailing slash from URL keys
        if ($UrlKeys -contains $key -and $value.EndsWith('/')) {
            $value = $value.TrimEnd('/')
        }
        
        $vars[$key] = $value
    }
}

Write-Host "==================================================================" -ForegroundColor Cyan
Write-Host " Vercel Environment Push" -ForegroundColor Cyan
Write-Host "==================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Source: $EnvFile"
Write-Host "Target: production"
Write-Host "Variables: $($vars.Count)"
if ($DryRun) {
    Write-Host "[DRY RUN MODE]" -ForegroundColor Yellow
}
Write-Host ""

$projectArg = if ($Project) { "--project=$Project" } else { "" }

foreach ($key in $vars.Keys | Sort-Object) {
    $value = $vars[$key]
    $displayValue = if ($key -match 'KEY|PASSWORD|SECRET|TOKEN') { '***' } else { $value }
    
    if ($DryRun) {
        Write-Host "  [DRY] $key = $displayValue" -ForegroundColor Gray
    }
    else {
        Write-Host "  -> $key" -NoNewline
        try {
            # Remove existing variable first (ignore errors if doesn't exist)
            $null = vercel env rm $key production --yes $projectArg 2>$null
            
            # Add new value using echo to avoid interactive prompt
            $value | vercel env add $key production $projectArg 2>&1 | Out-Null
            Write-Host " OK" -ForegroundColor Green
        }
        catch {
            Write-Host " FAILED: $($_.Exception.Message)" -ForegroundColor Red
        }
    }
}

Write-Host ""
if ($DryRun) {
    Write-Host "Run without -DryRun to push to Vercel" -ForegroundColor Yellow
}
else {
    Write-Host "Pushed $($vars.Count) variables to Vercel production" -ForegroundColor Green
    Write-Host ""
    Write-Host "Redeploy with: vercel --prod" -ForegroundColor Cyan
}
