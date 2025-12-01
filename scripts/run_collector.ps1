. "$PSScriptRoot/load_env.ps1"

$root = Split-Path -Parent $PSScriptRoot

$python = Join-Path $root ".venv" "Scripts" "python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    $python = "python"
}

$arguments = @(
    "-m", "etl.src.collector_v2",
    "--composite",
    "--use-idempotent-composite",
    "--case-number", "SMOKE-DEMO-0001"
)

Write-Host "Running collector v2 smoke insert" -ForegroundColor Cyan
& $python @arguments
if ($LASTEXITCODE -ne 0) {
    Write-Error "collector_v2 execution failed"
    exit $LASTEXITCODE
}
