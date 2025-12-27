$ErrorActionPreference = 'Stop'

. "$PSScriptRoot/load_env.ps1"

$root = Split-Path -Parent $PSScriptRoot

$python = Join-Path $root ".venv" "Scripts" "python.exe"
if (-not (Test-Path -LiteralPath $python)) {
	$python = "python"
}

# Use here-string for safe Python execution (pipe to stdin to preserve quotes)
$EnsureSessionScript = @'
from etl.src.auth.session_manager import ensure_session
ensure_session()
'@

Write-Host "Ensuring WebCivil session" -ForegroundColor Cyan
$EnsureSessionScript | & $python -
if ($LASTEXITCODE -ne 0) {
	Write-Error "Session bootstrap failed"
	exit $LASTEXITCODE
}

Write-Host "Running collector_v2 dry-run navigation" -ForegroundColor Cyan
& $python -m etl.src.collector_v2 --dry-run
if ($LASTEXITCODE -ne 0) {
	Write-Error "collector_v2 dry-run failed"
	exit $LASTEXITCODE
}

Write-Host "Smoke run complete" -ForegroundColor Green
