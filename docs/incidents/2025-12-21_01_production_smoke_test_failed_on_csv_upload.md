# Incident Report

<!-- Incident: Production Smoke Test Failed on CSV Upload -->

## Metadata

| Field       | Value                |
| ----------- | -------------------- |
| Incident ID | `2025-12-21-01`      |
| Severity    | `SEV-2`              |
| Status      | `Resolved`           |
| Created     | 2025-12-21 20:25 UTC |
| Resolved    | 2025-12-21 20:30 UTC |
| Owner       | @mccabetrow          |

---

## 1. Executive Summary

**What happened?**  
The Release Commander smoke test script failed when uploading a CSV file to the production Storage API, despite the API being fully operational.

**Who was impacted?**  
No end users were impacted; this was a false positive in our deployment verification tooling that blocked the release pipeline.

---

## 2. Timeline

<!-- All timestamps in UTC. Be specific. -->

| Time (UTC)           | Event                                                                          |
| -------------------- | ------------------------------------------------------------------------------ |
| 2025-12-21 14:00 UTC | **Detection**: Release Commander script reported failure on CSV upload         |
| 2025-12-21 14:05 UTC | Investigation started; verified API endpoint manually via curl (200 OK)        |
| 2025-12-21 14:10 UTC | Root cause identified: PowerShell 5.1 multipart form handling differs from PS7 |
| 2025-12-21 14:15 UTC | **Mitigation**: Manually verified API via Python `smoke_prod_storage.py`       |
| 2025-12-21 20:30 UTC | **Resolution**: Added PS version check to gate_preflight.ps1                   |

---

## 3. Root Cause Analysis (The 5 Whys)

<!--
  Ask "Why?" five times to drill down to the true root cause.
  Stop when you reach something actionable.
-->

1. **Why did the incident occur?**  
   → Smoke test reported CSV upload failure

2. **Why did that happen?**  
   → PowerShell script sent malformed multipart/form-data request

3. **Why did that happen?**  
   → PowerShell 5.1 `Invoke-RestMethod` handles `-Form` parameter differently than PowerShell 7

4. **Why did that happen?**  
   → Local development environment uses Windows PowerShell 5.1 (bundled with Windows)

5. **Why did that happen?**  
   → **ROOT CAUSE:** Tooling dependency mismatch — scripts assumed PS7 but ran on PS5.1

---

## 4. Corrective Actions

### Immediate Fix (What stopped the bleeding?)

- Manually verified API functionality using Python tool: `python -m tools.smoke_prod_storage`
- Confirmed production API was healthy; false positive in tooling

### Permanent Fix (The Rule)

- **Commit:** [`ea2ae60`](https://github.com/mccabetrow/dragonfly_civil/commit/ea2ae60)
- **Description:** Added PowerShell version check to `gate_preflight.ps1` that warns when running on PS5.1 and recommends PS7+

### The Invariant

<!--
  CRITICAL: An incident is NOT closed until this is filled.
  What test or monitor was added so this cannot happen silently again?
-->

- [x] **Test Added:** Version check in `scripts/gate_preflight.ps1` — Warns if `$PSVersionTable.PSVersion.Major -lt 7`
- [ ] **Monitor Added:** N/A (tooling fix, not runtime monitor)

---

## 5. Lessons Learned

- PowerShell version differences can cause subtle API failures
- Prefer Python for cross-platform API testing (more predictable behavior)
- Add explicit version checks to scripts that depend on modern PowerShell features

---

## 6. Sign-Off

| Role           | Name        | Date       |
| -------------- | ----------- | ---------- |
| Incident Owner | @mccabetrow | 2025-12-21 |
| Reviewer       | —           | —          |

<!--
  ✅ Checklist before closing:
  - [x] Timeline is complete
  - [x] Root cause identified
  - [x] Permanent fix PR merged
  - [x] Test OR Monitor added (The Invariant)
  - [ ] INCIDENT_LOG.md updated
-->
