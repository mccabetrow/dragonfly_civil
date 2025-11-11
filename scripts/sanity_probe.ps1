Param()

. "$PSScriptRoot\load_env.ps1" | Out-Null

$BASE = "https://$($env:SUPABASE_PROJECT_REF).supabase.co"
$KEY  = $env:SUPABASE_SERVICE_ROLE_KEY
$H = @{
	apikey           = $KEY
	Authorization    = "Bearer $KEY"
	Accept           = "application/json"
	'Content-Profile'= 'public'
	'Accept-Profile' = 'public'
}
$uri = "$BASE/rest/v1/v_cases?select=case_id&limit=1"

try {
	$r = Invoke-RestMethod -UseBasicParsing -Headers $H -Uri $uri -Method GET
	Write-Host "OK:" ($r | ConvertTo-Json -Compress)
	exit 0
} catch {
	Write-Host "ERR:" $_.Exception.Message
	if ($_.Exception.Response -and $_.Exception.Response.GetResponseStream()) {
		$reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
		Write-Host ($reader.ReadToEnd())
	}
	exit 1
}
