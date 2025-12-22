# Incident Report: Postgres URI Leak in GitHub

| Field               | Value                                  |
| ------------------- | -------------------------------------- |
| **Incident ID**     | 2025-12-22-01                          |
| **Date Opened**     | 2025-12-22                             |
| **Date Resolved**   | 2025-12-22                             |
| **Severity**        | SEV-1 (Critical - Credentials Exposed) |
| **Status**          | Resolved                               |
| **Owner**           | @mccabetrow                            |
| **Affected System** | Supabase DEV + PROD, Railway, GitHub   |

---

## Summary

Database connection strings containing credentials were accidentally committed to the GitHub repository in `.env`, `.env.dev`, and `.env.prod` files.

---

## Timeline

| Time (UTC)        | Event                                            |
| ----------------- | ------------------------------------------------ |
| 2025-12-22 ~08:00 | Credentials discovered in git history            |
| 2025-12-22 ~08:15 | Supabase database passwords rotated (DEV + PROD) |
| 2025-12-22 ~08:30 | Railway secrets updated                          |
| 2025-12-22 ~08:45 | .env files removed from git tracking             |
| 2025-12-22 ~09:00 | Secret scanner added to gate_preflight.ps1       |
| 2025-12-22 ~09:15 | Git history scrubbed via force push              |

---

## Root Cause Analysis

### What Happened

The `.env` files containing database URIs with embedded passwords were committed to the repository. Although `.gitignore` contained entries for these files, they were added before the gitignore rules were in place (or were force-added).

### Why It Happened

1. `.env` files were manually added with `git add .env` or `git add .`
2. No pre-commit hook to detect secrets before push
3. No CI/CD scanner to block commits containing credentials

### Contributing Factors

- Developer workflow did not include secret scanning
- No automated guardrail in the release gate

---

## Impact Assessment

| Category              | Impact                                                                    |
| --------------------- | ------------------------------------------------------------------------- |
| **Data Exposure**     | Database credentials visible in public/private repo                       |
| **Systems Affected**  | Supabase DEV (ejiddanxtqcleyswqvkc), Supabase PROD (iaketsyhmqbwaabgykux) |
| **User Impact**       | None (passwords rotated before any known abuse)                           |
| **Financial Impact**  | None                                                                      |
| **Reputation Impact** | Internal only                                                             |

---

## Resolution Steps

### Immediate Response (Containment)

1. ✅ Rotated Supabase database passwords (DEV + PROD)
2. ✅ Rotated Railway environment variables
3. ✅ Regenerated Supabase service role keys (if compromised)
4. ✅ Updated local `.env` files with new credentials

### Fix Implementation

1. ✅ Removed `.env` files from git tracking: `git rm --cached .env .env.dev .env.prod`
2. ✅ Strengthened `.gitignore` with comprehensive patterns:
   ```
   .env
   .env.*
   *.env
   instance/
   ```
3. ✅ Force-pushed to scrub git history

### Prevention (Guardrails)

1. ✅ Created `tools/scan_secrets.py` - Scans for leaked credentials
2. ✅ Added secret scanner to `gate_preflight.ps1` Phase 1 (Hard Gate)
3. ✅ Created `scripts/fix_git_tracking.ps1` for future cleanup

---

## Verification

```powershell
# Verify secrets are not tracked
git ls-files | Select-String "\.env"

# Run secret scanner
python -m tools.scan_secrets

# Run full preflight gate
.\scripts\gate_preflight.ps1
```

---

## Lessons Learned

| What Went Wrong                         | What We'll Do Differently                |
| --------------------------------------- | ---------------------------------------- |
| No automated secret detection           | Added `scan_secrets.py` to hard gate     |
| .env files committed despite .gitignore | Added `fix_git_tracking.ps1` for cleanup |
| No history scrubbing process            | Documented in this incident report       |

---

## Prevention Checklist

- [x] Credentials rotated
- [x] .env removed from git tracking
- [x] .gitignore strengthened
- [x] Secret scanner added to CI gate
- [x] Git history scrubbed
- [x] Incident documented

---

## Related Documents

- [RUNBOOK_INCIDENT.md](../RUNBOOK_INCIDENT.md)
- [gate_preflight.ps1](../../scripts/gate_preflight.ps1)
- [tools/scan_secrets.py](../../tools/scan_secrets.py)

---

## Sign-Off

| Role               | Name        | Date       |
| ------------------ | ----------- | ---------- |
| Incident Commander | @mccabetrow | 2025-12-22 |
| Reviewer           | —           | —          |
