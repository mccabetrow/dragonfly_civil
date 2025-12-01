# Operations Onboarding

This guide walks through the day-to-day operational checks for Dragonfly Civil. Keep it handy when you first take the console into production.

---

## How to run the importer

1. **Activate the virtual environment** (one time per shell):
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```
2. **Load environment variables** for the target Supabase project:
   ```powershell
   .\scripts\load_env.ps1
   ```
3. **Pick your mode**:
   - Demo/Staging: leave `SUPABASE_MODE` as-is or set `demo`/`dev` as needed.
   - Production: `powershell -Command "$env:SUPABASE_MODE='prod'"`
4. **Dry run the importer** to confirm row counts and validation:
   ```powershell
   .\.venv\Scripts\python.exe -m etl.src.plaintiff_importer --csv path\to\plaintiffs.csv
   ```
5. **Commit the load** once the dry run summary looks correct:
   ```powershell
   .\.venv\Scripts\python.exe -m etl.src.plaintiff_importer --csv path\to\plaintiffs.csv --commit
   ```
   Always keep the CSV snapshot in `data_in/` or an archive so you can re-run if needed.

---

## How to run the preflight scripts

Run these before every major import, deploy, or investor walk-through. They set `SUPABASE_MODE`, run `db_push` in checks mode, config + security audits, `doctor_all`, and pytest.

```powershell
# Dev sandbox
$env:SUPABASE_MODE = 'dev'
./scripts/preflight_dev.ps1

# Production
$env:SUPABASE_MODE = 'prod'
./scripts/preflight_prod.ps1
```

- The VS Code tasks **Preflight (Dev)** and **Preflight (Prod)** wrap these commands if you prefer Ctrl+Shift+P → “Run Task…”.
- Stop immediately on any `[FAIL]` output, fix the referenced tool (config_check, security_audit, doctor_all, pytest), then rerun until green.

---

## How to verify a plaintiff load

1. **Smoke the tables**:
   ```powershell
   .\.venv\Scripts\python.exe -m tools.smoke_plaintiffs
   ```
   - Look for expected counts in plaintiffs, contacts, overview, and call queue.
2. **Check the dashboard**:
   - Open `http://localhost:5173/` (dev) or the deployed dashboard.
   - Navigate to **Cases** → ensure the new plaintiffs appear in the workbench and funnel panels.
3. **Inspect Supabase directly** (optional but useful):
   - Go to Supabase dashboard → SQL editor.
   - Run: `select * from public.plaintiffs order by created_at desc limit 20;`
   - Spot-check contact entries via `public.plaintiff_contacts`.
4. **Review status history** if the importer populated notes:
   ```sql
   select *
   from public.plaintiff_status_history
   order by changed_at desc
   limit 20;
   ```

---

## How to run doctor_all

`doctor_all` orchestrates the doctor checks plus plaintiff and enforcement smoke tests.

```powershell
.\.venv\Scripts\python.exe -m tools.doctor_all --env prod
```

- Use `--env dev` or omit the flag to target the demo environment.
- Review the output for `[PASS]` lines; if anything fails, the script exits non-zero and prints the failing section. Preflight already calls this, but ops can run it directly for spot checks.
- The VS Code task **Doctor All** (Ctrl+Shift+D) runs the same command with `--env prod`.

---

## How to see open tasks in Supabase dashboard

1. Sign in to the Supabase project.
2. Navigate to **Table Editor** → `public.v_plaintiff_open_tasks`.
3. Filter or sort as needed to view `status`, `due_at`, and `note` columns.
4. For deeper detail, join `public.plaintiff_tasks` with `public.plaintiffs` via the SQL editor:
   ```sql
   select p.name, t.*
   from public.plaintiff_tasks t
   join public.plaintiffs p on p.id = t.plaintiff_id
   where t.status in ('open', 'in_progress')
   order by t.due_at nulls last;
   ```

---

## What to do if something fails

1. **Importer errors**
   - Read the exception output; most validation issues reference the CSV row number or column.
   - Fix the source file, re-run the dry run, then commit once clean.
2. **Smoke, doctor, or preflight failures**
   - Note which section failed (e.g., `db_push checks`, `Collectability Snapshot`, `Queues`).
   - Check recent migrations under `supabase/db/migrations/` and ensure they’ve been applied with `scripts/db_push.ps1 -SupabaseEnv <env>`.
   - If the failure is a missing view, run `python -m tools.pgrst_reload` (already part of db_push) or `scripts/bootstrap.ps1 -Mode reload`.
3. **Dashboard anomalies**
   - Confirm `npm run build` and `npm run dev` are in sync with the latest backend views.
   - Use the `Doctor All` task to confirm the Supabase environment is reachable.
4. **Escalation**
   - Document the failing command, environment, and error output.
   - Ping the engineering channel or the on-call developer with the details and any reproduction steps.
   - Attach relevant CSVs/logs if data inconsistencies triggered the issue.

Stay disciplined: rerun `doctor_all` and `smoke_plaintiffs` after fixes so you know the environment is healthy again.
