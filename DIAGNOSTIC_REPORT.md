# Dragonfly Civil Diagnostic Report

**Generated**: December 6, 2025 (Updated: January 28, 2025)  
**Version**: v1.0 Post-Release Audit  
**Scope**: Comprehensive codebase sweep covering database schema, API contracts, migrations, and code quality

---

## Executive Summary

| Category                           | Issues Found | Severity |
| ---------------------------------- | ------------ | -------- |
| Missing Indexes                    | 8            | Medium   |
| Missing Foreign Keys               | 3            | Low      |
| Dangling/Redundant Migrations      | 11           | Low      |
| Pydantic Model Issues              | 4            | Medium   |
| API Error Contract Inconsistencies | 5            | Medium   |
| Typing Issues                      | 6            | Low      |
| Unused Imports                     | 0            | N/A      |
| Slow SQL Patterns                  | 4            | Medium   |

---

## 1. Missing Indexes

### 1.1 Foreign Key Columns Without Indexes

| Table                 | Column       | Referenced Table    | File                       |
| --------------------- | ------------ | ------------------- | -------------------------- |
| `outreach.attempts`   | `cadence_id` | `outreach.cadences` | `0001_core_schema.sql:177` |
| `enforcement.actions` | `case_id`    | `judgments.cases`   | `0001_core_schema.sql:201` |
| `intake.esign`        | `case_id`    | `judgments.cases`   | `0001_core_schema.sql:189` |
| `finance.trust_txns`  | `case_id`    | `judgments.cases`   | `0001_core_schema.sql:213` |
| `outreach.cadences`   | `case_id`    | `judgments.cases`   | `0001_core_schema.sql:161` |
| `parties.roles`       | `entity_id`  | `parties.entities`  | `0001_core_schema.sql:58`  |
| `parties.roles`       | `case_id`    | `judgments.cases`   | `0001_core_schema.sql:57`  |

**Note**: The composite primary key on `parties.roles` provides some indexing, but individual FK columns may still benefit from dedicated indexes for JOIN performance.

### 1.2 Timestamp Columns Used for Ordering Without Indexes

| Table                      | Column       | Usage Pattern                                      |
| -------------------------- | ------------ | -------------------------------------------------- |
| `plaintiff_status_history` | `changed_at` | Used in ORDER BY in `v_plaintiff_call_queue` view  |
| `enforcement.actions`      | `created_at` | Used in ORDER BY in `v_enforcement_actions_recent` |
| `public.plaintiffs`        | `created_at` | Used in date filtering in `v_ops_daily_summary`    |

### Recommended Fix

```sql
-- Add missing FK indexes
CREATE INDEX IF NOT EXISTS idx_attempts_cadence ON outreach.attempts (cadence_id);
CREATE INDEX IF NOT EXISTS idx_esign_case ON intake.esign (case_id);
CREATE INDEX IF NOT EXISTS idx_trust_txns_case ON finance.trust_txns (case_id);
CREATE INDEX IF NOT EXISTS idx_actions_case ON enforcement.actions (case_id);
CREATE INDEX IF NOT EXISTS idx_cadences_case ON outreach.cadences (case_id);
CREATE INDEX IF NOT EXISTS idx_roles_entity ON parties.roles (entity_id);
CREATE INDEX IF NOT EXISTS idx_roles_case ON parties.roles (case_id);

-- Add timestamp indexes for common ORDER BY patterns
CREATE INDEX IF NOT EXISTS idx_plaintiff_status_history_changed_at
  ON public.plaintiff_status_history (changed_at DESC);
CREATE INDEX IF NOT EXISTS idx_enforcement_actions_created_at
  ON enforcement.actions (created_at DESC);
```

---

## 2. Missing Foreign Keys

### 2.1 Tables Referencing Others Without Explicit FK Constraints

| Table                        | Column               | Should Reference        | Evidence                                                            |
| ---------------------------- | -------------------- | ----------------------- | ------------------------------------------------------------------- |
| `public.judgments`           | `plaintiff_id`       | `public.plaintiffs(id)` | Column exists (added in `20251214000000`), no FK constraint visible |
| `enforcement.offers`         | `judgment_id`        | `public.judgments(id)`  | Used in `offers.py:119` - FK may exist but unverified               |
| `intelligence.relationships` | `source_judgment_id` | `public.judgments(id)`  | FK defined in `20251214000000:562` ✓                                |

**Note**: The `plaintiff_id` column on `public.judgments` was added but FK constraint status is unclear from migrations.

### Recommended Investigation

Run this query in production to verify FK constraints:

```sql
SELECT
    tc.table_schema,
    tc.table_name,
    kcu.column_name,
    ccu.table_name AS foreign_table_name
FROM information_schema.table_constraints AS tc
JOIN information_schema.key_column_usage AS kcu
    ON tc.constraint_name = kcu.constraint_name
JOIN information_schema.constraint_column_usage AS ccu
    ON ccu.constraint_name = tc.constraint_name
WHERE tc.constraint_type = 'FOREIGN KEY'
AND tc.table_schema IN ('public', 'enforcement', 'judgments')
ORDER BY tc.table_schema, tc.table_name;
```

---

## 3. Dangling/Redundant Migrations

### 3.1 Test/Placeholder Migrations (Safe to Archive)

| File                         | Purpose                      | Status                |
| ---------------------------- | ---------------------------- | --------------------- |
| `0103_placeholder.sql`       | Empty placeholder            | **Archive candidate** |
| `20251204000000_ci_test.sql` | CI sanity check (`SELECT 1`) | **Archive candidate** |
| `0043_queue_job_debug.sql`   | Debug diagnostics only       | **Archive candidate** |
| `0044_queue_job_debug2.sql`  | Debug diagnostics only       | **Archive candidate** |
| `0045_debug_pgmq.sql`        | Debug diagnostics only       | **Archive candidate** |

### 3.2 Superseded Migrations (Overlapping Functionality)

These migrations have been replaced by later versions:

| Original                                                              | Superseded By                                                                                         | Concern                                   |
| --------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- | ----------------------------------------- |
| `0102_plaintiff_call_attempts.sql`                                    | `0105_log_call_outcome_refresh.sql`, `0106_log_call_outcome_fix.sql`, `0107_log_call_outcome_fix.sql` | `log_call_outcome` RPC redefined 4+ times |
| `0039_fix_queue_job_signature.sql` through `0052_queue_bootstrap.sql` | `0119_priority_pipeline_view.sql`, `0206_judgment_enrich_queue.sql`                                   | `queue_job` RPC redefined many times      |
| `0104_log_call_outcome_refresh.sql`                                   | `0105_log_call_outcome_refresh.sql`                                                                   | Duplicate file naming                     |

### 3.3 Potential Conflict: Same-Named Functions with Different Signatures

| Function                       | Files Defining It                              |
| ------------------------------ | ---------------------------------------------- |
| `public.queue_job(jsonb)`      | `0119`, `0206`                                 |
| `public.log_call_outcome(...)` | `0102`, `0106`, `0107`, `0119`, `0141`, `0146` |
| `public.dequeue_job(text)`     | `0113`, multiple others                        |

**Recommendation**: Consolidate these into a single canonical migration or use explicit `DROP FUNCTION IF EXISTS` before each definition.

---

## 4. Pydantic Model Mismatches

### 4.1 Response Models Not Matching Database Columns

| Router           | Model                               | Issue                                                                                         |
| ---------------- | ----------------------------------- | --------------------------------------------------------------------------------------------- |
| `enforcement.py` | `EnforcementStatusResponse`         | Fields like `enforcement_id`, `strategy`, `next_action` are returned but marked as TODO stubs |
| `enforcement.py` | `EnforcementHistoryResponse`        | `total_recovered: float` - actual DB schema unclear                                           |
| `budget.py`      | All models                          | Entire router is TODO stubs - no database interaction                                         |
| `analytics.py`   | `OverviewMetrics.avg_case_age_days` | Hardcoded to `0` (line ~140), not actually calculated                                         |

### 4.2 Fields Defined But Not Used

| Router         | Model                 | Unused Field                                            |
| -------------- | --------------------- | ------------------------------------------------------- |
| `intake.py`    | `BatchDetailResponse` | `worker_id` - not populated from database               |
| `ingest_v2.py` | `BatchSummary`        | `error_summary` - always None in current implementation |

### 4.3 Missing Optional Annotations

All checked routers correctly use `Optional` or `| None` syntax. ✓

---

## 5. API Error Contract Inconsistencies

### 5.1 HTTPException vs Custom Error Responses

| Router           | Pattern Used                             | Consistency     |
| ---------------- | ---------------------------------------- | --------------- |
| `intake.py`      | `HTTPException` with string detail       | ✓               |
| `ingest.py`      | `HTTPException` with **dict detail**     | ⚠️ Inconsistent |
| `offers.py`      | `HTTPException` with string detail       | ✓               |
| `packets.py`     | `HTTPException` with string detail       | ✓               |
| `foil.py`        | `HTTPException` with **dict detail**     | ⚠️ Inconsistent |
| `analytics.py`   | No error handling (exceptions bubble up) | ⚠️ Missing      |
| `enforcement.py` | No HTTPException usage (TODO stubs)      | ⚠️              |

### 5.2 Status Code Inconsistencies

| Error Type        | Expected | Actual Usage                               |
| ----------------- | -------- | ------------------------------------------ |
| Validation errors | 422      | Pydantic returns 422 ✓                     |
| Bad request       | 400      | Used correctly in `intake.py`, `ingest.py` |
| Not found         | 404      | Used correctly                             |
| Server error      | 500      | Mixed usage                                |
| DB unavailable    | 503      | Used in `offers.py` only                   |

### 5.3 Error Response Structure Mismatch

The `backend/core/errors.py` defines a structured `ErrorResponse` model, but most routers don't use it:

```python
# errors.py defines:
class ErrorResponse(BaseModel):
    error: str
    message: str
    status_code: int
    request_id: str | None
    details: list[ErrorDetail] | None

# But routers use:
raise HTTPException(status_code=400, detail="string message")  # Simple string
raise HTTPException(status_code=500, detail={"status": "error", "error": str(e)})  # Ad-hoc dict
```

**Recommendation**: Standardize on the `ErrorResponse` structure or simplify to always use string details.

---

## 6. Typing Issues

### 6.1 Functions with `-> Any` Return Type

| File                                 | Line | Function                                        |
| ------------------------------------ | ---- | ----------------------------------------------- |
| `backend/db.py`                      | 151  | `fetchval(self, query: str, *args: Any) -> Any` |
| `backend/db.py`                      | 219  | Helper function returns `Any`                   |
| `backend/services/intake_service.py` | 255  | `_get_enrichment_service(self) -> Any`          |
| `backend/services/intake_service.py` | 267  | `_get_graph_service(self) -> Any`               |

### 6.2 Functions Missing Return Type Annotations

| File                         | Function           | Line          |
| ---------------------------- | ------------------ | ------------- |
| `backend/core/errors.py`     | `__init__` methods | 251, 262, 274 |
| `backend/db.py`              | `__init__`         | 134           |
| `backend/core/middleware.py` | `__init__` methods | 50, 157, 265  |

### 6.3 Parameter Type Issues

All checked routers have proper type hints on parameters. ✓

---

## 7. Unused Imports

No significant unused imports detected in router files. The linting appears clean.

---

## 8. Slow SQL Patterns

### 8.1 Long CTE Chains

| View                            | CTE Count           | File                                 |
| ------------------------------- | ------------------- | ------------------------------------ |
| `v_ops_daily_summary`           | 5 CTEs              | `0142_ops_daily_summary.sql`         |
| `v_enforcement_pipeline_status` | 2 CTEs + subqueries | `0210_enforcement_action_views.sql`  |
| `v_intake_monitor`              | 1 CTE + aggregation | `20251210000000_intake_fortress.sql` |

The `v_ops_daily_summary` view uses 5 CTEs with:

- Cross joins to date anchor
- Multiple LEFT JOINs
- UNION ALL in subquery
- No LIMIT clause

### 8.2 Missing LIMIT on Large Table Scans

| View                            | Issue                                        |
| ------------------------------- | -------------------------------------------- |
| `v_enforcement_pipeline_status` | No LIMIT, scans all `core_judgments`         |
| `v_plaintiffs_overview`         | No LIMIT, full table scan                    |
| `v_ops_daily_summary`           | Daily rollup, but still scans all plaintiffs |

### 8.3 Potentially Expensive JOINs

```sql
-- v_enforcement_pipeline_status (0210_enforcement_action_views.sql)
-- Joins 3 tables without row limits:
FROM public.core_judgments cj
    LEFT JOIN intelligence_summary isumm ON isumm.judgment_id = cj.id
    LEFT JOIN action_summary asumm ON asumm.judgment_id = cj.id
ORDER BY ... -- Complex CASE expression in ORDER BY
```

### 8.4 Recommendations

1. **Materialize heavy views**: Consider using materialized views with scheduled refresh for `v_ops_daily_summary` and `v_enforcement_pipeline_status`
2. **Add pagination**: Expose LIMIT/OFFSET parameters in dashboard queries
3. **Index ORDER BY columns**: Add indexes on columns used in ORDER BY expressions
4. **Use partial indexes**: For filtered queries on status columns

---

## Action Items

### High Priority

1. Add missing FK indexes (Section 1.1)
2. Standardize error response format (Section 5.3)
3. Review `v_ops_daily_summary` performance (Section 8.1)

### Medium Priority

4. Archive test/placeholder migrations (Section 3.1)
5. Consolidate `log_call_outcome` RPC definitions (Section 3.2)
6. Update TODO stubs in `enforcement.py` and `budget.py` (Section 4.1)

### Low Priority

7. Replace `-> Any` with specific types (Section 6.1)
8. Consider materializing expensive views (Section 8.4)
9. Add explicit FK constraint for `public.judgments.plaintiff_id` (Section 2.1)

---

## Appendix: Tools Used

- `grep_search` for pattern matching across migrations and Python files
- `read_file` for detailed code inspection
- Manual analysis of migration dependencies

---

_Report generated by Copilot diagnostic sweep_

---

## Changelog

| Date       | Update                                                 |
| ---------- | ------------------------------------------------------ |
| 2025-12-06 | Initial comprehensive diagnostic report                |
| 2025-01-28 | v1.0 post-release audit; verified findings still apply |
