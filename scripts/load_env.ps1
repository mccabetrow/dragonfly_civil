Param(
    [string]$EnvPath = $(Join-Path -Path (Join-Path -Path $PSScriptRoot -ChildPath '..') -ChildPath '.env')
)

Write-Host "Loading environment variables from $EnvPath"

if (-not (Test-Path -LiteralPath $EnvPath)) {
    Write-Host "  .env file not found" -ForegroundColor Yellow
    return
}

Get-Content -Path $EnvPath | ForEach-Object {
    if ($_ -match '^\s*#') { return }
    if ($_ -match '^\s*$') { return }

    $name, $value = $_ -split('=', 2)
    $name  = $name.Trim()
    $value = $value.Trim()

    if (-not [string]::IsNullOrWhiteSpace($name)) {
        Set-Item -Path "Env:$name" -Value $value
        $isSensitive = $name -match '^SUPABASE_DB_URL' -or $name -match 'PASSWORD'
        $displayValue = if ($isSensitive) { '***' } else { $value }
        Write-Host "  $name=$displayValue"
    }
}

Write-Host "Done loading .env"
