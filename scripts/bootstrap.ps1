Param(
    [ValidateSet('full','link','push','reload','smoke')]
    [string]$Mode = 'full'
)

$ErrorActionPreference = 'Stop'

. "$PSScriptRoot\pwsh_helpers.ps1"

$activate = Join-Path $PSScriptRoot "..\.venv\Scripts\Activate.ps1"
if (Test-Path $activate) {
    & $activate
}

Import-EnvFile

function Invoke-DbPush {
    supabase db push --yes --dns-resolver https --db-url "$env:SUPABASE_DB_URL"
}

switch ($Mode) {
    'link' {
        supabase link --project-ref ejiddanxtqcleyswqvkc
        break
    }
    'push' {
        Invoke-DbPush
        break
    }
    'reload' {
        Invoke-PostgrestReload
        break
    }
    'smoke' {
        Invoke-Smoke
        break
    }
    default {
        Invoke-DbPush
        Invoke-PostgrestReload
        Invoke-Smoke
    }
}

Write-Host "BOOTSTRAP OK"
