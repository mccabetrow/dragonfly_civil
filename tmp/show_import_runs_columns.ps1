$ErrorActionPreference = 'Stop'
$env:SUPABASE_MODE = 'dev'
$env:PYTHONPATH = "$PSScriptRoot\.."
python tmp/show_import_runs_columns.py
