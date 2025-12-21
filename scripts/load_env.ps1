<#
.SYNOPSIS
    Load environment variables from an env file into the current session.

.DESCRIPTION
    ONE FILE, ONE ENVIRONMENT PATTERN:
    - Default: loads .env.dev
    - Use -Mode prod to load .env.prod
    - Use -EnvPath for custom file location

.PARAMETER Mode
    Environment mode: 'dev' or 'prod'. Determines which file to load.

.PARAMETER EnvPath
    Override the env file path entirely. Takes precedence over -Mode.

.EXAMPLE
    .\load_env.ps1                    # loads .env.dev
    .\load_env.ps1 -Mode prod         # loads .env.prod
    .\load_env.ps1 -EnvPath .env.local
#>
Param(
    [ValidateSet('dev', 'prod')]
    [string]$Mode = 'dev',

    [string]$EnvPath
)

# Resolve the env file path
$RepoRoot = Join-Path -Path $PSScriptRoot -ChildPath '..'

if ([string]::IsNullOrWhiteSpace($EnvPath)) {
    $EnvPath = Join-Path -Path $RepoRoot -ChildPath ".env.$Mode"
}

Write-Host "Loading environment from: $EnvPath" -ForegroundColor Cyan

if (-not (Test-Path -LiteralPath $EnvPath)) {
    Write-Host "  ⚠ File not found: $EnvPath" -ForegroundColor Yellow
    Write-Host "  Create .env.dev or .env.prod from .env.example" -ForegroundColor Gray
    return
}

# Also set ENV_FILE so Python config picks up the same file
Set-Item -Path "Env:ENV_FILE" -Value $EnvPath
Write-Host "  ENV_FILE=$EnvPath"

$loadedCount = 0
Get-Content -Path $EnvPath | ForEach-Object {
    if ($_ -match '^\s*#') { return }
    if ($_ -match '^\s*$') { return }

    $name, $value = $_ -split ('=', 2)
    $name = $name.Trim()
    $value = $value.Trim()

    if (-not [string]::IsNullOrWhiteSpace($name)) {
        Set-Item -Path "Env:$name" -Value $value
        $script:loadedCount++
        $isSensitive = $name -match 'KEY|PASSWORD|SECRET|TOKEN' -or $name -match '^SUPABASE_DB_URL'
        $displayValue = if ($isSensitive) { '***' } else { $value }
        Write-Host "  $name=$displayValue"
    }
}

# Canonical Names Only: Remove deprecated env vars so Python never sees them
# These legacy variables may leak through parent processes or IDE settings
Remove-Item Env:\SUPABASE_DB_URL_DEV -ErrorAction SilentlyContinue
Remove-Item Env:\SUPABASE_DB_URL_PROD -ErrorAction SilentlyContinue

Write-Host "[OK] Loaded $loadedCount variables from .env.$Mode" -ForegroundColor Green
