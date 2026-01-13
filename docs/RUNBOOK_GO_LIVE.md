# Dragonfly Civil - Go-Live Runbook

**Version:** 2.0  
**Last Updated:** 2026-01-07  
**Author:** Dragonfly SRE Team

> **Purpose:** Single source of truth for production deployment.  
> **Audience:** Release manager, on-call engineer.  
> **Usage:** Open this on your second monitor during deployment.

---

## Table of Contents

1. [Deployment Sequence (The Golden Path)](#deployment-sequence-the-golden-path)
   - [Phase 0: Freeze](#phase-0-freeze-)
   - [Phase 1: Certification (The Gate)](#phase-1-certification-the-gate-)
   - [Phase 2: Technical Golden Path](#phase-2-technical-golden-path-)
   - [Phase 3: Business Proof of Life](#phase-3-business-proof-of-life-)
   - [Phase 4: Ingest (The Button)](#phase-4-ingest-the-button-)
2. [Post-Go-Live Verification](#post-go-live-verification)
3. [Go-Live Announcement Template](#go-live-announcement-template)
4. [Green Light Requirements](#green-light-requirements)
5. [Failure Modes & CLI Fixes](#failure-modes--cli-fixes)
6. [Monitoring & Alerts](#monitoring--alerts)
7. [Rollback Procedures](#rollback-procedures)

---

## Deployment Sequence (The Golden Path)

### Pre-Flight Checklist

| Item             | Command / Action            | Expected               |
| ---------------- | --------------------------- | ---------------------- |
| Git status clean | `git status`                | No uncommitted changes |
| On `main` branch | `git branch --show-current` | `main`                 |
| Latest pull      | `git pull origin main`      | Already up to date     |
| CI passing       | Check GitHub Actions        | ✅ Green               |
| `.env` loaded    | `./scripts/load_env.ps1`    | No errors              |

---

### Phase 0: Freeze 🧊

**Goal:** Ensure the codebase is stable and ready for production.

#### 0.1 Verify Clean State

```powershell
git status
git log --oneline -5
```

- [ ] Working tree clean
- [ ] Latest commit matches expected release

#### 0.2 Verify CI Gate

```powershell
# Check that go_live_gate runs in CI
gh run list --workflow=ci.yml --limit=3
```

- [ ] Most recent CI run is green
- [ ] `go_live_gate` job passed

#### 0.3 Set Environment

```powershell
$env:SUPABASE_MODE = 'prod'
./scripts/load_env.ps1
```

- [ ] Environment variables loaded
- [ ] No credential warnings

---

### Phase 1: Certification (The Gate) 🚪

**Goal:** All 11 production gates must pass before proceeding.

#### 1.1 Run Production Gate

```powershell
python -m tools.go_live_gate --env prod
```

**Expected Output:**

```
✅ Gate 1: Environment Configuration
✅ Gate 2: Database Connectivity
✅ Gate 3: Schema Consistency
✅ Gate 4: RLS Enforcement
✅ Gate 5: Critical Views
✅ Gate 6: Worker Health
✅ Gate 7: API Endpoints
✅ Gate 8: Audit Trail
✅ Gate 9: Security Hardening
✅ Gate 10: Backup Verification
✅ Gate 11: Rate Limiting

🎉 ALL 11 GATES PASSED - READY FOR GO-LIVE
```

- [ ] All 11 gates passed
- [ ] No warnings or degraded states

#### 1.2 Verify Worker Health

```powershell
python -m tools.monitor_workers --env prod
```

- [ ] All workers reporting healthy
- [ ] No stale heartbeats (> 5 min)
- [ ] Memory/CPU within limits

#### 1.3 Inspect Job Queue

```powershell
python -m tools.queue_inspect --env prod
```

- [ ] No stuck jobs
- [ ] Queue depth acceptable (< 100 pending)
- [ ] No poison messages

---

### Phase 2: Technical Golden Path 🛤️

**Goal:** Proves DB, API, and Views are functional end-to-end.

#### 2.1 Run Golden Path

```powershell
python -m tools.golden_path --env prod --cleanup
```

**Expected Output:**

```
============================================================
GOLDEN PATH TEST SUITE
Environment: PROD
============================================================
✅ Database connection established
✅ Schema version verified
✅ Critical views accessible
✅ API health endpoint responding
✅ Test entity lifecycle (create → read → delete)
✅ Cleanup complete

🎉 GOLDEN PATH: ALL CHECKS PASSED
============================================================
```

- [ ] All checks passed
- [ ] Cleanup confirmed (no orphaned test data)

#### 2.2 Verify Critical Views

```powershell
python -m tools.smoke_plaintiffs --env prod
```

- [ ] `v_plaintiffs_overview` returns rows
- [ ] `v_judgment_pipeline` accessible
- [ ] `v_enforcement_overview` accessible

---

### Phase 3: Business Proof of Life 📋

**Goal:** Proves business invariants hold – we won't sue without authorization.

#### 3.1 Run Business Logic Verification

```powershell
python -m tools.verify_business_logic --env prod
```

> ⚠️ **This will prompt for confirmation before running against prod.**

**Expected Output:**

```
============================================================
BUSINESS LOGIC VERIFICATION
Environment: PROD
============================================================
✅ PASS  The Block: Enforcement blocked and remediation task created
✅ PASS  The Cure: Both fee_agreement and loa registered
✅ PASS  The Success: Enforcement authorized and executed

🎉 ALL BUSINESS INVARIANTS VERIFIED
   The system correctly:
   • BLOCKS enforcement without signed consent
   • ALLOWS enforcement with valid LOA + Fee Agreement
============================================================
```

- [ ] "The Block" test passed (unauthorized = blocked)
- [ ] "The Cure" test passed (consent registration works)
- [ ] "The Success" test passed (authorized = allowed)

#### 3.2 Verify Audit Trail

```powershell
python -m tools.verify_court_proof --env prod
```

- [ ] Audit log immutability confirmed
- [ ] Evidence vault lockdown verified

---

### Phase 4: Ingest (The Button) 🚀

**Goal:** Begin processing real data.

#### 4.1 Pre-Ingest Verification

```powershell
# Check ingest queue is empty
python -m tools.queue_inspect --env prod --queue ingest
```

- [ ] No pending ingest jobs
- [ ] Workers ready to receive

#### 4.2 Trigger Ingest

**Option A: Automated Trigger**

```powershell
python -m backend.workers.ingest_trigger
```

**Option B: Manual CSV Drop**

```powershell
# Copy validated CSV to ingest folder
Copy-Item "data_in/validated_batch.csv" -Destination "data_in/live/"
```

#### 4.3 Monitor Ingest Progress

```powershell
# Watch ingest in real-time
python -m tools.monitor_ingest --env prod --follow
```

- [ ] Rows processing without errors
- [ ] No validation failures
- [ ] Completion confirmation received

---

## Post-Go-Live Verification

### Immediate Checks (T+5 min)

```powershell
# Verify data landed
python -m tools.doctor_all --env prod

# Check dashboard views
python -m tools.smoke_plaintiffs --env prod
```

- [ ] Doctor reports healthy
- [ ] Dashboard views populated

### Monitoring Checks (T+30 min)

```powershell
# Worker health
python -m tools.monitor_workers --env prod

# Queue depth
python -m tools.queue_inspect --env prod
```

- [ ] Workers stable
- [ ] No queue backlog

---

## Deployment Sign-Off

| Phase                   | Passed | Initials | Timestamp |
| ----------------------- | ------ | -------- | --------- |
| Phase 0: Freeze         | ☐      | \_\_\_   | \_\_\_    |
| Phase 1: Certification  | ☐      | \_\_\_   | \_\_\_    |
| Phase 2: Golden Path    | ☐      | \_\_\_   | \_\_\_    |
| Phase 3: Business Proof | ☐      | \_\_\_   | \_\_\_    |
| Phase 4: Ingest         | ☐      | \_\_\_   | \_\_\_    |
| Post-Go-Live            | ☐      | \_\_\_   | \_\_\_    |

---

## Go-Live Announcement Template

Use `tools/generate_announcement.py` to auto-generate this with real metrics:

```bash
python -m tools.generate_announcement --env prod
```

### Manual Template

```
╔══════════════════════════════════════════════════════════════════════════════╗
║                                                                              ║
║                    🚀 DRAGONFLY CIVIL - GO-LIVE ANNOUNCEMENT 🚀              ║
║                                                                              ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                              ║
║  Environment:  PRODUCTION                                                    ║
║  Timestamp:    YYYY-MM-DD HH:MM UTC                                          ║
║                                                                              ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  SYSTEM HEALTH                                                               ║
║                                                                              ║
║  Doctor Checks:     ✅ ALL PASSED (9/9 checks)                               ║
║  PostgREST Cache:   ✅ Reloaded                                              ║
║                                                                              ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  BATCH PIPELINE METRICS (Last 24 Hours)                                      ║
║                                                                              ║
║  Total Batches:     [X]                                                      ║
║  Completed:         [X]                                                      ║
║  Failed:            [X]                                                      ║
║  Success Rate:      [X]%                                                     ║
║                                                                              ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  NEXT STEPS                                                                  ║
║                                                                              ║
║  1. Monitor Sentinel:  python -m backend.workers.sentinel --json             ║
║  2. Check Dashboard:   https://dragonfly-dashboard.vercel.app                ║
║  3. Review Logs:       Supabase Dashboard → Logs → API                       ║
║                                                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝
```

---

## Green Light Requirements

Before declaring Go-Live, the system must pass **The 3 Proofs**:

### Automated Verification

```bash
python -m tools.verify_green_light --env prod
```

### The 3 Proofs

| Proof                  | Test                 | Success Criteria                                      |
| ---------------------- | -------------------- | ----------------------------------------------------- |
| **1. Happy Path**      | Upload valid CSV     | `status=completed`, `row_count_inserted > 0`          |
| **2. Idempotency**     | Re-upload same file  | `status=skipped` OR same `batch_id`                   |
| **3. Quality Control** | Upload malformed CSV | `status=failed`, `rejection_reason` contains "budget" |

### Expected Output

```
═══════════════════════════════════════════════════════════════════════════════
  🚦 GREEN LIGHT VERIFICATION - The 3 Proofs
═══════════════════════════════════════════════════════════════════════════════

  ┌─────────────────────────────────────────────────────────────────┐
  │  Proof                              │  Result  │  Duration      │
  ├─────────────────────────────────────────────────────────────────┤
  │  Proof 1: Happy Path (Valid Data)   │   ✅     │    0.25s       │
  │  Proof 2: Idempotency               │   ✅     │    0.12s       │
  │  Proof 3: Quality Control           │   ✅     │    0.18s       │
  └─────────────────────────────────────────────────────────────────┘

  ╔═════════════════════════════════════════════════════════════════╗
  ║    🟢  GREEN LIGHT - ALL 3 PROOFS PASSED                       ║
  ║    The intake pipeline is PRODUCTION READY.                    ║
  ╚═════════════════════════════════════════════════════════════════╝
```

---

## Failure Modes & CLI Fixes

### Quick Reference Table

| Scenario | Symptom                            | CLI Fix                                                       |
| -------- | ---------------------------------- | ------------------------------------------------------------- |
| **A**    | Backend Disconnected / Pooler Down | `python -m tools.fix_pooler_connection --env prod`            |
| **B**    | 500 Error on Dashboard / PGRST002  | `python -m tools.fix_schema_cache --env prod`                 |
| **C**    | Ingest Stuck on "Processing"       | `python -m tools.fix_stuck_batch --env prod`                  |
| **D**    | Batch Failed / Red Status          | `python -m tools.analyze_errors --env prod --batch-id [UUID]` |

---

### Scenario A: Backend Disconnected (Pooler Down)

**Symptoms:**

- Railway/backend shows "Connection refused" or timeout
- Dashboard shows "Unable to connect to database"
- Port 6543 (pooler) unresponsive

**Diagnosis:**

```bash
python -m tools.fix_pooler_connection --env prod
```

**Expected Output:**

```
══════════════════════════════════════════════════════════════════════════════
  CIRCUIT BREAKER BYPASS - Connection Diagnostics
══════════════════════════════════════════════════════════════════════════════

  Environment: PROD

──────────────────────────────────────────────────────────────────────────────
  Testing Connection Ports
──────────────────────────────────────────────────────────────────────────────
  Port 6543 (Transaction Pooler): ❌ FAILED - Connection refused
  Port 5432 (Direct Connection):  ✅ HEALTHY

──────────────────────────────────────────────────────────────────────────────
  ⚠️  POOLER IS DOWN - Use Direct Connection Bypass
──────────────────────────────────────────────────────────────────────────────

  Copy this DSN to Railway environment variables:
  postgresql://postgres:****@db.xxx.supabase.co:5432/postgres
```

**Action:**

1. Copy the bypass DSN from the output
2. Paste into Railway → Environment Variables → `DATABASE_URL`
3. Redeploy Railway service
4. Open Supabase support ticket for pooler restoration

---

### Scenario B: 500 Error on Dashboard (Schema Cache Stale)

**Symptoms:**

- Dashboard returns 500 errors
- API returns `PGRST002` error code
- Message: "Could not query the database for the schema cache"

**Diagnosis & Fix:**

```bash
python -m tools.fix_schema_cache --env prod
```

**Expected Output:**

```
══════════════════════════════════════════════════════════════════════════════
  SCHEMA HEALER - PGRST002 Resolution Tool
══════════════════════════════════════════════════════════════════════════════

  Environment: PROD

──────────────────────────────────────────────────────────────────────────────
  Pre-Check: Testing API Health
──────────────────────────────────────────────────────────────────────────────
  API Status: ⚠️  PGRST002 detected

──────────────────────────────────────────────────────────────────────────────
  Healing: Sending NOTIFY pgrst
──────────────────────────────────────────────────────────────────────────────
  ✅ NOTIFY pgrst sent successfully

──────────────────────────────────────────────────────────────────────────────
  Verification: Testing API Health (with retry)
──────────────────────────────────────────────────────────────────────────────
  Attempt 1/5: ⚠️  Still stale, waiting 3s...
  Attempt 2/5: ✅ API responding normally

  ✅ PGRST002 RESOLVED - Schema cache reloaded successfully
```

**If NOTIFY Doesn't Work:**

1. Go to Supabase Dashboard → Project Settings → Database
2. Click "Restart Database"
3. Wait 30-60 seconds
4. Re-run the fix tool to verify

---

### Scenario C: Ingest Stuck on "Processing"

**Symptoms:**

- Batch shows `status=processing` for > 30 minutes
- No progress in row counts
- Watcher may have crashed

**Diagnosis:**

```bash
python -m tools.fix_stuck_batch --env prod
```

**Expected Output (Stuck Batches Found):**

```
══════════════════════════════════════════════════════════════════════════════
  BATCH UNSTICKER - Stuck Batch Resolution Tool
══════════════════════════════════════════════════════════════════════════════

  Environment: PROD
  Action: RETRY
  Threshold: 30 minutes

──────────────────────────────────────────────────────────────────────────────
  Auto-Detecting Stuck Batches
──────────────────────────────────────────────────────────────────────────────

  Found 2 stuck batch(es):

  ┌────────────────────────────────────────────────────────────────────────┐
  │  Batch ID                             │  Filename    │  Stuck Duration │
  ├────────────────────────────────────────────────────────────────────────┤
  │  abc123...                            │  batch1.csv  │  45 minutes     │
  │  def456...                            │  batch2.csv  │  62 minutes     │
  └────────────────────────────────────────────────────────────────────────┘

  ⚡ Resetting batches to 'uploaded' for retry...
  ✅ Reset 2 batch(es) - Watcher will pick them up
```

**Options:**

```bash
# Auto-detect and retry stuck batches
python -m tools.fix_stuck_batch --env prod

# Auto-detect and abort stuck batches (mark as failed)
python -m tools.fix_stuck_batch --env prod --action abort

# Fix a specific batch
python -m tools.fix_stuck_batch --env prod --batch-id abc123-def456 --action retry
```

---

### Scenario D: Batch Failed / High Error Rate

**Symptoms:**

- Batch shows `status=failed`
- Red status indicator on dashboard
- `rejection_reason` populated

**Diagnosis:**

```bash
# Analyze a specific failed batch
python -m tools.analyze_errors --env prod --batch-id [UUID]

# Show recent failed batches
python -m tools.analyze_errors --env prod --recent 5

# Aggregated error summary
python -m tools.analyze_errors --env prod --summary
```

**Expected Output:**

```
══════════════════════════════════════════════════════════════════════════════
  ERROR ANALYZER - Batch Processing Diagnostics
══════════════════════════════════════════════════════════════════════════════

  Environment: PROD
  Batch ID: abc123-def456-...

──────────────────────────────────────────────────────────────────────────────
  Batch Details
──────────────────────────────────────────────────────────────────────────────
  Filename:        import_2025_01_05.csv
  Status:          failed
  Rejection:       Error budget exceeded: 15.3% invalid rows (threshold: 10%)

  Row Counts:
    Total:         1000
    Valid:         847
    Invalid:       153
    Inserted:      0

──────────────────────────────────────────────────────────────────────────────
  Recommendations
──────────────────────────────────────────────────────────────────────────────
  1. Review the source CSV for data quality issues
  2. Check data_error/ folder for failed row details
  3. Consider increasing error_threshold_percent if data is acceptable
  4. Contact data provider if errors are systemic
```

**Common Error Patterns:**

| Rejection Reason          | Cause                  | Action                                  |
| ------------------------- | ---------------------- | --------------------------------------- |
| `Error budget exceeded`   | >10% invalid rows      | Review CSV quality, contact data source |
| `Duplicate file_hash`     | File already processed | Expected behavior, no action needed     |
| `Missing required fields` | CSV format issue       | Check column mapping                    |
| `Parse error`             | Malformed CSV          | Validate CSV structure                  |

---

## Monitoring & Alerts

### Sentinel Worker

Continuous monitoring of pipeline health:

```bash
# Run sentinel with JSON output (for logging)
python -m backend.workers.sentinel --json

# Run once for spot check
python -m backend.workers.sentinel --once
```

### Key Metrics to Watch

| Metric              | Healthy Range | Alert Threshold |
| ------------------- | ------------- | --------------- |
| Batch Success Rate  | > 95%         | < 90%           |
| Avg Processing Time | < 500ms       | > 2000ms        |
| Error Rate          | < 5%          | > 10%           |
| Stuck Batches       | 0             | > 0 for > 30min |

### Dashboard URLs

- **Production Dashboard:** https://dragonfly-dashboard.vercel.app
- **Supabase Dashboard:** https://supabase.com/dashboard/project/iaketsyhmqbwaabgykux

---

## Rollback Procedures

### If Go-Live Fails

1. **Stop Ingest Traffic:**

   ```bash
   # Disable the watcher if running
   # Contact upstream data sources to pause file drops
   ```

2. **Assess Damage:**

   ```bash
   python -m tools.doctor --env prod
   python -m tools.analyze_errors --env prod --summary
   ```

3. **Rollback Migration (if needed):**

   ```sql
   -- In Supabase SQL Editor, run the down migration
   -- Example: DROP TABLE IF EXISTS intake.new_table;
   ```

4. **Restore from Backup:**
   - Supabase Dashboard → Database → Backups
   - Point-in-Time Recovery available

### Emergency Contacts

| Role             | Contact             |
| ---------------- | ------------------- |
| SRE On-Call      | [Contact Info]      |
| Database Admin   | [Contact Info]      |
| Supabase Support | support@supabase.io |

---

## Appendix: Full CLI Reference

### Verification Tools

```bash
# Green Light verification (3 Proofs)
python -m tools.verify_green_light --env prod

# Doctor checks
python -m tools.doctor --env prod

# Smoke tests
python -m tools.smoke_simplicity --env prod
python -m tools.smoke_plaintiffs --env prod
```

### SRE Ops Tools

```bash
# Connection diagnostics
python -m tools.fix_pooler_connection --env prod

# Schema cache healer
python -m tools.fix_schema_cache --env prod

# Stuck batch unsticker
python -m tools.fix_stuck_batch --env prod

# Error analyzer
python -m tools.analyze_errors --env prod --summary
```

### Announcement Generator

```bash
# Generate Go-Live announcement with real metrics
python -m tools.generate_announcement --env prod

# Save to file
python -m tools.generate_announcement --env prod --output announcement.md
```

---

**Document Version History:**

| Version | Date       | Author   | Changes                                               |
| ------- | ---------- | -------- | ----------------------------------------------------- |
| 2.0     | 2026-01-07 | SRE Team | Added 4-phase deployment sequence, sign-off checklist |
| 1.0     | 2025-01-05 | SRE Team | Initial release                                       |
