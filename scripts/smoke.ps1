param(
	[string]$CaseId
)

$ErrorActionPreference = 'Stop'

Get-Content .env | ForEach-Object {
	if ($_ -match '^\s*#' -or [string]::IsNullOrWhiteSpace($_)) { return }
	$kv = $_ -split '=', 2
	if ($kv.Length -eq 2) {
		$name = $kv[0].Trim()
		$val = $kv[1].Trim()
		setx $name $val | Out-Null
		Set-Item -Path "Env:$name" -Value $val | Out-Null
	}
}

$BASE = $env:SUPABASE_URL
$KEY  = $env:SUPABASE_SERVICE_ROLE_KEY
if (-not $BASE -or -not $KEY) {
	Write-Error "Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY in environment."
}

$casesUrl = "$BASE/rest/v1/v_cases_with_org?select=case_id,case_number,source,created_at&order=created_at.desc&limit=3"

try {
	$casesResponse = Invoke-WebRequest -Uri $casesUrl -Headers @{ apikey=$KEY; Authorization="Bearer $KEY"; Accept="application/json" }
	Write-Host "Latest cases:" -ForegroundColor Cyan
	Write-Host $casesResponse.Content
} catch {
	if ($_.Exception.Response -and $_.Exception.Response.GetResponseStream()) {
		$reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
		$json = $reader.ReadToEnd()
		Write-Error "Case request failed: $($_.Exception.Response.StatusDescription)`n$json"
	} else {
		throw
	}
}

if ($CaseId) {
	$entitiesUrl = "$BASE/rest/v1/v_entities_simple?case_id=eq.$CaseId&select=entity_id,role,name_full,created_at&order=created_at.asc"
	try {
		$entitiesResponse = Invoke-WebRequest -Uri $entitiesUrl -Headers @{ apikey=$KEY; Authorization="Bearer $KEY"; Accept="application/json" }
		$content = $entitiesResponse.Content
		if (-not $content -or $content -eq "[]") {
			Write-Host "No entities found for case_id ${CaseId}" -ForegroundColor Yellow
		} else {
			Write-Host "Entities for case_id ${CaseId}:" -ForegroundColor Cyan
			Write-Host $content
		}
	} catch {
		if ($_.Exception.Response -and $_.Exception.Response.GetResponseStream()) {
			$reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
			$json = $reader.ReadToEnd()
			Write-Error "Entity request failed: $($_.Exception.Response.StatusDescription)`n$json"
		} else {
			throw
		}
	}
}
