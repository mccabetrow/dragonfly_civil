# 🐉 Dragonfly Codex: Engineering Standards & AI Guide

**Mission:** Build the world's most automated legal asset recovery platform.
**Standard:** Institutional Grade. Zero Defects. Full Observability.

---

## 🤖 Master System Prompt (For Claude/Opus)

_Paste this at the start of every new chat session._

> **Role:** You are the Lead Staff Engineer for Dragonfly Civil.
> **Rules:**
>
> 1. **No Cowboy Changes:** All DB changes must be timestamped migrations (`supabase/migrations/`). Never raw SQL.
> 2. **Full-Stack Units:** Every feature request requires: Migration + Backend Code + Tests + Observability hooks.
> 3. **Stack:** FastAPI (Python 3.12), Supabase (Postgres), Pydantic v2, pytest, React/Vite.
> 4. **Safety:** Tests must mock external calls. DB migrations must be idempotent where possible.
> 5. **Output:** Provide full file contents ready for copy-paste.

---

## 📋 Task Templates

### **Template A: New Analytics Feature**

_Use for dashboards (e.g., Intake Radar, CEO Command Center)._

- **Migration:** Create `analytics.v_<name>` returning a single row of aggregated metrics using `COALESCE` (no nulls).
- **Backend:** Add `GET /api/v1/analytics/<name>` with a Pydantic response model.
- **Tests:** Integration test ensuring endpoint returns 200 OK and correct schema.

### **Template B: New Worker / Queue Processor**

_Use for automation (e.g., Bank Levy Worker, Enforcement Engine)._

- **Migration:** Add `job_type` to `ops.job_type_enum`. Create necessary `enforcement` tables.
- **Backend:** Create `backend/workers/<name>.py`.
  - Loop: `FOR UPDATE SKIP LOCKED`.
  - Log: Write status to `ops.intake_logs`.
- **Tests:** Mock the DB connection. Assert job claiming and error handling logic.

### **Template C: New Frontend Page**

_Use for UI (e.g., Intake Station)._

- **Components:** Create `src/pages/<PageName>.tsx`.
- **Hooks:** Create `src/hooks/use<PageName>Data.ts` with auto-refresh/polling.
- **UX:** Use Skeleton loaders (no spinners). Handle error states gracefully.

---

## 🏗️ Architecture Pillars

1.  **Ingestion:** All raw data enters via `ops.ingest_batches` -> `ops.job_queue`.
2.  **Enforcement:** Logic lives in `backend/agents/`. Workers trigger Agents.
3.  **Observability:** If it isn't logged to `ops.intake_logs` or a `v_` view, it didn't happen.
