[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$Url,

    [Parameter(Mandatory = $true)]
    [ValidateSet('prod', 'dev')]
    [string]$Env,

    [switch]$Strict
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$modulePath = Join-Path -Path $PSScriptRoot -ChildPath 'ProdGateHelpers.psm1'
if (-not (Test-Path $modulePath)) {
    Write-Error "ProdGate helpers not found at $modulePath"
    exit 2
}
Import-Module $modulePath -Force

function Write-ProdGateHeader {
    param(
        [string]$Target,
        [string]$Environment,
        [bool]$StrictMode
    )

    $line = '=' * 60
    Write-Host $line -ForegroundColor Cyan
    Write-Host " DRAGONFLY PROD GATE" -ForegroundColor Cyan
    Write-Host " Target: $Target" -ForegroundColor Cyan
    Write-Host " Environment: $Environment | Strict: $StrictMode" -ForegroundColor Cyan
    Write-Host $line -ForegroundColor Cyan
}

function Fail-ProdGate {
    param(
        [string]$Message,
        [string]$Remediation,
        [int]$ExitCode = 1
    )

    $line = '=' * 60
    Write-Host ''
    Write-Host $line -ForegroundColor Red
    Write-Host "❌ PROD GATE FAILURE" -ForegroundColor Red
    Write-Host "Reason: $Message" -ForegroundColor Red
    if ($Remediation) {
        Write-Host "Remediation: $Remediation" -ForegroundColor Yellow
    }
    Write-Host $line -ForegroundColor Red
    exit $ExitCode
}

function Invoke-ProdGateRequest {
    param(
        [string]$BaseUrl,
        [string]$Path,
        [string]$Label
    )

    $relative = if ($Path.StartsWith('/')) { $Path } else { "/$Path" }
    $uri = "$BaseUrl$relative"
    Write-Host "→ $Label ($uri)" -ForegroundColor DarkCyan
    $requestParams = @{
        Uri        = $uri
        Method     = 'Get'
        TimeoutSec = 15
        Headers    = @{ 'Accept' = 'application/json'; 'User-Agent' = 'prod-gate/1.0' }
    }
    try {
        if ($PSVersionTable.PSVersion.Major -ge 6) {
            return Invoke-WebRequest @requestParams -SkipHttpErrorCheck
        }
        else {
            return Invoke-WebRequest @requestParams -UseBasicParsing
        }
    }
    catch {
        Fail-ProdGate "Request to $uri failed" $_.Exception.Message
    }
}

function Invoke-PythonTool {
    param(
        [string]$DisplayName,
        [string[]]$Arguments
    )

    $workspaceRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
    try {
        $pythonExe = Get-ProdGatePythonPath -WorkspaceRoot $workspaceRoot
    }
    catch {
        Fail-ProdGate "Unable to locate python executable" $_.Exception.Message 2
    }

    Write-Host "→ $DisplayName" -ForegroundColor DarkCyan
    Write-Host "   Command: $pythonExe $($Arguments -join ' ')"
    $output = & $pythonExe @Arguments 2>&1
    $exitCode = $LASTEXITCODE
    if ($output) {
        $output | ForEach-Object { Write-Host "   $_" }
    }
    if ($exitCode -ne 0) {
        Fail-ProdGate "$DisplayName failed" "Inspect output above for remediation"
    }
}

try {
    $uri = [Uri]$Url
}
catch {
    Fail-ProdGate "Invalid Url parameter" "Provide a valid https:// Railway domain" 2
}

if ($uri.Scheme -ne 'https') {
    Fail-ProdGate "URL must use HTTPS" "Use https://<railway-domain>" 2
}

$baseUrl = "{0}://{1}" -f $uri.Scheme, $uri.Authority
Write-ProdGateHeader -Target $baseUrl -Environment $Env -StrictMode:$Strict.IsPresent

# Step 1: GET /
$rootResponse = Invoke-ProdGateRequest -BaseUrl $baseUrl -Path '/' -Label 'Service identity'
if (Test-RailwayFallbackHeader $rootResponse.Headers) {
    Fail-ProdGate "Railway fallback detected" "Attach the domain to the dragonfly-api service"
}

try {
    $rootJson = $rootResponse.Content | ConvertFrom-Json -ErrorAction Stop
}
catch {
    Fail-ProdGate "Unable to parse JSON from /" $_.Exception.Message
}

if ($rootJson.service_name -ne 'dragonfly-api') {
    Fail-ProdGate "Unexpected service_name '$($rootJson.service_name)'" "Deploy dragonfly-api to this domain"
}
Write-Host "   service_name: $($rootJson.service_name)" -ForegroundColor Green

# Step 2: /health
$healthResponse = Invoke-ProdGateRequest -BaseUrl $baseUrl -Path '/health' -Label 'Health check'
if ($healthResponse.StatusCode -ne 200) {
    Fail-ProdGate "/health returned $($healthResponse.StatusCode)" "Check API deployment and logs"
}
$shaHeader = $healthResponse.Headers['X-Dragonfly-SHA-Short']
$envHeader = $healthResponse.Headers['X-Dragonfly-Env']
if (-not $shaHeader -or -not $envHeader) {
    Fail-ProdGate "Missing X-Dragonfly-* headers on /health" "Ensure release metadata headers are configured"
}
Write-Host "   X-Dragonfly-SHA-Short: $shaHeader" -ForegroundColor Green
Write-Host "   X-Dragonfly-Env: $envHeader" -ForegroundColor Green

# Step 3: /readyz
$readyResponse = Invoke-ProdGateRequest -BaseUrl $baseUrl -Path '/readyz' -Label 'Readiness check'
if ($readyResponse.StatusCode -eq 200) {
    Write-Host "   /readyz returned 200" -ForegroundColor Green
}
elseif (-not $Strict.IsPresent -and $readyResponse.StatusCode -eq 503) {
    Write-Warning "/readyz returned 503 but continuing because -Strict was not provided"
}
else {
    Fail-ProdGate "/readyz returned $($readyResponse.StatusCode)" "Resolve readiness blockers or rerun when healthy"
}

# Step 4: /whoami
$whoamiResponse = Invoke-ProdGateRequest -BaseUrl $baseUrl -Path '/whoami' -Label 'Identity check'
try {
    $whoamiData = Parse-WhoAmIJson -Json $whoamiResponse.Content
}
catch {
    Fail-ProdGate "Unable to parse /whoami" $_.Exception.Message
}

Write-Host "   database_ready: $($whoamiData.DatabaseReady)"
Write-Host "   dsn_identity: $(Mask-SensitiveValue -Value $whoamiData.DsnIdentity)"
if (-not $whoamiData.DatabaseReady) {
    Fail-ProdGate "Database not ready according to /whoami" "Investigate Supabase connectivity"
}

# Step 5: python -m tools.probe_db --env prod
if (-not $env:DATABASE_URL) {
    Write-Warning "DATABASE_URL not set; tools.probe_db will rely on defaults"
}
else {
    Write-Host "   DATABASE_URL: $(Mask-SensitiveValue -Value $env:DATABASE_URL)"
}
Invoke-PythonTool -DisplayName 'tools.probe_db' -Arguments @('-m', 'tools.probe_db', '--env', 'prod')

# Step 6: python -m tools.certify_prod
Invoke-PythonTool -DisplayName 'tools.certify_prod' -Arguments @('-m', 'tools.certify_prod', '--url', $baseUrl, '--env', $Env)

Write-Host '' -ForegroundColor Green
Write-Host ('=' * 60) -ForegroundColor Green
Write-Host "✅ PROD GATE PASS" -ForegroundColor Green
Write-Host "All gates satisfied. Safe to proceed." -ForegroundColor Green
Write-Host ('=' * 60) -ForegroundColor Green
exit 0
