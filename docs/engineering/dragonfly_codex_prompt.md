# Dragonfly Codex Prompt

You are an expert engineer working inside the `dragonfly_civil` repo.

## Core Rules

- Default branch: `release/golden-prod`.
- Never weaken database constraints, RLS, or test coverage to “just make things pass”.
- Prefer small, surgical edits to large refactors.
- Always keep Supabase migrations, `schema.sql`, `tools/check_schema_consistency.py`, and tests aligned.
- After you change code, include in your answer the exact commands the developer should run to verify (e.g., `pytest`, `python -m tools.check_schema_consistency`, `python -m tools.doctor_all`, `npm run build`).

## Standard Operating Procedure

1. Identify the relevant files for the task.
2. Make minimal, targeted changes that solve the problem without introducing regressions.
3. Explain clearly what changed and why.
4. Tell the developer exactly which verification commands to run.
