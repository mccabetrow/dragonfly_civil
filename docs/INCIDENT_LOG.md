# Dragonfly Civil — Incident Log

> **Anti-Fragility Principle:** Every incident makes the system stronger.  
> See [RUNBOOK_INCIDENT.md](RUNBOOK_INCIDENT.md) for the response protocol.

---

## Active Incidents

| ID  | Date | Title                 | Severity | Status | Owner | Link |
| --- | ---- | --------------------- | -------- | ------ | ----- | ---- |
| —   | —    | _No active incidents_ | —        | —      | —     | —    |

---

## Resolved Incidents (2025)

| ID            | Date       | Title                                      | Severity | Status   | Owner       | Link                                                                            |
| ------------- | ---------- | ------------------------------------------ | -------- | -------- | ----------- | ------------------------------------------------------------------------------- |
| 2025-12-22-01 | 2025-12-22 | Postgres URI Leak in GitHub                | SEV-1    | Resolved | @mccabetrow | [Report](incidents/2025-12-22_01_postgres_uri_leak_github.md)                   |
| 2025-12-21-01 | 2025-12-21 | Production Smoke Test Failed on CSV Upload | SEV-2    | Resolved | @mccabetrow | [Report](incidents/2025-12-21_01_production_smoke_test_failed_on_csv_upload.md) |

---

## Statistics

| Metric                         | Value |
| ------------------------------ | ----- |
| Total Incidents (2025)         | 2     |
| SEV-1 Count                    | 1     |
| SEV-2 Count                    | 1     |
| SEV-3 Count                    | 0     |
| Mean Time to Resolution (MTTR) | ~1h   |

---

## How to Log a New Incident

```bash
# Use the scaffolder to create a new incident report
python -m tools.new_incident "Brief description of what happened"
```

This will:

1. Generate a unique incident ID
2. Create a report from the template
3. Place it in `docs/incidents/`

**Remember:** Update this log when the incident is resolved!
