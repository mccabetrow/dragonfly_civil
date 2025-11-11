@echo off
setlocal

pushd "%~dp0.." || exit /b 1

powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0load_env.ps1"
if errorlevel 1 goto :err

powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0sanity_probe.ps1"
if errorlevel 1 goto :err

call .\.venv\Scripts\python.exe -m tools.doctor
if errorlevel 1 goto :err

call .\.venv\Scripts\python.exe -m src.workers.enrich_bundle
if errorlevel 1 goto :err

call .\.venv\Scripts\python.exe -m src.workers.score_cases --limit 5
if errorlevel 1 goto :err

call .\.venv\Scripts\python.exe -m pytest -q
if errorlevel 1 goto :err

popd
exit /b 0

:err
set ERR=%errorlevel%
popd
exit /b %ERR%
