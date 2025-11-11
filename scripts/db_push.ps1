param(
  [switch]$IncludeAll = $false
)

$SupabaseExe = "$env:LOCALAPPDATA\Programs\supabase\supabase.exe"

if (!(Test-Path $SupabaseExe)) {
  Write-Error "Supabase CLI not found at $SupabaseExe"
  exit 1
}

& $SupabaseExe migration list

if ($IncludeAll) {
  & $SupabaseExe db push --include-all
} else {
  & $SupabaseExe db push
}
