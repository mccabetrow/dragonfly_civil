# Dragonfly Civil — Incident Response Runbook

> **Mission:** Respond fast, fix permanently, get stronger.

---

## Severity Definitions

### SEV-1 — Critical 🔴

**Definition:** Data loss, security breach, or system completely down.

| Aspect            | Requirement                                                    |
| ----------------- | -------------------------------------------------------------- |
| Response Time     | **Immediate** — Stop everything                                |
| Resolution Target | ASAP (hours, not days)                                         |
| Communication     | Notify stakeholders immediately                                |
| Examples          | Database corruption, auth bypass, all workers dead, money lost |

**Actions:**

1. Drop everything. This is the only priority.
2. Start incident report: `python -m tools.new_incident "SEV-1: Title"`
3. Log timestamps as you work (you'll forget later).
4. Fix first, document after.

---

### SEV-2 — Major 🟠

**Definition:** Feature broken or performance significantly degraded.

| Aspect            | Requirement                                                   |
| ----------------- | ------------------------------------------------------------- |
| Response Time     | Within 1 hour                                                 |
| Resolution Target | Within 24 hours                                               |
| Communication     | Update team in daily standup                                  |
| Examples          | Intake queue stuck, dashboard not loading, worker OOM crashes |

**Actions:**

1. Create incident report immediately.
2. Investigate root cause.
3. Deploy fix within 24h.
4. Add test/monitor before closing.

---

### SEV-3 — Minor 🟡

**Definition:** Annoyance, glitch, or cosmetic issue.

| Aspect            | Requirement                                         |
| ----------------- | --------------------------------------------------- |
| Response Time     | Within 24 hours                                     |
| Resolution Target | Next sprint                                         |
| Communication     | Log in issue tracker                                |
| Examples          | UI typo, slow query (not critical), edge case error |

**Actions:**

1. Create incident report (optional for true minor issues).
2. File GitHub issue with `sev-3` label.
3. Fix in next sprint.

---

## The Response Protocol

### Phase 1: Detection & Triage (0-5 min)

```
1. [ ] Assign severity (SEV-1/2/3)
2. [ ] Create incident report: python -m tools.new_incident "Title"
3. [ ] Start logging timeline in the report
4. [ ] If SEV-1: Notify stakeholders
```

### Phase 2: Investigation (5-30 min)

```
1. [ ] Check monitor.py logs / Railway dashboard
2. [ ] Check Supabase logs (Dashboard → Logs)
3. [ ] Run doctor: python -m tools.doctor --env prod
4. [ ] Check SLO dashboard for anomalies
5. [ ] Identify root cause (use 5 Whys technique)
```

### Phase 3: Mitigation (Stop the Bleeding)

```
1. [ ] Apply immediate fix (restart, rollback, hotfix)
2. [ ] Verify service restored
3. [ ] Document what you did in the incident report
```

### Phase 4: Permanent Fix

```
1. [ ] Write proper fix with tests
2. [ ] Create PR, get review
3. [ ] Merge and deploy
4. [ ] Update incident report with PR link
```

### Phase 5: Closure (The Invariant)

```
1. [ ] Add test that prevents recurrence
   OR
   [ ] Add monitor that detects faster
2. [ ] Update docs/INCIDENT_LOG.md
3. [ ] Mark incident as Resolved
4. [ ] Conduct brief post-mortem (SEV-1/2 only)
```

---

## The Golden Rule

> **An incident is not closed until a Test (prevent recurrence) or Monitor (detect faster) is merged.**

This is non-negotiable. Every incident must leave the system stronger.

---

## Quick Reference: Common Issues

| Symptom       | Likely Cause   | Quick Check                           |
| ------------- | -------------- | ------------------------------------- |
| Queue stuck   | Worker dead    | Railway dashboard → check worker logs |
| DLQ growing   | Bad input data | Check `ops.intake_dead_letter_queue`  |
| Slow queries  | Missing index  | `EXPLAIN ANALYZE` on slow query       |
| Auth failures | Token expired  | Check Supabase service_role key       |
| OOM crash     | Memory leak    | Check Railway memory graph            |

---

## Useful Commands

```bash
# Check system health
python -m tools.doctor --env prod

# Check SLO status
python -m backend.workers.monitor --once --slo

# View recent errors
python -m tools.ops_summary --env prod

# Reload PostgREST schema cache
python -m tools.pgrst_reload --env prod
```

---

## Escalation Path

1. **On-call engineer** — First responder
2. **Tech lead** — SEV-1 requires immediate escalation
3. **CEO** — Notify for any data loss or security incident

---

## Post-Mortem Template (SEV-1/2)

After resolution, schedule a 30-min review:

1. What happened? (Facts only)
2. What went well in our response?
3. What could we have done better?
4. What systemic changes prevent recurrence?

Document findings in the incident report.

---

## Files & Locations

| Resource          | Path                                |
| ----------------- | ----------------------------------- |
| Incident Template | `docs/templates/incident_report.md` |
| Incident Reports  | `docs/incidents/`                   |
| Incident Log      | `docs/INCIDENT_LOG.md`              |
| Scaffolder Tool   | `python -m tools.new_incident`      |

---

_Last updated: 2025-12-21_
