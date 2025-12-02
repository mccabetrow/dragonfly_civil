param(
    [string]$CsvPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptRoot
Set-Location $repoRoot

if (-not $CsvPath -or $CsvPath.Trim().Length -eq 0) {
    $CsvPath = Join-Path $repoRoot 'intake_900.csv'
}

$batchName = '900-wave-1'
$pythonExe = Join-Path $repoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) {
    Write-Host "[FAIL] Python interpreter not found at $pythonExe. Run scripts/bootstrap.ps1 first." -ForegroundColor Red
    exit 1
}

if (-not (Test-Path -LiteralPath $CsvPath)) {
    Write-Host "[FAIL] CSV not found: $CsvPath" -ForegroundColor Red
    exit 1
}

$env:SUPABASE_MODE = 'dev'
Write-Host "[900-DRY-RUN] Starting 900-plaintiff dry run against DEV..." -ForegroundColor Yellow
Write-Host "           CSV: $CsvPath"
Write-Host "        Batch: $batchName"

function Invoke-Step {
    param(
        [Parameter(Mandatory)][string]$Label,
        [Parameter(Mandatory)][string[]]$Command
    )

    Write-Host "    -> $Label"
    & $Command[0] $Command[1..($Command.Length - 1)]
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[FAIL] $Label (exit $LASTEXITCODE)" -ForegroundColor Red
        exit $LASTEXITCODE
    }
    Write-Host "[OK] $Label" -ForegroundColor Green
}

Write-Host "[BEFORE] ops_summary snapshot" -ForegroundColor Cyan
Invoke-Step "ops_summary (dev)" @($pythonExe, '-m', 'tools.ops_summary', '--env', 'dev')

Write-Host "[RUN] tools.dry_run_900" -ForegroundColor Cyan
Invoke-Step "dry_run_900" @(
    $pythonExe, '-m', 'tools.dry_run_900',
    '--env', 'dev',
    '--csv', $CsvPath,
    '--batch-name', $batchName
)

Write-Host "[QA] tools.import_qa" -ForegroundColor Cyan
Invoke-Step "import_qa jbi900" @(
    $pythonExe, '-m', 'tools.import_qa',
    'jbi900', $batchName,
    '--env', 'dev'
)

Write-Host "[AFTER] ops_summary snapshot" -ForegroundColor Cyan
Invoke-Step "ops_summary (dev, after)" @($pythonExe, '-m', 'tools.ops_summary', '--env', 'dev')

Write-Host "[900-DRY-RUN] Completed successfully. Review import_qa + BEFORE/AFTER ops_summary." -ForegroundColor Green
