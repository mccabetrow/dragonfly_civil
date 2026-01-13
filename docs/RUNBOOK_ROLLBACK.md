# Railway Rollback Runbook — Dragonfly Civil

> **Mission:** When production degrades, we roll back immediately. Fix-forward is forbidden while customers are burning.

---

## 1. Trigger Criteria

Initiate this runbook the moment any of the following persist for **more than 5 minutes**:

- **Critical alerts** are firing continuously (PagerDuty, OpsGenie, or Grafana red for >5 mins).
- **Go-Live Gate (prod)** is failing or blocked (production deploy gate red, prod_gate scripts failing).
- **Data corruption is detected** (replication lag, invalid balances, missing judgments, or ETL ingest drift confirmed).

If unsure, err on the side of rollback.

---

## 2. Identification — Choose the Safe Commit

1. **Open Railway Dashboard** → select the production service.
2. Click the **Deployments** tab.
3. **Current (bad) SHA:**
   - The deployment at the top marked _Current_ or _Active_.
   - Note the Git SHA and author; screenshot for the incident doc.
4. **Last known good SHA:**
   - Look for the most recent deployment with a **green check** (status = Successful) _before_ the bad one.
   - Confirm it served traffic successfully (duration >10 minutes, no alerts logged during that window).
   - Copy its Git SHA and link; this is the rollback target.

Document both SHAs in Slack immediately so the team is aligned.

---

## 3. Railway Rollback Procedure

1. **Open the Deployments tab** for the impacted Railway service (API, workers, scheduler, etc.).
2. Locate the **last known good commit** identified above.
3. Click the **ellipsis (⋯)** next to that deployment → choose **Redeploy**.
4. Confirm the prompt; Railway will rebuild and redeploy that historical image.
5. **Monitor Build Logs**:
   - Ensure `Build succeeded` is displayed.
   - Confirm `Deploy succeeded` and instance restarts without errors.
6. Repeat for every affected Railway service (API, workers, scheduler) so all components run the same good SHA.

If any redeploy fails, halt and escalate to SRE + Engineering leadership.

---

## 4. Verification After Rollback

1. **Run production gate checks immediately:**
   ```powershell
   # Requires prod env vars via scripts/load_env.ps1
   .\scripts\prod_gate.ps1
   ```
   - The script must exit 0.
   - If it fails, capture logs and escalate.
2. **Observe live metrics:**
   - Hit `/api/metrics` (auth required) and verify error counters stop growing.
   - Confirm queue depths and worker heartbeats look normal.
3. **Confirm alert recovery:**
   - Alerts should auto-resolve. If they continue, keep incident open and investigate.
4. **Communicate:**
   - Post status in `#ops` Slack channel with: bad SHA, good SHA, rollback time, current health.

---

## 5. Incident Report Template

Create `docs/incidents/YYYYMMDD-<slug>.md` using the template below and file an incident within 24 hours.

```markdown
# Post-Mortem: <Service> - <Date>

## Incident Summary

- **Start:** <timestamp UTC>
- **Detection:** <how it was discovered>
- **Impact:** <users, data, duration>
- **Resolution:** <rollback SHA, time>

## Root Cause

- Fact-based description of the fault, not guesses.

## Timeline

| Time (UTC) | Event                 |
| ---------- | --------------------- |
| HH:MM      | alert fired           |
| HH:MM      | rollback started      |
| HH:MM      | rollback completed    |
| HH:MM      | verification finished |

## Action Items

- [ ] **Prevent:** <test, gate, or process change>
- [ ] **Detect:** <monitoring/logging improvement>
- [ ] **Mitigate:** <documentation, automation, or training>
- Owner + due date for each item.
```

Keep the incident open until action items are assigned and scheduled.
