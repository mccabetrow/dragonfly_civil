# Dragonfly Civil — Standard Operating Procedures Bundle

> **Version:** 1.0 | **Effective:** December 2025 | **Classification:** Internal Operations

---

## Document Index

This bundle consolidates all operational procedures for Dragonfly Civil.

| Document        | Location                        | Purpose                        |
| --------------- | ------------------------------- | ------------------------------ |
| Full SOP Bundle | `docs/operations/SOP_BUNDLE.md` | CEO, Ops, and Offer procedures |
| CEO Playbook    | `docs/CEO_PLAYBOOK.md`          | Executive quick reference      |
| Ops Manual      | `docs/OPS_MANUAL.md`            | Operations team reference      |
| Intake Gateway  | `docs/ops_intake_gateway.md`    | CSV ingestion procedures       |

---

## Quick Reference

### Daily Operations Checklist

#### Morning (CEO)

1. ☐ Open Radar Dashboard → `Enforcement → Radar`
2. ☐ Review KPI strip: Total Pipeline, Avg Score, Pending Offers
3. ☐ Apply "Buy Candidate" filter (Score ≥ 75, Tier A/B)
4. ☐ Review top 10 cases in Detail Drawer
5. ☐ Mark priority cases for same-day action

#### Morning (Ops)

1. ☐ Check Enrichment Health → `Ops → Enrichment Health`
2. ☐ Review overnight batch processing status
3. ☐ Address any failed rows in `data_error/`
4. ☐ Run Doctor check: `python -m tools.doctor_all --env prod`

#### Intake (When Vendor CSV Arrives)

1. ☐ Validate CSV structure (headers match schema)
2. ☐ Upload via `Operations → Intake Upload`
3. ☐ Record Batch ID
4. ☐ Monitor enrichment progress
5. ☐ Verify success rate ≥ 95%

---

## System Health Commands

```powershell
# Check system health
$env:SUPABASE_MODE = 'prod'
.\.venv\Scripts\python.exe -m tools.doctor --env prod

# Run security audit
.\.venv\Scripts\python.exe -m tools.security_audit --env prod

# Check migration status
.\.venv\Scripts\python.exe -m tools.migration_status --env prod

# View priority pipeline
.\.venv\Scripts\python.exe -m tools.priority_pipeline --limit 20
```

---

## Escalation Matrix

| Issue                      | First Response                       | Escalation            |
| -------------------------- | ------------------------------------ | --------------------- |
| Radar shows no data        | Refresh page, check SystemDiagnostic | Engineering via Slack |
| Batch stuck "Processing"   | Wait 5 min, check Enrichment Health  | Engineering via Slack |
| CORS errors on console     | Check Railway env vars               | Engineering via Slack |
| Database connection failed | Run Doctor check                     | On-call engineer      |
| Security audit failure     | Review RLS policies                  | Security team         |

---

## Environment Reference

### Production URLs

- **Backend API:** `https://dragonflycivil-production-d57a.up.railway.app`
- **Frontend Console:** `https://dragonfly-console1.vercel.app`
- **Supabase Dashboard:** (internal link)

### Critical Environment Variables

| Variable                 | Location | Purpose                  |
| ------------------------ | -------- | ------------------------ |
| `SUPABASE_MODE`          | Backend  | `dev` or `prod`          |
| `DRAGONFLY_API_KEY`      | Railway  | API authentication       |
| `DRAGONFLY_CORS_ORIGINS` | Railway  | Allowed frontend origins |
| `VITE_API_BASE_URL`      | Vercel   | Backend API URL          |
| `VITE_DRAGONFLY_API_KEY` | Vercel   | API key for frontend     |

---

## Deployment Procedures

### Standard Deploy (No Schema Changes)

1. Commit and push to `main`
2. Wait for Railway and Vercel auto-deploy
3. Verify: Check SystemDiagnostic badge on console

### Deploy with Migrations

1. Run preflight: `./scripts/preflight_prod.ps1`
2. Push migrations: `./scripts/db_push.ps1 -SupabaseEnv prod`
3. Commit and push to `main`
4. Verify: Run Doctor check on prod

### Emergency Rollback

1. Identify last known good commit
2. `git revert <bad-commit>`
3. Force push to trigger redeploy
4. Notify stakeholders

---

## Compliance Reminders

### FCRA Requirements

- All debtor data access is logged
- DELETE operations blocked on sensitive tables
- Audit trail maintained for 7 years

### FDCPA Requirements

- No calls before 8 AM or after 9 PM local time
- Maximum 7 calls per week per debtor
- Call outcomes logged immediately

### Data Retention

- Plaintiff contacts: Never deleted (soft delete only)
- Offer history: Retained indefinitely
- Activity logs: 7 year retention

---

## Contact Information

| Role                | Contact                |
| ------------------- | ---------------------- |
| Engineering Lead    | Slack `#dragonfly-ops` |
| Operations Manager  | (internal contact)     |
| Security/Compliance | (internal contact)     |

---

_This document summarizes procedures from across the documentation. For detailed procedures, refer to the individual documents listed in the Document Index._
