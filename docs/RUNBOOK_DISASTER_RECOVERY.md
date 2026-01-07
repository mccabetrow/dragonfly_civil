# Dragonfly Civil – Disaster Recovery Runbook

> **Classification:** INTERNAL – Operations Team  
> **Last Updated:** 2026-01-06  
> **Owner:** Platform Engineering

---

## 🎯 Recovery Targets

| Metric                             | Target       | Notes                                               |
| ---------------------------------- | ------------ | --------------------------------------------------- |
| **RPO** (Recovery Point Objective) | **24 Hours** | Point-in-Time Recovery enabled via Supabase         |
| **RTO** (Recovery Time Objective)  | **4 Hours**  | From incident detection to full service restoration |

---

## 🚨 The "Oh Sh\*t" Procedure

When the database is gone, corrupted, or compromised, execute these steps **in order**.

### Step 1: Stop the Bleeding

**Goal:** Prevent dirty writes from workers hitting a broken or restoring database.

```bash
# Railway CLI
railway service scale workers --replicas 0

# Or via Railway Dashboard:
# Project → Workers Service → Settings → Instances → 0
```

**Verification:** Confirm no active connections in Supabase Dashboard → Database → Connections.

---

### Step 2: Restore from Backup

**Goal:** Recover database to a known-good state.

1. Open **Supabase Dashboard** → Your Project
2. Navigate to **Database** → **Backups**
3. Click **Restore**
4. Select **Point in Time** and choose a timestamp **before** the incident
5. Confirm and wait for restoration (typically 10-30 minutes)

⚠️ **CRITICAL:** Note the exact restoration timestamp for audit purposes.

---

### Step 3: Verify Integrity

**Goal:** Confirm the restored database passes all go-live checks.

```bash
# Set environment
$env:SUPABASE_MODE = "prod"

# Run the full gate
python -m tools.go_live_gate --env prod --skip-discord
```

**Expected Output:** All 11 gates GREEN ✅

If any gate fails:

- **Migration Integrity** → Run `./scripts/db_push.ps1 -SupabaseEnv prod`
- **Subsystem Smoke Tests** → Check views exist, may need PostgREST reload
- **Worker Health** → Expected to show stale (workers are scaled down)

---

### Step 4: Re-Connect (Credential Rotation)

**Goal:** Rotate credentials as a precautionary measure.

1. **Supabase Dashboard** → Settings → API
2. Generate new **Service Role Key**
3. Update Railway environment variables:

```bash
# Railway CLI
railway variables set SUPABASE_SERVICE_KEY="new-key-here"
railway variables set SUPABASE_URL="https://your-project.supabase.co"
```

4. Verify `.env.prod` locally matches (for tooling)

---

### Step 5: Resume Operations

**Goal:** Bring the system back online.

```bash
# Scale workers back up
railway service scale workers --replicas 1

# Or via Railway Dashboard:
# Project → Workers Service → Settings → Instances → 1
```

**Post-Resume Verification:**

```bash
# Check worker heartbeats (wait 2 minutes)
python -m tools.monitor_workers --env prod
```

---

## 📋 Incident Checklist

Use this during an actual incident:

- [ ] Incident detected at: `__:__ UTC`
- [ ] Workers scaled to 0 at: `__:__ UTC`
- [ ] Restoration initiated at: `__:__ UTC`
- [ ] Restoration completed at: `__:__ UTC`
- [ ] Go-live gate passed at: `__:__ UTC`
- [ ] Credentials rotated: Yes / No
- [ ] Workers resumed at: `__:__ UTC`
- [ ] Full service confirmed at: `__:__ UTC`
- [ ] Post-incident review scheduled: Yes / No

---

## 🧪 Drill Schedule

| Frequency     | Environment              | Scope                            |
| ------------- | ------------------------ | -------------------------------- |
| **Quarterly** | `dragonfly-staging`      | Full restore + go-live gate      |
| **Annually**  | `dragonfly-prod` (clone) | Full restore to isolated project |

### Drill Procedure

1. Clone production to `dragonfly-dr-test` project
2. Execute Steps 2-5 against the clone
3. Document any issues
4. Update this runbook if gaps found

**Next Scheduled Drill:** Q2 2026

---

## 📞 Escalation Contacts

| Role             | Contact              | When to Escalate      |
| ---------------- | -------------------- | --------------------- |
| On-Call Engineer | _Check PagerDuty_    | First responder       |
| Platform Lead    | _Internal Directory_ | RTO at risk (>2hr)    |
| CTO              | _Internal Directory_ | Data loss confirmed   |
| Supabase Support | support@supabase.io  | Platform-level issues |

---

## 📝 Post-Incident Review Template

After every DR event (real or drill), document:

1. **Timeline:** Minute-by-minute actions
2. **Root Cause:** What triggered the incident?
3. **Data Impact:** Any data loss within RPO?
4. **RTO Achieved:** Actual downtime vs target
5. **Lessons Learned:** Process improvements
6. **Action Items:** Assigned with owners and dates

---

## 🔗 Related Documents

- [RUNBOOK_MOM.md](RUNBOOK_MOM.md) – Migration Operations Manual
- [RUNBOOK_DAD.md](RUNBOOK_DAD.md) – Deployment & Admin Guide
- [WORKER_DEPLOYMENT.md](WORKER_DEPLOYMENT.md) – Worker fleet operations
- [CEO_PLAYBOOK.md](CEO_PLAYBOOK.md) – Business continuity context

---

_Remember: The goal isn't to never have incidents—it's to recover faster than anyone notices._
