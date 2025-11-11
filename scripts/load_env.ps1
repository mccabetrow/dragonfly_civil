param(
  [string]$EnvFile = ".env"
)

if (!(Test-Path $EnvFile)) {
  Write-Error "No .env found at $EnvFile"
  exit 1
}

Get-Content $EnvFile | ForEach-Object {
  if ($_ -match '^\s*#') { return }
  if ($_ -match '^\s*$') { return }
  if ($_ -match '^\s*([^=]+)\s*=\s*(.*)\s*$') {
    $key = $matches[1].Trim()
    $val = $matches[2].Trim().Trim("'`"").Trim()
    if ($val -match '^(.*?)(\s+#.*)$') { $val = $matches[1].Trim() }
    Set-Item -Path "Env:$key" -Value $val
  }
}

Write-Host "Loaded env: SUPABASE_PROJECT_REF=$($env:SUPABASE_PROJECT_REF)"
Write-Host "Loaded env: SUPABASE_SERVICE_ROLE_KEY (length)=$($env:SUPABASE_SERVICE_ROLE_KEY.Length)"
