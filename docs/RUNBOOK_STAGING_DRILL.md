# RUNBOOK: Staging Drill (Disaster Recovery Validation)

> **Classification:** Internal Operations  
> **Owner:** Engineering Manager  
> **Last Updated:** 2026-01-07  
> **RTO Target:** < 4 hours from cold backup to certified platform

---

## 🎯 Objective

Validate that Dragonfly Civil can be **fully rebuilt from a cold backup** within the 4-hour Recovery Time Objective (RTO). This drill proves our disaster recovery capabilities and satisfies quarterly compliance requirements.

---

## 📅 Frequency

**Quarterly** — First week of:

- January
- April
- July
- October

| Quarter | Drill Window | Sign-off Due |
| ------- | ------------ | ------------ |
| Q1      | Jan 1–7      | Jan 10       |
| Q2      | Apr 1–7      | Apr 10       |
| Q3      | Jul 1–7      | Jul 10       |
| Q4      | Oct 1–7      | Oct 10       |

---

## 👥 Required Personnel

| Role           | Responsibility                                           |
| -------------- | -------------------------------------------------------- |
| **Drill Lead** | Orchestrates the drill, tracks RTO clock                 |
| **DBA**        | Restores backup, applies sanitization                    |
| **Engineer**   | Runs certification gates, documents results              |
| **Witness**    | Independent observer (Manager or Lead from another team) |

---

## ⏱️ RTO Clock

The drill is **timed from T+0** (environment creation) to **T+PASS** (golden path verified).

| Milestone                  | Target | Actual   |
| -------------------------- | ------ | -------- |
| T+0: Spin Up               | 0:00   | **\_\_** |
| T+1: Restore Complete      | 1:00   | **\_\_** |
| T+2: Sanitization Complete | 1:15   | **\_\_** |
| T+3: Go-Live Gates Pass    | 2:30   | **\_\_** |
| T+4: Golden Path Pass      | 3:00   | **\_\_** |
| T+5: Teardown Complete     | 3:30   | **\_\_** |
| **Total RTO**              | < 4:00 | **\_\_** |

---

## 🚀 Protocol

### Phase 1: Spin Up (T+0)

Create a temporary Railway environment for the drill.

```bash
# Generate drill environment name with date stamp
$DrillDate = Get-Date -Format "yyyyMMdd"
$DrillEnv = "dragonfly-drill-$DrillDate"

# Create Railway environment (via Railway CLI or Dashboard)
railway environment create $DrillEnv
```

**Dashboard Method:**

1. Go to [Railway Dashboard](https://railway.app/dashboard)
2. Select `dragonfly-civil` project
3. Click **Environments** → **New Environment**
4. Name: `dragonfly-drill-YYYYMMDD`
5. Do NOT copy variables from production (we'll configure manually)

**Required Environment Variables:**

```env
SUPABASE_MODE=drill
SUPABASE_URL=<drill-db-url>
SUPABASE_ANON_KEY=<drill-anon-key>
SUPABASE_SERVICE_KEY=<drill-service-key>
DRILL_MODE=true
```

> ⏱️ **Checkpoint:** Environment created. Record time: `______`

---

### Phase 2: Restore (T+1)

Apply the latest production backup snapshot to the drill database.

#### Option A: Supabase Point-in-Time Recovery

```bash
# Via Supabase Dashboard:
# 1. Go to Project Settings → Database → Backups
# 2. Select latest daily backup
# 3. Restore to a NEW project (drill instance)
```

#### Option B: Manual pg_dump Restore

```bash
# Restore from backup file
$BackupFile = "backups/dragonfly_prod_latest.sql"
$DrillDbUrl = "<DRILL_DATABASE_URL>"

pg_restore --clean --if-exists --no-owner --no-acl `
  -d $DrillDbUrl $BackupFile
```

#### Option C: Supabase CLI Restore

```bash
# List available backups
supabase db backups list --project-ref <prod-ref>

# Download latest backup
supabase db dump --project-ref <prod-ref> -f drill_restore.sql

# Apply to drill instance
psql $DrillDbUrl -f drill_restore.sql
```

> ⏱️ **Checkpoint:** Backup restored. Record time: `______`

---

### Phase 3: Sanitize (T+2)

> ⚠️ **CRITICAL STEP** — Prevents accidental PII leakage from drill environment

Run the sanitization script to nullify all personally identifiable information:

```sql
-- ============================================
-- DRILL SANITIZATION SCRIPT
-- Run against drill database ONLY
-- ============================================

BEGIN;

-- Verify we're in a drill environment (safety check)
DO $$
BEGIN
  IF current_database() NOT LIKE '%drill%' THEN
    RAISE EXCEPTION 'ABORT: This does not appear to be a drill database!';
  END IF;
END $$;

-- Sanitize parties table (defendants, plaintiffs, etc.)
UPDATE public.parties
SET contact_info = '{}'::jsonb,
    email = NULL,
    phone = NULL
WHERE contact_info IS NOT NULL
   OR email IS NOT NULL
   OR phone IS NOT NULL;

-- Sanitize plaintiffs table
UPDATE public.plaintiffs
SET email = 'drill-' || id || '@example.invalid',
    phone = NULL,
    address = NULL,
    city = NULL,
    state = NULL,
    zip = NULL
WHERE email IS NOT NULL;

-- Sanitize plaintiff_contacts
UPDATE public.plaintiff_contacts
SET email = 'drill-' || id || '@example.invalid',
    phone = '555-000-0000',
    notes = '[SANITIZED FOR DRILL]'
WHERE email IS NOT NULL OR phone IS NOT NULL;

-- Sanitize any user data
UPDATE auth.users
SET email = 'drill-' || id || '@example.invalid',
    phone = NULL,
    raw_user_meta_data = '{}'::jsonb
WHERE email NOT LIKE '%@example.invalid';

-- Clear sensitive metadata from judgments
UPDATE public.judgments
SET debtor_ssn_last4 = NULL,
    notes = regexp_replace(notes, '\d{3}-\d{2}-\d{4}', '[SSN-REDACTED]', 'g')
WHERE debtor_ssn_last4 IS NOT NULL;

-- Log sanitization
INSERT INTO ops.audit_log (action, details, created_at)
VALUES (
  'DRILL_SANITIZATION',
  jsonb_build_object(
    'drill_date', current_date,
    'sanitized_at', now(),
    'tables_processed', ARRAY['parties', 'plaintiffs', 'plaintiff_contacts', 'auth.users', 'judgments']
  ),
  now()
);

COMMIT;

-- Verification query
SELECT
  'parties' as table_name,
  COUNT(*) FILTER (WHERE contact_info != '{}') as unsanitized_count
FROM public.parties
UNION ALL
SELECT
  'plaintiffs',
  COUNT(*) FILTER (WHERE email NOT LIKE 'drill-%@example.invalid' AND email IS NOT NULL)
FROM public.plaintiffs
UNION ALL
SELECT
  'plaintiff_contacts',
  COUNT(*) FILTER (WHERE email NOT LIKE 'drill-%@example.invalid' AND email IS NOT NULL)
FROM public.plaintiff_contacts;
```

**Expected Output:**

```
 table_name         | unsanitized_count
--------------------+-------------------
 parties            |                 0
 plaintiffs         |                 0
 plaintiff_contacts |                 0
```

> ⏱️ **Checkpoint:** Sanitization complete. Unsanitized count = 0. Record time: `______`

---

### Phase 4: Certify (T+3)

Run the Go-Live Gate certification against the drill environment.

```powershell
# Set drill environment
$env:SUPABASE_MODE = 'drill'

# Run all production gates
python -m tools.go_live_gate --env drill
```

**Expected Output:**

```
═══════════════════════════════════════════════════════════
  🚀 GO-LIVE GATE CERTIFICATION — DRILL
═══════════════════════════════════════════════════════════

[Gate 1/11] Schema Integrity ............ ✅ PASS
[Gate 2/11] Migration Status ............ ✅ PASS
[Gate 3/11] View Deployability .......... ✅ PASS
[Gate 4/11] RLS Enforcement ............. ✅ PASS
...
[Gate 11/11] Business Logic ............. ✅ PASS

═══════════════════════════════════════════════════════════
  ✅ ALL GATES PASSED — DRILL CERTIFIED
═══════════════════════════════════════════════════════════
```

**All 11 gates must pass.** If any gate fails:

1. Document the failure
2. Fix in the drill environment
3. Re-run certification
4. Note remediation time in RTO tracking

> ⏱️ **Checkpoint:** All gates passed. Record time: `______`

---

### Phase 5: Verify (T+4)

Run the Golden Path integration test with cleanup.

```powershell
# Run golden path with automatic cleanup
python -m tools.golden_path --env drill --cleanup
```

**Expected Output:**

```
═══════════════════════════════════════════════════════════
  🛤️  GOLDEN PATH — DRILL
═══════════════════════════════════════════════════════════

[Step 1] Create Plaintiff ............... ✅ PASS
[Step 2] Create Judgment ................ ✅ PASS
[Step 3] Trigger Enrichment ............. ✅ PASS
[Step 4] Verify Collectability .......... ✅ PASS
[Step 5] Check Queue Processing ......... ✅ PASS
[Step 6] Cleanup Test Data .............. ✅ PASS

═══════════════════════════════════════════════════════════
  ✅ GOLDEN PATH COMPLETE — DRILL VERIFIED
═══════════════════════════════════════════════════════════
```

> ⏱️ **Checkpoint:** Golden path verified. Record time: `______`

---

### Phase 6: Teardown (T+5)

> ⚠️ **MANDATORY** — Drill environments must be destroyed immediately after validation

```bash
# Railway CLI teardown
railway environment delete dragonfly-drill-YYYYMMDD --yes

# OR via Dashboard:
# 1. Go to Railway Dashboard
# 2. Select dragonfly-civil project
# 3. Environments → dragonfly-drill-YYYYMMDD
# 4. Settings → Delete Environment
```

**If using a separate Supabase project for drill:**

```bash
# Delete the drill Supabase project
supabase projects delete <drill-project-ref> --confirm
```

**Verification:**

- [ ] Railway drill environment deleted
- [ ] Drill database deleted or paused
- [ ] No drill credentials remain in password managers
- [ ] Drill environment removed from any CI/CD references

> ⏱️ **Checkpoint:** Teardown complete. Record time: `______`

---

## 📋 Drill Completion Checklist

| Step                 | Status | Time     | Sign-off     |
| -------------------- | ------ | -------- | ------------ |
| Spin Up              | ☐      | **\_\_** | **\_\_\_\_** |
| Restore              | ☐      | **\_\_** | **\_\_\_\_** |
| Sanitize             | ☐      | **\_\_** | **\_\_\_\_** |
| Certify (11 gates)   | ☐      | **\_\_** | **\_\_\_\_** |
| Verify (Golden Path) | ☐      | **\_\_** | **\_\_\_\_** |
| Teardown             | ☐      | **\_\_** | **\_\_\_\_** |
| **Total RTO**        | ☐      | **\_\_** | **\_\_\_\_** |

---

## 📊 Drill Report Template

After each drill, file a report:

```markdown
# Staging Drill Report — YYYY-MM-DD

## Summary

- **Date:** YYYY-MM-DD
- **Drill Lead:** [Name]
- **Witness:** [Name]
- **Result:** PASS / FAIL
- **Total RTO:** X hours Y minutes
- **RTO Target Met:** YES / NO

## Timeline

| Phase    | Target | Actual | Delta |
| -------- | ------ | ------ | ----- |
| Spin Up  | 0:00   | 0:XX   | +/-XX |
| Restore  | 1:00   | X:XX   | +/-XX |
| Sanitize | 1:15   | X:XX   | +/-XX |
| Certify  | 2:30   | X:XX   | +/-XX |
| Verify   | 3:00   | X:XX   | +/-XX |
| Teardown | 3:30   | X:XX   | +/-XX |

## Issues Encountered

1. [Issue description and resolution]
2. [Issue description and resolution]

## Recommendations

1. [Improvement for next drill]
2. [Process optimization]

## Sign-off

- Drill Lead: ********\_\_******** Date: ****\_\_****
- Witness: ********\_\_******** Date: ****\_\_****
- Engineering Manager: ********\_\_******** Date: ****\_\_****
```

---

## 🚨 Failure Scenarios

### If RTO Exceeds 4 Hours

1. **Continue the drill** — Do not abort
2. Document where time was lost
3. Complete all phases
4. File an incident report
5. Schedule remediation work before next quarter

### If Gates Fail

1. Document failing gate(s)
2. Attempt fix in drill environment
3. If unfixable, note as blocking issue
4. Report to Engineering Manager immediately
5. Create JIRA ticket for root cause analysis

### If Sanitization Fails

> ⚠️ **DATA BREACH RISK**

1. **STOP the drill immediately**
2. Disconnect drill environment from all networks
3. Delete the drill database
4. Notify Security team
5. Investigate sanitization script failure

---

## 🔐 Security Reminders

1. **Never** connect drill environment to production services
2. **Never** use production API keys in drill environment
3. **Always** run sanitization before any testing
4. **Always** destroy drill environment within 24 hours
5. **Never** export data from drill environment
6. Drill database credentials must be unique (not shared with prod)

---

## 📚 Related Documents

- [RUNBOOK_GO_LIVE.md](RUNBOOK_GO_LIVE.md) — Production deployment protocol
- [RUNBOOK_MOM.md](RUNBOOK_MOM.md) — Maintenance operations
- [RUNBOOK_DAD.md](RUNBOOK_DAD.md) — Data administration
- [CEO_PLAYBOOK.md](CEO_PLAYBOOK.md) — Business continuity overview

---

## 📝 Revision History

| Version | Date       | Author      | Changes                |
| ------- | ---------- | ----------- | ---------------------- |
| 1.0     | 2026-01-07 | Engineering | Initial drill protocol |

---

_This runbook is reviewed and updated quarterly after each drill._
