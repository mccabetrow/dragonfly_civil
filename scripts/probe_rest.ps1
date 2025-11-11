. "$PSScriptRoot\load_env.ps1" | Out-Null
$BASE="https://$($env:SUPABASE_PROJECT_REF).supabase.co"
$KEY=$env:SUPABASE_SERVICE_ROLE_KEY
$H=@{apikey=$KEY; Authorization="Bearer $KEY"; Accept="application/json"; 'Content-Profile'='public'; 'Accept-Profile'='public'}
$r = Invoke-WebRequest -UseBasicParsing -Headers $H -Uri "$BASE/rest/v1/v_cases?select=case_id&limit=1" -Method GET
"StatusCode: $($r.StatusCode)`nBody: $($r.Content)"
