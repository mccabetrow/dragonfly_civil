$ErrorActionPreference = 'Stop'

Set-Location -Path (Join-Path $PSScriptRoot '..')

& .\.venv\Scripts\Activate.ps1
$env:PYTHONPATH = (Get-Location).Path

python -m workers.runner
