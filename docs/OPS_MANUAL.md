# The Ops Manual

**Dragonfly Civil – Operations Standard Operating Procedures**

_Version 1.0 | December 2025_

---

## Purpose

This manual defines the daily operating procedures for the Operations Manager. Each time block ensures the enforcement pipeline maintains flow, paperwork is processed efficiently, and all plaintiffs receive appropriate attention based on their tier priority.

---

## Daily Schedule Overview

| Time     | Activity                      | Duration | Priority    |
| -------- | ----------------------------- | -------- | ----------- |
| 10:00 AM | Intake Queue Review           | 60 min   | 🔴 Critical |
| 11:00 AM | Prioritize Today's Plaintiffs | 45 min   | 🔴 Critical |
| 2:00 PM  | Signature / Paperwork Queue   | 90 min   | 🟡 High     |
| 4:00 PM  | FOIL Responses Reconciliation | 60 min   | 🟡 High     |

---

## 10:00 AM – Intake Queue Review

### Objective

Process all new plaintiff submissions from the overnight queue, validate completeness, and route for priority scoring.

### Standard Operating Procedure

- [ ] **Step 1:** Open the Ops Dashboard at `https://dashboard.dragonflycivil.com/ops`
- [ ] **Step 2:** Navigate to **Intake Gateway → Pending Queue**
- [ ] **Step 3:** For each new submission, verify:
  - [ ] Plaintiff contact information complete
  - [ ] Judgment documentation attached
  - [ ] Case number and court verified
  - [ ] Debtor information provided
- [ ] **Step 4:** Run validation check (auto-triggered on review)
- [ ] **Step 5:** Route valid submissions to priority scoring
- [ ] **Step 6:** Flag incomplete submissions for follow-up

### Intake Validation Checklist

| Field               | Required    | Validation Rule        |
| ------------------- | ----------- | ---------------------- |
| Plaintiff Name      | ✅          | Non-empty, proper case |
| Email               | ✅          | Valid email format     |
| Phone               | ✅          | 10-digit US format     |
| Judgment Amount     | ✅          | > $0, numeric          |
| Case Number         | ✅          | Court format match     |
| Judgment Date       | ✅          | Not future dated       |
| Court Name          | ✅          | From approved list     |
| Debtor SSN (last 4) | ⚠️ Optional | 4 digits if provided   |

### Queue Status Codes

| Status              | Meaning                 | Action Required        |
| ------------------- | ----------------------- | ---------------------- |
| `pending_review`    | Awaiting Ops review     | Complete SOP Steps 3-6 |
| `validation_failed` | Missing required fields | Contact plaintiff      |
| `approved`          | Ready for scoring       | Auto-routes to planner |
| `rejected`          | Does not meet criteria  | Send rejection notice  |
| `needs_documents`   | Awaiting attachments    | Follow up within 48h   |

### Intake Metrics to Track

- [ ] Queue depth at start of shift: **\_\_**
- [ ] Submissions processed: **\_\_**
- [ ] Approval rate: **\_\_**%
- [ ] Average processing time: **\_\_** min

### Daily Intake Log

```
Date: ____________
Starting Queue: ______ items
Processed: ______ items
Approved: ______ | Rejected: ______ | Pending: ______
Notes: _______________________________________________
```

---

## 11:00 AM – Prioritize Today's Plaintiffs

### Objective

Review the plaintiff priority queue and assign enforcement actions based on tier classification and collectability scores.

### Standard Operating Procedure

- [ ] **Step 1:** Open **Plaintiff Overview → Priority Pipeline**
- [ ] **Step 2:** Filter by `status = active` and sort by priority score (descending)
- [ ] **Step 3:** Review top 20 plaintiffs and their current tier:
  - [ ] **Tier 1 (VIP):** Immediate action required
  - [ ] **Tier 2 (High Priority):** Same-day action
  - [ ] **Tier 3 (Standard):** Within 48 hours
  - [ ] **Tier 4 (Monitoring):** Weekly review
- [ ] **Step 4:** Assign specific tasks to each priority plaintiff
- [ ] **Step 5:** Update status notes with today's action plan
- [ ] **Step 6:** Flag any requiring CEO escalation

### Tier Classification Matrix

| Tier         | Judgment Amount   | Collectability | Action Cadence |
| ------------ | ----------------- | -------------- | -------------- |
| 1 - VIP      | > $50,000         | > 80           | Daily touch    |
| 2 - High     | $25,000 - $50,000 | > 70           | Every 2 days   |
| 3 - Standard | $10,000 - $25,000 | > 50           | Weekly         |
| 4 - Monitor  | < $10,000         | < 50           | Bi-weekly      |

### Task Assignment Codes

| Code    | Task Type               | Typical Duration  |
| ------- | ----------------------- | ----------------- |
| OPS-SKP | Skip trace request      | 24-48h turnaround |
| OPS-GAR | Garnishment preparation | 2-3 days          |
| OPS-LEV | Bank levy filing        | 3-5 days          |
| OPS-FOL | Follow-up call          | Same day          |
| OPS-DOC | Document collection     | 1-2 days          |
| OPS-ESC | CEO escalation          | Immediate         |

### Priority Assignment Log

| Plaintiff  | Tier     | Judgment $    | Task Assigned | Due Date     |
| ---------- | -------- | ------------- | ------------- | ------------ |
| ****\_**** | \_\_\_\_ | $**\_\_\_\_** | OPS-\_\_\_    | **\_\_\_\_** |
| ****\_**** | \_\_\_\_ | $**\_\_\_\_** | OPS-\_\_\_    | **\_\_\_\_** |
| ****\_**** | \_\_\_\_ | $**\_\_\_\_** | OPS-\_\_\_    | **\_\_\_\_** |
| ****\_**** | \_\_\_\_ | $**\_\_\_\_** | OPS-\_\_\_    | **\_\_\_\_** |
| ****\_**** | \_\_\_\_ | $**\_\_\_\_** | OPS-\_\_\_    | **\_\_\_\_** |

---

## 2:00 PM – Signature / Paperwork Queue

### Objective

Process all documents requiring signature, notarization, or filing. Ensure all legal paperwork moves through the system without delay.

### Standard Operating Procedure

- [ ] **Step 1:** Open **Document Queue → Pending Signatures**
- [ ] **Step 2:** Sort by priority (Tier 1 first, then by age)
- [ ] **Step 3:** For each document package:
  - [ ] Verify all fields completed
  - [ ] Check plaintiff signature obtained
  - [ ] Confirm notarization if required
  - [ ] Validate court filing requirements
- [ ] **Step 4:** Prepare documents for filing/mailing
- [ ] **Step 5:** Update document status in system
- [ ] **Step 6:** Schedule courier/filing as needed

### Document Type Processing Guide

| Document Type            | Signature Req        | Notary Req | Filing Deadline    |
| ------------------------ | -------------------- | ---------- | ------------------ |
| Garnishment Order        | Plaintiff + Attorney | ❌         | 5 business days    |
| Bank Levy                | Plaintiff            | ✅         | 3 business days    |
| Property Lien            | Plaintiff + Attorney | ✅         | 10 business days   |
| Settlement Agreement     | Both Parties         | ✅         | Upon execution     |
| FOIL Request             | Ops Manager          | ❌         | N/A                |
| Satisfaction of Judgment | Plaintiff            | ✅         | 30 days of payment |

### Paperwork Quality Checklist

- [ ] All signature lines completed
- [ ] Dates are current and consistent
- [ ] Case numbers match across all documents
- [ ] Dollar amounts verified against judgment
- [ ] Court name and address correct
- [ ] Return address included
- [ ] Postage/filing fees calculated

### Document Processing Log

| Document Type  | Plaintiff  | Case #   | Status     | Filed/Mailed |
| -------------- | ---------- | -------- | ---------- | ------------ |
| ******\_****** | ****\_**** | **\_\_** | **\_\_\_** | ☐ Yes ☐ No   |
| ******\_****** | ****\_**** | **\_\_** | **\_\_\_** | ☐ Yes ☐ No   |
| ******\_****** | ****\_**** | **\_\_** | **\_\_\_** | ☐ Yes ☐ No   |

### Metrics to Track

- [ ] Documents processed today: **\_\_**
- [ ] Average processing time: **\_\_** min
- [ ] Rejection rate (errors): **\_\_**%
- [ ] Filing deadline compliance: **\_\_**%

---

## 4:00 PM – FOIL Responses Reconciliation

### Objective

Process incoming Freedom of Information Law (FOIL) responses, extract debtor asset information, and update case records.

### Standard Operating Procedure

- [ ] **Step 1:** Check FOIL response inbox (email + physical mail)
- [ ] **Step 2:** Log all received responses in tracking system
- [ ] **Step 3:** For each response, extract and record:
  - [ ] Employment information (employer, wages)
  - [ ] Bank account indicators
  - [ ] Property ownership records
  - [ ] Vehicle registrations
  - [ ] License/permit information
- [ ] **Step 4:** Update debtor profile with new intel
- [ ] **Step 5:** Recalculate collectability score
- [ ] **Step 6:** Flag high-value discoveries for immediate action

### FOIL Response Types

| Agency             | Information Type              | Typical Response Time |
| ------------------ | ----------------------------- | --------------------- |
| DMV                | Vehicle registration, address | 10-14 days            |
| Dept. of Labor     | Employer, wage info           | 14-21 days            |
| County Clerk       | Property records              | 7-10 days             |
| Tax Assessor       | Property ownership            | 7-10 days             |
| Secretary of State | Business ownership            | 5-7 days              |

### Response Processing Codes

| Code      | Meaning                  | Next Action                     |
| --------- | ------------------------ | ------------------------------- |
| FOIL-HIT  | Actionable info received | Update profile, escalate        |
| FOIL-NEG  | No records found         | Document, try alternate agency  |
| FOIL-PART | Partial information      | Submit follow-up request        |
| FOIL-REJ  | Request rejected         | Review grounds, appeal if valid |
| FOIL-PEND | Response pending         | Follow up if > 21 days          |

### High-Value Discovery Triggers

Immediately escalate to priority queue if FOIL reveals:

- [ ] Employer with wages > $50K/year
- [ ] Bank account at known institution
- [ ] Real property ownership
- [ ] Business ownership with active revenue
- [ ] Multiple vehicles indicating assets

### FOIL Reconciliation Log

| Case #   | Agency   | Response Code | Key Finding    | Action Taken     |
| -------- | -------- | ------------- | -------------- | ---------------- |
| **\_\_** | **\_\_** | FOIL-\_\_\_   | ****\_\_\_**** | ****\_\_\_\_**** |
| **\_\_** | **\_\_** | FOIL-\_\_\_   | ****\_\_\_**** | ****\_\_\_\_**** |
| **\_\_** | **\_\_** | FOIL-\_\_\_   | ****\_\_\_**** | ****\_\_\_\_**** |

### Daily FOIL Metrics

```
Date: ____________
Responses Received: ______
Hit Rate: ______%
High-Value Discoveries: ______
Pending Requests (aging): ______
```

---

## Weekly Ops Checkpoint

Complete every Friday by 4:00 PM:

- [ ] All intake queue items processed (zero backlog target)
- [ ] Plaintiff priority list updated for next week
- [ ] Document filing log reconciled
- [ ] FOIL request pipeline reviewed (new requests submitted)
- [ ] Escalation items resolved or handed off
- [ ] Weekly metrics compiled for CEO review

### Weekly Metrics Summary

| Metric                 | This Week | Last Week | Δ Trend |
| ---------------------- | --------- | --------- | ------- |
| Intake Processed       | **\_\_**  | **\_\_**  | \_\_\_% |
| Plaintiffs Prioritized | **\_\_**  | **\_\_**  | \_\_\_% |
| Documents Filed        | **\_\_**  | **\_\_**  | \_\_\_% |
| FOIL Responses         | **\_\_**  | **\_\_**  | \_\_\_% |
| Escalations to CEO     | **\_\_**  | **\_\_**  | \_\_\_% |

---

## Error Handling & Escalation

### When to Escalate to CEO

| Situation                          | Escalation Path               |
| ---------------------------------- | ----------------------------- |
| Tier 1 plaintiff complaint         | Immediate CEO notification    |
| Document filing rejection          | Review with legal, notify CEO |
| FOIL reveals major asset (> $100K) | Priority CEO call queue       |
| System outage > 1 hour             | CEO + IT notification         |
| Debtor threatens legal action      | Immediate legal + CEO         |

### Common Error Resolution

| Error                      | Resolution                        |
| -------------------------- | --------------------------------- |
| Duplicate plaintiff entry  | Merge records, preserve history   |
| Incorrect judgment amount  | Verify with court, update + note  |
| Missing debtor SSN         | Submit skip trace request         |
| FOIL request rejected      | Review rejection reason, resubmit |
| Document signature missing | Contact plaintiff, resend package |

---

## System Quick Reference

| Function              | Dashboard Location           |
| --------------------- | ---------------------------- |
| Intake Queue          | Ops → Intake Gateway         |
| Plaintiff Priority    | Overview → Priority Pipeline |
| Document Queue        | Ops → Paperwork Queue        |
| FOIL Tracking         | Ops → FOIL Management        |
| Skip Trace Status     | Enforcement → Skip Trace     |
| Collectability Scores | Plaintiff → Detail View      |

---

_This manual is confidential and proprietary to Dragonfly Civil._

**Document Control**

- Created: December 2025
- Last Updated: December 3, 2025
- Owner: Operations Department
- Review Cycle: Quarterly
