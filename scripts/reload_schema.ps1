Param()

$ErrorActionPreference = 'Stop'

. "$PSScriptRoot\load_env.ps1"

$base = $env:SUPABASE_URL
$key = $env:SUPABASE_SERVICE_ROLE_KEY

if (-not $base -or -not $key) {
    throw 'Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY'
}

$uri = $base.TrimEnd('/') + '/rest/v1/rpc/pgrst_reload'
$headers = @{ apikey = $key; Authorization = "Bearer $key" }

Invoke-RestMethod -Method Post -Uri $uri -Headers $headers | Out-Null
Write-Host 'PostgREST reload requested.'
