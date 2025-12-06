# Dragonfly Civil – CEO Guide

**Executive Reference Manual for Daily Operations**

_Version 1.0 | December 2025_

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Dad's Daily Screens](#2-dads-daily-screens)
3. [Enforcement Radar Metrics](#3-enforcement-radar-metrics)
4. [Offer Engine Prioritization](#4-offer-engine-prioritization)
5. [Mom's Ops Console](#5-moms-ops-console)
6. [Definitions & Glossary](#6-definitions--glossary)
7. [Troubleshooting Guide](#7-troubleshooting-guide)

---

## 1. Architecture Overview

Dragonfly Civil is a judgment enforcement operating system that connects plaintiffs with enforcement actions through intelligent prioritization.

### System Components

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         DRAGONFLY ARCHITECTURE                          │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│   ┌──────────────┐    ┌──────────────┐    ┌──────────────┐             │
│   │   INTAKE     │───>│  ENRICHMENT  │───>│   SCORING    │             │
│   │   Gateway    │    │   Workers    │    │   Engine     │             │
│   └──────────────┘    └──────────────┘    └──────────────┘             │
│          │                   │                   │                      │
│          v                   v                   v                      │
│   ┌─────────────────────────────────────────────────────────┐          │
│   │                    SUPABASE / POSTGRES                   │          │
│   │  ┌────────────┐  ┌────────────┐  ┌────────────────┐     │          │
│   │  │ plaintiffs │  │ judgments  │  │ enforcement_   │     │          │
│   │  │            │  │            │  │ actions        │     │          │
│   │  └────────────┘  └────────────┘  └────────────────┘     │          │
│   └─────────────────────────────────────────────────────────┘          │
│          │                   │                   │                      │
│          v                   v                   v                      │
│   ┌──────────────┐    ┌──────────────┐    ┌──────────────┐             │
│   │   CALL       │    │ ENFORCEMENT  │    │    OFFER     │             │
│   │   QUEUE      │    │    RADAR     │    │    ENGINE    │             │
│   └──────────────┘    └──────────────┘    └──────────────┘             │
│                                                                         │
│                    ┌──────────────────────┐                            │
│                    │  DRAGONFLY DASHBOARD │                            │
│                    │    (React + Vite)    │                            │
│                    └──────────────────────┘                            │
└─────────────────────────────────────────────────────────────────────────┘
```

### Data Flow

1. **Intake Gateway** – Plaintiffs submit judgment data via CSV import or manual entry
2. **Enrichment Workers** – Background jobs enhance cases with skip-trace data, asset discovery, and employment info
3. **Scoring Engine** – Calculates collectability scores (0–100) based on enrichment data
4. **Offer Engine** – Assigns offer strategies (BUY, CONTINGENCY, LOW_PRIORITY) based on score + judgment value
5. **Dashboard** – Visualizes the pipeline for CEO enforcement decisions and Ops call management

### Technology Stack

| Component   | Technology                          |
| ----------- | ----------------------------------- |
| Database    | Supabase (PostgreSQL)               |
| Backend API | FastAPI + Uvicorn on Railway        |
| Frontend    | React + TypeScript + Vite on Vercel |
| Workers     | Background Python jobs (n8n/cron)   |
| Auth        | API key authentication              |

---

## 2. Dad's Daily Screens

### Screen 1: Enforcement Radar (`/radar`)

**Purpose:** Your daily command center for identifying which judgments to pursue.

**When to use:** Every morning at 9:00 AM during the "Review Actionable Liquidity" block.

**Key features:**

- KPI strip showing Buy Candidates, Contingency cases, and Actionable Liquidity
- Sortable/filterable data table with all active judgments
- Click any row to open the Case Detail drawer
- Export to CSV for offline analysis

**Morning checklist:**

1. Filter to **BUY_CANDIDATE** → Sort by Score → Call top 5–10 plaintiffs
2. Filter to **CONTINGENCY** → Sort by Amount → Pitch top 10–15 plaintiffs
3. Check Enrichment Health widget (top-right) – Green = healthy

### Screen 2: Pipeline Dashboard (`/pipeline`)

**Purpose:** Bird's-eye view of the entire enforcement funnel.

**Key metrics displayed:**

- Total Active Cases
- Cases by Stage (Intake → Enrichment → Scoring → Enforcement)
- Tier breakdown (Tier A / Tier B / Tier C)
- Weekly velocity trends

### Screen 3: Executive Scoreboard

**Purpose:** CEO-level KPIs at a glance.

**Metrics:**

- **Actionable Liquidity** – Total $ available for immediate collection
- **Recovery Velocity** – Collections per day/week/month
- **Closure Rate** – Judgments fully resolved
- **Conversion Rate** – Offers accepted / offers made

### Screen 4: Litigation Budget Engine

**Purpose:** Approve weekly enforcement spend.

**Categories tracked:**
| Category | Weekly Cap | Approval Threshold |
|---------------|------------|--------------------------|
| Skip Tracing | $2,500 | Auto-approve |
| Garnishments | $5,000 | CEO approval required |
| Bank Levies | $7,500 | CEO approval required |
| Marshal Fees | $10,000 | CEO approval + ROI > 3:1 |
| FOIL Requests | $500 | Auto-approve |

---

## 3. Enforcement Radar Metrics

### Collectability Score (0–100)

The score predicts how likely we are to recover money from a judgment.

| Range  | Rating    | Action                        |
| ------ | --------- | ----------------------------- |
| 70–100 | 🟢 High   | Great candidates – call first |
| 40–69  | 🟡 Medium | Worth pursuing                |
| 0–39   | ⚪ Low    | Deprioritize                  |
| NULL   | — Pending | Awaiting enrichment           |

**Score Components:**

| Factor           | Weight | Data Source             |
| ---------------- | ------ | ----------------------- |
| Asset Indicators | 30%    | Skip trace / TLO        |
| Employment       | 25%    | Employment verification |
| Banking          | 20%    | Bank account discovery  |
| Judgment Recency | 15%    | Days since judgment     |
| Prior Payments   | 10%    | Payment history         |

### Offer Strategy

| Strategy           | Badge   | Meaning                                     |
| ------------------ | ------- | ------------------------------------------- |
| BUY_CANDIDATE      | 🟢 BUY  | High value + high score. Make a cash offer. |
| CONTINGENCY        | 🟡 CONT | Good candidate for contingency collection.  |
| ENRICHMENT_PENDING | ⚪ PEND | Waiting for skip-trace data.                |
| LOW_PRIORITY       | 🔴 LOW  | Deprioritize – check back later.            |

### KPI Definitions

| KPI                    | Definition                                    |
| ---------------------- | --------------------------------------------- |
| Buy Candidate Count    | Cases with BUY_CANDIDATE strategy             |
| Buy Candidate Value    | Sum of judgment amounts for buy candidates    |
| Contingency Count      | Cases with CONTINGENCY strategy               |
| Total Actionable Value | BUY + CONTINGENCY case values combined        |
| Average Score          | Mean collectability score across scored cases |

---

## 4. Offer Engine Prioritization

### How the Offer Engine Works

The Offer Engine automatically classifies every judgment into an actionable strategy:

```
┌─────────────────────────────────────────────────────────────┐
│                    OFFER ENGINE LOGIC                       │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│   Is collectability_score NULL?                            │
│       YES → ENRICHMENT_PENDING                             │
│       NO  ↓                                                 │
│                                                             │
│   Is score >= 70 AND amount >= $10,000?                    │
│       YES → BUY_CANDIDATE                                  │
│       NO  ↓                                                 │
│                                                             │
│   Is score >= 40 OR amount >= $5,000?                      │
│       YES → CONTINGENCY                                    │
│       NO  → LOW_PRIORITY                                   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Offer Types

| Type        | Description                                         |
| ----------- | --------------------------------------------------- |
| Purchase    | Buy the judgment outright for a lump sum            |
| Contingency | Collect on behalf of plaintiff for a percentage fee |

### Offer Lifecycle

```
offered → negotiation → accepted/rejected/expired
```

| Status      | Meaning                                  |
| ----------- | ---------------------------------------- |
| offered     | Initial offer extended to plaintiff      |
| negotiation | Back-and-forth on terms                  |
| accepted    | Plaintiff agreed – proceed to onboarding |
| rejected    | Plaintiff declined – document reason     |
| expired     | No response after follow-up period       |

---

## 5. Mom's Ops Console

### Primary Screen: Call Queue (`/call-queue`)

**Purpose:** Work through daily outbound calls to plaintiffs.

**Workflow:**

1. Open the Call Queue page from the left navigation
2. Calls are sorted by **Due Date** – most urgent at top
3. For each call:
   - Click the phone icon to dial
   - Let it ring 6+ times; leave voicemail if no answer
   - Click **Log Outcome** to record result
   - Set follow-up date if needed

### Call Outcome Codes

| Outcome              | When to Use                            |
| -------------------- | -------------------------------------- |
| Reached + Next Steps | Spoke with plaintiff, agreed on action |
| Left Voicemail       | No answer, left the standard script    |
| Bad Number           | Line disconnected or wrong number      |
| Do Not Call          | Plaintiff explicitly declined contact  |

### Column Definitions

| Column    | Meaning                                        |
| --------- | ---------------------------------------------- |
| Plaintiff | Name of person to call (click for profile)     |
| Tier      | Priority: A (red) = first, B (amber), C (blue) |
| Due       | When the call should be made (red = overdue)   |
| Status    | New, Follow-up, or Completed                   |
| Contact   | Phone number and contact notes                 |
| Actions   | Buttons: Call, Outcome, Schedule               |

### Secondary Screen: Intake Gateway

**Purpose:** Process new plaintiff submissions.

**Validation checklist:**

- ✅ Plaintiff name (required)
- ✅ Email (valid format)
- ✅ Phone (10-digit US)
- ✅ Judgment amount (> $0)
- ✅ Case number (court format)
- ✅ Judgment date (not future)
- ⚠️ Debtor SSN last 4 (optional)

---

## 6. Definitions & Glossary

### Core Entities

| Term            | Definition                                                       |
| --------------- | ---------------------------------------------------------------- |
| **Plaintiff**   | The judgment creditor – our client who owns the judgment         |
| **Defendant**   | The judgment debtor – the person who owes money                  |
| **Judgment**    | A court order requiring the defendant to pay the plaintiff       |
| **Case Number** | Court-assigned identifier for the judgment (e.g., CV-2024-12345) |

### System Concepts

| Term                     | Definition                                                 |
| ------------------------ | ---------------------------------------------------------- |
| **Intake**               | The process of receiving and validating new plaintiff data |
| **Enrichment**           | Background process that adds skip-trace and asset data     |
| **Collectability Score** | 0–100 rating predicting recovery likelihood                |
| **Offer Strategy**       | System recommendation: BUY, CONTINGENCY, PENDING, or LOW   |

### Enforcement Terms

| Term             | Definition                                                          |
| ---------------- | ------------------------------------------------------------------- |
| **Enforcement**  | Legal actions to collect on a judgment (levies, garnishments, etc.) |
| **Bank Levy**    | Court order to seize funds from debtor's bank account               |
| **Garnishment**  | Court order to collect from debtor's wages                          |
| **Skip Trace**   | Locating a debtor's current address, employer, and assets           |
| **FOIL Request** | Freedom of Information request for public records                   |

### Dashboard Terms

| Term                     | Definition                                                |
| ------------------------ | --------------------------------------------------------- |
| **Radar**                | Enforcement Radar – prioritized list of actionable cases  |
| **Pipeline**             | Funnel view showing cases by stage                        |
| **Call Queue**           | List of plaintiffs due for outbound calls                 |
| **Tier**                 | Priority classification: Tier A (highest), Tier B, Tier C |
| **Actionable Liquidity** | Total $ in cases ready for immediate enforcement          |

### Offer Terms

| Term                | Definition                                                  |
| ------------------- | ----------------------------------------------------------- |
| **Purchase**        | Buy the judgment for a lump-sum cash payment                |
| **Contingency**     | Collect on the judgment for a percentage of recovered funds |
| **Conversion Rate** | Percentage of offers that are accepted                      |

---

## 7. Troubleshooting Guide

### Problem: Radar shows "Unable to Load"

**Symptoms:** Error banner with "Unable to Load Radar" message.

**Diagnosis:**

1. Check if the API is responding: Open `https://api.dragonflycivil.com/health`
2. Look for 401 errors (authentication) in browser console

**Solutions:**

- If 401 error: Verify `VITE_DRAGONFLY_API_KEY` matches `DRAGONFLY_API_KEY` in Railway
- If 500 error: Check Railway logs for backend exceptions
- If network error: Check your internet connection

### Problem: Call Queue is empty

**Symptoms:** No rows in the call queue despite known pending calls.

**Diagnosis:**

1. Click **Refresh** button and wait 10 seconds
2. Check if date filter is limiting results

**Solutions:**

- Expand date range filter to "All Due"
- Run `python -m tools.doctor --env dev` to verify database connectivity
- Check Slack `#daily-ops` for outage notes

### Problem: Collectability scores all showing NULL

**Symptoms:** Every case shows "—" instead of a score.

**Diagnosis:** Enrichment workers may be stalled.

**Solutions:**

1. Check Enrichment Health widget in top-right of Radar
2. Run `python -m tools.doctor_all --env prod` to check queue health
3. If queue is backed up, alert engineering in `#daily-ops`

### Problem: Dashboard login fails

**Symptoms:** "Session expired" or login loop.

**Diagnosis:**

1. Check Caps Lock is off
2. Try incognito window

**Solutions:**

- Clear cookies and try again
- Press `Ctrl+Shift+R` for hard refresh
- If still failing after 2 attempts, ping engineering

### Problem: Offers not saving

**Symptoms:** Click "Submit Offer" but nothing happens.

**Diagnosis:** Check browser console for errors.

**Solutions:**

- Ensure `offer_amount` is greater than 0
- Verify judgment_id is valid
- Check network tab for 400/500 responses

### Emergency Contacts

| Issue Type        | Contact                           |
| ----------------- | --------------------------------- |
| System outage     | Slack `#daily-ops`                |
| Data issues       | Engineering team                  |
| Login problems    | Engineering team                  |
| Process questions | Review this guide or CEO Playbook |

---

## Quick Reference Card

### Dad's Daily Schedule

| Time     | Activity                    | Screen        |
| -------- | --------------------------- | ------------- |
| 9:00 AM  | Review Actionable Liquidity | Radar         |
| 10:00 AM | Approve Litigation Budget   | Budget Engine |
| 1:00 PM  | CEO Calls                   | Radar + Queue |
| 4:00 PM  | Review Recovery Velocity    | Pipeline      |

### Mom's Daily Schedule

| Time     | Activity              | Screen         |
| -------- | --------------------- | -------------- |
| 10:00 AM | Intake Queue Review   | Intake Gateway |
| 11:00 AM | Prioritize Plaintiffs | Pipeline       |
| 2:00 PM  | Paperwork Queue       | Tasks          |
| 4:00 PM  | FOIL Reconciliation   | FOIL Tracker   |

### Key Shortcuts

| Action              | How                                 |
| ------------------- | ----------------------------------- |
| Refresh dashboard   | `Ctrl+R` or Refresh button          |
| Hard refresh        | `Ctrl+Shift+R`                      |
| Export Radar to CSV | Click Download icon in Radar header |
| Open Case Detail    | Click any row in Radar table        |

---

_Last updated: December 2025_
