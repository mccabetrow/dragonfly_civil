# Demo Script: Dragonfly Console

## 1. Data pipeline: Simplicity → Supabase
- Navigate to **docs/runbook_phase1.md** (show pre-ingest checklist) then switch to **CLI terminal**.
- Say: "We start by dropping a new Simplicity export into `data_in/`; the watcher automatically picks it up."
- Highlight: `make smoke` or **Insert: Composite** task; point out real-time logs updating Supabase.
- Click into `/overview` dashboard: "Point out that the pipeline tallies ingested cases and flags queue health."

## 2. Collectability overview & tiers
- Open `/collectability` page.
- Say: "This view ranks judgments by tier so we know where to focus."
- Click tier filter pill: "Show how Tier A/B/C segmentation responds instantly; mention scoring logic combines amount + age."
- Demonstrate sorting: "Click the Judgment Amount header and note the up/down arrow for quick prioritization."

## 3. Case-level drilldown
- Move to `/cases` page.
- Say: "Here’s the searchable roster of judgments with tier and last enrichment status."
- Click a case row: "Point out the drawer’s three-column layout — summary, enrichment timeline, FOIL responses."
- Emphasize: "Mention we can walk from plaintiff/defendant context through every enrichment touch with zero extra clicks."

## 4. FOIL & enrichment tracking
- Still in the case drawer, scroll to FOIL card.
- Say: "Each FOIL response is logged with agency, received date, and notes — ready for compliance conversations."
- Highlight Enrichment history column: "Call out the stub bundle keeping tiers fresh, plus timestamps for when action occurred."
- Optional: switch back to `/overview` to underscore total counts and last run status.

## 5. Next steps / scale-up vision
- Return to `/overview` or the AppShell sidebar for context.
- Say: "Next we plug in live outreach (n8n) and move enrichment from stub to vendor feeds."
- Point out: "Supabase schema already supports adding enforcement flows and escalations; the dashboard just needs toggles."
- Close with ask: "Mention we’re ready to onboard 10–20 cases per week once outreach templates are approved."