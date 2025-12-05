# Dragonfly Civil – Standard Operating Procedures (SOP) v2.0

> **Effective Date:** December 2024  
> **Owner:** Operations Team  
> **Classification:** Internal / Investor Due Diligence

---

## Table of Contents

1. [Morning CEO Routine](#1-morning-ceo-routine)
2. [Ops Intake Routine](#2-ops-intake-routine)
3. [Offer Routine](#3-offer-routine)
4. [System Health Checklist](#4-system-health-checklist)
5. [Safety & Escalation](#5-safety--escalation)

---

## 1. Morning CEO Routine

**Who:** Dad (CEO)  
**When:** Daily, 8:30–9:00 AM  
**Goal:** 15-minute portfolio check, approve high-value offers, monitor system health

### Step 1: Log In

| Step | Action                                                          |
| ---- | --------------------------------------------------------------- |
| 1.1  | Open browser → Go to **https://dragonfly-dashboard.vercel.app** |
| 1.2  | Sign in with your credentials (Google SSO or email/password)    |
| 1.3  | Verify you see the sidebar with "CEO Overview" at the top       |

### Step 2: Review CEO Overview Dashboard

| Step | Action                                  | What to Look For                                       |
| ---- | --------------------------------------- | ------------------------------------------------------ |
| 2.1  | Click **"CEO Overview"** in the sidebar | Page loads with 4 KPI cards                            |
| 2.2  | Check **Judgments Under Management**    | Total count and dollar value of portfolio              |
| 2.3  | Check **Buy Candidates**                | High-value cases ready for purchase offers             |
| 2.4  | Check **Offers Accepted**               | Acceptance rate should be >50% (healthy)               |
| 2.5  | Check **System Health** badge           | Should show "Healthy" (green)                          |
| 2.6  | Scan **Recent Activity** feed           | Look for overnight events (new cases, accepted offers) |

#### ✅ CEO Overview Checklist

- [ ] Total judgments count looks reasonable (not suddenly zero)
- [ ] Buy candidates exist (we have work to do)
- [ ] Acceptance rate is stable or improving
- [ ] System shows "Healthy" status
- [ ] No unusual "System Alert" events in activity feed

### Step 3: Review Enforcement Radar

| Step | Action                                      |
| ---- | ------------------------------------------- |
| 3.1  | Click **"Radar"** in the sidebar            |
| 3.2  | Click the **"Strategy"** dropdown filter    |
| 3.3  | Select **"BUY_CANDIDATE"**                  |
| 3.4  | Sort by **Judgment Amount** (highest first) |

#### What You See on Radar:

| Column                   | Meaning                                             |
| ------------------------ | --------------------------------------------------- |
| **Defendant**            | Who owes the money                                  |
| **Judgment Amount**      | Original judgment value                             |
| **Collectability Score** | 0-100 (higher = more likely to collect)             |
| **Offer Strategy**       | BUY_CANDIDATE, CONTINGENCY, DEFER, or DO_NOT_PURSUE |
| **Last Activity**        | Most recent event for this case                     |

### Step 4: Approve Offers

| Step | Action                                                          |
| ---- | --------------------------------------------------------------- |
| 4.1  | Click on a **BUY_CANDIDATE** row to open case detail            |
| 4.2  | Review the **ScoreCard** tab (employment, assets, recency)      |
| 4.3  | Review the **Intelligence** tab (entities, relationships)       |
| 4.4  | Click **"Create Offer"** button                                 |
| 4.5  | Enter offer amount (typically 10-15% of judgment for purchases) |
| 4.6  | Select offer type: **Purchase** or **Contingency**              |
| 4.7  | Add any notes                                                   |
| 4.8  | Click **"Submit Offer"**                                        |

#### ✅ Offer Decision Framework

| Score Range | Recommendation                        |
| ----------- | ------------------------------------- |
| 80-100      | Strong BUY – offer 12-15% of judgment |
| 60-79       | Good BUY – offer 10-12% of judgment   |
| 40-59       | Consider CONTINGENCY instead          |
| Below 40    | DEFER or DO_NOT_PURSUE                |

### Step 5: Review Timelines & Events

| Step | Action                                                          |
| ---- | --------------------------------------------------------------- |
| 5.1  | Click the **"Timeline"** tab on any case                        |
| 5.2  | Review events from newest to oldest                             |
| 5.3  | Look for: enrichment completed, offers sent, responses received |

#### Event Types Explained:

| Event               | Meaning                                 |
| ------------------- | --------------------------------------- |
| `judgment_created`  | New case added to system                |
| `judgment_enriched` | Skip trace / asset search completed     |
| `offer_created`     | You submitted an offer                  |
| `offer_accepted`    | Plaintiff accepted your offer 🎉        |
| `offer_rejected`    | Plaintiff declined – consider follow-up |
| `packet_generated`  | Legal packet created and ready to send  |
| `batch_ingested`    | New CSV data was imported               |

### Step 6: Decide on Packet Generation

| Step | Action                                                        |
| ---- | ------------------------------------------------------------- |
| 6.1  | For accepted offers, click **"Generate Packet"**              |
| 6.2  | Verify packet preview looks correct                           |
| 6.3  | Click **"Confirm & Generate"**                                |
| 6.4  | Packet will be ready in `/data_out/` folder or sent via email |

---

## 2. Ops Intake Routine

**Who:** Mom (Operations Manager)  
**When:** When new vendor CSV arrives (typically 1-2x per week)  
**Goal:** Import new cases into the system, verify data quality, queue for enrichment

### Step 1: Receive & Validate CSV

| Step | Action                                                 |
| ---- | ------------------------------------------------------ |
| 1.1  | Download CSV from vendor email (Simplicity, JBI, etc.) |
| 1.2  | Save to `data_in/` folder with descriptive name        |
| 1.3  | Open in Excel – quick visual check for obvious issues  |

#### ✅ CSV Pre-Flight Checklist

- [ ] File opens without errors
- [ ] Has expected columns (defendant name, judgment amount, case number)
- [ ] No completely blank rows in the middle
- [ ] Dates look reasonable (not all 1900 or 2099)
- [ ] Dollar amounts don't have weird characters

### Step 2: Trigger Import via n8n

| Step | Action                                                               |
| ---- | -------------------------------------------------------------------- |
| 2.1  | Open **n8n** at `https://n8n.dragonfly.local` (or your n8n URL)      |
| 2.2  | Find workflow: **"CSV Intake – Simplicity"** (or appropriate vendor) |
| 2.3  | Click **"Execute Workflow"** button                                  |
| 2.4  | When prompted, upload the CSV file                                   |
| 2.5  | Wait for completion (watch the green checkmarks)                     |

#### Alternative: Command Line Import

```powershell
# From project root, run:
$env:SUPABASE_MODE = "prod"
.\.venv\Scripts\python.exe -m tools.run_import `
  --source simplicity `
  --csv "data_in/your_file.csv" `
  --batch-name "2024-12-04-simplicity" `
  --commit
```

### Step 3: Verify Import in Dashboard

| Step | Action                                    |
| ---- | ----------------------------------------- |
| 3.1  | Open dashboard → **Radar** page           |
| 3.2  | Sort by **"Created"** (newest first)      |
| 3.3  | Verify new cases appear with today's date |
| 3.4  | Spot-check 2-3 cases:                     |

#### ✅ Import Verification Checklist

- [ ] Expected number of rows imported (check n8n output)
- [ ] Case numbers match source CSV
- [ ] Defendant names look correct (not garbled)
- [ ] Judgment amounts match source
- [ ] No duplicate case numbers created
- [ ] Cases are in "PENDING_ENRICHMENT" or similar status

### Step 4: Spot-Check Data Quality

| Step | Action                           |
| ---- | -------------------------------- |
| 4.1  | Click on 2 random new cases      |
| 4.2  | Check that key fields populated: |

| Field           | Should Have           |
| --------------- | --------------------- |
| Defendant Name  | Real name, not blank  |
| Judgment Amount | Dollar amount > 0     |
| Case Number     | Matches vendor format |
| Court/Venue     | If provided by vendor |
| Judgment Date   | Reasonable date       |

### Step 5: Monitor Enrichment Queue

| Step | Action                                                |
| ---- | ----------------------------------------------------- |
| 5.1  | Go to **Settings** → **System Health**                |
| 5.2  | Check **Enrichment Health** panel                     |
| 5.3  | Verify jobs are processing (pending count decreasing) |
| 5.4  | If jobs stuck > 30 minutes, escalate to Tech Support  |

### Step 6: Document the Intake

| Step | Action                                               |
| ---- | ---------------------------------------------------- |
| 6.1  | Log the import in the intake tracker spreadsheet     |
| 6.2  | Note: date, vendor, file name, row count, any issues |

---

## 3. Offer Routine

**Who:** Operations Team (Mom, with CEO approval for large offers)  
**When:** After enrichment completes, or when following up on prior offers  
**Goal:** Make compelling offers, track outcomes, maintain professional relationships

### Step 1: Prepare for Calls

| Step | Action                                                        |
| ---- | ------------------------------------------------------------- |
| 1.1  | Open **Radar** → Filter by **"Ready for Offer"** status       |
| 1.2  | Sort by **Collectability Score** (highest first)              |
| 1.3  | Open case detail → Review **ScoreCard** and **Intelligence**  |
| 1.4  | Note key facts: judgment amount, defendant employment, assets |

### Step 2: Use the Offer Modal

| Step | Action                                         |
| ---- | ---------------------------------------------- |
| 2.1  | Click **"Create Offer"** button on case detail |
| 2.2  | Fill in the offer details:                     |

| Field            | Guidance                                                   |
| ---------------- | ---------------------------------------------------------- |
| **Offer Amount** | Start at 10-12% for purchases, adjust based on score       |
| **Offer Type**   | "Purchase" (we buy it) or "Contingency" (we collect for %) |
| **Expiration**   | Typically 14-30 days                                       |
| **Notes**        | Key talking points, plaintiff contact info                 |

### Step 3: Make the Call

#### 📞 Purchase Offer Script

> _"Good morning/afternoon, this is [Your Name] calling from Dragonfly Civil. I'm reaching out regarding the judgment you hold against [Defendant Name] in case number [Case Number]._
>
> _I understand this judgment has been outstanding for some time, and collecting on it can be frustrating and time-consuming. We specialize in purchasing judgments like this, which means we would pay you a lump sum today, and we take over all the collection efforts._
>
> _Based on our analysis of this case, we'd like to offer you $[Offer Amount] for an outright purchase of this judgment. This is cash in your pocket within [timeframe], and you don't have to deal with the collection process at all._
>
> _Would you be interested in discussing this further?"_

#### Common Responses & Rebuttals:

| They Say                           | You Say                                                                                                                                                 |
| ---------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| "That's too low"                   | "I understand. The offer reflects the time and expense involved in collection. What amount would work for you?"                                         |
| "I want to think about it"         | "Of course. Our offer is valid for [X] days. Can I follow up with you on [specific date]?"                                                              |
| "How do I know you're legitimate?" | "Great question. I can send you our company information, references, and a sample purchase agreement for your review."                                  |
| "I'd rather collect myself"        | "Understood. If you change your mind or want help, we also offer contingency collection where we only get paid if we collect. Would that interest you?" |

#### 📞 Contingency Offer Script

> _"Good morning/afternoon, this is [Your Name] from Dragonfly Civil. I'm calling about the judgment you hold against [Defendant Name]._
>
> _We specialize in collecting on difficult judgments, and we work on a contingency basis – meaning you pay nothing upfront, and we only earn a fee when we successfully collect._
>
> _Our standard arrangement is [X]% of whatever we collect. We handle all the work – skip tracing, asset discovery, legal filings – and you receive a check when we're successful._
>
> _Would you like to hear more about how this works?"_

### Step 4: Record the Outcome

| Step | Action                                              |
| ---- | --------------------------------------------------- |
| 4.1  | After the call, return to the case in the dashboard |
| 4.2  | Click on the offer you created                      |
| 4.3  | Update the **Status**:                              |

| Status                  | When to Use                                      |
| ----------------------- | ------------------------------------------------ |
| **Accepted**            | Plaintiff agreed – proceed to packet generation  |
| **Rejected**            | Firm no – note reason, consider future follow-up |
| **Negotiating**         | They countered or want to discuss further        |
| **No Response**         | Couldn't reach, voicemail left                   |
| **Follow-Up Scheduled** | They want to think – note callback date          |

| Step | Action                                                                          |
| ---- | ------------------------------------------------------------------------------- |
| 4.4  | Add **Notes** with call details: who you spoke with, their concerns, next steps |
| 4.5  | If **Accepted**, proceed to generate packet                                     |

### Step 5: Generate Packet for Accepted Offers

| Step | Action                                        |
| ---- | --------------------------------------------- |
| 5.1  | Click **"Generate Packet"** on accepted offer |
| 5.2  | Select packet type:                           |

| Packet Type               | Contents                                          |
| ------------------------- | ------------------------------------------------- |
| **Purchase Agreement**    | Assignment of judgment, payment terms, signatures |
| **Contingency Agreement** | Collection authorization, fee structure, terms    |

| Step | Action                                                      |
| ---- | ----------------------------------------------------------- |
| 5.3  | Review the generated preview                                |
| 5.4  | Click **"Confirm & Send"** (or download for manual sending) |
| 5.5  | Packet status updates to "Sent" with timestamp              |

### Step 6: Follow-Up on Pending Packets

| Step | Action                                              |
| ---- | --------------------------------------------------- |
| 6.1  | Open **Radar** → Filter by **"Packet Sent"** status |
| 6.2  | Sort by **"Packet Sent Date"** (oldest first)       |
| 6.3  | For packets > 7 days old without response:          |
| 6.4  | Make follow-up call using script:                   |

> _"Hi [Name], this is [Your Name] from Dragonfly Civil. I'm following up on the purchase agreement we sent over on [date] regarding the [Defendant] judgment. Did you have a chance to review it? Do you have any questions I can answer?"_

---

## 4. System Health Checklist

**Who:** Operations Team (daily) / Tech Support (weekly deep-dive)  
**When:** Morning check + whenever something seems off  
**Goal:** Catch problems before they affect operations

### Daily Quick Check (5 minutes)

#### ✅ Dashboard Health

| Check               | How                                         | Expected Result                     |
| ------------------- | ------------------------------------------- | ----------------------------------- |
| Dashboard loads     | Open https://dragonfly-dashboard.vercel.app | Page loads in < 5 seconds           |
| Data appears        | Check Radar has cases                       | Not empty, recent dates visible     |
| CEO Overview works  | Open /ceo/overview                          | KPI cards show numbers (not errors) |
| System Health badge | Check badge on CEO Overview                 | Shows "Healthy" (green)             |

#### ✅ API Health

| Check           | How                               | Expected Result                  |
| --------------- | --------------------------------- | -------------------------------- |
| Supabase status | Visit https://status.supabase.com | All green                        |
| API responds    | Open any case detail              | Data loads without error message |

#### ✅ n8n Workflow Status

| Check            | How                    | Expected Result                       |
| ---------------- | ---------------------- | ------------------------------------- |
| n8n accessible   | Open your n8n URL      | Login page or dashboard appears       |
| Daily CEO Brief  | Check "Executions" tab | Ran this morning ~8:30 AM             |
| CSV Intake       | Check workflow history | Last run succeeded (if used recently) |
| Packet Follow-Up | Check workflow history | Last run succeeded                    |

### Weekly Deep-Dive (15 minutes, Mondays)

#### ✅ Enrichment Health

```
Open: Dashboard → Settings → System Health
```

| Metric        | Healthy  | Warning   | Critical  |
| ------------- | -------- | --------- | --------- |
| Pending Jobs  | < 50     | 50-200    | > 200     |
| Failed Jobs   | 0        | 1-5       | > 5       |
| Last Activity | < 1 hour | 1-4 hours | > 4 hours |

#### ✅ Database Size & Performance

```powershell
# Run from project root:
.\.venv\Scripts\python.exe -m tools.doctor --env prod
```

Expected output:

- "All tables accessible" ✓
- "Views responding" ✓
- Row counts look reasonable

#### ✅ Worker Status

| Check           | How                                  | Expected Result        |
| --------------- | ------------------------------------ | ---------------------- |
| Workers running | Check hosting platform (Railway/Fly) | Workers show "Running" |
| Recent activity | Check worker logs                    | Log entries from today |
| No crash loops  | Check restart count                  | < 3 restarts today     |

### Troubleshooting Quick Reference

| Symptom              | Likely Cause             | First Step                        |
| -------------------- | ------------------------ | --------------------------------- |
| Dashboard won't load | Vercel issue or internet | Check https://status.vercel.com   |
| Data not appearing   | Supabase issue           | Check https://status.supabase.com |
| Enrichment stuck     | Worker down              | Check worker hosting platform     |
| n8n workflow failed  | Credential or data issue | Check n8n execution logs          |
| "Unhealthy" badge    | Failed jobs in queue     | Escalate to Tech Support          |

---

## 5. Safety & Escalation

**Principle:** When in doubt, pause and ask. Better to delay than to make an expensive mistake.

### When to Call Technical Support (You)

#### 🔴 Call Immediately

| Situation                                   | Why                        |
| ------------------------------------------- | -------------------------- |
| Dashboard shows errors for > 15 minutes     | System may be down         |
| "Unhealthy" status with failed jobs > 10    | Processing pipeline broken |
| Sensitive data visible that shouldn't be    | Security issue             |
| Import created thousands of duplicate cases | Data corruption            |
| Workers show "Crashed" status               | Production issue           |

#### 🟡 Call Within 4 Hours

| Situation                                    | Why                     |
| -------------------------------------------- | ----------------------- |
| Enrichment queue stuck for > 2 hours         | May need restart        |
| n8n workflow failed and you don't know why   | May need debugging      |
| New vendor CSV format doesn't match expected | May need mapping update |
| Unusual spike or drop in case numbers        | May indicate data issue |

#### 📱 Tech Support Contact

- **Phone:** [Your Phone Number]
- **Email:** [Your Email]
- **Best Hours:** 9 AM - 6 PM Eastern
- **After Hours:** Text for emergencies only

### When to Pause Packet Generation

#### 🛑 STOP Immediately If:

| Issue                                                  | Risk                                   |
| ------------------------------------------------------ | -------------------------------------- |
| Packet shows wrong defendant name                      | Sent to wrong person = legal liability |
| Dollar amounts look wrong (off by 10x)                 | Invalid contract                       |
| Template has visible placeholder text like `{{FIELD}}` | Unprofessional, invalid                |
| Packet is for a case you don't recognize               | Possible data mixup                    |
| Legal language looks garbled or incomplete             | Unenforceable contract                 |

#### What to Do:

1. **Do NOT send the packet**
2. Take a screenshot of the issue
3. Note the case number and offer ID
4. Call Tech Support immediately
5. Document in the incident log

### When to Call Legal Counsel

#### 📞 Consult Legal Before Proceeding If:

| Situation                                            | Why                              |
| ---------------------------------------------------- | -------------------------------- |
| Plaintiff threatens lawsuit                          | Need legal response              |
| Debtor claims bankruptcy                             | Different collection rules apply |
| Judgment is from a state you're unfamiliar with      | Jurisdiction-specific rules      |
| Plaintiff wants terms outside normal parameters      | Contract review needed           |
| Any communication mentioning "attorney" or "lawsuit" | Legal response needed            |
| FDCPA or CFPB mentioned                              | Regulatory compliance issue      |

#### 🏛️ Legal Counsel Contact

- **Primary:** [Law Firm Name]
- **Phone:** [Law Firm Phone]
- **Email:** [Law Firm Email]
- **Retainer Status:** [Active/Need to engage]

### Incident Documentation

When any escalation occurs, document in the **Incident Log**:

| Field          | What to Record                        |
| -------------- | ------------------------------------- |
| Date/Time      | When you noticed the issue            |
| Reporter       | Your name                             |
| Case Number(s) | If applicable                         |
| Description    | What happened, what you saw           |
| Impact         | What couldn't be done because of this |
| Actions Taken  | What you tried, who you called        |
| Resolution     | How it was fixed (fill in later)      |
| Prevention     | What could prevent this in future     |

---

## Appendix: Quick Reference Cards

### Card 1: Morning CEO Routine (Pocket Version)

```
□ 1. Log in to dashboard
□ 2. CEO Overview → Check 4 KPIs (all green?)
□ 3. Radar → Filter BUY_CANDIDATE → Sort by amount
□ 4. Review top 5 cases → Check ScoreCard & Intel
□ 5. Approve offers (10-12% for 60+ scores)
□ 6. Generate packets for accepted offers
□ 7. Note any issues for Ops team
```

### Card 2: CSV Import Checklist (Pocket Version)

```
□ 1. Download CSV from vendor email
□ 2. Save to data_in/ folder
□ 3. Quick Excel check (opens? columns look right?)
□ 4. Run n8n workflow OR command line import
□ 5. Dashboard → Radar → Sort by Created (newest)
□ 6. Spot-check 2-3 cases
□ 7. Log in intake tracker
```

### Card 3: Call Outcome Codes

| Code | Meaning       | Next Step                                  |
| ---- | ------------- | ------------------------------------------ |
| ACC  | Accepted      | Generate packet                            |
| REJ  | Rejected      | Note reason, maybe retry in 6 months       |
| NEG  | Negotiating   | Schedule follow-up, update offer if needed |
| NR   | No Response   | Try again tomorrow, max 3 attempts         |
| FU   | Follow-Up Set | Add to calendar, call on scheduled date    |
| WN   | Wrong Number  | Research correct contact                   |
| DNC  | Do Not Call   | Remove from call list, note in system      |

---

## Version History

| Version | Date     | Author   | Changes                                      |
| ------- | -------- | -------- | -------------------------------------------- |
| 2.0     | Dec 2024 | Ops Team | Complete rewrite with new dashboard features |
| 1.0     | Oct 2024 | Ops Team | Initial SOP bundle                           |

---

_This document is confidential and intended for internal use and investor due diligence only._
