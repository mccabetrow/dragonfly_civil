function Import-EnvFile {
  param([string]$Path = ".env")
  if (!(Test-Path $Path)) { throw ".env not found at $Path" }
  Get-Content $Path | ForEach-Object {
    if ($_ -match '^\s*#' -or [string]::IsNullOrWhiteSpace($_)) { return }
    $kv = $_ -split '=',2
    if ($kv.Length -eq 2) {
      $name = $kv[0].Trim()
      $val = $kv[1].Trim()
      Set-Item -Path "Env:$name" -Value $val
    }
  }
  Write-Host "Loaded env: SUPABASE_URL=$($env:SUPABASE_URL)"
}

function Invoke-PostgrestReload {
  if (-not $env:SUPABASE_URL -or -not $env:SUPABASE_SERVICE_ROLE_KEY) {
    throw "Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY"
  }
  $uri = ($env:SUPABASE_URL.TrimEnd('/')) + "/rest/v1/rpc/pgrst_reload"
  $headers = @{ apikey = $env:SUPABASE_SERVICE_ROLE_KEY; Authorization = "Bearer $($env:SUPABASE_SERVICE_ROLE_KEY)" }
  Invoke-RestMethod -Method Post -Uri $uri -Headers $headers | Out-Null
  Write-Host "PostgREST reload requested."
}

function Invoke-Smoke {
  param([string]$CaseId)
  if (-not $env:SUPABASE_URL -or -not $env:SUPABASE_SERVICE_ROLE_KEY) {
    throw "Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY"
  }
  $base = $env:SUPABASE_URL.TrimEnd('/')
  $headers = @{ apikey = $env:SUPABASE_SERVICE_ROLE_KEY; Authorization = "Bearer $($env:SUPABASE_SERVICE_ROLE_KEY)" }

  $u = "$base/rest/v1/v_cases_with_org?select=case_id,case_number,source,created_at&order=created_at.desc&limit=3"
  try {
    $resp = Invoke-WebRequest -Uri $u -Headers $headers -UseBasicParsing
    Write-Host "== Latest cases =="
    $resp.Content
  } catch {
    if ($_.Exception.Response) {
      $r = New-Object IO.StreamReader($_.Exception.Response.GetResponseStream())
      Write-Error $r.ReadToEnd()
    } else { throw }
  }

  if ($CaseId) {
    $u2 = "$base/rest/v1/v_entities_simple?case_id=eq.$CaseId&select=entity_id,role,name_full,created_at&order=created_at.asc"
    try {
      $resp2 = Invoke-WebRequest -Uri $u2 -Headers $headers -UseBasicParsing
      Write-Host "== Entities for $CaseId =="
      $resp2.Content
    } catch {
      if ($_.Exception.Response) {
        $r2 = New-Object IO.StreamReader($_.Exception.Response.GetResponseStream())
        Write-Error $r2.ReadToEnd()
      } else { throw }
    }
  }
}
