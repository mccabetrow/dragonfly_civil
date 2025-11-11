param()

$ErrorActionPreference = 'Stop'

. "$PSScriptRoot\load_env.ps1" | Out-Null

if (-not $env:SUPABASE_URL -or -not $env:SUPABASE_SERVICE_ROLE_KEY) {
    Write-Error "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set. Run scripts\load_env.ps1 first."
    exit 1
}

$base = $env:SUPABASE_URL.TrimEnd('/')
$anon = $env:SUPABASE_ANON_KEY
$service = $env:SUPABASE_SERVICE_ROLE_KEY

$publicHeaders = @{
    apikey = $service
    Authorization = "Bearer $service"
    Accept = 'application/json'
}

function Invoke-Check {
    param(
        [Parameter(Mandatory)][string]$Description,
        [Parameter(Mandatory)][scriptblock]$Probe
    )

    try {
        & $Probe
        Write-Host "[OK] $Description"
        return $true
    }
    catch {
        Write-Error "[FAIL] $Description`n$($_.Exception.Message)"
        return $false
    }
}

$allPassed = $true

$allPassed = Invoke-Check -Description 'v_cases_with_org reachable' -Probe {
    Invoke-RestMethod -Method Get -Uri "$base/rest/v1/v_cases_with_org?select=case_id&limit=1" -Headers $publicHeaders | Out-Null
} -and $allPassed

$idempotentHeaders = @{
    apikey = $anon
    Authorization = "Bearer $anon"
    'Content-Type' = 'application/json'
    Prefer = 'return=representation'
    Accept = 'application/json'
}

$payload = [pscustomobject]@{
    payload = [pscustomobject]@{
        case = [pscustomobject]@{
            case_number = 'SMOKE-PREFLIGHT-0001'
            source = 'preflight'
            title = 'Preflight Check'
            court = 'NYC Civil Court'
        }
        entities = @(
            [pscustomobject]@{ role = 'plaintiff'; name_full = 'Preflight Alpha' },
            [pscustomobject]@{ role = 'defendant'; name_full = 'Preflight Beta' }
        )
    }
} | ConvertTo-Json -Depth 5

$allPassed = Invoke-Check -Description 'insert_or_get_case_with_entities idempotent RPC' -Probe {
    Invoke-RestMethod -Method Post -Uri "$base/rest/v1/rpc/insert_or_get_case_with_entities" -Headers $idempotentHeaders -Body $payload | Out-Null
} -and $allPassed

if ($allPassed) {
    Write-Host 'Preflight checks passed.'
    exit 0
}
else {
    Write-Error 'Preflight checks failed.'
    exit 1
}
