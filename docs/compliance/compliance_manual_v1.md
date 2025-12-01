# Dragonfly Civil – Compliance Manual v1.0

> **Document Status:** ACTIVE – Training Required Before Operations  
> **Effective Date:** December 2025  
> **Owner:** COO/CTO (Compliance Coordinator)  
> **Review Cycle:** Quarterly or upon regulatory change

---

## Table of Contents

1. [Scope & Regulatory Framework](#1-scope--regulatory-framework)
2. [FCRA Compliance](#2-fcra-compliance)
3. [FDCPA Compliance](#3-fdcpa-compliance)
4. [Data Security & Privacy](#4-data-security--privacy)
5. [System-Enforced Controls](#5-system-enforced-controls)
6. [Operator Requirements](#6-operator-requirements)
7. [Prohibited Conduct](#7-prohibited-conduct)
8. [Incident Response](#8-incident-response)
9. [Training & Certification](#9-training--certification)

---

## 1. Scope & Regulatory Framework

### 1.1 What We Do

Dragonfly Civil LLC is a **civil judgment enforcement company** operating in New York. We:

- Purchase or acquire assignments of court judgments
- Locate debtors and their assets through licensed skip-tracing
- Execute legal enforcement remedies (garnishments, levies, subpoenas)
- Communicate with judgment debtors to facilitate payment

**We are NOT:**

- A harassment operation
- A scam or fraud scheme
- Above the law

Every action we take is backed by a valid court judgment. We enforce what courts have already decided.

### 1.2 Laws That Govern Us

| Law                          | What It Covers                 | Our Exposure                |
| ---------------------------- | ------------------------------ | --------------------------- |
| **FDCPA** (15 U.S.C. § 1692) | Debt collection communications | HIGH – All debtor contact   |
| **FCRA** (15 U.S.C. § 1681)  | Consumer report access         | HIGH – Skip tracing         |
| **GLBA** (15 U.S.C. § 6801)  | Financial data safeguards      | MEDIUM – Data security      |
| **NY CPLR Article 52**       | Enforcement procedures         | HIGH – All enforcement      |
| **NY GOL § 5-1501**          | Assignment requirements        | HIGH – Judgment acquisition |
| **NY Banking Law § 9-x**     | Exempt funds                   | HIGH – Bank levies          |

### 1.3 Why Compliance Matters

**Legal consequences of violations:**

- FDCPA: $1,000 per violation + actual damages + attorney fees
- FCRA: $100–$1,000 per willful violation + punitive damages
- Class actions can multiply exposure exponentially
- NY AG enforcement actions
- Loss of ability to enforce judgments

**Business consequences:**

- Reputation damage
- Inability to acquire judgment portfolios
- Personal liability for officers
- Insurance coverage denial

---

## 2. FCRA Compliance

### 2.1 What Is a Consumer Report?

A "consumer report" is any communication from a Consumer Reporting Agency (CRA) bearing on a consumer's:

- Credit worthiness
- Credit standing
- Credit capacity
- Character
- General reputation
- Personal characteristics
- Mode of living

**Our skip-trace vendors (idiCORE, TLO, etc.) provide consumer reports.**

### 2.2 Permissible Purpose

We may ONLY access consumer reports for **permissible purposes** under 15 U.S.C. § 1681b:

| Purpose                      | When It Applies                | Our Use    |
| ---------------------------- | ------------------------------ | ---------- |
| **Collection of an account** | We own or service the judgment | ✅ PRIMARY |
| **Review of an account**     | Existing debtor relationship   | ✅ ALLOWED |
| **Court order**              | Subpoena or court directive    | ✅ ALLOWED |
| **Consumer consent**         | Written authorization          | RARE       |

**NEVER access a consumer report:**

- Before we own/service the judgment
- For personal curiosity
- For non-collection purposes
- For marketing
- For anyone outside the company

### 2.3 System Enforcement: external_data_calls

Every skip-trace query is logged automatically:

```sql
-- Every API call to idiCORE, TLO, etc. creates a record:
external_data_calls:
  - id (auto)
  - judgment_id (required - links to our permissible purpose)
  - provider (idiCORE, TLO, etc.)
  - endpoint (which API called)
  - http_status (response code)
  - called_at (timestamp)
  - called_by (user/system)
  - permissible_purpose (documented reason)
  - response_summary (no PII stored)
```

**Audit capability:** We can prove every consumer report access was:

- Tied to a specific judgment we own
- Made for a documented permissible purpose
- Logged with timestamp and user

### 2.4 Operator Requirements for FCRA

**Before running a skip trace:**

- [ ] Confirm judgment is in our system
- [ ] Confirm we own or service the judgment
- [ ] Document the reason (system does this automatically)

**After receiving results:**

- [ ] Use data only for enforcement
- [ ] Do not share outside the company
- [ ] Do not retain longer than needed

**If we take adverse action based on consumer report:**

- [ ] Provide adverse action notice (rare for enforcement)
- [ ] Include CRA contact information
- [ ] Inform of right to dispute

### 2.5 FCRA Red Flags

🚨 **Stop and escalate if:**

- Someone asks to run a trace "just to check"
- A request comes in without a judgment ID
- Anyone outside the company asks for report data
- You're asked to look up someone not in our system

---

## 3. FDCPA Compliance

### 3.1 Overview

The Fair Debt Collection Practices Act protects consumers from abusive, deceptive, and unfair debt collection. It applies to **every communication** with a debtor.

**Key principle:** We enforce judgments firmly but fairly. A court has already ruled in our favor – we don't need to be aggressive or deceptive.

### 3.2 Initial Communication Requirements

The **first communication** with a debtor must include or be followed within 5 days by the "validation notice":

**Required Elements:**

1. Amount of the debt
2. Name of the creditor (original judgment creditor or us)
3. Statement that unless disputed within 30 days, debt is assumed valid
4. Statement that we will provide verification if disputed in writing
5. Statement that we will provide original creditor name if requested

**Our System:** Validation notices are tracked in `debtor_communications` with `validation_sent_at` timestamp.

### 3.3 Time & Place Restrictions

#### Calling Hours

**Federal FDCPA:** No calls before 8:00 AM or after 9:00 PM **in the debtor's time zone**

**Our System Enforcement:**

```sql
-- fn_is_fdcpa_allowed_time(debtor_timezone TEXT)
-- Returns TRUE only during permissible hours
-- Called before every outbound dial
```

| Debtor Location | Earliest Call (ET) | Latest Call (ET) |
| --------------- | ------------------ | ---------------- |
| Eastern Time    | 8:00 AM            | 9:00 PM          |
| Central Time    | 9:00 AM            | 10:00 PM         |
| Mountain Time   | 10:00 AM           | 11:00 PM         |
| Pacific Time    | 11:00 AM           | 12:00 AM         |

**If unknown timezone:** Assume earliest restriction (8 AM ET, 6 PM PT)

#### Place Restrictions

**Do NOT call:**

- Workplace if debtor says employer disapproves
- Any number debtor has asked us not to call
- After debtor requests written-only communication

### 3.4 Communication Content Requirements

#### Every Communication Must:

1. **Identify the caller:** "This is [Name] from Dragonfly Civil"
2. **State purpose:** "I'm calling about a court judgment"
3. **Mini-Miranda (first contact):** "This is an attempt to collect a debt. Any information obtained will be used for that purpose."

#### Every Communication Must NOT:

1. ❌ Threaten violence or criminal prosecution
2. ❌ Use obscene or profane language
3. ❌ Publish debtor's name on "bad debt" lists
4. ❌ Advertise the debt for sale to coerce payment
5. ❌ Cause phone to ring repeatedly to harass
6. ❌ Call without meaningful disclosure of identity
7. ❌ Misrepresent amount owed
8. ❌ Falsely imply attorney involvement
9. ❌ Threaten action we cannot or will not take
10. ❌ Communicate with third parties about the debt

### 3.5 Dispute Handling

**If debtor disputes the debt in writing within 30 days:**

1. **STOP** all collection activity
2. Log dispute in system immediately
3. Obtain verification (court judgment, assignment docs)
4. Send verification to debtor
5. Resume collection only after verification sent

**Verification must include:**

- Copy of judgment (or summary)
- Assignment documentation showing our ownership
- Calculation of amount owed (principal + interest)

### 3.6 Cease & Desist

**If debtor requests in writing that we stop contact:**

1. **STOP** all direct communication
2. We may still:

   - Send one final notice stating we're ceasing contact
   - Continue legal enforcement (garnishments, levies)
   - Notify debtor of specific legal actions taken

3. Log cease request in system
4. Flag debtor record as "cease communication"

### 3.7 FDCPA Red Flags

🚨 **Stop and escalate if:**

- Debtor says "stop calling me" (document and flag)
- Debtor disputes the debt (document and pause)
- Debtor claims it's not their debt (verify identity)
- Debtor mentions attorney (note and continue carefully)
- Debtor mentions bankruptcy (STOP - verify filing)
- Debtor becomes hostile or threatens (disengage)

---

## 4. Data Security & Privacy

### 4.1 Data We Handle

| Data Type        | Classification | Handling                                |
| ---------------- | -------------- | --------------------------------------- |
| SSN              | CONFIDENTIAL   | Encrypted, minimal access, never verbal |
| Bank accounts    | CONFIDENTIAL   | Encrypted, enforcement use only         |
| Employment info  | CONFIDENTIAL   | Encrypted, enforcement use only         |
| Home address     | CONFIDENTIAL   | Encrypted, service/filing only          |
| Phone numbers    | INTERNAL       | System access only                      |
| Judgment amounts | INTERNAL       | Business use                            |
| Court records    | PUBLIC         | Standard handling                       |

### 4.2 Access Principles

**Need-to-Know:** Access only the data required for your specific task.

**Minimum Necessary:** Use the minimum data needed to accomplish the purpose.

**No Screenshots:** Do not screenshot, photograph, or copy PII outside the system.

**No Personal Devices:** Do not access PII from personal phones or computers.

**No Verbal SSN:** Never read a full SSN aloud, even on internal calls.

### 4.3 System Enforcement: RLS & Audit

**Row-Level Security (RLS):**

- All PII tables have RLS enabled
- Access controlled by role and context
- Even with database access, users see only permitted data

**Append-Only Audit Logs:**

- All changes to PII tables are logged
- Logs cannot be modified or deleted
- Full audit trail for compliance review

**Access Logging:**

- Every data access creates log entry
- Quarterly access review by Compliance Coordinator
- Anomalous access flagged for investigation

### 4.4 Data Incidents

**What is a data incident?**

- Unauthorized access to PII
- Accidental disclosure of PII
- Lost or stolen device with data access
- Suspicious activity in systems
- Vendor breach affecting our data

**Immediate response:**

1. Stop the activity causing the incident
2. Report to COO/CTO immediately
3. Do not attempt to "fix" or "cover up"
4. Document everything you observed

---

## 5. System-Enforced Controls

### 5.1 Control Summary

| Control             | What It Prevents                 | System Component              |
| ------------------- | -------------------------------- | ----------------------------- |
| FDCPA Time Guard    | Calls outside permitted hours    | `fn_is_fdcpa_allowed_time()`  |
| FCRA Audit Log      | Untracked consumer report access | `external_data_calls` table   |
| Append-Only Logs    | Audit trail tampering            | Database triggers             |
| RLS                 | Unauthorized data access         | Supabase RLS policies         |
| Validation Tracking | Missing validation notices       | `debtor_communications`       |
| Dispute Flag        | Collection during dispute        | `judgments.dispute_status`    |
| Cease Flag          | Contact after cease request      | `debtors.cease_communication` |

### 5.2 Operator Reliance on Controls

**You may rely on:**

- System showing "call allowed" before dialing
- System showing no dispute flag before collection
- System showing no cease flag before contact

**You must NOT:**

- Override or ignore system warnings
- Attempt to work around controls
- Assume controls are wrong without verification

**If system seems wrong:**

- Stop the action
- Report to COO/CTO
- Document the discrepancy

---

## 6. Operator Requirements

### 6.1 Before Every Call

- [ ] Check system shows call is permitted (time check)
- [ ] Review debtor record for flags (dispute, cease, bankruptcy)
- [ ] Have judgment details ready (case number, amount, creditor)
- [ ] Have script/talking points available
- [ ] Be in a private location (others cannot hear call)

### 6.2 During Every Call

- [ ] Identify yourself and company
- [ ] State purpose of call
- [ ] Deliver Mini-Miranda on first contact
- [ ] Listen for dispute, hardship, or validation requests
- [ ] Take notes in real-time
- [ ] Stay calm and professional regardless of debtor's tone

### 6.3 After Every Call

- [ ] Log call outcome in system immediately
- [ ] Note any requests (dispute, validation, cease, written)
- [ ] Update follow-up schedule
- [ ] Flag any compliance concerns
- [ ] Report any threats or concerning behavior

### 6.4 Documentation Standards

**Every contact must be logged with:**

- Date and time
- Phone number called
- Person reached (debtor, other, voicemail)
- Outcome (payment, promise, dispute, etc.)
- Notes on conversation
- Follow-up actions scheduled

**Documentation must be:**

- Factual, not editorial
- Complete but concise
- Entered same day (preferably immediately)
- Free of inappropriate comments

---

## 7. Prohibited Conduct

### 7.1 Absolute Prohibitions

The following actions are **NEVER permitted** and are grounds for immediate termination:

| Prohibition                                   | Why                       |
| --------------------------------------------- | ------------------------- |
| Threatening violence or harm                  | Criminal, FDCPA violation |
| Using obscene language                        | FDCPA violation           |
| Calling outside permitted hours               | FDCPA violation           |
| Lying about amount owed                       | FDCPA violation           |
| Pretending to be attorney/government          | Criminal, FDCPA violation |
| Discussing debt with third parties            | FDCPA violation           |
| Continuing collection during dispute          | FDCPA violation           |
| Accessing reports without permissible purpose | FCRA violation            |
| Sharing PII outside company                   | Data breach               |
| Overriding system controls                    | Compliance violation      |

### 7.2 Prohibited Phrases

**Never say:**

❌ "You'll go to jail if you don't pay"

- Collection is civil, not criminal

❌ "We'll tell your employer/family about this"

- Third-party disclosure prohibited

❌ "We're going to sue you" (unless actually filing)

- Cannot threaten action we won't take

❌ "This will ruin your credit forever"

- Judgments have finite impact

❌ "You have no choice but to pay"

- Debtor always has options

❌ "I'm calling from the court/sheriff"

- False government affiliation

❌ "This is your final notice" (if it's not)

- Deceptive statement

❌ Any insults, name-calling, or personal attacks

- Harassment

### 7.3 Gray Areas – Ask Before Acting

**Check with supervisor before:**

- Calling a number debtor didn't provide directly
- Leaving detailed voicemail
- Sending communication through new channel
- Accepting unusual payment arrangement
- Responding to attorney letter
- Any situation not covered by training

---

## 8. Incident Response

### 8.1 Complaint Handling

**When a debtor complains:**

1. **Listen** – Do not interrupt or become defensive
2. **Acknowledge** – "I understand you're concerned about..."
3. **Document** – Note exactly what they said
4. **Escalate** – "Let me have a supervisor review this"
5. **Flag** – Mark account for review
6. **Pause** – No further collection until reviewed

**Complaint categories:**

- Harassment claim → Immediate supervisor review
- Wrong person claim → Identity verification required
- Dispute of amount → Validation required
- Bankruptcy claim → STOP, verify filing
- Attorney representation → Note and proceed carefully

### 8.2 Regulatory Inquiry Response

**If you receive contact from:**

- CFPB
- NY Attorney General
- NY Department of Financial Services
- Any court or government agency

**Immediate response:**

1. Be polite and professional
2. Do NOT provide substantive information
3. Say: "I'll need to have our management respond to this"
4. Get contact information and reference number
5. Notify CEO immediately
6. Do not discuss with anyone except management

### 8.3 Litigation Response

**If you receive:**

- Lawsuit papers
- Subpoena
- Cease and desist from attorney

**Immediate response:**

1. Do not ignore or discard
2. Note date received
3. Forward to CEO same day
4. Do not contact debtor until cleared
5. Preserve all related documents

---

## 9. Training & Certification

### 9.1 Initial Training Requirements

Before handling any debtor contact, operators must complete:

| Module                   | Duration | Passing Score |
| ------------------------ | -------- | ------------- |
| FDCPA Fundamentals       | 2 hours  | 85%           |
| FCRA Basics              | 1 hour   | 85%           |
| System Training          | 2 hours  | Practical     |
| Call Handling            | 1 hour   | Role-play     |
| Compliance Manual Review | 1 hour   | Attestation   |

### 9.2 Ongoing Requirements

| Requirement          | Frequency   |
| -------------------- | ----------- |
| Compliance refresher | Quarterly   |
| Call quality review  | Monthly     |
| Policy update review | As released |
| Re-certification     | Annual      |

### 9.3 Certification Attestation

```
I, _________________, have read and understand the Dragonfly Civil
Compliance Manual v1.0. I agree to:

- Follow all FDCPA and FCRA requirements
- Use company systems properly
- Protect consumer data
- Report compliance concerns immediately
- Ask questions when unsure

I understand that violations may result in disciplinary action,
including termination, and may expose me to personal liability.

Signature: _________________ Date: _________________
```

---

## Appendix: Quick Reference

### A.1 FDCPA Call Checklist

```
□ System shows call permitted
□ No dispute flag on account
□ No cease communication flag
□ Identified myself and company
□ Stated purpose of call
□ Delivered Mini-Miranda (if first contact)
□ Logged call and outcome
□ Scheduled follow-up if needed
```

### A.2 Key Contacts

| Role            | Contact        | When to Use                       |
| --------------- | -------------- | --------------------------------- |
| Supervisor      | [Ops Director] | Daily questions, call escalation  |
| Compliance      | [COO/CTO]      | Compliance concerns, incidents    |
| Management      | [CEO]          | Legal threats, regulatory contact |
| Outside Counsel | [TBD]          | Upon management approval only     |

### A.3 Regulatory Resources

- CFPB FDCPA Information: consumerfinance.gov/ask-cfpb
- FTC FCRA Guidance: ftc.gov/tips-advice/business-center
- NY Courts Self-Help: nycourts.gov/courthelp

---

_This manual is a living document. Report any errors, gaps, or suggestions to the Compliance Coordinator._
