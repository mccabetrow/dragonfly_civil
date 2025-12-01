# Codex / AI Prompts for Dragonfly

These are the standard prompts we use with Cursor, Copilot Chat, or the OpenAI VS Code extension when working on this repo. The idea: highlight relevant files or folders, then run the appropriate prompt in the AI chat.

---

## 1. Create migration

**Prompt:**

> You are my Supabase/Postgres migration assistant for the Dragonfly Civil project.
>
> Given the existing migrations in `supabase/migrations` and our current schema, create a new SQL migration that does the following:
>
> - [Describe change, e.g. "Add a new table `plaintiff_contacts` with indexes, RLS, and grants consistent with our existing patterns."]
>
> Requirements:
>
> - Follow the existing naming conventions for migrations.
> - Include `CREATE TABLE`, indexes, constraints, RLS policies, and GRANT statements consistent with similar existing tables.
> - Make the migration idempotent where possible.
> - Do not drop or modify existing objects unless I explicitly tell you to.

---

## 2. Add RPC

**Prompt:**

> You are my Supabase RPC designer for the Dragonfly Civil project.
>
> Using the existing RPCs as examples (in `supabase/migrations` and any `rpc_*.sql` files), create a new RPC function called `[function_name]` that:
>
> - [Describe what it should do, e.g. "Insert or update a plaintiff record and return the normalized row from the canonical view."]
>
> Requirements:
>
> - Use our existing naming conventions for functions and parameters.
> - Include `SECURITY DEFINER` or `INVOKER` as appropriate based on similar RPCs.
> - Add appropriate `GRANT EXECUTE` statements.
> - Ensure it is safe to call multiple times (idempotent where it makes sense).
> - Return a well-typed record (not `SETOF anyelement`).

---

## 3. Add tests for X

**Prompt:**

> You are my test-writing assistant for the Dragonfly Civil Python backend.
>
> Look at the existing tests in `tests/` and the implementation in `[path/to/module.py]`, and then:
>
> - Add tests for `[function or behavior to test]`.
>
> Requirements:
>
> - Follow the existing pytest style and fixtures.
> - Cover both happy-path and edge cases.
> - Use realistic sample data consistent with the rest of the test suite.
> - Keep tests deterministic (no external API calls or network unless there are existing patterns/fixtures for them).

---

## 4. Refactor importer

**Prompt:**

> You are my refactoring assistant for the Dragonfly Civil import pipeline.
>
> I want you to refactor the importer code in `[path/to/importer.py]` to make it:
>
> - Easier to read and maintain.
> - More robust (better error handling and logging).
> - Consistent with our project structure and style.
>
> Requirements:
>
> - Do not change external behavior or public interfaces unless you explicitly suggest a safe improvement.
> - Preserve logging semantics and error paths that are important for operations.
> - Extract helper functions where it simplifies complex logic.
> - Keep it compatible with existing tests, or update tests if the refactor truly improves design.
> - Suggest any additional tests we should add to cover tricky branches.

---

## 5. How to use these

1. Open the relevant file(s) in VS Code.
2. Select them in the Explorer or open them in tabs.
3. Open your AI chat (OpenAI extension, Copilot Chat, or Cursor).
4. Paste the relevant prompt from above.
5. Fill in the bracketed parts `[like this]` with specifics.
6. Let the AI propose changes, then review carefully and apply via diff.

---

## CODex Rules

Copy-paste this into codex_prompts.md in your repo. CODex RULE 1 — NEVER GUESS ENVIRONMENT

Before running any repair, Codex must ALWAYS ask itself:

Environment = value of SUPABASE_MODE
If SUPABASE_MODE not explicitly dev or prod:
STOP and ask user which environment

Codex must not fix production history unless you explicitly confirm.

🧠 CODex RULE 2 — AUTOMATIC MIGRATION DIAGNOSIS

Whenever you get an error like:

duplicate key value violates unique constraint "schema_migrations_pkey"

relation already exists, skipping

migration failed halfway

Codex should immediately run this diagnostic routine:

1. List all migrations in supabase/migrations
2. List all schema_migrations rows in target database:
   SELECT version, name FROM supabase_migrations.schema_migrations ORDER BY version;
3. Compare the two lists:
   - Missing in DB → migration needs to run
   - Missing locally → warn user
   - Down file with same version → error
   - Version in DB but SQL not applied → corrupted state

Then Codex chooses one of two safe actions:

If DEV

Codex can:

DELETE FROM supabase_migrations.schema_migrations WHERE version = 'XXXX';

and rerun db_push.

If PROD

Codex must NOT delete.
Instead, it must:

Create a new migration with the next version number,
containing ONLY the missing SQL required to repair prod.

🧠 CODex RULE 3 — MIGRATION HYGIENE

Codex must enforce:

NO .down.sql in this repo
Every migration must be idempotent
Every migration must start with BEGIN;
Every migration must end with COMMIT;
Functions must be created with CREATE OR REPLACE
Columns must use ADD COLUMN IF NOT EXISTS
Indexes must use IF NOT EXISTS

This prevents 99% of the issues you’ve been running into.

🧠 CODex RULE 4 — AUTOMATIC FREEZE SYNC

Any time migrations change, Codex must run:

$env:SUPABASE_MODE='dev'
python -m tools.check_schema_consistency --freeze

Then include the new freeze in the PR.

🧠 CODex RULE 5 — AUTOMATIC PRE-FLIGHT

Before approving ANY change touching SQL, Codex must run locally:

tasks: preflight_dev.ps1
tasks: preflight_prod.ps1 (checks mode ONLY)

If any step fails, Codex must give you:

Exact file → exact line → exact fix

🧠 CODex RULE 6 — MIGRATION RECOVERY PROTOCOL

If a migration breaks, Codex must automatically generate a recovery file:

tmp/migration*repair*<timestamp>.md

Containing:

the root cause

the environment it happened in

the safe repair action

the SQL needed

the updated migration

the commands to rerun

This makes recovery predictable instead of chaotic.

🧠 CODex RULE 7 — MIGRATION LINTING

Codex must lint every migration before accepting it:

Are BEGIN/COMMIT present?
Are all functions CREATE OR REPLACE?
Are all triggers IF NOT EXISTS?
Does any statement drop something needed by prod?
Does any statement assume a column does NOT exist?
Does the file follow naming: ####\_description.sql?
Is version unique in repo?
Is version > highest version in prod?

🧠 CODex RULE 8 — AUTOFIX SCRIPT

Codex must maintain one script:

tools/autofix_migrations.py

This script should:

load migrations

load schema freeze

compare

autofix missing grants or missing RLS

autofix missing functions

rewrite views

produce a corrected SQL file

It doesn’t apply it — it just generates the fix.

Codex then turns the output into a real migration.
