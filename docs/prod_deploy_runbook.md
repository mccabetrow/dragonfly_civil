# Dragonfly Civil – Production Deployment Runbook

> **Audience:** CEO, Operations Lead, and non-technical stakeholders  
> **Last Updated:** December 9, 2025

---

## What This Document Covers

This runbook explains what happens automatically when our engineering team pushes code changes to the main branch, and what to do if something goes wrong.

---

## 1. What Happens When We Push to Main

Every time a developer pushes code to the `main` branch on GitHub, an automated pipeline runs. Think of it like an assembly line that checks the work, applies database changes, and deploys the updated application.

### The Pipeline Steps (In Order)

| Step                             | What It Does                                                                          | If It Fails...                                      |
| -------------------------------- | ------------------------------------------------------------------------------------- | --------------------------------------------------- |
| **1. Run Tests**                 | Runs automated checks against our development database to make sure nothing is broken | ❌ Stops the pipeline. No changes reach production. |
| **2. Apply Database Migrations** | Updates the production database structure (new columns, tables, etc.)                 | ❌ Stops the pipeline. App deploys are skipped.     |
| **3. Deploy Backend (Railway)**  | Deploys the Python backend that powers our APIs                                       | ⚠️ Warning logged, but continues                    |
| **4. Deploy Dashboard (Vercel)** | Deploys the web dashboard you use daily                                               | ⚠️ Warning logged, but continues                    |
| **5. Send Notification**         | Posts a message to Discord with success ✅ or failure ❌                              | N/A                                                 |

**Key Point:** If tests fail, nothing else happens. Production is protected.

---

## 2. Understanding Test Results

### What Are "Tests"?

Tests are automated checks written by the engineering team. They verify that:

- Data imports correctly
- Calculations (like collectability scores) work as expected
- Database queries return the right results
- The dashboard can load the views it needs

### What Does It Mean If Tests Fail?

| Scenario      | What It Means                       | Impact                                          |
| ------------- | ----------------------------------- | ----------------------------------------------- |
| ✅ Tests Pass | The code changes work correctly     | Pipeline continues                              |
| ❌ Tests Fail | Something in the new code is broken | **Pipeline stops. Production is NOT affected.** |

**If tests fail:** The developer who pushed the code will see the failure and fix it. You don't need to do anything, but you won't see new features until it's resolved.

---

## 3. How Database Migrations Work

### What Is a Migration?

A migration is a set of instructions that changes the database structure. For example:

- Adding a new column to track "plaintiff tier"
- Creating a new table for enforcement actions
- Adding a new view for the dashboard

### How It Works

1. Developer writes a migration file (like `20251209_add_enforcement_tables.sql`)
2. When they push to main, the pipeline automatically applies it to production
3. The database is updated without losing any existing data

### Safety Features

- Migrations only run if tests pass first
- The pipeline checks that required settings are configured before running
- If a migration fails, the app deploys are skipped (so the old app keeps working with the old database)

---

## 4. How to Read the GitHub Actions Page

### Getting There

1. Go to: **github.com/mccabetrow/dragonfly_civil**
2. Click the **"Actions"** tab at the top
3. You'll see a list of recent pipeline runs

### What You'll See

| Icon               | Meaning              |
| ------------------ | -------------------- |
| 🟢 Green checkmark | Everything succeeded |
| 🔴 Red X           | Something failed     |
| 🟡 Yellow dot      | Currently running    |
| ⚪ Gray dot        | Waiting or skipped   |

### Reading a Specific Run

Click on any run to see details:

```
✅ Checkout repo
✅ Set up Python 3.12
✅ Install dependencies
✅ Install Supabase CLI
✅ Run tests against Dev         ← If this fails, everything stops
✅ Apply migrations to Prod      ← Database changes
✅ Trigger Railway deploy        ← Backend server
✅ Trigger Vercel deploy         ← Dashboard website
✅ Notify Discord on success     ← You get the notification
```

If any step has a ❌, click on it to see the error message.

---

## 5. Troubleshooting Guide

### Scenario A: Tests Failed

**What You'll See:**

- Discord notification: "❌ Dragonfly Prod Deploy FAILED"
- GitHub Actions shows red X on "Run tests against Dev"

**What It Means:**

- The new code has a bug
- Production is completely unaffected (nothing changed)

**What To Do:**

1. Don't panic – production is safe
2. Notify the engineering team (they likely already know)
3. Wait for the fix – they'll push a corrected version

**Timeline:** Usually fixed within 1-2 hours during business hours.

---

### Scenario B: Supabase Push Failed

**What You'll See:**

- Discord notification: "❌ Dragonfly Prod Deploy FAILED"
- GitHub Actions shows red X on "Apply migrations to Prod"

**What It Means:**

- Tests passed, but the database update failed
- This could be a connection issue or a conflict with existing data
- The app was NOT deployed (old version still running)

**What To Do:**

1. Check if the dashboard is still working (it should be)
2. Notify engineering immediately – this needs manual attention
3. Do NOT retry the pipeline yourself

**Timeline:** May require 30 minutes to several hours depending on the issue.

---

### Scenario C: Railway or Vercel Deploy Failed

**What You'll See:**

- Discord notification: "🚀 Dragonfly Prod Deployed" (still shows success)
- But the dashboard or API seems outdated

**What It Means:**

- Database was updated successfully
- The app deployment webhook didn't trigger properly
- This is usually a temporary network issue

**What To Do:**

1. Wait 5 minutes and refresh the dashboard
2. If still not updated, notify engineering
3. They can manually trigger a deploy from Railway/Vercel

**Timeline:** Usually resolved within 15-30 minutes.

---

### Scenario D: Discord Shows Failure Notification

**What You'll See:**

- Discord message with red ❌ icon
- Includes: commit ID, author name, and link to the run

**What To Do:**

1. Click the link in the Discord message to open GitHub Actions
2. Look for the step with the red X
3. Share this information with engineering if they haven't already seen it

**What the Notification Tells You:**

```
❌ Dragonfly Prod Deploy FAILED
├── Commit: abc1234          ← Which code change triggered this
├── Author: john_developer   ← Who pushed the code
└── [View run]               ← Click to see details
```

---

## 6. Quick Reference: Who To Contact

| Issue                             | First Contact                   | Escalation         |
| --------------------------------- | ------------------------------- | ------------------ |
| Tests failing                     | Wait 1 hour, then check Discord | Engineering lead   |
| Database migration failed         | Engineering lead immediately    | CTO                |
| Dashboard not updating            | Engineering team                | Vercel support     |
| API not responding                | Engineering team                | Railway support    |
| Discord notifications not working | Engineering team                | N/A (non-critical) |

---

## 7. Glossary

| Term               | Plain English                                              |
| ------------------ | ---------------------------------------------------------- |
| **Pipeline**       | The automated process that runs when code is pushed        |
| **Main branch**    | The "official" version of our code that runs in production |
| **Migration**      | A database update (adding columns, tables, etc.)           |
| **Deploy**         | Publishing new code so users can access it                 |
| **Railway**        | The service that runs our backend Python code              |
| **Vercel**         | The service that hosts our dashboard website               |
| **Supabase**       | Our database provider (where all the judgment data lives)  |
| **GitHub Actions** | The service that runs our automated pipeline               |

---

## 8. What You Should NEVER Do

❌ **Don't** click "Re-run jobs" on GitHub Actions unless engineering asks you to  
❌ **Don't** push code to the repository yourself  
❌ **Don't** change settings in Railway, Vercel, or Supabase directly  
❌ **Don't** share the Discord failure notifications publicly (they may contain internal info)

---

## 9. What You CAN Do

✅ **Do** check the dashboard to see if things are working  
✅ **Do** report issues you notice (slow loading, missing data, errors)  
✅ **Do** share the GitHub Actions link with engineering when asking about a failure  
✅ **Do** wait patiently – most issues are resolved quickly

---

## 10. Summary

| Event                            | Your Action                                             |
| -------------------------------- | ------------------------------------------------------- |
| 🟢 Green notification in Discord | Everything worked! No action needed.                    |
| 🔴 Red notification in Discord   | Check if dashboard works. Notify engineering if urgent. |
| Dashboard seems outdated         | Wait 5 min, then notify engineering.                    |
| Dashboard is completely down     | Notify engineering immediately.                         |

**Remember:** The pipeline is designed to protect production. If something fails, the safest thing is to wait for engineering to investigate.

---

_Questions about this runbook? Ask the engineering team or update this document as processes change._
