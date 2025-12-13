# Dragonfly Civil — Production Acceptance Checklist

**Purpose**
This document defines the non‑negotiable acceptance criteria that must be satisfied **before any production deployment**. Dragonfly ships only when every checkbox below is verified. This checklist exists to prevent regressions, demo failures, and operator confusion.

---

## 0. Release Metadata (Required)

- [ ] **Commit SHA:** **************\_\_**************
- [ ] **Branch:** main
- [ ] **Deployment Target:** Railway (API) / Vercel (Console)
- [ ] **Environment:** production
- [ ] **Release Owner:** ************\_\_\_************
- [ ] **Date / Time:** **************\_\_**************

---

## 1. CI & Test Gate (Hard Block)

All automated tests must pass before deployment.

- [ ] `pytest` passes locally with no failures
- [ ] No skipped tests related to intake, enforcement, or control‑plane endpoints
- [ ] All new logic introduced in this release includes test coverage
- [ ] No test relies on production secrets or live data

**Result:** ⬜ PASS / ⬜ FAIL

---

## 2. Database & Schema Integrity

Ensure production schema is aligned and safe.

- [ ] All migrations applied to **prod** via approved workflow
- [ ] No pending migrations (`db_push --prod` reports clean)
- [ ] No breaking schema changes to base tables used by UI
- [ ] New tables/views include explicit grants where required
- [ ] Optional views are never required for dashboard endpoints

**Result:** ⬜ PASS / ⬜ FAIL

---

## 3. Control Plane — Boring Endpoints (Never 500)

These endpoints **must never return HTTP 500** under any circumstance.

### 3.1 System Status

- [ ] `GET /health` → 200 OK
- [ ] `GET /api/v1/system/status` → 200 OK
- [ ] Response uses standard API envelope
- [ ] Degraded state returned if dependencies unavailable

### 3.2 Intake State (Authoritative UI Source)

- [ ] `GET /api/v1/intake/state` → 200 OK
- [ ] Depends only on base tables (`ops.ingest_batches`, `ops.job_queue`, etc.)
- [ ] Returns **all required fields** even if degraded
- [ ] On DB failure, returns `degraded=true` (never throws)
- [ ] Response includes `trace_id`

### 3.3 Intake Batches (Non‑Critical, Degradable)

- [ ] `GET /api/v1/intake/batches` → 200 OK
- [ ] Pagination works (`limit`, `offset`)
- [ ] On error, returns degraded response (never 500)
- [ ] Does not block UI rendering if degraded

**Result:** ⬜ PASS / ⬜ FAIL

---

## 4. Intake Write Path (CSV Upload)

- [ ] `POST /api/v1/intake/upload` accepts valid CSV
- [ ] Successful upload returns `batch_id`
- [ ] UI transitions to **Upload Accepted** (not failed)
- [ ] Validation errors are row‑level, not upload‑level
- [ ] Upload failure only shown if POST request fails

**Result:** ⬜ PASS / ⬜ FAIL

---

## 5. Orchestration & Workers

- [ ] Workers online (heartbeat within threshold)
- [ ] `ops.job_queue` reflects pending/processing jobs accurately
- [ ] No jobs stuck in `processing` beyond SLA
- [ ] Worker down state surfaces as **Workers Degraded**, not generic failure

**Result:** ⬜ PASS / ⬜ FAIL

---

## 6. Decision Engine (Enforcement Strategy)

- [ ] Strategy logic unchanged OR changes fully tested
- [ ] `test_strategy_agent.py` passes (100%)
- [ ] Strategy execution is deterministic and side‑effect controlled
- [ ] No direct coupling to UI or intake state

**Result:** ⬜ PASS / ⬜ FAIL

---

## 7. Realtime & UI Resilience

- [ ] UI loads Intake page without blocking errors
- [ ] UI renders data using `/intake/state` as primary source
- [ ] Realtime disconnect does **not** break UI (polling fallback active)
- [ ] No infinite reconnect loops observed in console
- [ ] UI never displays false "Upload Failed" state

**Result:** ⬜ PASS / ⬜ FAIL

---

## 8. Smoke Tests (Required)

Run all production verification scripts:

- [ ] `scripts/prod_smoke.ps1` → **ALL CHECKS PASS**
- [ ] `scripts/verify_simplicity.ps1` → **Ingestion Verified**

**Result:** ⬜ PASS / ⬜ FAIL

---

## 9. Observability & Debuggability

- [ ] All degraded responses include `trace_id`
- [ ] Corresponding logs exist in Railway with same `trace_id`
- [ ] Error codes are structured and greppable
- [ ] No raw exception strings leaked to UI

**Result:** ⬜ PASS / ⬜ FAIL

---

## 10. Manual UI Walkthrough (Human Check)

Perform a live walkthrough:

- [ ] Open Dashboard → no blocking errors
- [ ] Navigate to Intake Station → state loads instantly
- [ ] Upload sample CSV → batch accepted
- [ ] Observe batch progress updating
- [ ] Errors shown only at row/batch level
- [ ] Cases page loads without error

**Result:** ⬜ PASS / ⬜ FAIL

---

## 11. Go / No‑Go Decision

- [ ] All sections PASS
- [ ] Release Owner approves deployment

**FINAL DECISION:** ⬜ GO / ⬜ NO‑GO

**Signed by:** ************\_\_\_************
**Timestamp:** ************\_\_\_************

---

## Policy

If **any single checkbox fails**, deployment is **blocked**. There are no overrides. Dragonfly Civil prioritizes reliability, truthfulness, and operator confidence over speed.
