# Plaintiff Model (Day 1)

This note captures how we represent plaintiffs inside Dragonfly Civil on day one. It is written for engineers, operators, and the folks running demos. Keep it pragmatic: this is the reference we will come back to while building dashboards, ETL, and automations.

## What we mean by a plaintiff

- A plaintiff is the individual or firm that owns one or more civil judgments.
- One plaintiff can have many judgments over time; each judgment contributes exposure we track in the dashboard.
- A plaintiff can have many contact points (phones, emails, addresses). Every contact belongs to exactly one plaintiff.

## Who needs this view

- **Mom** – runs sales, onboarding, and the ongoing relationship. She needs a quick read on where each plaintiff is in the sales funnel and who to call next.
- **Dad** – leads enforcement work once a plaintiff signs. He watches the same record to see outstanding exposure, queued enforcement tasks, and whether legal has follow-ups.
- **Me** – manages the whole pipeline. I use the aggregate plaintiff list to understand how the book of business is growing, which plaintiffs are stuck, and how much judgment exposure is signed versus still in motion.

## Sales status ladder

We track the plaintiff-level sales motion in `plaintiffs.status`. Changes are append-only events in `plaintiff_status_history`.

1. **`new`** – row arrived from a CSV or import; no outreach performed.
2. **`contacted`** – we actively reached out (email, phone, meeting) but have not qualified.
3. **`qualified`** – we validated interest and fit (e.g., they have enforceable judgments and want our help).
4. **`sent_agreement`** – retainer or services agreement has been issued.
5. **`signed`** – agreement executed; plaintiff transitions to onboarding and enforcement.
6. **`lost`** – not moving forward (wrong fit, declined, unresponsive).

### Status mechanics

- Every status change logs a row in `plaintiff_status_history` with timestamp and optional reason/actor.
- The latest status drives the dashboard badge and determines which workflow (sales vs enforcement) is surfaced.
- ETL defaults new imports to `new` unless a more advanced status is provided by a trusted upstream source.

## Tables we own

### `plaintiffs`

The core entity: one row per plaintiff. Key columns:

- `id` – surrogate primary key.
- `name` / `name_normalized` – display name and dedup key.
- `short_name` – optional condensed display for UI chips.
- `status` – current sales status (see ladder above).
- `metadata` – JSON blob for importer source, counties, sample cases, etc.
- `created_at` / `updated_at` – audit timestamps (maintained by trigger).

### `plaintiff_contacts`

Contact roster for each plaintiff. Key columns:

- `id` – surrogate primary key.
- `plaintiff_id` – FK to `plaintiffs.id`.
- `contact_type` – `email`, `phone`, `address`, `website`, or `other`.
- `contact_value` – the address/number/URL.
- `label` – optional note (e.g., “Billing”, “Managing Partner”).
- `is_primary` – flag used by the dashboard to highlight the go-to contact for each channel.
- `created_at` / `updated_at` – audit timestamps.

We enforce one primary contact per type via a partial unique index so the UI can safely promote the “best” email/phone.

### `plaintiff_status_history`

Append-only log of status transitions. Key columns:

- `id` – surrogate primary key.
- `plaintiff_id` – FK to `plaintiffs.id`.
- `status` – the status value applied.
- `recorded_at` – UTC timestamp for the transition (defaults to now()).
- `recorded_by` – optional human or automation name.
- `reason` – freeform context (e.g., “Declined – using in-house counsel”).

## How judgments tie in

- `public.judgments.plaintiff_id` references `plaintiffs.id`.
- Legacy rows may leave `plaintiff_id` null; the importer or enrichment scripts should backfill when possible.
- All new intakes and ETL pathways must set `plaintiff_id` or create the plaintiff first, then attach judgments.

This FK is what powers aggregate views such as `public.v_plaintiff_summary` and connects case-level data (collectability, tasks, exposure) back to the sales view.

## How the dashboard uses it

- The “Plaintiff workbench” card reads `v_plaintiff_summary` to surface exposure, latest status, and primary contact info so sales knows who to call and enforcement sees signed volume.
- The Cases table pulls `v_judgment_pipeline` to show stage (intake → outreach → enforcement → collected) for each judgment, colored by plaintiff status.
- Search and filters operate on `status`, `total_judgment_amount`, and contact availability to quickly find plaintiffs at the same stage or with missing data.

## Automation and ETL guidance

- CSV intakes feed `plaintiff_importer.py`, which groups rows by normalized plaintiff name, upserts into `plaintiffs`, refreshes contacts, and records status events. Always run with `--dry-run` first.
- When judgments arrive without a known plaintiff, create or look up the plaintiff before calling `insert_or_get_case_with_entities`; this keeps the FK intact and avoids orphaned exposure.
- Automations that change the sales stage (e.g., agreement sent) should call an RPC or use the Supabase client to append to `plaintiff_status_history` and update `plaintiffs.status` in the same transaction.

## Working agreements

- Keep status values limited to the ladder above; if we need more nuance, add metadata or reason strings rather than new enumerations.
- Treat contacts as customer-facing data. Update them via the dashboard or vetted ETL—not ad-hoc SQL—to preserve primaries.
- If a plaintiff merges or splits, write a migration or maintenance script: reassign judgments, move contacts, and archive the old row without deleting history.

This is the document to share with new engineers or ops staff when they jump into plaintiff work. It answers “what columns matter, who uses them, and how does the data flow” without burying them in schemas.
