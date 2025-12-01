# Dragonfly Civil Operating Model

## High-Level Flow (Text Diagram)
```
Intake Sources → Qualification & Docket Prep → Enrichment & Scoring → Enforcement Playbooks → Payment & Compliance Monitoring → Plaintiff Reporting
        (web, csv, mail)            (review, triage)             (assets, contactability)      (levy, income exec, liens)        (queues, workers)             (dashboards, briefs)
```

## 1. Current Manual Enforcement Workflow ("Dad Mode")
1. **Judgment Intake & Validation** – New judgments arrive via WebCivil searches, NYSCEF updates, or plaintiff emails. Dad prints or saves each judgment, confirms docket accuracy, and records the case in his spreadsheet with debtor contact notes.
2. **Asset Recon & Contact Discovery** – He calls plaintiffs to confirm balances, digs through skip-trace vendors (TLO, Lexis) for bank accounts and employers, and files FOIL requests when information is stale.
3. **Prioritization & Case Framing** – Cases are triaged by collectability hunches (recent employment, homeowner status, prior contact). He annotates the spreadsheet with tiers (A/B/C) and flags special handling (wage-friendly vs asset-heavy).
4. **Enforcement Execution** – For high-promise cases he drafts and files income executions or property restraining notices, liaises with the sheriff or marshal, and schedules bank levies. Mid-tier cases get demand letters and monitored payment plans. Low-tier cases are parked until new intel arrives.
5. **Collections & Follow-up** – Incoming payments are logged manually in the spreadsheet. He reconciles balances monthly, follows up on bounced checks, and coordinates stipulations or satisfaction filings.
6. **Plaintiff Reporting** – Weekly, he compiles email summaries with action taken, outstanding balances, and roadblocks. Quarterly, he produces PDF ledgers from the spreadsheet for each plaintiff portfolio.

## 2. Current Automation Footprint ("Dragonfly Today")
1. **Automated Intake** – `collector_v1` and n8n flows ingest CSV exports (Simplicity, internal lists) and WebCivil scrapes into Supabase `judgments.cases` via `insert_or_get_case_with_entities`.
   - *Automation Hook:* Ensure `.env`/`SUPABASE_MODE` selects dev/prod correctly; `scripts/demo_smoke_prod.ps1` offers a full prod smoke.
2. **Normalization & Enrichment** – Workers (`workers.runner`, `worker_enrich`) consume queue messages to hydrate enrichment runs, compute collectability tiers, and attach FOIL responses.
   - *Automation Hook:* `tools.doctor` validates queues, views, and sequence grants before prod runs.
3. **Scoring & Dashboards** – `v_collectability_snapshot` feeds the React dashboard (Overview, Cases, Collectability pages) to surface tiering, asset hints, and FOIL timelines.
   - *Automation Hook:* Tailwind dashboards pull directly from Supabase; ensure migrations 0058+ remain applied.
4. **Enforcement Support** – `spawn_enforcement_flow` RPC seeds enforcement tasks (bank levy queue, income execution reminders) though final filings remain manual.
   - *Automation Hook:* `workers.queue_client` monitors pgmq queues and dispatches tasks; `tools.list_queue_functions` verifies RPC health.
5. **Reporting** – `runbook_ops` process and dashboards provide weekly health checks, but plaintiff-facing PDFs are still manual.

## 3. Target Operating Model (12–18 Months)

### 3.1 Intake & Qualification
1. **Source Consolidation** – WebCivil scraper V2, NYSCEF docket monitor, Simplicity API sync, and plaintiff spreadsheet drops feed a unified intake queue.
2. **Automated De-duplication** – Ingestion service normalizes party names, cross-matches existing cases, and flags conflicts.
3. **Triage Rules Engine** – Cases are auto-tagged by portfolio, jurisdiction, balance, and freshness; urgent cases trigger immediate enrichment jobs.

**Automation Hooks**
- n8n workflows and `collector_v2` call `insert_or_get_case_with_entities` with metadata for source, channel, and ingestion confidence.
- `scripts/check_prod_schema.py` and `tools.demo_insert_case` stay part of CI smoke to ensure RPCs and views exist in prod.

### 3.2 Enrichment & Scoring
1. **Collectability Layer** – Automated pulls from employment, property, banking vendors update `enrichment_runs` with confidence scores.
2. **Contactability Layer** – Phone/email verification services feed contact tiers; unreachable defendants trigger alternate outreach sequences.
3. **Asset Scoring Layer** – Machine scoring combines balance, asset presence, and historical response to produce enforcement priority bands.

**Automation Hooks**
- Python enrichment workers integrate with vendor APIs; each run pushes structured JSON into Supabase and publishes a scoring event to pgmq.
- Scheduled analytics notebooks recalibrate weights and update `score_profiles` tables.

### 3.3 Enforcement Playbooks
1. **Playbook Selection** – Based on scoring bands, automation suggests Bank Levy, Income Execution, Property Lien, or Settlement Outreach.
2. **Task Orchestration** – `spawn_enforcement_flow` creates tasks with deadlines, document templates, and required approvals.
3. **Execution Tracking** – Status changes (filed, served, paid) are recorded via queue-driven updates; exceptions route to human review.

**Automation Hooks**
- n8n or Temporal workflows trigger document assembly (Word/PDF) from Supabase data.
- Sheriffs/marshal responses feed back through intake connectors (email parser → Supabase update).

### 3.4 Payment, Monitoring, and Reporting
1. **Payment Capture** – ACH/lockbox integrations reconcile payments; partials auto-adjust outstanding balance fields.
2. **Compliance Monitoring** – Dashboards alert when levies stall or income executions miss remittances.
3. **Plaintiff Reporting** – Automated weekly digest emails (HTML + CSV attachments) provide action status, balances, and upcoming enforcement milestones.

**Automation Hooks**
- Supabase functions aggregate portfolio KPIs; a scheduled job emails reports via SendGrid/Resend.
- Dashboard widgets surface SLA breaches; alerts post to #ops Discord via webhook used by `tools.doctor` failures.

## 4. Glossary & Roles
1. **Case Manager (Dad)** – Oversees enforcement decisions, approves settlements, escalates exceptions.
2. **Automation Orchestrator (Dragonfly Platform)** – Handles intake, enrichment, scoring, task creation, and status tracking.
3. **Vendors & Agencies** – Skip tracing providers, sheriffs/marshals, banks responding to levies.
4. **Plaintiffs** – Receive periodic reports, approve major enforcement actions, and supply new case batches.

---
This operating model anchors today’s manual expertise while outlining the automation milestones that keep Dragonfly’s codebase aligned with real-world enforcement. Continuous updates should sync with runbook revisions and CI smoke outputs (`demo_smoke_prod.ps1`).
