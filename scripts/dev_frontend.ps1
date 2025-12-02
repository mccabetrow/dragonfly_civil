[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptRoot
$dashboardDir = Join-Path $repoRoot 'dragonfly-dashboard'

Write-Host '[INFO] Starting Dragonfly dashboard dev server' -ForegroundColor Cyan
Write-Host "[INFO] Repository root: $repoRoot" -ForegroundColor Cyan
Write-Host "[INFO] Dashboard directory: $dashboardDir" -ForegroundColor Cyan

if (-not (Test-Path -LiteralPath $dashboardDir)) {
    Write-Host '[FAIL] dragonfly-dashboard directory is missing.' -ForegroundColor Red
    exit 1
}

Set-Location -LiteralPath $dashboardDir

$nodeModulesPath = Join-Path $dashboardDir 'node_modules'
if (-not (Test-Path -LiteralPath $nodeModulesPath)) {
    Write-Host '[INFO] node_modules missing; running npm install' -ForegroundColor Yellow
    npm install
} else {
    Write-Host '[INFO] node_modules exists; skipping npm install' -ForegroundColor Green
}

Write-Host '[INFO] Launching Vite dev server (npm run dev -- --host 127.0.0.1 --clearScreen false)' -ForegroundColor Cyan
npm run dev -- --host 127.0.0.1 --clearScreen false
