[CmdletBinding()]
param(
    [ValidateSet('dev', 'prod')]
    [string]$SupabaseEnv = $env:SUPABASE_MODE
)

$ErrorActionPreference = 'Stop'

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptDir

# Load .env so connection strings are available
. "$scriptDir\load_env.ps1"

if (-not $SupabaseEnv) {
    $SupabaseEnv = if ($env:SUPABASE_MODE) { $env:SUPABASE_MODE } else { 'dev' }
}

if ($SupabaseEnv -notin @('dev', 'prod')) {
    Write-Error "Unsupported SUPABASE_MODE '$SupabaseEnv'. Use 'dev' or 'prod'."
    exit 1
}

$envSuffix = if ($SupabaseEnv -eq 'prod') { '_PROD' } else { '' }
$dbUrlVar = "SUPABASE_DB_URL$envSuffix"
$dbUrl = (Get-Item -Path "Env:$dbUrlVar" -ErrorAction SilentlyContinue)?.Value

if (-not $dbUrl) {
    Write-Error "Environment variable $dbUrlVar is not set. Ensure load_env.ps1 populated it."
    exit 1
}

$psqlArgs = @('-d', $dbUrl, '-c', 'SELECT version, name, inserted_at FROM supabase_migrations.schema_migrations ORDER BY version;')

Write-Host "[INFO] Querying Supabase migrations (env=$SupabaseEnv)" -ForegroundColor Cyan

try {
    $process = Start-Process -FilePath 'psql' -ArgumentList $psqlArgs -WorkingDirectory $repoRoot -NoNewWindow -PassThru -Wait
    if ($process.ExitCode -ne 0) {
        Write-Error "psql exited with code $($process.ExitCode)."
        exit $process.ExitCode
    }
}
catch {
    Write-Error "Failed to execute psql: $_"
    exit 1
}
***