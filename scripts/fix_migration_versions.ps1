$py = "$PSScriptRoot\..\venv\Scripts\python.exe"
if (!(Test-Path $py)) {
  $py = "python"
}
& $py scripts\fix_migration_versions.py
