# Dragonfly Civil – Week 1 Go-Live Execution Plan

> **Version:** 1.0  
> **Effective Date:** December 2, 2025  
> **Status:** READY FOR EXECUTION  
> **Prepared By:** McCabe (COO/CTO)  
> **Approved By:** Dad (CEO)

---

## Executive Summary

This document outlines the 7-day execution plan for Dragonfly Civil's operational launch. The week progresses from infrastructure hardening and small supervised imports through to the full 900-judgment portfolio go-live.

**Key Milestones:**

- Days 1–2: Infrastructure, banking, and mini-import validation (10–30 cases)
- Days 3–4: Scaled import testing (50–100 cases), Mom ops training
- Days 5–6: Final preflight, documentation, go/no-go decision
- Day 7: Full 900 portfolio import (weekend go-live window)

**Capital Position:**

- $125,000 → JBI (900-judgment portfolio)
- $125,000 → Operations reserve (enforcement, legal, tech, buffer)

---

## Team Roles & Responsibilities

| Role             | Name   | Primary Responsibilities                                            |
| ---------------- | ------ | ------------------------------------------------------------------- |
| **CEO**          | Dad    | Capital allocation, strategy, legal signoff, external relationships |
| **COO/CTO**      | McCabe | Engineering, deployment, system reliability, dashboards, queues     |
| **Ops Director** | Mom    | Outbound calls, signature review, enforcement execution             |

---

## Daily Execution Plan

---

# Day 1: Monday — Foundation & Banking

## Day Objective

> Establish financial infrastructure and validate production environment readiness.

---

### Dad (CEO) Tasks

| Task                                                        | Duration | Notes                                         |
| ----------------------------------------------------------- | -------- | --------------------------------------------- |
| Open Dragonfly Civil LLC business bank account              | 2–3 hrs  | Mercury, Relay, or Chase Business recommended |
| Set up dual-signature policy for transfers >$5,000          | 30 min   | Document in approval matrix                   |
| Review and sign JBI acquisition agreement (if not complete) | 1 hr     | Confirm $125K wire schedule                   |
| Review `corporate_shell.md` for any gaps                    | 30 min   | Flag items for attorney                       |

---

### McCabe (COO/CTO) Tasks

| Task                                               | Duration | Notes                                 |
| -------------------------------------------------- | -------- | ------------------------------------- |
| Deploy Mom Enforcement Console to Vercel (staging) | 1 hr     | Use `dragonfly-staging.vercel.app`    |
| Verify all workers are functional in dev           | 1 hr     | `preflight_dev.ps1` must pass         |
| Configure Discord webhook for daily digest         | 30 min   | Test with `daily_ops_digest_v1.json`  |
| Document production deployment checklist           | 1 hr     | Create `docs/deployment_checklist.md` |
| Run `tools.doctor --env prod`                      | 15 min   | Verify prod schema health             |

---

### Mom (Ops Director) Tasks

| Task                                          | Duration | Notes                         |
| --------------------------------------------- | -------- | ----------------------------- |
| Read `compliance_manual_v1.md` (Sections 1–5) | 1.5 hrs  | Take notes, flag questions    |
| Read `mom_desk_card.md`                       | 30 min   | Print physical copy for desk  |
| Read `scripts_and_templates.md`               | 1 hr     | Familiarize with call scripts |
| Set up workstation with Console access        | 30 min   | McCabe to provide staging URL |

---

### Technical Tasks

```
[ ] Run: preflight_dev.ps1 → must be GREEN
[ ] Run: preflight_prod.ps1 → must be GREEN
[ ] Verify: Supabase prod views accessible
[ ] Deploy: Vercel staging environment
[ ] Test: Discord daily digest webhook
[ ] Document: deployment_checklist.md
```

---

### Financial Control Actions

| Action                           | Owner | Status |
| -------------------------------- | ----- | ------ |
| Business bank account opened     | Dad   | ⬜     |
| Dual-signature policy documented | Dad   | ⬜     |
| JBI wire schedule confirmed      | Dad   | ⬜     |
| $125K ops reserve segregated     | Dad   | ⬜     |

---

### 🎯 Must-Complete Item

> **Business bank account must be opened and dual-signature policy documented.**
>
> _Rationale: No financial operations can proceed without banking infrastructure._

---

### End-of-Day Review Checklist

```
[ ] Bank account opened or application submitted
[ ] Dual-signature policy documented
[ ] Vercel staging deployed and accessible
[ ] preflight_dev.ps1 = GREEN
[ ] preflight_prod.ps1 = GREEN
[ ] Discord webhook tested
[ ] Mom completed compliance reading (Sections 1–5)
[ ] All blockers documented for Day 2
```

---

### Risk Register

| Risk                     | Likelihood | Impact | Mitigation                                      |
| ------------------------ | ---------- | ------ | ----------------------------------------------- |
| Bank account delay       | Medium     | High   | Apply early morning; have backup bank ready     |
| Vercel deployment issues | Low        | Medium | Fall back to local development; debug next day  |
| Prod schema drift        | Low        | High   | Doctor checks catch this; fix before proceeding |

---

---

# Day 2: Tuesday — Mini-Import Alpha (10 Judgments)

## Day Objective

> Execute first supervised import of 10 judgments to validate end-to-end pipeline.

---

### Dad (CEO) Tasks

| Task                                     | Duration | Notes                                    |
| ---------------------------------------- | -------- | ---------------------------------------- |
| Finalize bank account setup (if pending) | 1 hr     | Complete application, verify access      |
| Review first 10 judgments for import     | 30 min   | Confirm these are valid, enforceable     |
| Draft JBI payment schedule memo          | 30 min   | Tranches: $50K → $50K → $25K suggested   |
| Call with attorney re: corporate docs    | 30 min   | Confirm LLC operating agreement is filed |

---

### McCabe (COO/CTO) Tasks

| Task                                       | Duration | Notes                                      |
| ------------------------------------------ | -------- | ------------------------------------------ |
| Prepare 10-judgment test CSV from JBI data | 30 min   | Select diverse case types                  |
| Run dry-run import: `--dry-run` flag       | 30 min   | Validate no errors                         |
| Execute live import of 10 judgments to dev | 30 min   | `--commit` flag                            |
| Run enrichment worker on 10 cases          | 30 min   | `enrich_worker --env dev --once`           |
| Verify tier assignment                     | 15 min   | Check `v_enforcement_pipeline_status`      |
| Walk Mom through Console with live data    | 1 hr     | Show pipeline, call queue, signature queue |

---

### Mom (Ops Director) Tasks

| Task                                               | Duration | Notes                            |
| -------------------------------------------------- | -------- | -------------------------------- |
| Complete compliance reading (Sections 6–9)         | 1 hr     | Finish `compliance_manual_v1.md` |
| Observe McCabe's import + enrichment demo          | 1 hr     | Ask questions, take notes        |
| Navigate Console: find the 10 imported cases       | 30 min   | Practice pipeline filtering      |
| Practice: identify one case ready for call         | 15 min   | Use call queue view              |
| Practice: open signature queue, review mock action | 15 min   | Do not approve yet               |

---

### Technical Tasks

```
[ ] Prepare: 10-judgment test CSV
[ ] Run: dry-run import (dev) → no errors
[ ] Run: live import (dev) → 10 plaintiffs created
[ ] Run: enrich_worker (dev) → all 10 enriched
[ ] Verify: tier assignment in pipeline view
[ ] Verify: call queue populated
[ ] Verify: signature queue accessible
[ ] Demo: Walk Mom through Console
```

---

### Financial Control Actions

| Action                           | Owner | Status |
| -------------------------------- | ----- | ------ |
| JBI payment schedule drafted     | Dad   | ⬜     |
| Attorney call completed          | Dad   | ⬜     |
| Bank account verified functional | Dad   | ⬜     |

---

### 🎯 Must-Complete Item

> **10-judgment import must succeed end-to-end: import → enrich → tier → visible in Console.**
>
> _Rationale: This validates the entire pipeline before scaling._

---

### End-of-Day Review Checklist

```
[ ] 10 judgments imported to dev
[ ] All 10 enriched successfully
[ ] Tier assignment visible in pipeline
[ ] Call queue shows eligible cases
[ ] Mom navigated Console independently
[ ] JBI payment schedule drafted
[ ] Attorney call completed
[ ] No blocking errors in logs
```

---

### Risk Register

| Risk                        | Likelihood | Impact | Mitigation                                 |
| --------------------------- | ---------- | ------ | ------------------------------------------ |
| Import CSV format mismatch  | Medium     | Medium | Use `--dry-run` first; fix schema issues   |
| Enrichment API failures     | Low        | Medium | Check API keys; retry logic exists         |
| Mom unfamiliar with Console | Medium     | Low    | Extend demo time; schedule Day 3 follow-up |

---

---

# Day 3: Wednesday — Mini-Import Beta (30 Judgments)

## Day Objective

> Scale import to 30 judgments; Mom begins supervised Console interaction.

---

### Dad (CEO) Tasks

| Task                             | Duration | Notes                            |
| -------------------------------- | -------- | -------------------------------- |
| Wire $50K (Tranche 1) to JBI     | 30 min   | Per payment schedule             |
| Confirm wire received with JBI   | 15 min   | Email/call confirmation          |
| Review ops reserve allocation    | 30 min   | Enforcement costs, legal, buffer |
| Sign any pending legal documents | 30 min   | Assignment agreements, etc.      |

---

### McCabe (COO/CTO) Tasks

| Task                                               | Duration | Notes                              |
| -------------------------------------------------- | -------- | ---------------------------------- |
| Prepare 30-judgment CSV (cumulative: now 40 total) | 30 min   | Verify no duplicates with prior 10 |
| Run dry-run import                                 | 15 min   |                                    |
| Execute live import of 30 judgments to dev         | 30 min   |                                    |
| Run enrichment worker                              | 30 min   |                                    |
| Verify tier assignment for all 40                  | 15 min   |                                    |
| Monitor: observe Mom's first Console session       | 1 hr     | Be available for questions         |
| Deploy staging to Vercel production URL            | 1 hr     | `dragonfly-console.vercel.app`     |

---

### Mom (Ops Director) Tasks

| Task                                             | Duration | Notes                       |
| ------------------------------------------------ | -------- | --------------------------- |
| **First supervised call session (1 hr max)**     | 1 hr     | 3–5 calls, McCabe observing |
| Document: questions/friction points              | 15 min   | Write down what's confusing |
| Review signature queue: approve 1–2 test actions | 30 min   | McCabe supervises           |
| Review daily digest (Discord)                    | 15 min   | Understand what it shows    |

---

### Technical Tasks

```
[ ] Prepare: 30-judgment CSV
[ ] Run: dry-run import (dev) → no errors
[ ] Run: live import (dev) → 30 plaintiffs created (40 total)
[ ] Run: enrich_worker (dev) → all enriched
[ ] Verify: tier assignment for all 40
[ ] Deploy: Vercel production URL live
[ ] Monitor: Mom's first call session
[ ] Test: Daily digest in Discord
```

---

### Financial Control Actions

| Action                           | Owner | Status |
| -------------------------------- | ----- | ------ |
| $50K Tranche 1 wired to JBI      | Dad   | ⬜     |
| Wire receipt confirmed           | Dad   | ⬜     |
| Ops reserve breakdown documented | Dad   | ⬜     |

---

### 🎯 Must-Complete Item

> **Mom must complete her first supervised outbound call session (minimum 3 calls).**
>
> _Rationale: Ops cannot scale without validated call workflow._

---

### End-of-Day Review Checklist

```
[ ] 30 new judgments imported (40 total in dev)
[ ] All 40 enriched
[ ] Mom completed 3+ supervised calls
[ ] Mom approved 1–2 signature queue items
[ ] Vercel production URL deployed
[ ] $50K Tranche 1 wired
[ ] Daily digest received in Discord
[ ] Friction points documented
```

---

### Risk Register

| Risk                     | Likelihood | Impact | Mitigation                                 |
| ------------------------ | ---------- | ------ | ------------------------------------------ |
| Wire delay               | Low        | High   | Send early; confirm with bank              |
| Mom call anxiety         | Medium     | Medium | Start with low-stakes cases; debrief after |
| Vercel deployment issues | Low        | Medium | Keep staging as fallback                   |

---

---

# Day 4: Thursday — Scale Test (100 Judgments)

## Day Objective

> Import 100 total judgments; validate system under realistic load; Mom operates semi-independently.

---

### Dad (CEO) Tasks

| Task                                  | Duration | Notes                        |
| ------------------------------------- | -------- | ---------------------------- |
| Wire $50K (Tranche 2) to JBI          | 30 min   | Per payment schedule         |
| Review 100-case portfolio composition | 30 min   | Mix of tiers, debtor types   |
| Draft investor update template        | 30 min   | For future LP communications |
| Review `investor_deck_outline.md`     | 30 min   | Flag any gaps                |

---

### McCabe (COO/CTO) Tasks

| Task                                                | Duration | Notes                         |
| --------------------------------------------------- | -------- | ----------------------------- |
| Prepare 60-judgment CSV (cumulative: now 100 total) | 30 min   |                               |
| Run dry-run import                                  | 15 min   |                               |
| Execute live import of 60 judgments to dev          | 30 min   |                               |
| Run enrichment worker in batch                      | 45 min   | May take longer with 60 cases |
| Performance check: verify Console responsiveness    | 30 min   | Views should load <3s         |
| Set up worker monitoring (logs, alerts)             | 1 hr     | Prepare for 900 scale         |
| Be available for Mom's questions                    | Ongoing  |                               |

---

### Mom (Ops Director) Tasks

| Task                                      | Duration | Notes                         |
| ----------------------------------------- | -------- | ----------------------------- |
| **Independent call session (2 hrs max)**  | 2 hrs    | 8–12 calls, McCabe on standby |
| Process signature queue items             | 30 min   | Approve/reject with notes     |
| Document: call outcomes in Console        | 30 min   | Use notes field               |
| Review pipeline: identify any stuck cases | 15 min   | Flag to McCabe                |

---

### Technical Tasks

```
[ ] Prepare: 60-judgment CSV
[ ] Run: dry-run import (dev) → no errors
[ ] Run: live import (dev) → 60 plaintiffs created (100 total)
[ ] Run: enrich_worker (dev) → all enriched
[ ] Performance: Console loads pipeline in <3s
[ ] Performance: Call queue loads in <2s
[ ] Set up: Worker monitoring/alerting
[ ] Verify: No stuck cases in pipeline
```

---

### Financial Control Actions

| Action                       | Owner | Status |
| ---------------------------- | ----- | ------ |
| $50K Tranche 2 wired to JBI  | Dad   | ⬜     |
| Wire receipt confirmed       | Dad   | ⬜     |
| Total deployed to JBI: $100K | Dad   | ⬜     |

---

### 🎯 Must-Complete Item

> **100 judgments must be imported and enriched with Console performance acceptable (<3s load times).**
>
> _Rationale: This is the minimum viable scale test before committing to 900._

---

### End-of-Day Review Checklist

```
[ ] 60 new judgments imported (100 total in dev)
[ ] All 100 enriched
[ ] Console performance acceptable
[ ] Mom completed 8+ independent calls
[ ] Signature queue items processed
[ ] Worker monitoring configured
[ ] $50K Tranche 2 wired
[ ] No performance degradation observed
```

---

### Risk Register

| Risk                       | Likelihood | Impact | Mitigation                     |
| -------------------------- | ---------- | ------ | ------------------------------ |
| Enrichment API rate limits | Medium     | Medium | Batch smaller; add delays      |
| Console slow at 100 cases  | Low        | High   | Index views; optimize queries  |
| Mom overwhelmed by volume  | Medium     | Medium | Cap call sessions; take breaks |

---

---

# Day 5: Friday — Go/No-Go Decision

## Day Objective

> Final preflight checks; team alignment; formal Go/No-Go decision for weekend 900 import.

---

### Dad (CEO) Tasks

| Task                                   | Duration | Notes                             |
| -------------------------------------- | -------- | --------------------------------- |
| Wire $25K (Tranche 3) to JBI           | 30 min   | Final tranche = $125K total       |
| **Chair Go/No-Go meeting (all hands)** | 1 hr     | Review checklist, risks, decision |
| Sign off on Go-Live if approved        | 15 min   | Document decision                 |
| Prepare weekend availability schedule  | 15 min   | Who's on call when                |

---

### McCabe (COO/CTO) Tasks

| Task                                                | Duration | Notes                              |
| --------------------------------------------------- | -------- | ---------------------------------- |
| Run full preflight suite against prod               | 1 hr     | `preflight_prod.ps1` must be GREEN |
| Prepare 900-judgment import CSV                     | 1 hr     | Final validation, deduplication    |
| Dry-run 900 import against prod                     | 30 min   | `--dry-run` flag                   |
| Document rollback procedure                         | 30 min   | What to do if import fails         |
| Prepare Go/No-Go checklist for meeting              | 30 min   | Technical readiness assessment     |
| **Present technical readiness at Go/No-Go meeting** | 30 min   |                                    |

---

### Mom (Ops Director) Tasks

| Task                                          | Duration | Notes                               |
| --------------------------------------------- | -------- | ----------------------------------- |
| Morning call session (1 hr)                   | 1 hr     | Continue working 100-case portfolio |
| Prepare ops readiness assessment              | 30 min   | Comfortable with tools? Blockers?   |
| **Present ops readiness at Go/No-Go meeting** | 15 min   |                                     |
| Confirm weekend availability                  | 15 min   | When can you monitor Console?       |

---

### Go/No-Go Meeting Agenda (4:00 PM)

```
1. Financial Status (Dad) — 5 min
   - JBI payments complete?
   - Ops reserve confirmed?

2. Technical Readiness (McCabe) — 15 min
   - Preflight results
   - 100-case performance metrics
   - Import dry-run results
   - Rollback procedure

3. Ops Readiness (Mom) — 10 min
   - Comfort with Console
   - Call workflow validated
   - Questions/concerns

4. Risk Review (All) — 10 min
   - Top 3 risks for 900 import
   - Mitigations confirmed

5. Decision (Dad) — 5 min
   - GO / NO-GO / CONDITIONAL GO

6. If GO: Schedule (McCabe) — 5 min
   - Import window: Saturday 10 AM
   - Monitoring plan
   - Escalation contacts
```

---

### Technical Tasks

```
[ ] Run: preflight_prod.ps1 → must be GREEN
[ ] Prepare: 900-judgment import CSV (final)
[ ] Run: dry-run 900 import (prod) → no errors
[ ] Document: rollback procedure
[ ] Prepare: Go/No-Go technical checklist
[ ] Present: technical readiness
```

---

### Financial Control Actions

| Action                       | Owner | Status |
| ---------------------------- | ----- | ------ |
| $25K Tranche 3 wired to JBI  | Dad   | ⬜     |
| Wire receipt confirmed       | Dad   | ⬜     |
| Total deployed to JBI: $125K | Dad   | ⬜     |
| Go/No-Go decision documented | Dad   | ⬜     |

---

### 🎯 Must-Complete Item

> **Go/No-Go meeting must occur with formal decision documented.**
>
> _Rationale: No 900 import without explicit team alignment._

---

### Go/No-Go Checklist

| Criterion                           | Required | Status |
| ----------------------------------- | -------- | ------ |
| `preflight_prod.ps1` = GREEN        | ✓        | ⬜     |
| 900 import dry-run = no errors      | ✓        | ⬜     |
| $125K wired to JBI                  | ✓        | ⬜     |
| Bank account operational            | ✓        | ⬜     |
| Console deployed to production URL  | ✓        | ⬜     |
| Mom completed 10+ independent calls | ✓        | ⬜     |
| Rollback procedure documented       | ✓        | ⬜     |
| Weekend availability confirmed      | ✓        | ⬜     |

**Decision:** ⬜ GO / ⬜ NO-GO / ⬜ CONDITIONAL GO

---

### End-of-Day Review Checklist

```
[ ] preflight_prod.ps1 = GREEN
[ ] 900 import dry-run successful
[ ] $25K Tranche 3 wired (total: $125K)
[ ] Go/No-Go meeting held
[ ] Decision documented
[ ] Weekend schedule confirmed
[ ] Rollback procedure ready
```

---

### Risk Register

| Risk                    | Likelihood | Impact | Mitigation                              |
| ----------------------- | ---------- | ------ | --------------------------------------- |
| Preflight fails on prod | Low        | High   | Fix blocking issues; delay if needed    |
| Team not aligned        | Low        | High   | Meeting resolves; NO-GO if disagreement |
| Wire delay              | Low        | High   | Send early; confirm before meeting      |

---

---

# Day 6: Saturday — 900 Import Go-Live

## Day Objective

> Execute full 900-judgment import; monitor for issues; validate production pipeline.

---

## 🚀 GO-LIVE WINDOW: Saturday 10:00 AM – 2:00 PM

_All team members available. McCabe leads technical execution._

---

### Dad (CEO) Tasks

| Task                                       | Duration | Notes                      |
| ------------------------------------------ | -------- | -------------------------- |
| Morning check-in with team (Slack/Discord) | 15 min   | Confirm everyone ready     |
| Monitor import progress remotely           | 1 hr     | McCabe leads; Dad observes |
| Post-import: review pipeline summary       | 30 min   | How many cases per tier?   |
| Draft "Day 1 Complete" memo for records    | 30 min   | Internal documentation     |

---

### McCabe (COO/CTO) Tasks

| Task                                         | Duration | Notes                         |
| -------------------------------------------- | -------- | ----------------------------- |
| **Execute 900-judgment import (prod)**       | 2 hrs    | With team on standby          |
| Monitor import progress (batches of 100–200) | Ongoing  | Log any errors                |
| Run enrichment worker on full batch          | 2–3 hrs  | May run in background         |
| Verify tier assignment for all 900           | 30 min   | Spot check + aggregate counts |
| Validate Console with 900 cases              | 30 min   | Performance acceptable?       |
| Post status updates to Discord               | Ongoing  | Every 30 min during import    |
| Document any issues encountered              | Ongoing  | For post-mortem               |

---

### Mom (Ops Director) Tasks

| Task                                     | Duration | Notes                                |
| ---------------------------------------- | -------- | ------------------------------------ |
| Morning availability: on standby         | 2 hrs    | Monitor Discord; available for calls |
| Post-import: review call queue           | 30 min   | See new cases populated              |
| Post-import: 3–5 test calls on new cases | 1 hr     | Validate data accuracy               |
| Flag any data issues to McCabe           | Ongoing  | Wrong phone numbers, etc.            |

---

### Import Execution Runbook

```bash
# Step 1: Final preflight (10:00 AM)
./scripts/preflight_prod.ps1

# Step 2: Backup existing data (10:15 AM)
# (Document current plaintiff count)

# Step 3: Execute import in batches (10:30 AM – 12:30 PM)
$env:SUPABASE_MODE = "prod"
python -m tools.run_import --source jbi --csv data/jbi_900_final.csv --batch-name "golive-900" --commit

# Step 4: Run enrichment (12:30 PM – 2:00 PM)
python -m tools.enrich_worker --env prod --verbose

# Step 5: Verify tier assignment (2:00 PM)
python -m tools.doctor --env prod

# Step 6: Validate Console (2:15 PM)
# Manual check: load pipeline, call queue, signature queue
```

---

### Technical Tasks

```
[ ] Final preflight: GREEN
[ ] 900 import executed
[ ] Enrichment worker completed
[ ] Tier assignment verified
[ ] Console performance validated
[ ] Discord updates posted
[ ] Issues documented
```

---

### 🎯 Must-Complete Item

> **900 judgments must be imported, enriched, and visible in Console by 4:00 PM.**
>
> _Rationale: This is the core deliverable for the week._

---

### End-of-Day Review Checklist

```
[ ] 900 plaintiffs imported to prod
[ ] All 900 enriched (or enrichment in progress)
[ ] Tier assignment visible
[ ] Console loads pipeline <5s at 900 scale
[ ] Mom tested 3–5 calls on new data
[ ] No critical errors
[ ] "Day 1 Complete" memo drafted
```

---

### Risk Register

| Risk                         | Likelihood | Impact | Mitigation                         |
| ---------------------------- | ---------- | ------ | ---------------------------------- |
| Import fails mid-batch       | Low        | High   | Rollback procedure; retry          |
| Enrichment API overload      | Medium     | Medium | Batch smaller; spread over time    |
| Console performance degrades | Low        | High   | Optimize queries; increase timeout |
| Data quality issues          | Medium     | Medium | Flag and fix; don't block ops      |

---

### Rollback Procedure (If Needed)

```sql
-- If import fails catastrophically, revert:
-- 1. Identify bad batch by batch_name
-- 2. Delete plaintiffs with that batch
-- 3. Reset import state
-- 4. Investigate root cause before retry

DELETE FROM plaintiffs WHERE batch_name = 'golive-900';
-- Confirm count before executing
```

---

---

# Day 7: Sunday — Stabilization & Week 1 Review

## Day Objective

> Monitor production stability; address issues; prepare for Week 2 operations.

---

### Dad (CEO) Tasks

| Task                                | Duration  | Notes                                   |
| ----------------------------------- | --------- | --------------------------------------- |
| Review pipeline summary with McCabe | 30 min    | Tier distribution, any anomalies        |
| Draft Week 1 summary for records    | 1 hr      | What went well, what to improve         |
| Plan Week 2 priorities              | 30 min    | First enforcement filings, call targets |
| Rest / family time                  | Afternoon | Avoid burnout                           |

---

### McCabe (COO/CTO) Tasks

| Task                                 | Duration  | Notes                             |
| ------------------------------------ | --------- | --------------------------------- |
| Morning: check enrichment completion | 30 min    | All 900 should be enriched by now |
| Run `tools.doctor --env prod`        | 15 min    | Verify health                     |
| Review any overnight errors/alerts   | 30 min    | Discord, logs                     |
| Fix any critical issues              | As needed |                                   |
| Document lessons learned             | 1 hr      | `docs/week_1_retrospective.md`    |
| Prepare Week 2 technical priorities  | 30 min    |                                   |
| Afternoon off                        | —         | Avoid burnout                     |

---

### Mom (Ops Director) Tasks

| Task                                | Duration  | Notes                                  |
| ----------------------------------- | --------- | -------------------------------------- |
| Morning: review call queue (30 min) | 30 min    | Familiarize with 900-case volume       |
| Light call session (1 hr max)       | 1 hr      | 5–10 calls to get comfortable          |
| Flag any urgent issues              | As needed |                                        |
| Prepare personal Week 2 plan        | 30 min    | Call targets, signature review cadence |
| Afternoon off                       | —         | Avoid burnout                          |

---

### Technical Tasks

```
[ ] Verify: all 900 enriched
[ ] Run: tools.doctor --env prod → GREEN
[ ] Review: overnight logs/alerts
[ ] Fix: any critical issues
[ ] Document: lessons learned
[ ] Prepare: Week 2 priorities
```

---

### 🎯 Must-Complete Item

> **Week 1 summary document must be drafted and all critical issues resolved.**
>
> _Rationale: Clean handoff to Week 2 operations._

---

### End-of-Day / End-of-Week Review Checklist

```
[ ] All 900 plaintiffs enriched
[ ] Pipeline healthy (doctor = GREEN)
[ ] No critical production issues
[ ] Week 1 summary drafted
[ ] Week 2 priorities identified
[ ] Team well-rested for Monday
```

---

### Risk Register

| Risk                        | Likelihood | Impact | Mitigation                         |
| --------------------------- | ---------- | ------ | ---------------------------------- |
| Enrichment still running    | Medium     | Low    | Let it complete; monitor           |
| Production issue discovered | Low        | Medium | Fix immediately or flag for Monday |
| Team burnout                | Medium     | Medium | Enforce afternoon off              |

---

---

## Week 1 Summary: Key Metrics to Track

| Metric                          | Target   | Actual |
| ------------------------------- | -------- | ------ |
| Plaintiffs imported             | 900      | ⬜     |
| Plaintiffs enriched             | 900      | ⬜     |
| Tier 1 (high priority)          | ~XX      | ⬜     |
| Tier 2 (medium priority)        | ~XX      | ⬜     |
| Tier 3 (low priority)           | ~XX      | ⬜     |
| Mom's calls completed           | 20+      | ⬜     |
| Signature queue items processed | 5+       | ⬜     |
| Capital deployed to JBI         | $125,000 | ⬜     |
| Production issues (P1)          | 0        | ⬜     |
| Preflight status                | GREEN    | ⬜     |

---

## Week 2 Preview

| Day       | Focus                                              |
| --------- | -------------------------------------------------- |
| Monday    | First enforcement filings (garnishments on Tier 1) |
| Tuesday   | Call campaign ramp-up (target: 30 calls)           |
| Wednesday | Settlement negotiation training                    |
| Thursday  | First demand letters sent                          |
| Friday    | Weekly review + Week 2 retrospective               |

---

## Appendix A: Contact List

| Role         | Name   | Phone        | Email                     | Availability   |
| ------------ | ------ | ------------ | ------------------------- | -------------- |
| CEO          | Dad    | XXX-XXX-XXXX | dad@dragonflycivil.com    | Business hours |
| COO/CTO      | McCabe | XXX-XXX-XXXX | mccabe@dragonflycivil.com | Extended       |
| Ops Director | Mom    | XXX-XXX-XXXX | mom@dragonflycivil.com    | Business hours |

---

## Appendix B: Escalation Matrix

| Issue Type                    | First Contact | Escalation                |
| ----------------------------- | ------------- | ------------------------- |
| Console not loading           | McCabe        | —                         |
| Import failure                | McCabe        | Dad (if financial impact) |
| Compliance question           | Mom           | Dad (if legal decision)   |
| Debtor threatens legal action | Mom           | Dad (immediate)           |
| Capital/wire issues           | Dad           | —                         |

---

## Appendix C: Document References

| Document             | Location                                       |
| -------------------- | ---------------------------------------------- |
| Corporate Shell      | `docs/corporate_shell.md`                      |
| Compliance Manual    | `docs/compliance_manual_v1.md`                 |
| Mom's Desk Card      | `docs/mom_desk_card.md`                        |
| Scripts & Templates  | `docs/scripts_and_templates.md`                |
| Brand Story          | `docs/brand_story.md`                          |
| Website Copy         | `docs/website_copy.md`                         |
| Investor Deck        | `docs/investor_deck_outline.md`                |
| Deployment Checklist | `docs/deployment_checklist.md` (to be created) |

---

## Appendix D: Daily Standup Template

```
## Daily Standup — [DATE]

### Dad (CEO)
- Yesterday:
- Today:
- Blockers:

### McCabe (COO/CTO)
- Yesterday:
- Today:
- Blockers:

### Mom (Ops Director)
- Yesterday:
- Today:
- Blockers:

### Key Metrics
- Plaintiffs: XXX
- Calls Today: XX
- Signatures Pending: XX
- Issues: X
```

---

## Sign-Off

| Role         | Name   | Signature      | Date         |
| ------------ | ------ | -------------- | ------------ |
| CEO          | Dad    | ****\_\_\_**** | **_/_**/2025 |
| COO/CTO      | McCabe | ****\_\_\_**** | **_/_**/2025 |
| Ops Director | Mom    | ****\_\_\_**** | **_/_**/2025 |

---

_This document is a living plan. Update daily as execution progresses._
