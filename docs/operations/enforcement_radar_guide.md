# Enforcement Radar — Operator Guide

> **Audience:** Dragonfly leadership and operations staff  
> **Last Updated:** December 2025  
> **Owner:** COO

---

## What Is the Enforcement Radar?

The **Enforcement Radar** is your daily command center for identifying which judgments to pursue. It ranks every active judgment by collectability and recommends an action strategy—so you know exactly where to focus your time and capital.

Think of it as a "hot list" that answers: **"Which cases should I call today, and why?"**

---

## What You See on the Page

| Column                   | What It Means                                                         |
| ------------------------ | --------------------------------------------------------------------- |
| **Plaintiff**            | The creditor we're working for                                        |
| **Defendant**            | The debtor who owes money                                             |
| **Judgment Amount**      | Dollar value of the judgment                                          |
| **Court / County**       | Where the judgment was filed                                          |
| **Judgment Date**        | When the court entered judgment                                       |
| **Collectability Score** | 0–100 score predicting how likely we are to recover (higher = better) |
| **Offer Strategy**       | Our recommended approach for this case (see below)                    |
| **Status**               | Current workflow stage                                                |

### Sorting & Filtering

- Click any **column header** to sort (e.g., click "Collectability Score" to see highest-scoring cases first).
- Use the **Offer Strategy** dropdown to filter by action type.
- Click any row to open a **detail drawer** with full case information.

---

## Offer Strategy Bands

Every judgment gets classified into one of four buckets based on its collectability score and judgment amount:

| Strategy                  | Criteria                                   | What It Means                                       | Your Action                                                  |
| ------------------------- | ------------------------------------------ | --------------------------------------------------- | ------------------------------------------------------------ |
| 🟢 **BUY_CANDIDATE**      | Score ≥ 70 AND Amount ≥ $10,000            | High confidence, high value. Worth buying outright. | **Call immediately.** Make a cash offer to the plaintiff.    |
| 🟡 **CONTINGENCY**        | Score ≥ 40 (but doesn't meet buy criteria) | Decent odds, but not strong enough to buy.          | **Offer contingency collection.** We take a % if we collect. |
| ⚪ **ENRICHMENT_PENDING** | Score is NULL (not yet calculated)         | We haven't run data enrichment yet.                 | **Wait.** The system will score it automatically.            |
| 🔴 **LOW_PRIORITY**       | Score < 40                                 | Low likelihood of recovery.                         | **Deprioritize.** Check back later if circumstances change.  |

---

## Morning Checklist ☀️

Follow this routine every business day:

### 1. Open the Radar

Navigate to **Radar** in the sidebar (or go directly to `/radar`).

### 2. Work the Buy Candidates First

1. Filter: **Offer Strategy = BUY_CANDIDATE**
2. Sort by **Collectability Score** (descending)
3. Call the **top 5–10 plaintiffs**
4. For each:
   - Open the detail drawer
   - Review defendant info
   - Make your offer

### 3. Then Work Contingency Cases

1. Filter: **Offer Strategy = CONTINGENCY**
2. Sort by **Judgment Amount** (descending)
3. Call or email the **top 10–15 plaintiffs**
4. Pitch our contingency collection service

### 4. Check the Enrichment Health Widget

Glance at the status indicator in the top-right of the Ops page. See the next section for what each status means.

### 5. Export If Needed

Click **Export CSV** to download the current filtered list for tracking or sharing with your team.

---

## Understanding the Enrichment Health Widget

The Enrichment Health widget shows the status of our background data enrichment jobs (TLO lookups, asset searches, etc.).

### Status Indicators

| Status       | Color     | What It Means                     | What To Do                                                                                       |
| ------------ | --------- | --------------------------------- | ------------------------------------------------------------------------------------------------ |
| **Healthy**  | 🟢 Green  | Jobs are processing normally.     | Nothing—carry on.                                                                                |
| **Idle**     | ⚪ Gray   | No jobs running and none pending. | Normal if we haven't imported new data recently.                                                 |
| **Backlog**  | 🟡 Yellow | More than 100 jobs pending.       | Jobs are queued but workers may be slow. Check back in 30 min. If it persists, ping engineering. |
| **Degraded** | 🔴 Red    | One or more jobs have failed.     | **Alert engineering immediately.** Failed jobs mean some judgments aren't getting scored.        |

### Reading the Numbers

- **Pending:** Jobs waiting to run
- **Processing:** Jobs currently running
- **Completed:** Successfully finished (last 24h)
- **Failed:** Jobs that errored out
- **Last Activity:** How long since the last job completed

If you see **Failed > 0**, click "View queue" to see which jobs failed, then notify the dev team.

---

## Frequently Asked Questions

### "Why is the collectability score NULL for some cases?"

**Answer:** The score gets calculated by our enrichment workers after we import a judgment. If you see `ENRICHMENT_PENDING`, it means:

- The case was just imported, or
- The enrichment job hasn't run yet, or
- (Rarely) The job failed silently

**What to do:** Wait 1–2 hours. If it's still NULL, check the Enrichment Health widget for failures.

---

### "Why don't some judgments appear on the Radar?"

**Answer:** The Radar only shows judgments where:

- Status is NOT "Satisfied" (already paid)
- Status is NOT "Expired" (too old to enforce)

If a judgment isn't appearing:

1. Check if it was marked Satisfied or Expired
2. Verify it was successfully imported (check the Data Ingestion page)
3. Search for it by case number in the Cases page

---

### "A judgment has a high score but low amount—should I still call?"

**Answer:** Probably not as a buy candidate. High score + low amount = easy to collect but not worth our capital. These are perfect **contingency** cases—offer to collect for a percentage.

---

### "The score seems wrong—the defendant is clearly broke."

**Answer:** The score is based on data we have (asset records, employment, property). If you have personal knowledge that contradicts the score:

1. Make a note in the case
2. Override your action accordingly
3. Tell engineering so we can improve the model

The score is a guide, not gospel. Your judgment matters.

---

### "What does 'Last Activity: 3h ago' mean?"

**Answer:** It means the last enrichment job completed 3 hours ago. If this number is very high (e.g., "2d ago") and you have pending jobs, the workers may be stuck. Notify engineering.

---

### "Can I change a case's offer strategy manually?"

**Answer:** Not directly—the strategy is calculated automatically. But you can:

1. Override the score if you have better intel
2. Change the case status to remove it from the Radar
3. Add notes explaining why you're treating it differently

---

## Quick Reference Card

```
┌─────────────────────────────────────────────────────────┐
│  MORNING ROUTINE                                        │
├─────────────────────────────────────────────────────────┤
│  1. Open Radar                                          │
│  2. Filter → BUY_CANDIDATE → Call top 5-10              │
│  3. Filter → CONTINGENCY → Call/email top 10-15         │
│  4. Check Enrichment Health (green = good)              │
│  5. Export CSV if needed for tracking                   │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│  ENRICHMENT HEALTH CHEAT SHEET                          │
├─────────────────────────────────────────────────────────┤
│  🟢 Healthy     → All good                              │
│  ⚪ Idle        → Normal if no new imports              │
│  🟡 Backlog     → Wait 30 min, then escalate            │
│  🔴 Degraded    → Alert engineering NOW                 │
└─────────────────────────────────────────────────────────┘
```

---

## Questions?

If something looks wrong or you're unsure how to proceed, reach out to the engineering team via Slack (#dragonfly-ops) or email.

**Remember:** The Radar is a tool to help you prioritize. Trust your instincts when the data doesn't match reality—and let us know so we can make the system smarter.
