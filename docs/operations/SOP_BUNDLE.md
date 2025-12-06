# Dragonfly Civil — Standard Operating Procedures

> **Version:** 1.0 | **Effective:** December 2025 | **Classification:** Internal Operations

---

## Table of Contents

1. [CEO Morning Routine](#1-ceo-morning-routine)
2. [Ops Intake Routine](#2-ops-intake-routine)
3. [Offer Script](#3-offer-script)

---

## 1. CEO Morning Routine

### Purpose

Identify high-value "Buy Candidates" using the Enforcement Radar before the market opens.

### Time Required

15–20 minutes

### Checklist

| Step | Action                                                                | Verification                                    |
| ---- | --------------------------------------------------------------------- | ----------------------------------------------- |
| ☐    | **Open Radar Dashboard** — Navigate to `Enforcement → Radar`          | Page loads with KPI strip visible               |
| ☐    | **Check KPIs** — Review Total Pipeline, Avg Score, and Pending Offers | Note any significant changes from yesterday     |
| ☐    | **Apply "Buy Candidate" Filter** — Set Score ≥ 75, Tier = A or B      | Table filters to high-value cases               |
| ☐    | **Sort by Judgment Amount** — Descending order                        | Largest opportunities appear first              |
| ☐    | **Review Top 10 Cases** — Click each row to open Detail Drawer        | —                                               |
| ☐    | **Check Scorecard Tab** — Verify collectability breakdown             | Flag cases with Employment ≥ 60, Assets ≥ 50    |
| ☐    | **Check Intelligence Tab** — Review debtor entities                   | Confirm employer/asset data is fresh (<30 days) |
| ☐    | **Check Offers Tab** — Review offer history                           | Note any pending or rejected offers             |
| ☐    | **Mark Priority Cases** — Star or tag top 3–5 for same-day action     | Use internal notes field                        |
| ☐    | **Export Daily List** — Download CSV of filtered results              | Save to `data_out/radar_YYYYMMDD.csv`           |

### Decision Criteria for "Buy Candidate"

```
┌─────────────────────────────────────────────────────────┐
│  ✓ Collectability Score ≥ 75                            │
│  ✓ Judgment Amount ≥ $5,000                             │
│  ✓ Known Employer OR Known Asset                        │
│  ✓ Debtor Age < 65 (if available)                       │
│  ✓ No prior rejected offers in last 90 days             │
└─────────────────────────────────────────────────────────┘
```

### Escalation

If the Radar shows 0 results or errors, contact Engineering via Slack `#dragonfly-ops`.

---

## 2. Ops Intake Routine

### Purpose

Upload plaintiff/judgment CSVs from vendors and verify enrichment pipeline health.

### Time Required

10–15 minutes per batch

### Pre-Upload Checklist

| Step | Action                                                             | Verification                  |
| ---- | ------------------------------------------------------------------ | ----------------------------- |
| ☐    | **Obtain CSV from vendor** — Simplicity, JBI, or manual export     | File is `.csv` format         |
| ☐    | **Validate file structure** — Open in Excel/Sheets, check headers  | Headers match expected schema |
| ☐    | **Check row count** — Note total rows for post-upload verification | Record: `_____ rows`          |
| ☐    | **Remove duplicates** — Filter for duplicate case numbers          | Deduplicated file saved       |

### Upload Procedure

| Step | Action                                                       | Verification                          |
| ---- | ------------------------------------------------------------ | ------------------------------------- |
| ☐    | **Navigate to Intake Portal** — `Operations → Intake Upload` | Upload form visible                   |
| ☐    | **Select Source System** — Choose vendor from dropdown       | Correct vendor selected               |
| ☐    | **Upload CSV** — Drag/drop or click to browse                | File name appears in uploader         |
| ☐    | **Review Preview** — Check first 5 rows in preview table     | Data looks correct                    |
| ☐    | **Click "Submit Batch"** — Confirm upload                    | Toast: "Batch submitted successfully" |
| ☐    | **Record Batch ID** — Copy the returned batch UUID           | Batch ID: `________________`          |

### Post-Upload Verification

| Step | Action                                                              | Verification                            |
| ---- | ------------------------------------------------------------------- | --------------------------------------- |
| ☐    | **Check Enrichment Health** — Navigate to `Ops → Enrichment Health` | View loads without errors               |
| ☐    | **Verify Batch Appears** — Find your batch in the list              | Status shows "Processing" or "Complete" |
| ☐    | **Monitor Progress** — Refresh every 2–3 minutes                    | Progress bar advances                   |
| ☐    | **Check Success Rate** — After completion, verify success %         | Target: ≥ 95% success                   |
| ☐    | **Review Failed Rows** — If failures exist, download error report   | Save to `data_error/`                   |
| ☐    | **Run Doctor Check** — Execute `tools.doctor_all --env dev`         | All checks pass                         |

### Enrichment Health Metrics

| Metric                | Target       | Action if Below                    |
| --------------------- | ------------ | ---------------------------------- |
| Success Rate          | ≥ 95%        | Review failed rows, contact vendor |
| Avg Processing Time   | < 30 sec/row | Check API quotas                   |
| Stale Data (>30 days) | < 10%        | Trigger re-enrichment              |

### Troubleshooting

| Issue                    | Resolution                         |
| ------------------------ | ---------------------------------- |
| "Invalid CSV format"     | Check encoding (UTF-8), remove BOM |
| "Duplicate case number"  | Already in system; skip or update  |
| "Enrichment timeout"     | Retry after 5 minutes              |
| Batch stuck "Processing" | Contact Engineering                |

---

## 3. Offer Script

### Purpose

Standardized phone script for contacting plaintiffs about judgment purchase offers.

### Pre-Call Preparation

| Step | Action                                                  |
| ---- | ------------------------------------------------------- |
| ☐    | Review case in Radar Detail Drawer                      |
| ☐    | Note judgment amount and debtor name                    |
| ☐    | Calculate offer range (typically 10–30 cents on dollar) |
| ☐    | Review prior contact history in Offers Tab              |
| ☐    | Have offer form ready to submit                         |

---

### Phone Script

#### Opening (0–30 seconds)

> **"Good [morning/afternoon], may I speak with [PLAINTIFF NAME]?**
>
> **This is [YOUR NAME] calling from Dragonfly Civil regarding your judgment against [DEBTOR NAME]. Do you have a few minutes to discuss an opportunity?"**

_If they ask who we are:_

> **"Dragonfly Civil is a judgment acquisition company. We purchase court-awarded judgments from plaintiffs like yourself."**

---

#### Value Proposition (30–60 seconds)

> **"I'm reaching out because we've reviewed your judgment for [AMOUNT] against [DEBTOR NAME], entered on [DATE].**
>
> **As you may know, collecting on a judgment can take years and often requires additional legal fees with no guarantee of recovery.**
>
> **We're prepared to make you a cash offer today, which means you receive funds within [TIMEFRAME] without any further effort or expense on your part."**

---

#### Presenting the Offer (60–90 seconds)

> **"Based on our analysis, we're prepared to offer you [OFFER AMOUNT] for the full assignment of this judgment.**
>
> **This represents approximately [X] cents on the dollar, which reflects the collectability factors we've assessed.**
>
> **The payment would be made via [wire transfer/certified check] within [3–5 business days] of completing the paperwork."**

---

#### Handling Objections

| Objection                              | Response                                                                                                                                            |
| -------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| **"That's too low"**                   | "I understand. Our offer reflects the current collectability. What amount would you consider fair? I can discuss with my team."                     |
| **"I can collect it myself"**          | "Many plaintiffs try that route. Our data shows the average collection timeline is [X years] with a [Y%] success rate. We remove that uncertainty." |
| **"I need to think about it"**         | "Absolutely. This offer is valid for [7 days]. May I follow up with you on [DATE]? What's the best number to reach you?"                            |
| **"How do I know you're legitimate?"** | "Great question. We're registered in [STATE], and I can email you our company information and references. Would you like that?"                     |
| **"I already have an attorney"**       | "We work with attorneys regularly. Would you prefer I contact your attorney directly, or would you like to discuss with them first?"                |

---

#### Closing (90–120 seconds)

_If interested:_

> **"Excellent. Here's what happens next:**
>
> 1. **I'll email you the purchase agreement today.**
> 2. **You review and sign — we use DocuSign for convenience.**
> 3. **Once signed, we initiate payment within [3 business days].**
>
> **What email address should I send the documents to?"**

_If not interested:_

> **"I understand. If your situation changes, please don't hesitate to reach out. May I send you my contact information for your records?**
>
> **Thank you for your time, [PLAINTIFF NAME]. Have a great [day/evening]."**

---

#### Post-Call Actions

| Step | Action                                                                   |
| ---- | ------------------------------------------------------------------------ |
| ☐    | **Log call outcome** — In Radar, click "Make Offer" or update notes      |
| ☐    | **Record offer details** — Amount, type (purchase/contingency), response |
| ☐    | **Schedule follow-up** — If callback requested, add to calendar          |
| ☐    | **Send documents** — If accepted, trigger DocuSign workflow              |
| ☐    | **Update status** — Change plaintiff status if appropriate               |

---

### Compliance Reminders

```
┌─────────────────────────────────────────────────────────┐
│  ⚠️  DO NOT discuss debtor's personal information       │
│  ⚠️  DO NOT guarantee specific collection outcomes      │
│  ⚠️  DO NOT pressure or use high-pressure tactics       │
│  ⚠️  DO record all offers in the system immediately     │
│  ⚠️  DO respect "Do Not Call" requests                  │
│  ⚠️  DO follow TCPA guidelines for call timing          │
└─────────────────────────────────────────────────────────┘
```

---

## Revision History

| Version | Date     | Author   | Changes         |
| ------- | -------- | -------- | --------------- |
| 1.0     | Dec 2025 | Ops Team | Initial release |

---

_For questions or updates to these procedures, contact the Operations Manager or submit a PR to `docs/operations/`._
