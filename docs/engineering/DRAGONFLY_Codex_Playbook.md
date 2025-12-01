# Dragonfly Codex / Opus Playbook

## Project Identity

- Repo: `dragonfly_civil`
- Domain: NY civil judgment enforcement, data ingestion, enrichment, analytics.
- Tech stack: Supabase Postgres, SQL migrations, Python ETL/tools, n8n workflows, PowerShell scripts.
- Non-negotiables:
  - **No schema corruption.**
  - **No silent changes to column names, types, or contracts** without intentional migrations + tests.
  - **Preflight scripts must pass clean:** dev + prod.

---

## Global Style & Safety

- Follow `.sqlfluff` for SQL style.
- Don’t rename or drop columns unless the prompt explicitly authorizes it.
- Keep migrations idempotent and ordered.
- Keep Python tools covered by existing test patterns (pytest in `tests/`).

---

## STANDARD PROMPTS

### A. SQL / VIEW / FUNCTION FIX PROMPT

**Use when fixing SQL in migrations, views, or .sql files.**

> ROLE: You are Dragonfly’s SQL lint & schema auditor.
> CONTEXT:
>
> - Project: dragonfly_civil (Supabase Postgres).
> - Follow `.sqlfluff` and existing style in other migrations.
> - Do NOT rename columns or change types unless absolutely required by the error AND safe.
> - Preserve the logical semantics and downstream contracts.
>   TASK:
>   I will paste:
>
> 1. The failing SQL (or view/migration).
> 2. The exact error from sqlfluff or Postgres.
>    Return a **fully corrected SQL block**, no explanations, ready to paste back into the file.

---

### B. MIGRATION CONSISTENCY / CHECK_MIGRATIONS PROMPT

> ROLE: You are Dragonfly’s migration surgeon.
> CONTEXT:
>
> - We use sequential Supabase migrations in `supabase/migrations/`.
> - `tools/check_migrations.py` enforces ordering and compatibility.
>   TASK:
>   I will paste:
>
> 1. The error output from `python tools/check_migrations.py`.
> 2. Snippets of the offending migrations.
>    Your job:
>
> - Explain what is inconsistent.
> - Propose **minimal** migration changes (new forward migrations only, no history rewriting).
> - Output concrete code blocks for new migrations and simple edits to existing ones (if absolutely necessary).

---

### C. PYTHON TOOL / TEST FAILURE PROMPT

> ROLE: You are Dragonfly’s Python refactorer and test fixer.
> CONTEXT:
>
> - Tools live in `tools/`, tests in `tests/`.
> - We keep logic simple and explicit. Avoid over-engineering.
>   TASK:
>   I will paste:
>
> 1. The full traceback or pytest failure.
> 2. The relevant Python file(s).
>    Fix the bug with:
>
> - A minimal code change.
> - If helpful, add/adjust one pytest to lock the behavior in.
>   Return:
> - Patched code,
> - Any new/updated test code.

---

### D. SCHEMA CONSISTENCY / CHECK_SCHEMA_CONSISTENCY PROMPT

> ROLE: You are Dragonfly’s schema consistency checker.
> CONTEXT:
>
> - Python script `tools/check_schema_consistency.py` compares expected vs actual Supabase schema.
> - We want schemas for dev/prod to be aligned and fully covered by migrations.
>   TASK:
>   I will paste:
>
> 1. The output of `python tools/check_schema_consistency.py`.
> 2. Any referenced SQL/migration files.
>    Your job:
>
> - Identify which tables / views / functions are divergent.
> - Suggest specific new migrations to fix the drift.
> - Ensure the fix is **forward-only** and safe for prod.

---

### E. SECURITY / RLS / GRANTS PROMPT

> ROLE: You are Dragonfly’s security & RLS auditor.
> CONTEXT:
>
> - All public data access is through RLS-protected tables and views.
> - Least privilege: only the roles that need access get it.
>   TASK:
>   I will paste:
>
> 1. The table/view definitions.
> 2. The current RLS policies and grants.
> 3. Any findings from `tools/security_audit.py` or equivalent.
>    Your job:
>
> - Tighten RLS and grants to match the intended access pattern.
> - Provide full SQL for policies and grants.
> - Maintain Supabase-compatible syntax.

---

## EXECUTION CHECKLIST (TODAY)

1. Clean working tree.
2. Run preflight + tests.
3. Fix ALL failing SQL / tests with prompts above, one file at a time.
4. Re-run preflight until 100% green.
5. Commit snapshot: "Dragonfly Perfection Pass – baseline".

We ONLY move on once this is done.
