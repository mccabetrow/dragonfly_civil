[CmdletBinding()]
param(
    [string]$ApiUrl
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$script:StartTime = Get-Date
$script:StepResults = New-Object System.Collections.Generic.List[object]
$script:ApiBaseUrl = $null
$script:PythonExe = $null

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptRoot
$EnvFile = Join-Path $RepoRoot '.env.prod'
$LoadEnvScript = Join-Path $ScriptRoot 'load_env.ps1'

function Add-StepResult {
    param(
        [string]$Name,
        [string]$Status,
        [string]$Details
    )

    $script:StepResults.Add([pscustomobject]@{
            Step    = $Name
            Status  = $Status
            Details = $Details
        }) | Out-Null
}

function Format-Detail {
    param($Value)
    if ($null -eq $Value) { return 'OK' }
    if ($Value -is [System.Array]) {
        return ($Value -join ' ')
    }
    return [string]$Value
}

function Run-Step {
    param(
        [string]$Name,
        [ScriptBlock]$Action
    )

    Write-Host "";
    Write-Host ("=== {0} ===" -f $Name) -ForegroundColor Cyan

    try {
        $result = & $Action
        $detail = Format-Detail -Value $result
        Add-StepResult -Name $Name -Status 'PASS' -Details $detail
        Write-Host ("  PASS: {0}" -f $detail) -ForegroundColor Green
    }
    catch {
        $message = $_.Exception.Message
        Add-StepResult -Name $Name -Status 'FAIL' -Details $message
        Write-Host ("  FAIL: {0}" -f $message) -ForegroundColor Red
        throw
    }
}

function Resolve-PythonExe {
    param([string]$Root)

    $candidates = @(
        (Join-Path $Root '.venv\\Scripts\\python.exe'),
        'python',
        'py'
    )

    foreach ($candidate in $candidates) {
        if ([string]::IsNullOrWhiteSpace($candidate)) { continue }
        try {
            $command = Get-Command $candidate -ErrorAction Stop
            return $command.Source
        }
        catch {
            continue
        }
    }

    throw 'Python executable not found. Activate the virtualenv or install Python.'
}

function Resolve-ApiBaseUrl {
    param([string]$Override)

    $candidates = @(
        $Override,
        $env:API_BASE_URL,
        $env:DRAGONFLY_PROD_URL,
        $env:PROD_GATE_BASE_URL,
        $env:RAILWAY_PUBLIC_DOMAIN
    )

    foreach ($candidate in $candidates) {
        if ([string]::IsNullOrWhiteSpace($candidate)) { continue }
        $url = $candidate.Trim()
        if (-not $url.StartsWith('http')) {
            $url = "https://$url"
        }
        return $url.TrimEnd('/')
    }

    throw 'API base URL not configured. Provide -ApiUrl or set API_BASE_URL/DRAGONFLY_PROD_URL.'
}

function Invoke-ApiCheck {
    param(
        [string]$BaseUrl,
        [string]$Path
    )

    if ([string]::IsNullOrWhiteSpace($BaseUrl)) {
        throw 'Base URL is empty'
    }

    $target = "{0}{1}" -f $BaseUrl.TrimEnd('/'), $Path

    try {
        $response = Invoke-WebRequest -Uri $target -Method Get -UseBasicParsing -TimeoutSec 20 -ErrorAction Stop
    }
    catch {
        throw "Request failed for $target: $($_.Exception.Message)"
    }

    if ($response.StatusCode -lt 200 -or $response.StatusCode -ge 300) {
        throw "Request $target returned HTTP $($response.StatusCode)"
    }

    return "HTTP $($response.StatusCode) $target"
}

function Invoke-ExternalCommand {
    param(
        [string]$Executable,
        [string[]]$Arguments,
        [string]$Label
    )

    Write-Host ("    > {0} {1}" -f $Executable, ($Arguments -join ' ')) -ForegroundColor DarkGray
    & $Executable @Arguments
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        throw "$Label failed (exit $exitCode)"
    }

    return 'Completed'
}

if (-not (Test-Path -LiteralPath $EnvFile)) {
    throw "Missing .env.prod at $EnvFile"
}

if (-not (Test-Path -LiteralPath $LoadEnvScript)) {
    throw "Missing helper script: $LoadEnvScript"
}

Push-Location $RepoRoot

$overallSuccess = $false
$failureMessage = $null

try {
    Run-Step 'Load .env.prod' {
        & $LoadEnvScript -EnvPath $EnvFile | Out-Host
        $env:SUPABASE_MODE = 'prod'
        $env:ENVIRONMENT = 'prod'
        return '.env.prod via load_env.ps1'
    }

    Run-Step 'Resolve python interpreter' {
        $script:PythonExe = Resolve-PythonExe -Root $RepoRoot
        return $script:PythonExe
    }

    Run-Step 'Resolve Railway API URL' {
        $script:ApiBaseUrl = Resolve-ApiBaseUrl -Override $ApiUrl
        return $script:ApiBaseUrl
    }

    Run-Step 'Probe /health' {
        Invoke-ApiCheck -BaseUrl $script:ApiBaseUrl -Path '/health'
    }

    Run-Step 'Probe /readyz' {
        Invoke-ApiCheck -BaseUrl $script:ApiBaseUrl -Path '/readyz'
    }

    Run-Step 'tools.go_live_gate --env prod' {
        Invoke-ExternalCommand -Executable $script:PythonExe -Arguments @('-m', 'tools.go_live_gate', '--env', 'prod') -Label 'go_live_gate'
    }

    Run-Step 'tools.smoke_deploy' {
        Invoke-ExternalCommand -Executable $script:PythonExe -Arguments @('-m', 'tools.smoke_deploy', '--url', $script:ApiBaseUrl) -Label 'smoke_deploy'
    }

    Run-Step 'tools.verify_business_logic --env prod' {
        Invoke-ExternalCommand -Executable $script:PythonExe -Arguments @('-m', 'tools.verify_business_logic', '--env', 'prod') -Label 'verify_business_logic'
    }

    Run-Step 'tools.verify_ingest_golden_path --env prod' {
        Invoke-ExternalCommand -Executable $script:PythonExe -Arguments @('-m', 'tools.verify_ingest_golden_path', '--env', 'prod') -Label 'verify_ingest_golden_path'
    }

    $overallSuccess = $true
}
catch {
    $overallSuccess = $false
    $failureMessage = $_.Exception.Message
}
finally {
    Pop-Location | Out-Null
}

Write-Host ""
Write-Host '------------------------------------------------------------'
Write-Host 'Step Summary:'
foreach ($result in $script:StepResults) {
    $color = switch ($result.Status) {
        'PASS' { 'Green' }
        'FAIL' { 'Red' }
        Default { 'Yellow' }
    }
    Write-Host ("  [{0}] {1} - {2}" -f $result.Status, $result.Step, $result.Details) -ForegroundColor $color
}
Write-Host '------------------------------------------------------------'

$duration = [math]::Round(((Get-Date) - $script:StartTime).TotalSeconds, 1)

$banner = '=' * 70
if ($overallSuccess) {
    Write-Host $banner -ForegroundColor Green
    Write-Host '  GO FOR PROD - ALL CHECKS PASSED' -ForegroundColor Green
    Write-Host $banner -ForegroundColor Green
    Write-Host ("Duration: {0}s" -f $duration)
    exit 0
}
else {
    Write-Host $banner -ForegroundColor Red
    Write-Host '  NO-GO - AT LEAST ONE CHECK FAILED' -ForegroundColor Red
    Write-Host $banner -ForegroundColor Red
    if ($failureMessage) {
        Write-Host ("Failure: {0}" -f $failureMessage) -ForegroundColor Yellow
    }
    Write-Host ("Duration: {0}s" -f $duration)
    exit 1
}
