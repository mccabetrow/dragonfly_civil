param(
    [string]$EnvFile = "$PSScriptRoot/../.env"
)

if (-not (Test-Path -LiteralPath $EnvFile)) {
    Write-Host "No .env file found at $EnvFile" -ForegroundColor Yellow
    return
}

Write-Host "Loading environment variables from $EnvFile" -ForegroundColor Cyan

Get-Content -Path $EnvFile | ForEach-Object {
    if (-not $_ -or $_.TrimStart().StartsWith('#')) { return }
    $parts = $_ -split '=', 2
    if ($parts.Count -ne 2) { return }
    $key = $parts[0].Trim()
    $value = $parts[1].Trim()
    $value = $value.Trim("'")
    $value = $value.Trim('"')
    [Environment]::SetEnvironmentVariable($key, $value)
    if ($key -match 'KEY|SECRET|PASS|TOKEN') {
        Write-Host "  $key=***" -ForegroundColor Gray
    } else {
        Write-Host "  $key=$value" -ForegroundColor Gray
    }
}
