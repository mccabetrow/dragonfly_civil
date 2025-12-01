# AI Coding Guidelines

This document captures the conventions Copilot, Cursor, and other assistants should follow when generating patches for Dragonfly Civil.

---

## Naming conventions

- **Python**: `snake_case` for variables, functions, and modules; `CapWords` for classes. Private helpers start with an underscore only when they truly should not be imported.
- **TypeScript/React**: `PascalCase` for components; `camelCase` for hooks, variables, and functions. Filenames mirror exported symbols (`PlaintiffFunnelPanel.tsx`).
- **Frontend architecture**: `dragonfly-dashboard/src/App.tsx` wires layout + providers, while `src/routes/navigation.ts` defines route groups. Keep hooks in `src/hooks/` aligned with `metricsState.ts` + `MetricsHookResult<T>` and honor demo safety via `demoSafeSelect`, `MetricsGate`, and `DemoLockCard`.
- **SQL**: `snake_case` for tables, columns, views, functions; avoid uppercase keywords unless required by legacy objects.
- **Migrations**: Timestamp prefix (`0081_`) followed by a clear slug (`enforcement_stage_rpc.sql`). Temporary drafts use `_temp.sql` until finalized.
- **Tasks/Jobs**: Use verbs that describe the action (`Doctor All`, `New Migration`).

---

## Health checks

- Local and CI readiness mirror `scripts/preflight_dev.ps1` / `scripts/preflight_prod.ps1` (db push checks → config_check → security_audit → doctor_all → pytest).
- Demo walkthroughs should rely on `scripts/demo_reset_and_smoke.ps1` to seed Supabase + refresh PostgREST before UI exercises.
- Frontend releases must finish with `cd dragonfly-dashboard && npm run build`.

---

## Migration patterns

- All schema changes live under `supabase/db/migrations/` with timestamped filenames.
- Migrations must be idempotent: `CREATE TABLE IF NOT EXISTS`, `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`.
- Grant statements should cover `anon`, `authenticated`, and `service_role` explicitly as needed.
- Include `-- migrate:up` / `-- migrate:down` sections when scripts are complex; otherwise document intent at the top.
- Avoid dropping objects unless the user explicitly requests it; prefer additive changes.
- When defining functions or views, use `CREATE OR REPLACE` and include relevant comments.

---

## RPC rules

- All RPC functions go in migrations with `CREATE OR REPLACE FUNCTION` and explicit parameter types.
- Use `SECURITY DEFINER` when the RPC must bypass row-level security; otherwise default to invoker.
- Validate inputs defensively (check for nulls, whitelist enumerated values).
- Return typed records (e.g., `RETURNS public.judgments`) or well-defined composite types; never return `record` without structure.
- Handle no-op updates gracefully (e.g., return early if the data is unchanged).
- Always follow with `REVOKE ALL` and `GRANT EXECUTE` statements for `anon`, `authenticated`, and `service_role` if appropriate.

---

## Testing patterns

- Tests live under `tests/` and use `pytest`.
- Prefer fixtures for shared data; keep tests deterministic and offline.
- Assert exact error messages only when they are part of the contract; otherwise match substrings.
- Cover both happy-path and edge cases (invalid inputs, permissions, missing data).
- Use realistic sample data consistent with ETL outputs and Supabase schemas.

---

## Logging style

- Use structured, succinct log messages; include context but avoid secrets (`host`, `count`, `env`).
- Python logging uses `logger.info/debug/warning/error`; no bare `print` in production code.
- Console output in scripts should start with a prefix (`[doctor_all]`, `[smoke_plaintiffs]`) to aid triage.
- For React/TypeScript, rely on `console.error` sparingly and only for unexpected states.

---

## Error-handling style

- Fail fast with informative messages; raise custom exceptions (e.g., `DoctorCheckError`) where the caller can surface details.
- Normalize errors before returning them to the UI or CLI so they’re user-friendly.
- For retries or fallbacks, log the attempt and reason for retry; cap retries to avoid loops.
- In SQL/PLpgSQL, use `RAISE EXCEPTION` with clear descriptions and include input values where safe.

---

## SQL style

- Prefer lowercase keywords (`select`, `from`, `where`) and align clauses vertically for readability.
- Use explicit `join` syntax; avoid implicit joins.
- Alias tables with short, descriptive letters (`p` for plaintiffs, `j` for judgments).
- Cast values explicitly (`::bigint`, `::numeric`) when coercing types.
- Wrap `now()` with `timezone('utc', now())` when storing timestamps to keep them normalized.
- Include comments for non-obvious logic, especially around security policies or stage transitions.

---

## Line-of-business domains

- **Judgments**: Core court judgments, amounts, case numbers, and enforcement stages tracked in `public.judgments` and derived views.
- **Plaintiffs**: Entities bringing judgments; includes contact info, status history, and pipeline metrics (`public.plaintiffs`, `public.plaintiff_contacts`).
- **Enforcement**: Post-judgment actions (levies, payment plans) represented via enforcement stages, queues, and the worker pipeline (`v_enforcement_overview`, `v_judgment_pipeline`).
- **Enrichment**: Data acquisition and enrichment runs that augment cases with additional metadata (`enrichment_runs`, queue-driven jobs).

Adhering to these guidelines keeps code coherent and production-ready for the Dragonfly Civil operations team.
