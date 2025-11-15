# Dragonfly Console — Quick Runbook for Dad

> **Note:** I’ll handle all setup ahead of time. Use these steps just to press go during a walkthrough.

## Ingest a new Simplicity export
Drop the latest CSV into the `data_in` folder, then run the ingest helper to load it into Supabase.

```powershell
Set-Location 'C:\Users\mccab\dragonfly_civil'
C:\Users\mccab\dragonfly_civil\.venv\Scripts\python.exe -m etl.src.collector_v1 --composite
```

## Run system health checks
Confirm the database, queues, and REST endpoints are responding before you demo.

```powershell
Set-Location 'C:\Users\mccab\dragonfly_civil'
C:\Users\mccab\dragonfly_civil\.venv\Scripts\python.exe -m tools.doctor
```

## Open the dashboard
Start the web dashboard so we can click through the tiers and case drawers live.

```powershell
Set-Location 'C:\Users\mccab\dragonfly_civil\dragonfly-dashboard'
npm run dev
```
