# Dragonfly Phase 1 Operations Runbook

## 1. Daily Start Check
- Run `python -m tools.doctor` inside the project virtualenv to verify environment health.
- Run `python -m tools.smoke` to confirm Supabase connectivity and queue availability.
- Open the dashboards (queue depth, case funnel, enforcement SLA) to make sure metrics are updating.

## 2. If the Queues Are Backing Up
- Review worker logs for errors or long-running jobs (tail the logs in your process manager or terminal).
- Restart the worker service:
  - Development: `python -m workers.runner`
  - Production: use the appropriate systemd or PM2 command noted in your deployment checklist.
- After restart, watch the queue depth dashboard to ensure counts begin to drop.

## 3. If a Case Is Missing
- Search by `case_number` in Supabase (Supabase Studio → public → judgments).
- Check `etl.runs` and `etl.events` tables for entries matching that `case_number` to see ingestion history and any errors.
- Re-enqueue the case via a SQL insert into the queue RPC or run the dedicated Python helper script provided for replays.
- Confirm the case appears in the dashboards and the watcher/collector logs.

## 4. Reprocessing a CSV
- Locate the relevant `manifest.jsonl` entry and remove the line containing the file hash you need to replay.
- Place the CSV back into the `data_in` folder (or the configured ingestion drop location).
- Monitor the collector logs or dashboards to confirm the file is reprocessed and new cases appear.
- Re-run smoke checks if needed to verify downstream processing.
