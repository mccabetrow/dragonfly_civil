[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^https://')]
    [string]$Url
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$modulePath = Join-Path -Path $PSScriptRoot -ChildPath 'ProdGateHelpers.psm1'
if (-not (Test-Path $modulePath)) {
    throw "ProdGateHelpers module not found at $modulePath"
}
Import-Module $modulePath -Force

$workspaceRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path

function Write-Section {
    param([string]$Title)
    $line = '=' * 60
    Write-Host ""; Write-Host $line -ForegroundColor Cyan
    Write-Host " $Title" -ForegroundColor Cyan
    Write-Host $line -ForegroundColor Cyan
}

function Get-GitInfo {
    param([string]$RepoRoot)
    $git = Get-Command git -ErrorAction Stop
    $sha = ( & $git.Source -C $RepoRoot rev-parse HEAD 2>$null ).Trim()
    $branch = ( & $git.Source -C $RepoRoot rev-parse --abbrev-ref HEAD 2>$null ).Trim()
    if (-not $sha) { $sha = 'unknown' }
    if (-not $branch) { $branch = 'unknown' }
    return [pscustomobject]@{ Sha = $sha; Branch = $branch }
}

function Get-PythonExecutable {
    param([string]$RepoRoot)
    return Get-ProdGatePythonPath -WorkspaceRoot $RepoRoot
}

function Write-PythonVersion {
    param([string]$PythonExe)
    $version = (& $PythonExe --version 2>&1).Trim()
    Write-Host "Python: $version"
}

function Invoke-Task {
    param(
        [string]$PythonExe,
        [string]$DisplayName,
        [string[]]$Arguments
    )
    Write-Host "→ $DisplayName" -ForegroundColor DarkCyan
    Write-Host "   Command: $PythonExe $($Arguments -join ' ')"
    $output = & $PythonExe @Arguments 2>&1
    $exitCode = $LASTEXITCODE
    if ($output) {
        $output | ForEach-Object { Write-Host "   $_" }
    }
    if ($exitCode -ne 0) {
        throw "$DisplayName failed with exit code $exitCode"
    }
}

Write-Section -Title 'Railway Diagnostics'

try {
    $gitInfo = Get-GitInfo -RepoRoot $workspaceRoot
    Write-Host "Git SHA: $($gitInfo.Sha)"
    Write-Host "Git Branch: $($gitInfo.Branch)"
}
catch {
    Write-Host "Git information unavailable: $($_.Exception.Message)" -ForegroundColor Yellow
}

try {
    $pythonExe = Get-PythonExecutable -RepoRoot $workspaceRoot
    Write-PythonVersion -PythonExe $pythonExe
}
catch {
    throw "Unable to locate Python executable: $($_.Exception.Message)"
}

Write-Section -Title 'Python diagnostics'

Invoke-Task -PythonExe $pythonExe -DisplayName 'tools.diagnose_boot' -Arguments @('-m', 'tools.diagnose_boot')

Invoke-Task -PythonExe $pythonExe -DisplayName 'tools.probe_db' -Arguments @('-m', 'tools.probe_db', '--env', 'prod', '--from-env')

Invoke-Task -PythonExe $pythonExe -DisplayName 'tools.certify_prod' -Arguments @('-m', 'tools.certify_prod', '--url', $Url, '--env', 'prod', '--no-fail-fast')

Write-Host "" -ForegroundColor Green
Write-Host ('=' * 60) -ForegroundColor Green
Write-Host "✅ railway_diag completed successfully" -ForegroundColor Green
Write-Host ('=' * 60) -ForegroundColor Green
