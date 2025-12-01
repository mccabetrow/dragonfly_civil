# 900-Plaintiff Intake Day Playbook – Dragonfly Civil

**Version:** 1.0  
**Date:** November 28, 2025  
**Authors:** McCabe (Tech), Mom (Ops), Dad (CEO)

---

## 1. Overview

### What Is "900 Day"?

This is the first time we import ~900 real plaintiffs from our vendor pipeline (Simplicity/JBI) into the Dragonfly system and begin live outreach. It's a milestone: proof that our tech, ops, and business model work together.

### The 3 Goals

| #   | Goal                      | Owner  | Success Looks Like                                         |
| --- | ------------------------- | ------ | ---------------------------------------------------------- |
| 1   | **Data Integrity**        | McCabe | Zero duplicate plaintiffs; all rows pass QA; no corruption |
| 2   | **Operational Readiness** | Mom    | Call Queue works; she can log outcomes same-day            |
| 3   | **Executive Visibility**  | Dad    | Metrics dashboard shows import counts + call stats by EOD  |

### Day Phases at a Glance

| Phase             | Time             | Who    | What                                   |
| ----------------- | ---------------- | ------ | -------------------------------------- |
| T-12 Hours        | Night before     | McCabe | Full dry run in dev; GO/NO-GO decision |
| Morning Preflight | 7:00–8:30 AM     | McCabe | Promote to prod; verify systems        |
| Ops Setup         | 8:30–9:00 AM     | Mom    | Log in; test drive; wait for GO        |
| Import Window     | 9:00–10:00 AM    | McCabe | Run real import; QA; send GO           |
| Call Window       | 10:00 AM–1:00 PM | Mom    | First 3-hour calling block             |
| Executive Review  | 1:00–2:00 PM     | Dad    | Review metrics; GO/NO-GO for scale     |
| Evening Wrap-Up   | 5:00–6:00 PM     | All    | Debrief; plan Day 2                    |

---

## 2. T-12 Hours (Night Before) – Founder Checklist

**Owner:** McCabe  
**Location:** Dev environment only

### Command Sequence

Run these in order. Each must pass before proceeding.

```
□ 1. Activate environment
      .\.venv\Scripts\Activate.ps1

□ 2. Run full test suite
      python -m pytest -q
      Expected: All tests pass (green)

□ 3. Push latest migrations to dev
      .\scripts\db_push.ps1 -SupabaseEnv dev
      Expected: "All migrations applied" or "Already up to date"

□ 4. Run schema consistency check
      python -m tools.check_schema_consistency --env dev
      Expected: No errors; warnings OK

□ 5. Run doctor_all (intake + enforcement checks)
      python -m tools.doctor_all --env dev
      Expected: All checks pass

□ 6. Run the 900 dry run
      .\scripts\import_900_dry_run.ps1
      Expected: Completes without [FAIL]; review QA output
```

### GO / NO-GO Criteria

| Criteria           | GO                 | NO-GO                                  |
| ------------------ | ------------------ | -------------------------------------- |
| pytest             | 100% pass          | Any failure                            |
| db_push            | Completes          | Migration error                        |
| schema consistency | 0 errors           | Any error                              |
| doctor_all         | All green          | Any critical fail                      |
| dry_run import     | <5 invalid rows    | ≥5 invalid OR any crash                |
| import_qa          | No critical issues | Duplicate detection OR schema mismatch |

### Communication to Mom & Dad

**If GO:**

> "Dry run passed. We're on for tomorrow at 9 AM. Mom, plan to be at the dashboard by 8:30. Dad, check the Executive Dashboard after 1 PM."

**If NO-GO:**

> "Found an issue in [X]. I'm fixing it tonight / pushing to tomorrow. I'll update you by 10 PM."

---

## 3. Morning of Intake – Technical Preflight (McCabe)

**Time:** 7:00–8:30 AM  
**Environment:** Promoting to PROD

### Command Sequence

```
□ 1. Run preflight for prod
      .\scripts\preflight_prod.ps1
      Expected: All checks pass

□ 2. Push migrations to prod
      .\scripts\db_push.ps1 -SupabaseEnv prod
      Expected: Migrations applied cleanly

□ 3. Run smoke_plaintiffs in prod
      $env:SUPABASE_MODE='prod'; python -m tools.smoke_plaintiffs
      Expected: Views return rows (may be 0, but no errors)

□ 4. Verify v_ops_daily_summary
      -- In Supabase SQL Editor (prod):
      SELECT * FROM v_ops_daily_summary;
      Expected: Returns 1 row with today's date; counts may be 0
```

### Dashboard Verification

```
□ 5. Open Ops Console in browser
      URL: [your-dashboard-url]/ops
      Expected: Page loads; no error banners

□ 6. Open Call Queue
      URL: [your-dashboard-url]/call-queue
      Expected: Page loads; shows empty or demo data

□ 7. Open Executive Dashboard
      URL: [your-dashboard-url]/executive
      Expected: Page loads; metrics cards render (even if 0)
```

### GO / NO-GO for Morning

| Check            | GO        | NO-GO            |
| ---------------- | --------- | ---------------- |
| preflight_prod   | Pass      | Any failure      |
| db_push prod     | Clean     | Migration error  |
| smoke_plaintiffs | No errors | Any error        |
| Dashboard pages  | All load  | Any page crashes |

**If NO-GO:** Do NOT proceed to import. Fix issue first. Text Mom: "Delay – stand by."

---

## 4. Morning of Intake – Ops Setup (Mom)

**Time:** 8:30–9:00 AM  
**Location:** Your computer with dashboard open

### Login Steps

```
□ 1. Open your browser (Chrome recommended)

□ 2. Go to: [dashboard URL]

□ 3. Log in with your credentials
      Username: _______________
      Password: _______________

□ 4. You should see the main navigation
```

### Pages You'll Use Today

| Page            | Purpose                                      | When            |
| --------------- | -------------------------------------------- | --------------- |
| **Call Queue**  | Shows plaintiffs to call, sorted by priority | During calling  |
| **Ops Console** | Log call outcomes; see your stats            | After each call |

### Test Drive (Practice)

```
□ 5. Click "Call Queue" in the navigation

□ 6. Find a test plaintiff (if available) or wait for McCabe's GO

□ 7. Click on one plaintiff row to see details

□ 8. Practice logging a call outcome:
      - Click "Log Call"
      - Select "No Answer"
      - Add a note: "Test call"
      - Click Save
      Expected: Toast message confirms save

□ 9. Refresh the page – the call should appear in history
```

### The Golden Rule

```
┌─────────────────────────────────────────────────────────┐
│  DO NOT START CALLING THE 900 PLAINTIFFS UNTIL         │
│  McCABE SENDS YOU A "GO" MESSAGE.                      │
│                                                         │
│  Wait for: "Mom – GO. Call Queue is live."             │
└─────────────────────────────────────────────────────────┘
```

---

## 5. Import Window – 900 Plaintiffs (McCabe)

**Time:** 9:00–10:00 AM  
**Environment:** PROD

### Import Sequence

```
□ 1. Set environment to prod
      $env:SUPABASE_MODE='prod'

□ 2. Run the real importer WITH commit
      python -m tools.run_import `
        --source jbi `
        --csv "C:\Users\mccab\dragonfly_civil\intake_900.csv" `
        --batch-name "900-wave-1" `
        --source-reference "900-wave-1" `
        --commit

□ 3. Watch the output for:
      - Row count processed
      - Any validation errors
      - Final summary

□ 4. Run import QA
      python -m tools.import_qa jbi900 900-wave-1 --env prod

□ 5. Check import_runs table
      -- In Supabase SQL Editor (prod):
      SELECT * FROM import_runs
      WHERE batch_name = '900-wave-1'
      ORDER BY created_at DESC LIMIT 1;
```

### What Good Output Looks Like

```
[IMPORT] Processing 900 rows...
[IMPORT] Validated: 897 | Invalid: 3
[IMPORT] Inserted: 897 plaintiffs
[IMPORT] Batch '900-wave-1' complete.

[QA] No duplicate plaintiff_ids detected
[QA] All required fields present
[QA] Status: PASS
```

### What Bad Output Looks Like

```
[IMPORT] ERROR: Duplicate plaintiff_id detected: PLT-12345
[IMPORT] FATAL: Database constraint violation on row 234
[QA] CRITICAL: 47 rows missing phone numbers
```

### If Things Go Wrong

| Scenario                     | Action                                              |
| ---------------------------- | --------------------------------------------------- |
| **<10 rows fail validation** | Proceed. Log the failures. Fix later.               |
| **10–50 rows fail**          | Pause. Review errors. Decide if fixable in 15 min.  |
| **>50 rows fail OR crash**   | STOP. Do not send GO. Text Mom: "Delay." Fix first. |
| **Database error**           | STOP. Check Supabase logs. May need to rollback.    |

### Send the GO

Once import completes and QA passes:

```
□ 6. Text Mom:
      "Mom – GO. Call Queue is live. 897 plaintiffs ready."

□ 7. Text Dad:
      "Dad – Import complete. 897 plaintiffs loaded. Mom is starting calls."
```

---

## 6. Call Window – First 3 Hours (Mom)

**Time:** 10:00 AM–1:00 PM  
**Goal:** 30–50 calls logged

### Priority Order

Call plaintiffs in this order (Call Queue sorts automatically):

| Priority | Judgment Amount | Why                        |
| -------- | --------------- | -------------------------- |
| 1        | $10,000+        | Highest potential recovery |
| 2        | $5,000–$9,999   | Strong mid-tier            |
| 3        | $1,000–$4,999   | Volume plays               |

### Call Outcome Statuses

Use these statuses in the "Log Call" form:

| Status                      | When to Use                         | What Happens Next              |
| --------------------------- | ----------------------------------- | ------------------------------ |
| **No Answer**               | Phone rang, no pickup, no voicemail | Auto-queued for retry          |
| **Left Voicemail**          | You left a message                  | Queued for follow-up in 2 days |
| **Bad Number**              | Disconnected / wrong person         | Flagged for data cleanup       |
| **Spoke – Not Interested**  | They declined                       | Marked inactive                |
| **Spoke – Mild Interest**   | Curious but not ready               | Follow-up in 1 week            |
| **Spoke – Strong Interest** | Wants more info                     | High priority follow-up        |
| **Ready to Sign**           | Wants to proceed NOW                | 🚨 Alert McCabe immediately    |

### Logging a Call

```
1. Click on a plaintiff in the Call Queue
2. Review their info (judgment amount, defendant, phone)
3. Make the call
4. Click "Log Call"
5. Select the outcome status
6. Add notes (keep it short – just the key facts)
7. Click Save
8. Move to the next plaintiff
```

### Sample Call Script (Short Version)

> "Hi, this is [Mom's name] calling from Dragonfly Civil. I'm reaching out about a judgment you have against [Defendant Name] for [Amount]. We help plaintiffs like you actually collect on these judgments. Do you have a few minutes to hear how it works?"

**If yes:** Explain briefly. Gauge interest. Log outcome.  
**If no:** "No problem. Can I send you some information?" Log outcome.  
**If voicemail:** "Hi, this is [name] from Dragonfly Civil about your judgment against [Defendant]. Please call me back at [number]."

### Target for This Block

| Metric          | Target | Stretch |
| --------------- | ------ | ------- |
| Calls attempted | 30     | 50      |
| Conversations   | 10     | 20      |
| Strong interest | 3      | 5       |
| Ready to sign   | 1      | 2       |

### If Something Breaks

| Problem                        | Action                                                                   |
| ------------------------------ | ------------------------------------------------------------------------ |
| Dashboard won't load           | Refresh. If still broken, text McCabe.                                   |
| "Log Call" button doesn't work | Refresh. Try again. If still broken, write notes on paper + text McCabe. |
| Plaintiff info looks wrong     | Log the call anyway. Note the issue. Tell McCabe at break.               |

---

## 7. Dad's Role – Executive Review

**Time:** 1:00–2:00 PM (after first call block)  
**Location:** Executive Dashboard + this checklist

### What to Look At

```
□ 1. Open Executive Dashboard
      URL: [dashboard-url]/executive

□ 2. Check the Import Summary card:
      - Total plaintiffs imported: Should be ~897
      - Import errors: Should be <10

□ 3. Check the Call Activity card:
      - Calls logged today: Should be 30–50
      - Conversations: Should be 10–20

□ 4. Check the Pipeline card:
      - Strong interest: How many?
      - Ready to sign: How many?
```

### v_ops_daily_summary Metrics

Ask McCabe to run this if you want raw numbers:

```sql
SELECT * FROM v_ops_daily_summary;
```

Key columns to review:

| Column                | What It Means          | Good | Concerning |
| --------------------- | ---------------------- | ---- | ---------- |
| `plaintiffs_imported` | Total loaded today     | ~900 | <800       |
| `calls_logged`        | Call outcomes recorded | 30+  | <20        |
| `conversations`       | Actual conversations   | 10+  | <5         |
| `strong_interest`     | Hot leads              | 3+   | 0          |

### GO / NO-GO Checkpoints

| Decision                              | GO Criteria                         | NO-GO Criteria                     |
| ------------------------------------- | ----------------------------------- | ---------------------------------- |
| **Continue calling this afternoon**   | 20+ calls logged, no system crashes | <10 calls OR dashboard broken      |
| **Scale up (add caller capacity)**    | 5+ strong interest, system stable   | <3 strong interest OR ops friction |
| **Approve first enforcement actions** | ≥1 signed agreement in hand         | No signatures yet                  |

### Questions to Ask McCabe

1. "Did the import run cleanly?"
2. "Are there any data quality issues we need to fix?"
3. "Is Mom hitting any friction in the UI?"
4. "What's our conversion rate so far (conversations ÷ calls)?"

---

## 8. Evening Wrap-Up – Debrief & Next-Day Plan

**Time:** 5:00–6:00 PM  
**Location:** Kitchen table (or Zoom)  
**Attendees:** McCabe, Mom, Dad

### Debrief Template

**Fill this out together:**

```
DATE: _______________

IMPORT STATS:
  Plaintiffs imported: _____
  Import errors: _____
  Data quality issues found: _____

CALL STATS:
  Calls attempted: _____
  Conversations: _____
  No answers: _____
  Bad numbers: _____
  Strong interest: _____
  Ready to sign: _____

WHAT WORKED:
  1. _________________________________
  2. _________________________________
  3. _________________________________

WHAT BROKE:
  1. _________________________________
  2. _________________________________

WHAT SURPRISED US:
  1. _________________________________
  2. _________________________________
```

### McCabe's Honest Questions

_Answer these truthfully. No self-delusion._

```
□ 1. Did the import actually work, or did I paper over errors?
      Answer: _________________________________

□ 2. Could Mom use the system without my help, or was I constantly troubleshooting?
      Answer: _________________________________

□ 3. Is our data quality good enough to trust, or are we building on sand?
      Answer: _________________________________

□ 4. Did Dad see clear metrics, or did I have to "explain" what he was looking at?
      Answer: _________________________________

□ 5. If we did this exact process with 5,000 plaintiffs, would it work?
      Answer: _________________________________
```

### Day 2 Focus Decision

Based on today's results, pick ONE focus for tomorrow:

| If...                          | Then Day 2 Focus Is...                       |
| ------------------------------ | -------------------------------------------- |
| Calls went well, system stable | **More calls** – double the volume           |
| System had friction, calls OK  | **Fix friction** – improve UX before scaling |
| Got 1+ "Ready to Sign"         | **Agreements workflow** – close the deal     |
| Data quality issues            | **Data cleanup** – fix before more calls     |
| Major system failure           | **Stabilize** – no calls until fixed         |

```
DAY 2 FOCUS: _________________________________

SPECIFIC TASKS:
  McCabe: _________________________________
  Mom: _________________________________
  Dad: _________________________________
```

---

## Quick Reference – Key Commands

| Task                   | Command                                                                                 |
| ---------------------- | --------------------------------------------------------------------------------------- |
| Run tests              | `python -m pytest -q`                                                                   |
| Push migrations (dev)  | `.\scripts\db_push.ps1 -SupabaseEnv dev`                                                |
| Push migrations (prod) | `.\scripts\db_push.ps1 -SupabaseEnv prod`                                               |
| Schema check           | `python -m tools.check_schema_consistency --env dev`                                    |
| Doctor all             | `python -m tools.doctor_all --env dev`                                                  |
| Dry run 900            | `.\scripts\import_900_dry_run.ps1`                                                      |
| Smoke plaintiffs       | `python -m tools.smoke_plaintiffs`                                                      |
| Import (prod, commit)  | `python -m tools.run_import --source jbi --csv [path] --batch-name 900-wave-1 --commit` |
| Import QA              | `python -m tools.import_qa jbi900 900-wave-1 --env prod`                                |
| Ops summary            | `python -m tools.ops_summary --env prod`                                                |

---

## Emergency Contacts

| Person | Role            | Phone              |
| ------ | --------------- | ------------------ |
| McCabe | Tech / Fixes    | ******\_\_\_****** |
| Mom    | Ops / Calling   | ******\_\_\_****** |
| Dad    | CEO / Decisions | ******\_\_\_****** |

---

**Print this. Keep it on the table. Execute the checklist.**

_"We're not hoping it works. We're making it work."_
