# n8n Alerts Workflow

This note explains how to pull alert data from the Dragonfly stack and forward it to SMS/Slack via n8n. The workflow relies on `python -m tools.alerts_export` and its HTTP surface.

## Alert Data

`tools/alerts_export.py` produces two key signals:

1. **Failed imports** – any `public.import_runs` rows that finished with `status = 'failed'` in the past 24 hours.
2. **Stale call tasks** – number of open `plaintiff_tasks` records with `kind = 'call'` whose `due_at` (or `created_at` fallback) is older than the configured threshold.

Example CLI run:

```powershell
python -m tools.alerts_export export --json --stale-days 3
```

Example HTTP call (when served via `uvicorn tools.alerts_export:app`):

```http
GET /alerts?stale_days=3
```

The response contains:

```json
{
  "env": "dev",
  "generated_at": "2025-11-18T21:18:00Z",
  "failed_imports": [
    {
      "id": "f3b0376a-...",
      "import_kind": "simplicity_plaintiffs",
      "source_system": "simplicity",
      "status": "failed",
      "file_name": "simplicity_sample.csv",
      "started_at": "2025-11-18T18:03:11Z",
      "finished_at": "2025-11-18T18:05:52Z",
      "error_count": 42,
      "batch_name": "daily_nj"
    }
  ],
  "open_call_tasks": {
    "stale_days_threshold": 3,
    "reference_timestamp": "2025-11-15T21:18:00Z",
    "stale_count": 5
  }
}
```

## n8n Workflow Pattern

1. **HTTP Request Node** (or **Execute Command**):
   - Option A: run the CLI directly with `python -m tools.alerts_export export --json`.
   - Option B: call the FastAPI endpoint exposed by `uvicorn tools.alerts_export:app --port 8082`.
2. **IF Node** examines `failed_imports` length and `open_call_tasks.stale_count`.
3. **Set / Code Node** builds a friendly message.
4. **Slack** (or **SMS/Twilio**) node posts the alert.

### Sample Slack Message Template

```
🚨 Dragonfly Alerts ({{ $json.env }})
Failed imports: {{ $json.failed_imports.length }}
Stale call tasks (>{{ $json.open_call_tasks.stale_days_threshold }}d): {{ $json.open_call_tasks.stale_count }}
Details: {{ $json.failed_imports.map(f => `${f.import_kind} batch ${f.batch_name || '-'}` ).join(', ') || 'n/a' }}
```

## Hosting Notes

- The HTTP API uses FastAPI; run with:

```powershell
uvicorn tools.alerts_export:app --host 0.0.0.0 --port 8082
```

- Ensure `SUPABASE_MODE`, `SUPABASE_DB_URL_*`, and service-role env vars are loaded (`./scripts/load_env.ps1`).
- For automation, consider a small container/VM that continuously serves the endpoint; n8n polls it every few minutes.

## Troubleshooting

- If the request fails, check connectivity to Supabase and confirm credentials are available to the process.
- Use `--pretty` with the CLI to inspect raw JSON while debugging.
- After schema updates, re-run `python -m tools.doctor_all --env dev` to ensure the alert queries still work.

## `notify_ops` payloads from automation

- **Call Queue Sync** uses `idempotency_key = call_sync_alert:<task_id>` and includes `plaintiff_id`, `task_id`, the RPC error, and any queue payload so ops can re-run `queue_job` or close the task manually.
- **Call Task Planner** emits `call_planner_alert:<plaintiff_id>` with `plaintiff_id`, `case_number`, and the response from `queue_job`. Treat a duplicate idempotency key as already handled.
- **Enforcement Escalation** has two alert families: `enforcement_alert:<case_id>` when `set_enforcement_stage` fails, and `enforcement_event_alert:<case_id>` when `log_enforcement_event` fails. Both include the full Supabase error JSON.
- All alerts land in the `notify_ops` queue; workers forward them to Slack/email. Searching for the idempotency key in `queue_jobs` shows whether the alert already fired.
