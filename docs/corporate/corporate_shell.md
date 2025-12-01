# Dragonfly Civil – Corporate Shell & Governance Framework

> **Document Status:** DRAFT v1.0 – For internal planning and attorney review  
> **Entity:** Dragonfly Civil LLC (New York Limited Liability Company)  
> **Effective Date:** Upon attorney approval and execution  
> **Last Updated:** December 2025

---

## Table of Contents

1. [Governance Structure](#1-governance-structure)
2. [Capital Allocation Policy](#2-capital-allocation-policy)
3. [Financial Controls & Approval Matrix](#3-financial-controls--approval-matrix)
4. [Compliance Framework](#4-compliance-framework)
5. [Data Governance & Privacy](#5-data-governance--privacy)
6. [Escalation Procedures](#6-escalation-procedures)
7. [Operational Policies](#7-operational-policies)
8. [Attorney Review Checklist](#8-attorney-review-checklist)

---

## 1. Governance Structure

### 1.1 Entity Overview

| Attribute        | Value                                                         |
| ---------------- | ------------------------------------------------------------- |
| Legal Name       | Dragonfly Civil LLC                                           |
| Jurisdiction     | New York                                                      |
| Entity Type      | Member-Managed LLC                                            |
| Primary Business | Civil judgment enforcement, skip tracing, debtor intelligence |
| Registered Agent | [TBD – Attorney to advise]                                    |

### 1.2 Member Roles & Responsibilities

#### Managing Member / CEO ("Dad")

**Title:** Managing Member, Chief Executive Officer

**Responsibilities:**

- Ultimate fiduciary responsibility for the company
- Final authority on strategic direction and major capital decisions
- Bank account signatory (all accounts)
- Contract execution authority for agreements >$5,000
- Relationship owner for institutional partners (banks, judgment sellers)
- Quarterly board reporting and financial oversight

**Voting Weight:** 51% (or as specified in Operating Agreement)

#### Member / COO-CTO ("Son")

**Title:** Member, Chief Operating Officer / Chief Technology Officer

**Responsibilities:**

- Product strategy and technology architecture
- Engineering team management and vendor relationships
- Data systems compliance (technical controls)
- Operational spending authority up to $5,000
- System security and access control
- Integration with legal/compliance requirements

**Voting Weight:** 24.5% (or as specified in Operating Agreement)

#### Operations Director ("Mom")

**Title:** Operations Director (may be Member or Employee)

**Responsibilities:**

- Daily enforcement operations management
- Call queue execution and plaintiff communication
- Document preparation and signature workflow
- Court filing coordination
- Vendor management (process servers, filing services)
- Operational spending authority up to $500

**Compensation:** Salary + performance bonus tied to recovery metrics

### 1.3 Decision-Making Framework

#### Unanimous Consent Required

The following actions require **written consent of all Members**:

- [ ] Admission of new members or equity issuance
- [ ] Sale, merger, or dissolution of the company
- [ ] Amendments to the Operating Agreement
- [ ] Personal guarantees or pledges of company assets
- [ ] Debt obligations exceeding $50,000
- [ ] Material change in business purpose
- [ ] Distributions exceeding retained earnings

#### Managing Member Authority

The Managing Member may act **without additional consent** for:

- [ ] Day-to-day business operations within approved budget
- [ ] Hiring/termination of employees (non-equity)
- [ ] Vendor contracts under $10,000 annual value
- [ ] Bank account management and routine transfers
- [ ] Tax elections and filings
- [ ] Insurance procurement and claims

#### Member Vote (Majority Required)

Decisions requiring **majority member vote** (by ownership percentage):

- [ ] Annual budget approval
- [ ] Capital calls or additional member contributions
- [ ] Single expenditures between $5,000 and $50,000
- [ ] New business lines or significant scope expansion
- [ ] Selection of outside counsel for non-routine matters
- [ ] Settlement of disputes exceeding $10,000

### 1.4 Mini-Board Cadence

#### Monthly Operations Review (1st Monday)

**Attendees:** All Members + Operations Director  
**Duration:** 60 minutes  
**Agenda:**

1. **Financial Dashboard** (15 min)

   - Cash position and runway
   - Monthly P&L vs. budget
   - Accounts receivable aging (judgments in collection)

2. **Pipeline Review** (20 min)

   - New judgments acquired
   - Enforcement stage progression
   - Recovery rate and cycle time

3. **Operations Report** (15 min)

   - Call queue metrics (connect rate, outcomes)
   - Pending signatures and court filings
   - Vendor performance issues

4. **Risk & Compliance** (10 min)
   - Any complaints or disputes received
   - Data incidents or system issues
   - Regulatory developments

**Output:** Meeting notes stored in `docs/minutes/YYYY-MM-monthly.md`

#### Quarterly Strategy Session (1st week of Q1, Q2, Q3, Q4)

**Attendees:** All Members  
**Duration:** 2-3 hours  
**Agenda:**

1. **Financial Performance** (30 min)

   - Quarterly financials review
   - Budget variance analysis
   - Cash flow projections

2. **Strategic Initiatives** (45 min)

   - Technology roadmap progress
   - New judgment acquisition channels
   - Partnership opportunities

3. **Capital Allocation** (30 min)

   - Investment policy compliance
   - Upcoming capital needs
   - Distribution decisions

4. **Risk Assessment** (30 min)

   - Portfolio quality review
   - Compliance audit findings
   - Insurance adequacy

5. **Goals for Next Quarter** (15 min)
   - Key objectives and owners
   - Resource requirements

**Output:** Quarterly report in `docs/quarterly/YYYY-QN-report.md`

---

## 2. Capital Allocation Policy

### 2.1 Overview

**Total Initial Capital:** $250,000 (loan proceeds)  
**Purpose:** Fund operations, judgment acquisition, and technology through profitability

### 2.2 Allocation Framework

| Category                        | Allocation | Amount   | Purpose                                     |
| ------------------------------- | ---------- | -------- | ------------------------------------------- |
| **Operating Reserve**           | 20%        | $50,000  | 6-month runway for fixed costs              |
| **Judgment Acquisition**        | 50%        | $125,000 | Purchase/settlement of judgment portfolios  |
| **Enforcement Costs**           | 20%        | $50,000  | Court fees, process servers, asset searches |
| **Technology & Infrastructure** | 10%        | $25,000  | Supabase, n8n, API costs, development       |

### 2.3 Category Definitions

#### Operating Reserve ($50,000)

**Purpose:** Ensure business continuity regardless of collection timing

**Permitted Uses:**

- Payroll and contractor payments
- Office/infrastructure costs (if any)
- Insurance premiums
- Professional services (accounting, legal)
- Loan interest payments

**Restrictions:**

- Minimum balance: $25,000 at all times
- Replenishment required within 30 days if below minimum
- No use for speculative investments

#### Judgment Acquisition Fund ($125,000)

**Purpose:** Purchase judgment portfolios or individual judgments

**Permitted Uses:**

- Direct judgment purchases from plaintiffs
- Portfolio acquisitions from brokers/attorneys
- Assignment fees and transfer costs
- Due diligence costs (skip tracing pre-purchase)

**Investment Criteria:**

- Minimum expected recovery rate: 15% of face value
- Maximum single judgment: $25,000 (10% of fund)
- Maximum single portfolio: $50,000 (40% of fund)
- Priority: Wage garnishment-eligible debtors with verified employment

**Approval Requirements:**

- <$5,000: COO/CTO approval
- $5,000–$25,000: CEO + COO/CTO approval
- > $25,000: All Members

#### Enforcement Cost Fund ($50,000)

**Purpose:** Fund collection activities on owned/managed judgments

**Permitted Uses:**

- Court filing fees (information subpoenas, restraining notices, etc.)
- Marshal/sheriff fees
- Process server fees
- Asset search and skip trace services
- Bank levy costs
- Property execution costs

**Per-Judgment Limits:**

- Maximum enforcement spend: 20% of judgment face value
- Exception: CEO approval for strategic high-value cases

**Tracking:** All costs logged per judgment in `judgment_costs` table

#### Technology Fund ($25,000)

**Purpose:** Maintain and improve operational technology

**Permitted Uses:**

- Supabase hosting (Pro tier)
- n8n cloud or self-hosted infrastructure
- API subscriptions (idiCORE, TLO, etc.)
- Development contractor costs
- Security tools and monitoring

**Approval Requirements:**

- Monthly recurring <$500: COO/CTO authority
- Annual contracts <$5,000: COO/CTO authority
- > $5,000: CEO + COO/CTO approval

### 2.4 Reallocation Rules

- Quarterly review of allocation percentages
- Reallocation between categories requires majority member vote
- Emergency reallocation (>10% shift): requires unanimous consent
- All reallocations documented in quarterly report

### 2.5 Distribution Policy

**No distributions until:**

1. Operating reserve at minimum ($25,000)
2. Loan obligations current
3. 90-day forward cash flow positive

**Distribution approval:**

- Quarterly, upon member vote
- Maximum: 50% of net quarterly profit
- Remainder retained for growth capital

---

## 3. Financial Controls & Approval Matrix

### 3.1 Bank Account Structure

#### Recommended Account Setup

| Account               | Purpose                              | Signatories           | Minimum Balance |
| --------------------- | ------------------------------------ | --------------------- | --------------- |
| **Operating Account** | Daily operations, payroll, vendors   | CEO, COO/CTO          | $10,000         |
| **Trust Account**     | Client funds (if acting as servicer) | CEO only              | Per agreement   |
| **Reserve Account**   | Operating reserve (savings)          | CEO, COO/CTO          | $25,000         |
| **Enforcement Float** | Court fees, marshal costs            | CEO, COO/CTO, Ops Dir | $5,000          |

#### Account Rules

- **Dual signature required:** Transfers >$5,000 between accounts
- **No personal commingling:** Ever
- **Monthly reconciliation:** By 10th of following month
- **Quarterly audit:** External review of all accounts

### 3.2 Spending Approval Matrix

| Amount             | Approver(s)                | Documentation                   | Timeline         |
| ------------------ | -------------------------- | ------------------------------- | ---------------- |
| **<$100**          | Ops Director               | Receipt/invoice                 | Same day         |
| **$100–$500**      | Ops Director               | Receipt + purpose note          | Same day         |
| **$500–$2,500**    | COO/CTO                    | Invoice + budget category       | 24 hours         |
| **$2,500–$5,000**  | COO/CTO + CEO notification | Invoice + written justification | 48 hours         |
| **$5,000–$25,000** | CEO + COO/CTO joint        | Formal approval memo            | 5 business days  |
| **>$25,000**       | All Members                | Board resolution                | 10 business days |

### 3.3 Expense Categories

#### Pre-Approved (Within Budget)

No additional approval needed if within monthly budget:

- Supabase/hosting fees
- API subscriptions (existing vendors)
- Court filing fees (standard)
- Process server fees (contracted rates)
- Office supplies <$100

#### Requires Approval

Always requires explicit approval regardless of amount:

- New vendor relationships
- Legal fees (non-routine)
- Travel expenses
- Marketing/advertising
- Equipment purchases >$500
- Software subscriptions (new)

### 3.4 Per-Judgment P&L Tracking

#### Cost Categories (Tracked in `judgment_costs` table)

```
judgment_costs:
  - judgment_id (FK)
  - cost_type: 'acquisition' | 'filing' | 'service' | 'search' | 'levy' | 'other'
  - amount: decimal
  - vendor: string
  - invoice_number: string
  - paid_at: timestamp
  - approved_by: string
  - notes: text
```

#### Revenue Categories (Tracked in `judgment_payments` table)

```
judgment_payments:
  - judgment_id (FK)
  - payment_type: 'garnishment' | 'levy' | 'voluntary' | 'settlement'
  - gross_amount: decimal
  - net_amount: decimal (after marshal fees, etc.)
  - received_at: timestamp
  - source: string
  - notes: text
```

#### P&L Calculation

```sql
-- Per-judgment profitability
SELECT
  j.id,
  j.case_index_number,
  j.principal_amount,
  COALESCE(SUM(c.amount), 0) as total_costs,
  COALESCE(SUM(p.net_amount), 0) as total_recovered,
  COALESCE(SUM(p.net_amount), 0) - COALESCE(SUM(c.amount), 0) as net_profit,
  CASE WHEN j.principal_amount > 0
    THEN COALESCE(SUM(p.net_amount), 0) / j.principal_amount * 100
    ELSE 0
  END as recovery_rate_pct
FROM core_judgments j
LEFT JOIN judgment_costs c ON c.judgment_id = j.id
LEFT JOIN judgment_payments p ON p.judgment_id = j.id
GROUP BY j.id, j.case_index_number, j.principal_amount;
```

### 3.5 Reporting Requirements

| Report               | Frequency | Owner               | Audience    |
| -------------------- | --------- | ------------------- | ----------- |
| Cash position        | Weekly    | COO/CTO             | All Members |
| Expense detail       | Monthly   | COO/CTO             | CEO         |
| Per-judgment P&L     | Monthly   | Ops Director        | All Members |
| Budget variance      | Monthly   | COO/CTO             | All Members |
| Financial statements | Quarterly | External accountant | All Members |

---

## 4. Compliance Framework

### 4.1 Regulatory Overview

Dragonfly Civil operates under multiple regulatory frameworks:

| Regulation          | Applicability                  | Key Requirements                                                     |
| ------------------- | ------------------------------ | -------------------------------------------------------------------- |
| **FDCPA**           | Debt collection communications | Validation notices, harassment prohibitions, time/place restrictions |
| **FCRA**            | Consumer report usage          | Permissible purpose, adverse action notices, accuracy                |
| **GLBA**            | Financial data safeguarding    | Written security program, vendor oversight                           |
| **NY GOL § 5-1501** | Judgment enforcement           | Proper assignment documentation                                      |
| **CPLR Article 52** | NY enforcement procedures      | Execution, garnishment, subpoena rules                               |

### 4.2 FDCPA Compliance

#### Covered Activities

All debtor communications related to judgment collection, including:

- Phone calls
- Letters and notices
- Emails (if used)
- Text messages (if used)

#### Required Practices

**Initial Communication (Validation Notice):**

- [ ] Amount of debt
- [ ] Name of creditor
- [ ] 30-day dispute rights statement
- [ ] Verification request instructions

**Ongoing Communications:**

- [ ] Identify as debt collector in every communication
- [ ] No calls before 8 AM or after 9 PM (debtor's time zone)
- [ ] Honor cease-and-desist requests
- [ ] No contact at workplace if prohibited
- [ ] No harassment, threats, or deceptive practices

**Prohibited Practices:**

- ❌ False, deceptive, or misleading representations
- ❌ Unfair practices (unauthorized fees, postdated checks)
- ❌ Threats of action we cannot or will not take
- ❌ Contact with third parties (except limited exceptions)
- ❌ Continued collection during dispute validation period

#### Documentation Requirements

Every debtor contact logged in system with:

- Date/time
- Communication method
- Content summary
- Outcome
- Any compliance flags

### 4.3 FCRA Compliance

#### Permissible Purpose

We may access consumer reports only for:

- **Collection of an account:** Judgment we own or service
- **Review of an account:** Existing debtor relationship

**NOT permitted:**

- Pre-acquisition screening without consent
- Employment or tenant screening
- Marketing purposes

#### Required Practices

**Before Accessing Consumer Report:**

- [ ] Document permissible purpose
- [ ] Verify vendor compliance (CRA registered)
- [ ] Log access with purpose code

**After Adverse Action Based on Report:**

- [ ] Provide adverse action notice
- [ ] Include CRA contact information
- [ ] Inform of right to free report
- [ ] Inform of right to dispute

**Data Handling:**

- [ ] Limit access to need-to-know personnel
- [ ] Secure storage (encrypted at rest)
- [ ] Disposal per FACTA requirements
- [ ] No resale or unauthorized sharing

#### Audit Trail

All consumer report access logged:

```
external_data_log:
  - judgment_id
  - provider (idiCORE, TLO, etc.)
  - endpoint
  - timestamp
  - user_id
  - permissible_purpose_code
  - result_summary (no PII)
```

### 4.4 GLBA Safeguards Rule

#### Written Information Security Program (WISP)

**Required Elements:**

1. **Designate Coordinator:** COO/CTO
2. **Risk Assessment:** Annual review of threats
3. **Safeguards Implementation:**
   - Access controls (role-based)
   - Encryption (transit + rest)
   - Secure development practices
   - Incident response plan
4. **Vendor Oversight:** Due diligence on service providers
5. **Program Updates:** Adjust based on changes/incidents

#### Technical Controls (Implemented)

| Control               | Implementation                         |
| --------------------- | -------------------------------------- |
| Access control        | Supabase RLS + API key authentication  |
| Encryption at rest    | Supabase managed encryption            |
| Encryption in transit | TLS 1.2+ required                      |
| Audit logging         | All data access logged                 |
| MFA                   | Required for admin access              |
| Backup                | Supabase PITR (Point-in-Time Recovery) |

### 4.5 State-Specific Requirements (New York)

#### Judgment Enforcement

- Proper assignment documentation filed with court
- Execution valid for 20 years (with proper renewals)
- Interest calculation per NY statutory rate
- Marshal/sheriff procedures per county rules

#### Consumer Protection

- NY CPLR 5222(i): Exempt funds notice required with restraining notice
- NY Banking Law § 9-x: Bank account protection for benefits
- NYC Consumer Protection Law: Additional disclosure requirements

---

## 5. Data Governance & Privacy

### 5.1 Data Classification

| Level            | Description          | Examples                          | Handling                               |
| ---------------- | -------------------- | --------------------------------- | -------------------------------------- |
| **Confidential** | PII + financial data | SSN, bank accounts, employer info | Encrypted, access-logged, need-to-know |
| **Internal**     | Business operations  | Judgment amounts, case status     | Access controlled, not public          |
| **Public**       | Court records        | Case numbers, public filings      | No special handling                    |

### 5.2 Data Handling Rules

#### Collection

- Collect only data necessary for judgment enforcement
- Document source of all data (court records, skip trace, debtor-provided)
- Verify accuracy before relying on data

#### Storage

- All PII encrypted at rest (Supabase default)
- Separate production and development environments
- No PII in logs, error messages, or analytics
- Regular backup verification

#### Access

- Role-based access control (RBAC)
- Access logged and auditable
- Quarterly access review
- Immediate revocation upon role change

#### Retention

| Data Type            | Retention Period              | Disposal Method     |
| -------------------- | ----------------------------- | ------------------- |
| Active judgment data | Life of judgment + 7 years    | Secure deletion     |
| Closed judgment data | 7 years from closure          | Secure deletion     |
| Consumer reports     | 90 days or purpose completion | Secure deletion     |
| Communication logs   | 7 years                       | Archive then delete |
| System logs          | 1 year                        | Automatic rotation  |

#### Disposal

- Secure deletion (not just soft delete)
- Vendor data destruction certificates
- No physical media (cloud-only)

### 5.3 Vendor Data Agreements

Required provisions in all vendor contracts handling our data:

- [ ] Confidentiality obligations
- [ ] Data use limitations (our purpose only)
- [ ] Security requirements (SOC 2 or equivalent)
- [ ] Breach notification (24-48 hours)
- [ ] Audit rights
- [ ] Return/destruction upon termination
- [ ] Indemnification for breaches

#### Approved Vendors

| Vendor           | Purpose             | Agreement Status    |
| ---------------- | ------------------- | ------------------- |
| Supabase         | Database/backend    | [Review ToS]        |
| idiCORE          | Skip tracing        | [Obtain DPA]        |
| n8n              | Workflow automation | [Review ToS]        |
| [Process Server] | Document service    | [Standard contract] |

---

## 6. Escalation Procedures

### 6.1 Escalation Categories

| Category               | Examples                                 | Initial Response | Escalation Path               |
| ---------------------- | ---------------------------------------- | ---------------- | ----------------------------- |
| **Consumer Complaint** | Dispute, harassment claim                | 24 hours         | Ops → COO → CEO → Counsel     |
| **Legal Threat**       | Lawsuit threat, cease & desist           | Same day         | Ops → CEO → Counsel           |
| **Data Incident**      | Breach, unauthorized access              | Immediate        | COO → CEO → Counsel + Insurer |
| **Operational Error**  | Wrong debtor contacted, incorrect amount | Same day         | Ops → COO → CEO               |
| **Regulatory Inquiry** | CFPB, NY AG, court inquiry               | Same day         | CEO → Counsel                 |

### 6.2 Consumer Complaint Handling

#### Step 1: Receipt & Logging (Ops Director)

- Log complaint in system immediately
- Classify: dispute, harassment, wrong person, other
- Pause collection activity on that judgment
- Acknowledge receipt within 24 hours

#### Step 2: Investigation (COO/CTO + Ops)

- Review all communication logs
- Verify judgment ownership and accuracy
- Check for any procedural violations
- Document findings

#### Step 3: Resolution (CEO if needed)

| Finding              | Action                            |
| -------------------- | --------------------------------- |
| Our error            | Correct, apologize, document      |
| Debtor dispute valid | Cease collection, verify debt     |
| Frivolous complaint  | Document, resume collection       |
| Compliance violation | Correct, assess exposure, counsel |

#### Step 4: Documentation

- Written response to consumer if required
- Internal incident report
- Process improvement if systemic

### 6.3 Data Incident Response

#### Severity Levels

| Level        | Definition                           | Response Time |
| ------------ | ------------------------------------ | ------------- |
| **Critical** | Confirmed breach, PII exposed        | Immediate     |
| **High**     | Suspected breach, potential exposure | 4 hours       |
| **Medium**   | Unauthorized access attempt, blocked | 24 hours      |
| **Low**      | Policy violation, no exposure        | 48 hours      |

#### Response Steps

1. **Contain:** Isolate affected systems
2. **Assess:** Determine scope and data involved
3. **Notify:** Internal stakeholders, counsel, insurer
4. **Remediate:** Fix vulnerability, restore systems
5. **Report:** Regulatory notifications if required
6. **Review:** Post-incident analysis and improvements

#### Notification Requirements

| Jurisdiction            | Threshold            | Timeline    |
| ----------------------- | -------------------- | ----------- |
| New York                | Any NY resident PII  | 30 days     |
| Federal (if applicable) | Varies               | Varies      |
| Affected individuals    | Depends on data type | As required |

### 6.4 Legal Threat Response

#### Immediate Actions

- [ ] Do NOT respond substantively without counsel review
- [ ] Preserve all related documents and communications
- [ ] Notify CEO immediately
- [ ] Engage outside counsel within 24 hours
- [ ] Review insurance coverage

#### Documentation

- Copy of threat/complaint
- All communications with that debtor
- All enforcement actions taken
- Internal compliance review

### 6.5 Escalation Contact List

| Role             | Name  | Phone | Email | Authority       |
| ---------------- | ----- | ----- | ----- | --------------- |
| CEO              | Dad   | [TBD] | [TBD] | Final decision  |
| COO/CTO          | Son   | [TBD] | [TBD] | Technical + ops |
| Ops Director     | Mom   | [TBD] | [TBD] | Daily ops       |
| Outside Counsel  | [TBD] | [TBD] | [TBD] | Legal advice    |
| Insurance Broker | [TBD] | [TBD] | [TBD] | Claims          |

---

## 7. Operational Policies

### 7.1 Judgment Acquisition Criteria

#### Minimum Requirements

- [ ] Valid New York state court judgment
- [ ] Judgment not satisfied or vacated
- [ ] Proper assignment documentation available
- [ ] Debtor information sufficient for enforcement
- [ ] No pending appeal or bankruptcy (verified)

#### Preferred Characteristics

- [ ] Debtor has verified employment (wage garnishment eligible)
- [ ] Judgment amount between $2,500 and $50,000
- [ ] Judgment age <5 years
- [ ] Consumer debt (not business-to-business)
- [ ] Clean title (no competing liens on judgment)

#### Due Diligence Checklist

- [ ] Court record verification
- [ ] Assignment chain review
- [ ] Basic skip trace (employment, address)
- [ ] Bankruptcy search (PACER)
- [ ] Existing enforcement search (eCourts)

### 7.2 Enforcement Action Selection

#### Priority Matrix

| Debtor Profile      | Primary Action       | Secondary Action     |
| ------------------- | -------------------- | -------------------- |
| Verified employment | Wage garnishment     | Information subpoena |
| Known bank account  | Bank levy            | Restraining notice   |
| Real property       | Property lien        | Execution            |
| Unknown assets      | Information subpoena | Asset search         |

#### Cost-Benefit Analysis

Before each enforcement action:

- Estimated cost
- Probability of success
- Expected recovery
- Time to recovery

Proceed if: `(Probability × Expected Recovery) > (2 × Estimated Cost)`

### 7.3 Communication Standards

#### Phone Calls

- Introduction: "This is [Name] calling from Dragonfly Civil regarding a court judgment."
- Mini-Miranda: "This is an attempt to collect a debt and any information obtained will be used for that purpose."
- Maximum attempts: 3 per week unless debtor engages
- No calls to workplace if debtor requests

#### Written Communications

- Plain language, professional tone
- All required disclosures included
- Sent via trackable method when required
- Copy retained in system

### 7.4 Settlement Authority

| Discount Level | Authority    | Documentation   |
| -------------- | ------------ | --------------- |
| 0-10%          | Ops Director | Standard form   |
| 11-25%         | COO/CTO      | Approval memo   |
| 26-50%         | CEO          | Formal approval |
| >50%           | All Members  | Resolution      |

---

## 8. Attorney Review Checklist

### 8.1 Documents Requiring Formal Drafting

The following require attorney drafting/review before execution:

#### Corporate Formation

- [ ] **Operating Agreement** – Full legal document with:

  - Member contributions and ownership percentages
  - Profit/loss allocation
  - Distribution waterfall
  - Management provisions
  - Transfer restrictions
  - Dissolution provisions
  - Indemnification clauses

- [ ] **Subscription Agreement** – For any outside investment

- [ ] **Member Resolutions** – Template for major decisions

#### Compliance Documents

- [ ] **FDCPA Compliance Manual** – Detailed procedures
- [ ] **FCRA Permissible Purpose Documentation** – Forms and procedures
- [ ] **Written Information Security Program (WISP)** – Per GLBA
- [ ] **Privacy Policy** – If consumer-facing communications
- [ ] **Data Processing Agreements** – With each vendor

#### Operational Documents

- [ ] **Judgment Assignment Agreement** – Template for acquisitions
- [ ] **Servicing Agreement** – If servicing for others
- [ ] **Contractor Agreements** – For any non-employee workers
- [ ] **Vendor Contracts** – Review of key vendors

### 8.2 Regulatory Filings/Registrations

- [ ] **NY LLC Formation** – Articles of Organization filed
- [ ] **EIN** – Federal tax ID obtained
- [ ] **NY Tax Registration** – State tax accounts
- [ ] **Debt Collector Registration** – If required (verify with counsel)
- [ ] **CFPB Registration** – If collecting >$2M annually (threshold review)

### 8.3 Insurance Requirements

- [ ] **E&O / Professional Liability** – For collection activities
- [ ] **Cyber Liability** – For data breach coverage
- [ ] **General Liability** – Standard business coverage
- [ ] **D&O Insurance** – If formal board structure

### 8.4 Questions for Counsel

1. **Debt collector licensing:** Does NY require specific registration for judgment purchasers vs. original creditors?

2. **FDCPA coverage:** Does FDCPA apply to purchasers of court judgments (post-judgment vs. pre-judgment debt)?

3. **Mini-Miranda scope:** Exact language required for our specific situation?

4. **Bank account structure:** Any trust account requirements for client funds?

5. **Interest calculation:** Proper method for calculating post-judgment interest in NY?

6. **Assignment requirements:** Checklist for valid judgment assignment documentation?

7. **Information subpoena:** Updated requirements post-2023 CPLR amendments?

8. **Exempt funds:** Obligations regarding exempt income identification?

### 8.5 Implementation Timeline

| Phase       | Tasks                                         | Timeline | Owner         |
| ----------- | --------------------------------------------- | -------- | ------------- |
| **Phase 1** | Operating Agreement, bank accounts, insurance | Week 1-2 | CEO + Counsel |
| **Phase 2** | Compliance documents, vendor agreements       | Week 3-4 | COO + Counsel |
| **Phase 3** | Operational procedures, training              | Week 5-6 | Ops + COO     |
| **Phase 4** | Audit and refinement                          | Month 3  | All           |

---

## Appendix A: Approval Form Templates

### A.1 Expenditure Approval Form

```
DRAGONFLY CIVIL LLC - EXPENDITURE APPROVAL

Date: _______________
Requestor: _______________
Amount: $_______________
Vendor: _______________
Purpose: _______________
Budget Category: [ ] Operations [ ] Judgment [ ] Enforcement [ ] Technology
Recurring: [ ] Yes [ ] No  If yes, frequency: _______________

Justification:
________________________________________________________________
________________________________________________________________

Approvals Required:
[ ] Ops Director (if <$500)
[ ] COO/CTO (if $500-$5,000)
[ ] CEO (if >$5,000)
[ ] All Members (if >$25,000)

Approved by: _______________ Date: _______________
```

### A.2 Judgment Acquisition Approval Form

```
DRAGONFLY CIVIL LLC - JUDGMENT ACQUISITION APPROVAL

Date: _______________
Case Number: _______________
Court: _______________
Plaintiff: _______________
Defendant: _______________
Judgment Amount: $_______________
Acquisition Cost: $_______________
Seller: _______________

Due Diligence Checklist:
[ ] Court record verified
[ ] Assignment chain reviewed
[ ] Skip trace completed
[ ] Bankruptcy search completed
[ ] Existing enforcement search completed

Risk Assessment:
Debtor Employment Status: _______________
Estimated Recovery Rate: _______________%
Expected Net Recovery: $_______________
Recommendation: [ ] Acquire [ ] Pass

Approvals:
[ ] COO/CTO (if <$5,000)
[ ] CEO + COO/CTO (if $5,000-$25,000)
[ ] All Members (if >$25,000)

Approved by: _______________ Date: _______________
```

---

## Appendix B: Compliance Checklists

### B.1 New Judgment Onboarding Checklist

- [ ] Assignment documentation received and verified
- [ ] Court record pulled and reviewed
- [ ] Debtor information entered in system
- [ ] Initial skip trace completed
- [ ] Bankruptcy/existing enforcement search completed
- [ ] Validation notice prepared
- [ ] Enforcement strategy selected
- [ ] Cost estimate approved

### B.2 Debtor Communication Checklist

- [ ] Permissible time (8 AM - 9 PM debtor's time)
- [ ] Mini-Miranda delivered
- [ ] Communication logged in system
- [ ] Outcome recorded
- [ ] Follow-up scheduled if needed
- [ ] Compliance flags checked

### B.3 Monthly Compliance Review

- [ ] All validation notices sent within 5 days
- [ ] No prohibited communications logged
- [ ] All disputes handled per procedure
- [ ] Consumer report access documented
- [ ] No data incidents reported
- [ ] Vendor compliance verified

---

_This document is for internal planning purposes and does not constitute legal advice. All policies and procedures should be reviewed by qualified legal counsel before implementation._
