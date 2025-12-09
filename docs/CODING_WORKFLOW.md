# 🛠️ Dragonfly Coding Workflow

## 1. The "Staff Engineer" Loop

1.  **Spec:** Write 2 sentences defining the business outcome.
2.  **Prompt:** Feed Claude the Spec + the relevant Template (A, B, or C).
3.  **Review:** Check Claude's output against the "Rules of Engagement" (Did it write tests? Is there a migration?).
4.  **Paste:** Apply changes to `backend/` and `supabase/migrations/`.

## 2. The Verification Loop (Local)

_Before committing anything:_

1.  **Migrate:** `\.\scripts\db_migrate.ps1 -SupabaseEnv dev`
2.  **Test:** `python -m pytest` (Must be Green).
3.  **Smoke:** `python -m tools.doctor --env dev`

## 3. The Deployment Loop (Production)

1.  **Commit:** `git commit -m "feat(scope): description"`
2.  **Push:** `git push origin main`
3.  **Watch:** Monitor GitHub Actions (`production_deploy`).
    - _Green Tests_ -> _Green Migration_ -> _Green Deploy_.
4.  **Verify:** `python -m tools.prod_smoke` (Points to Prod DB).

## 4. Emergency Protocol

_If Prod Breaks:_

1.  **Do NOT** run SQL manually.
2.  **Do** revert the commit or push a `fix(...)` commit immediately.
3.  **Check:** Discord Alerts for "Failed Phase".
