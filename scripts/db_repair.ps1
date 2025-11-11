$SupabaseExe = "$env:LOCALAPPDATA\Programs\supabase\supabase.exe"

& $SupabaseExe migration list

try { & $SupabaseExe migration repair --status applied 0001 } catch {}
try { & $SupabaseExe migration repair --status applied 0002 } catch {}
try { & $SupabaseExe migration repair --status applied 0003 } catch {}

& $SupabaseExe migration list
