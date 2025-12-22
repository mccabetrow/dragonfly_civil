# Incident Report

<!--
  TEMPLATE: Copy this file to docs/incidents/YYYY-MM-DD_ID_title.md
  Or use: python -m tools.new_incident "Brief Title"
-->

## Metadata

| Field       | Value                       |
| ----------- | --------------------------- |
| Incident ID | `YYYY-MM-DD-01`             |
| Severity    | `SEV-1` / `SEV-2` / `SEV-3` |
| Status      | `Open` / `Resolved`         |
| Created     | YYYY-MM-DD HH:MM UTC        |
| Resolved    | YYYY-MM-DD HH:MM UTC        |
| Owner       | @github_handle              |

---

## 1. Executive Summary

**What happened?**

<!-- One sentence: "The intake queue stopped processing jobs due to X." -->

**Who was impacted?**

<!-- One sentence: "All new plaintiff imports were delayed by 2 hours." -->

---

## 2. Timeline

<!-- All timestamps in UTC. Be specific. -->

| Time (UTC)       | Event                                      |
| ---------------- | ------------------------------------------ |
| YYYY-MM-DD HH:MM | **Detection**: Alert fired / User reported |
| YYYY-MM-DD HH:MM | Investigation started                      |
| YYYY-MM-DD HH:MM | Root cause identified                      |
| YYYY-MM-DD HH:MM | **Mitigation**: Immediate fix deployed     |
| YYYY-MM-DD HH:MM | **Resolution**: Permanent fix merged       |

---

## 3. Root Cause Analysis (The 5 Whys)

<!--
  Ask "Why?" five times to drill down to the true root cause.
  Stop when you reach something actionable.
-->

1. **Why did the incident occur?**  
   →

2. **Why did that happen?**  
   →

3. **Why did that happen?**  
   →

4. **Why did that happen?**  
   →

5. **Why did that happen?**  
   → **ROOT CAUSE:**

---

## 4. Corrective Actions

### Immediate Fix (What stopped the bleeding?)

<!-- What did you do in the moment to restore service? -->

-

### Permanent Fix (The Rule)

<!-- Link to the PR that fixes the underlying issue -->

- **PR:** [#XXX](https://github.com/mccabetrow/dragonfly_civil/pull/XXX)
- **Description:**

### The Invariant

<!--
  CRITICAL: An incident is NOT closed until this is filled.
  What test or monitor was added so this cannot happen silently again?
-->

- [ ] **Test Added:** `tests/test_XXX.py::test_XXX` — Prevents recurrence
- [ ] **Monitor Added:** `ops.view_XXX` / Alert in `monitor.py` — Detects faster

---

## 5. Lessons Learned

<!-- Optional but valuable. What would you do differently? -->

-

---

## 6. Sign-Off

| Role           | Name | Date |
| -------------- | ---- | ---- |
| Incident Owner |      |      |
| Reviewer       |      |      |

<!--
  ✅ Checklist before closing:
  - [ ] Timeline is complete
  - [ ] Root cause identified
  - [ ] Permanent fix PR merged
  - [ ] Test OR Monitor added (The Invariant)
  - [ ] INCIDENT_LOG.md updated
-->
