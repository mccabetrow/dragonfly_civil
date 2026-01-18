<#
.SYNOPSIS
    Dragonfly Production Gate - The "Red Button" Release Gate

.DESCRIPTION
    This script acts as the definitive GO/NO-GO gate before production releases.
    It validates service identity, health, readiness, and database connectivity.

.PARAMETER Url
    The target URL to test. Defaults to production Railway domain.

.PARAMETER Env
    Target environment (dev or prod). Defaults to 'prod'.

.PARAMETER Strict
    Fail immediately on any 503 readiness response. Without this flag,
    503 is treated as a warning for degraded mode.

.EXAMPLE
    # Default production check
    .\prod_gate.ps1

.EXAMPLE
    # Explicit URL and strict mode
    .\prod_gate.ps1 -Url https://dragonfly-api.railway.app -Env prod -Strict

.EXAMPLE
    # Dev environment check
    .\prod_gate.ps1 -Url http://localhost:8888 -Env dev

.NOTES
    Exit Codes:
      0 - ✅ GO FOR LAUNCH - All gates passed
      1 - ❌ ABORT - One or more gates failed
      2 - Script/parameter error
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [ValidateNotNullOrEmpty()]
    [string]$Url = 'https://dragonfly-api-production.up.railway.app',

    [Parameter(Mandatory = $false)]
    [ValidateSet('prod', 'dev')]
    [string]$Env = 'prod',

    [switch]$Strict
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# =============================================================================
# MODULE IMPORTS
# =============================================================================

$modulePath = Join-Path -Path $PSScriptRoot -ChildPath 'ProdGateHelpers.psm1'
if (-not (Test-Path $modulePath)) {
    Write-Error "ProdGate helpers not found at $modulePath"
    exit 2
}
Import-Module $modulePath -Force

# =============================================================================
# HELPER FUNCTIONS
# ==================================================================================================

function Write-ProdGateHeader {
    ader {
        param(
            [string]$Target, ,
            [string]$Environment,
            [bool]$StrictMode   [bool]$StrictMode
        )

        $line = '=' * 72
        Write-Host ''-Host ''
        Write-Host $line -ForegroundColor Cyan $line -ForegroundColor Cyan
        Write-Host '  🐉 DRAGONFLY PRODUCTION GATE' -ForegroundColor Cyann
        Write-Host $line -ForegroundColor Cyan-Host $line -ForegroundColor Cyan
        Write-Host "  Target:      $Target" -ForegroundColor Cyanrite-Host "  Target:      $Target" -ForegroundColor Cyan
        Write-Host "  Environment: $Environment" -ForegroundColor Cyanost "  Environment: $Environment" -ForegroundColor Cyan
        Write-Host "  Strict Mode: $StrictMode" -ForegroundColor Cyan
        Write-Host "  Timestamp:   $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor Cyanrite-Host "  Timestamp:   $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor Cyan
        Write-Host $line -ForegroundColor Cyan   Write-Host $line -ForegroundColor Cyan
        Write-Host ''    Write-Host ''
    }

    function Write-GoForLaunch {
        $line = '=' * 72
        Write-Host ''rite-Host ''
        Write-Host $line -ForegroundColor Green    Write-Host $line -ForegroundColor Green
        Write-Host '  ✅ GO FOR LAUNCH' -ForegroundColor Green
        Write-Host $line -ForegroundColor Green-Host $line -ForegroundColor Green
        Write-Host '  All production gates satisfied.' -ForegroundColor Green
        Write-Host '  Service is healthy and ready to accept traffic.' -ForegroundColor Greenrite-Host '  Service is healthy and ready to accept traffic.' -ForegroundColor Green
        Write-Host $line -ForegroundColor Greenost $line -ForegroundColor Green
        Write-Host ''
    }

    function Write-Abort {
        param(
            [string]$Message,
            [string]$Remediation
        )

        $line = '=' * 72line = '=' * 72
        Write-Host ''
        Write-Host $line -ForegroundColor Red
        Write-Host '  ❌ ABORT' -ForegroundColor Redrite-Host '  ❌ ABORT' -ForegroundColor Red
        Write-Host $line -ForegroundColor Red   Write-Host $line -ForegroundColor Red
        Write-Host "  Reason: $Message" -ForegroundColor Red    Write-Host "  Reason: $Message" -ForegroundColor Red
        if ($Remediation) {
            f ($Remediation) {
                Write-Host '''
        Write-Host '  Remediation:' -ForegroundColor Yellow       Write-Host '  Remediation:' -ForegroundColor Yellow
        Write-Host "    $Remediation" -ForegroundColor Yellow Write-Host "    $Remediation" -ForegroundColor Yellow
    }
    Write-Host $line -ForegroundColor Red   Write-Host $line -ForegroundColor Red
    Write-Host ''    Write-Host ''
}

function Fail-ProdGate {unction Fail-ProdGate {
    param(    param(
        [string]$Message,
        [string]$Remediation,
        [int]$ExitCode = 1        [int]$ExitCode = 1
    )

    Write-Abort -Message $Message -Remediation $Remediation
    exit $ExitCode
}

function Write-CheckResult {function Write-CheckResult {
    param((
        [string]$Label,
        [bool]$Passed,   [bool]$Passed,
        [string]$Detailring]$Detail
    )

    if ($Passed) {    if ($Passed) {
        Write-Host "  ✅ $Label" -ForegroundColor Greenn
        if ($Detail) {
            Write-Host "     $Detail" -ForegroundColor DarkGray       Write-Host "     $Detail" -ForegroundColor DarkGray
        }
    }    }
    else {
        Write-Host "  ❌ $Label" -ForegroundColor Red
        if ($Detail) {
            Write-Host "     $Detail" -ForegroundColor Red
        }   }
    }
}}

function Invoke-ProdGateRequest {
    param(
        [string]$BaseUrl,
        [string]$Path,   [string]$Path,
        [string]$Label
    )

    $relative = if ($Path.StartsWith('/')) { $Path } else { "/$Path" } { $Path } else { "/$Path" }
    $uri = "$BaseUrl$relative"
    Write-Host "→ $Label" -ForegroundColor DarkCyan
    Write-Host "  GET $uri" -ForegroundColor DarkGray-Host "  GET $uri" -ForegroundColor DarkGray

    $requestParams = @{
        Uri        = $uriri        = $uri
        Method     = 'Get'   Method     = 'Get'
        TimeoutSec = 15meoutSec = 15
        Headers    = @{ 'Accept' = 'application/json'; 'User-Agent' = 'prod-gate/2.0' }
    }

    try {
        if ($PSVersionTable.PSVersion.Major -ge 6) {
            return Invoke-WebRequest @requestParams -SkipHttpErrorCheck   return Invoke-WebRequest @requestParams -SkipHttpErrorCheck
        }
        else {   else {
            return Invoke-WebRequest @requestParams -UseBasicParsing return Invoke-WebRequest @requestParams -UseBasicParsing
        }
    }
    catch {    catch {
        return @{
            StatusCode = 0
            Content    = $_.Exception.Message       Content    = $_.Exception.Message
            Headers    = @{}
            Exception  = $_
        }   }
    }
}

function Invoke-PythonTool {
    param(
        [string]$DisplayName,
        [string[]]$Arguments   [string[]]$Arguments
    )    )

    $workspaceRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Pathh (Join-Path $PSScriptRoot '..')).Path
    try {
        $pythonExe = Get-ProdGatePythonPath -WorkspaceRoot $workspaceRoot   $pythonExe = Get-ProdGatePythonPath -WorkspaceRoot $workspaceRoot
    }
    catch {
        Fail-ProdGate "Unable to locate python executable" $_.Exception.Message 2   Fail-ProdGate "Unable to locate python executable" $_.Exception.Message 2
    }

    Write-Host "→ $DisplayName" -ForegroundColor DarkCyan
    Write-Host "  $pythonExe $($Arguments -join ' ')" -ForegroundColor DarkGray

    $output = & $pythonExe @Arguments 2>&1 2>&1
    $exitCode = $LASTEXITCODEexitCode = $LASTEXITCODE

    if ($output) {    if ($output) {
        $output | ForEach-Object {
            $maskedLine = Mask-OutputLine -Line $_$_
            Write-Host "  $maskedLine" -ForegroundColor DarkGrayDarkGray
        }
    }

    return $exitCode   return $exitCode
}

# ============================================================================= =============================================================================
# MAIN EXECUTION
# =============================================================================

# Validate URL format
try {
    $uri = [Uri]$Url
}
catch {
    Fail-ProdGate "Invalid Url parameter: $Url" "Provide a valid https:// URL" 2
}

if ($Env -eq 'prod' -and $uri.Scheme -ne 'https') {
    Fail-ProdGate "Production URL must use HTTPS" "Use https://<domain>" 2
}

$baseUrl = "{0}://{1}" -f $uri.Scheme, $uri.Authority
Write-ProdGateHeader -Target $baseUrl -Environment $Env -StrictMode:$Strict.IsPresent

$allChecksPassed = $true

try {
    # =========================================================================
    # CHECK 1: GET / - Service Identity
    # =========================================================================
    $rootResponse = Invoke-ProdGateRequest -BaseUrl $baseUrl -Path '/' -Label 'Service Identity Check'

    # Check for Railway fallback
    if ($rootResponse.Headers -and (Test-RailwayFallbackHeader $rootResponse.Headers)) {
        Write-CheckResult -Label 'Service Identity' -Passed $false -Detail 'Railway fallback detected - domain not attached'
        Fail-ProdGate 'Railway fallback detected' 'Attach the domain to the dragonfly-api service in Railway'
    }

    # Check for HTTP errors
    if ($rootResponse.StatusCode -eq 0) {
        Write-CheckResult -Label 'Service Identity' -Passed $false -Detail "Connection failed: $($rootResponse.Content)"
        Fail-ProdGate 'Connection failed' 'Check URL and network connectivity'
    }

    if ($rootResponse.StatusCode -ge 400) {
        Write-CheckResult -Label 'Service Identity' -Passed $false -Detail "HTTP $($rootResponse.StatusCode)"
        Fail-ProdGate "Service returned HTTP $($rootResponse.StatusCode)" 'Check deployment status'
    }

    # Parse JSON response
    try {
        $rootJson = $rootResponse.Content | ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        Write-CheckResult -Label 'Service Identity' -Passed $false -Detail 'Response is not valid JSON'
        Fail-ProdGate 'Unable to parse JSON from /' 'Verify correct service is deployed'
    }

    # Verify service_name
    if ($rootJson.service_name -ne 'dragonfly-api') {
        Write-CheckResult -Label 'Service Identity' -Passed $false -Detail "service_name='$($rootJson.service_name)'"
        Fail-ProdGate "Wrong service: expected 'dragonfly-api', got '$($rootJson.service_name)'" 'Deploy dragonfly-api to this domain'
    }

    $identityDetail = "service_name=$($rootJson.service_name) sha=$($rootJson.sha_short) env=$($rootJson.env)"
    Write-CheckResult -Label 'Service Identity' -Passed $true -Detail $identityDetail

    # =========================================================================
    # CHECK 2: GET /health - Liveness
    # =========================================================================
    $healthResponse = Invoke-ProdGateRequest -BaseUrl $baseUrl -Path '/health' -Label 'Liveness Check'

    if ($healthResponse.StatusCode -eq 200) {
        Write-CheckResult -Label '/health (Liveness)' -Passed $true -Detail '200 OK'
    }
    else {
        Write-CheckResult -Label '/health (Liveness)' -Passed $false -Detail "HTTP $($healthResponse.StatusCode)"
        Fail-ProdGate "/health returned $($healthResponse.StatusCode)" 'Check API deployment and logs'
    }

    # =========================================================================
    # CHECK 3: GET /readyz - Readiness (DB Connected)
    # =========================================================================
    $readyResponse = Invoke-ProdGateRequest -BaseUrl $baseUrl -Path '/readyz' -Label 'Readiness Check'

    if ($readyResponse.StatusCode -eq 200) {
        Write-CheckResult -Label '/readyz (Readiness)' -Passed $true -Detail '200 OK - Database connected'
    }
    elseif ($readyResponse.StatusCode -eq 503) {
        try {
            $readyPayload = $readyResponse.Content | ConvertFrom-Json -ErrorAction Stop
            $reason = $readyPayload.reason
            $nextRetry = $readyPayload.next_retry_in_seconds
            $failures = $readyPayload.consecutive_failures
            $detail = "reason=$reason next_retry=${nextRetry}s failures=$failures"
        }
        catch {
            $detail = '503 Service Unavailable'
        }

        if ($Strict.IsPresent) {
            Write-CheckResult -Label '/readyz (Readiness)' -Passed $false -Detail $detail
            Fail-ProdGate '/readyz returned 503 (DB not ready)' 'Resolve database connectivity issues'
        }
        else {
            Write-Host "  ⚠️ /readyz (Readiness)" -ForegroundColor Yellow
            Write-Host "     $detail (non-strict mode)" -ForegroundColor Yellow
        }
    }
    else {
        Write-CheckResult -Label '/readyz (Readiness)' -Passed $false -Detail "HTTP $($readyResponse.StatusCode)"
        Fail-ProdGate "/readyz returned $($readyResponse.StatusCode)" 'Check API and database status'
    }

    # =========================================================================
    # CHECK 4: GET /whoami - Extended Identity
    # =========================================================================
    $whoamiResponse = Invoke-ProdGateRequest -BaseUrl $baseUrl -Path '/whoami' -Label 'Extended Identity Check'

    if ($whoamiResponse.StatusCode -eq 200) {
        try {
            $whoamiData = Parse-WhoAmIJson -Json $whoamiResponse.Content

            if ($whoamiData.Env -ne $Env) {
                Write-CheckResult -Label '/whoami (Environment)' -Passed $false -Detail "env='$($whoamiData.Env)' expected='$Env'"
                Fail-ProdGate "Environment mismatch: got '$($whoamiData.Env)', expected '$Env'" 'Deploy correct environment'
            }

            $whoamiDetail = "env=$($whoamiData.Env) sha=$($whoamiData.ShaShort) db_ready=$($whoamiData.DatabaseReady)"
            Write-CheckResult -Label '/whoami (Environment)' -Passed $true -Detail $whoamiDetail
        }
        catch {
            Write-CheckResult -Label '/whoami (Environment)' -Passed $false -Detail "Parse error: $_"
        }
    }
    else {
        Write-Host "  ⚠️ /whoami returned $($whoamiResponse.StatusCode)" -ForegroundColor Yellow
    }

    # =========================================================================
    # CHECK 5: Internal Database Probe
    # =========================================================================
    Write-Host ''
    Write-Host '→ Internal Database Probe' -ForegroundColor DarkCyan

    $probeExitCode = Invoke-PythonTool -DisplayName 'tools.probe_db' -Arguments @('-m', 'tools.probe_db', '--env', $Env, '--from-env')

    if ($probeExitCode -eq 0) {
        Write-CheckResult -Label 'Database Probe' -Passed $true -Detail 'Connection verified'
    }
    else {
        Write-CheckResult -Label 'Database Probe' -Passed $false -Detail "Exit code: $probeExitCode"
        $allChecksPassed = $false
        if ($Strict.IsPresent) {
            Fail-ProdGate 'Database probe failed' 'Check DATABASE_URL and Supabase status'
        }
        else {
            Write-Host "  ⚠️ Database probe failed (non-strict mode)" -ForegroundColor Yellow
        }
    }

    # =========================================================================
    # CHECK 6: Production Certifier
    # =========================================================================
    Write-Host ''
    Write-Host '→ Production Certifier' -ForegroundColor DarkCyan

    $certArgs = @('-m', 'tools.certify_prod', '--url', $baseUrl, '--env', $Env)
    if (-not $Strict.IsPresent) {
        $certArgs += '--no-fail-fast'
    }

    $certExitCode = Invoke-PythonTool -DisplayName 'tools.certify_prod' -Arguments $certArgs

    if ($certExitCode -eq 0) {
        Write-CheckResult -Label 'Production Certifier' -Passed $true -Detail 'All checks passed'
    }
    else {
        Write-CheckResult -Label 'Production Certifier' -Passed $false -Detail "Exit code: $certExitCode"
        $allChecksPassed = $false
        if ($Strict.IsPresent) {
            Fail-ProdGate 'Production certification failed' 'Review certify_prod output above'
        }
        else {
            Write-Host "  ⚠️ Certifier failed (non-strict mode)" -ForegroundColor Yellow
        }
    }

    # =========================================================================
    # FINAL VERDICT
    # =========================================================================
    Write-Host ''

    if ($allChecksPassed) {
        Write-GoForLaunch
        exit 0
    }
    else {
        Write-Abort -Message 'One or more checks failed' -Remediation 'Review warnings above and re-run with -Strict for hard enforcement'
        exit 1
    }
}
catch {
    Fail-ProdGate "Unexpected script error: $($_.Exception.Message)" 'Check script execution' 2
}
# MAIN EXECUTION
# =============================================================================

# Validate URL format
try {
    $uri = [Uri]$Url
}
catch {
    Fail-ProdGate "Invalid Url parameter: $Url" "Provide a valid https:// URL" 2
}

if ($Env -eq 'prod' -and $uri.Scheme -ne 'https') {
    Fail-ProdGate "Production URL must use HTTPS" "Use https://<domain>" 2
}

$baseUrl = "{0}://{1}" -f $uri.Scheme, $uri.Authority
Write-ProdGateHeader -Target $baseUrl -Environment $Env -StrictMode:$Strict.IsPresent

$allChecksPassed = $true

try {
    # =========================================================================
    # CHECK 1: GET / - Service Identity
    # =========================================================================
    $rootResponse = Invoke-ProdGateRequest -BaseUrl $baseUrl -Path '/' -Label 'Service Identity Check'

    # Check for Railway fallback
    if ($rootResponse.Headers -and (Test-RailwayFallbackHeader $rootResponse.Headers)) {
        Write-CheckResult -Label 'Service Identity' -Passed $false -Detail 'Railway fallback detected - domain not attached'
        Fail-ProdGate 'Railway fallback detected' 'Attach the domain to the dragonfly-api service in Railway'
    }

    # Check for HTTP errors
    if ($rootResponse.StatusCode -eq 0) {
        Write-CheckResult -Label 'Service Identity' -Passed $false -Detail "Connection failed: $($rootResponse.Content)"
        Fail-ProdGate 'Connection failed' 'Check URL and network connectivity'
    }

    if ($rootResponse.StatusCode -ge 400) {
        Write-CheckResult -Label 'Service Identity' -Passed $false -Detail "HTTP $($rootResponse.StatusCode)"
        Fail-ProdGate "Service returned HTTP $($rootResponse.StatusCode)" 'Check deployment status'
    }

    # Parse JSON response
    try {
        $rootJson = $rootResponse.Content | ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        Write-CheckResult -Label 'Service Identity' -Passed $false -Detail 'Response is not valid JSON'
        Fail-ProdGate 'Unable to parse JSON from /' 'Verify correct service is deployed'
    }

    # Verify service_name
    if ($rootJson.service_name -ne 'dragonfly-api') {
        Write-CheckResult -Label 'Service Identity' -Passed $false -Detail "service_name='$($rootJson.service_name)'"
        Fail-ProdGate "Wrong service: expected 'dragonfly-api', got '$($rootJson.service_name)'" 'Deploy dragonfly-api to this domain'
    }

    $identityDetail = "service_name=$($rootJson.service_name) sha=$($rootJson.sha_short) env=$($rootJson.env)"
    Write-CheckResult -Label 'Service Identity' -Passed $true -Detail $identityDetail

    # =========================================================================
    # CHECK 2: GET /health - Liveness
    # =========================================================================
    $healthResponse = Invoke-ProdGateRequest -BaseUrl $baseUrl -Path '/health' -Label 'Liveness Check'

    if ($healthResponse.StatusCode -eq 200) {
        Write-CheckResult -Label '/health (Liveness)' -Passed $true -Detail '200 OK'
    }
    else {
        Write-CheckResult -Label '/health (Liveness)' -Passed $false -Detail "HTTP $($healthResponse.StatusCode)"
        Fail-ProdGate "/health returned $($healthResponse.StatusCode)" 'Check API deployment and logs'
    }

    # =========================================================================
    # CHECK 3: GET /readyz - Readiness (DB Connected)
    # =========================================================================
    $readyResponse = Invoke-ProdGateRequest -BaseUrl $baseUrl -Path '/readyz' -Label 'Readiness Check'

    if ($readyResponse.StatusCode -eq 200) {
        Write-CheckResult -Label '/readyz (Readiness)' -Passed $true -Detail '200 OK - Database connected'
    }
    elseif ($readyResponse.StatusCode -eq 503) {
        try {
            $readyPayload = $readyResponse.Content | ConvertFrom-Json -ErrorAction Stop
            $reason = $readyPayload.reason
            $nextRetry = $readyPayload.next_retry_in_seconds
            $failures = $readyPayload.consecutive_failures
            $detail = "reason=$reason next_retry=${nextRetry}s failures=$failures"
        }
        catch {
            $detail = '503 Service Unavailable'
        }

        if ($Strict.IsPresent) {
            Write-CheckResult -Label '/readyz (Readiness)' -Passed $false -Detail $detail
            Fail-ProdGate '/readyz returned 503 (DB not ready)' 'Resolve database connectivity issues'
        }
        else {
            Write-Host "  ⚠️ /readyz (Readiness)" -ForegroundColor Yellow
            Write-Host "     $detail (non-strict mode)" -ForegroundColor Yellow
        }
    }
    else {
        Write-CheckResult -Label '/readyz (Readiness)' -Passed $false -Detail "HTTP $($readyResponse.StatusCode)"
        Fail-ProdGate "/readyz returned $($readyResponse.StatusCode)" 'Check API and database status'
    }

    # =========================================================================
    # CHECK 4: GET /whoami - Extended Identity
    # =========================================================================
    $whoamiResponse = Invoke-ProdGateRequest -BaseUrl $baseUrl -Path '/whoami' -Label 'Extended Identity Check'

    if ($whoamiResponse.StatusCode -eq 200) {
        try {
            $whoamiData = Parse-WhoAmIJson -Json $whoamiResponse.Content

            if ($whoamiData.Env -ne $Env) {
                Write-CheckResult -Label '/whoami (Environment)' -Passed $false -Detail "env='$($whoamiData.Env)' expected='$Env'"
                Fail-ProdGate "Environment mismatch: got '$($whoamiData.Env)', expected '$Env'" 'Deploy correct environment'
            }

            $whoamiDetail = "env=$($whoamiData.Env) sha=$($whoamiData.ShaShort) db_ready=$($whoamiData.DatabaseReady)"
            Write-CheckResult -Label '/whoami (Environment)' -Passed $true -Detail $whoamiDetail
        }
        catch {
            Write-CheckResult -Label '/whoami (Environment)' -Passed $false -Detail "Parse error: $_"
        }
    }
    else {
        Write-Host "  ⚠️ /whoami returned $($whoamiResponse.StatusCode)" -ForegroundColor Yellow
    }

    # =========================================================================
    # CHECK 5: Internal Database Probe
    # =========================================================================
    Write-Host ''
    Write-Host '→ Internal Database Probe' -ForegroundColor DarkCyan

    $probeExitCode = Invoke-PythonTool -DisplayName 'tools.probe_db' -Arguments @('-m', 'tools.probe_db', '--env', $Env, '--from-env')

    if ($probeExitCode -eq 0) {
        Write-CheckResult -Label 'Database Probe' -Passed $true -Detail 'Connection verified'
    }
    else {
        Write-CheckResult -Label 'Database Probe' -Passed $false -Detail "Exit code: $probeExitCode"
        $allChecksPassed = $false
        if ($Strict.IsPresent) {
            Fail-ProdGate 'Database probe failed' 'Check DATABASE_URL and Supabase status'
        }
        else {
            Write-Host "  ⚠️ Database probe failed (non-strict mode)" -ForegroundColor Yellow
        }
    }

    # =========================================================================
    # CHECK 6: Production Certifier
    # =========================================================================
    Write-Host ''
    Write-Host '→ Production Certifier' -ForegroundColor DarkCyan

    $certArgs = @('-m', 'tools.certify_prod', '--url', $baseUrl, '--env', $Env)
    if (-not $Strict.IsPresent) {
        $certArgs += '--no-fail-fast'
    }

    $certExitCode = Invoke-PythonTool -DisplayName 'tools.certify_prod' -Arguments $certArgs

    if ($certExitCode -eq 0) {
        Write-CheckResult -Label 'Production Certifier' -Passed $true -Detail 'All checks passed'
    }
    else {
        Write-CheckResult -Label 'Production Certifier' -Passed $false -Detail "Exit code: $certExitCode"
        $allChecksPassed = $false
        if ($Strict.IsPresent) {
            Fail-ProdGate 'Production certification failed' 'Review certify_prod output above'
        }
        else {
            Write-Host "  ⚠️ Certifier failed (non-strict mode)" -ForegroundColor Yellow
        }
    }

    # =========================================================================
    # FINAL VERDICT
    # =========================================================================
    Write-Host ''

    if ($allChecksPassed) {
        Write-GoForLaunch
        exit 0
    }
    else {
        Write-Abort -Message 'One or more checks failed' -Remediation 'Review warnings above and re-run with -Strict for hard enforcement'
        exit 1
    }
}
catch {
    Fail-ProdGate "Unexpected script error: $($_.Exception.Message)" 'Check script execution' 2
}
