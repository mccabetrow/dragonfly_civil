param(
    [switch]$Once,
    [int]$Interval = 2
)

$ErrorActionPreference = 'Stop'

Set-Location -Path (Join-Path $PSScriptRoot '..')

& .\.venv\Scripts\Activate.ps1
$env:PYTHONPATH = (Get-Location).Path

$arguments = @('-m', 'judgment_ingestor.main')
if ($Once.IsPresent) {
    $arguments += '--once'
}
$arguments += @('--interval', $Interval)

python @arguments
