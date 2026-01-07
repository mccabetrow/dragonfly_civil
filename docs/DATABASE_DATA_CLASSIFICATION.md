# Dragonfly Civil — Data Classification Standard

> _"Data without classification is a liability. Data with classification is an asset."_

This document defines the mandatory data classification schema for all database columns in Dragonfly Civil.

---

## Overview

Every column in core tables **must** have a classification comment in JSON format. This enables:

1. **Compliance** — Automated audits detect unclassified PII
2. **Access Control** — RLS policies can reference sensitivity levels
3. **Data Governance** — Clear ownership and handling requirements
4. **Incident Response** — Rapid identification of affected data in breaches

---

## Classification Schema

All column comments must be valid JSON with the following structure:

```json
{
  "tag": "PII",
  "sensitivity": "HIGH",
  "description": "Human-readable description of the field"
}
```

### Required Fields

| Field         | Type   | Required    | Description                         |
| ------------- | ------ | ----------- | ----------------------------------- |
| `tag`         | string | ✅ Yes      | Classification category (see below) |
| `sensitivity` | string | Recommended | Sensitivity level (see below)       |
| `description` | string | Recommended | Human-readable description          |

---

## Classification Tags

| Tag            | Emoji | Description                         | Examples                                | Handling Requirements                           |
| -------------- | ----- | ----------------------------------- | --------------------------------------- | ----------------------------------------------- |
| `PUBLIC`       | 🌐    | Public record, freely accessible    | Case numbers, court names, filing dates | Standard logging OK                             |
| `INTERNAL`     | 🏢    | Internal use only, not sensitive    | IDs, timestamps, status codes           | No special handling                             |
| `CONFIDENTIAL` | 🔒    | Business confidential               | Strategy notes, internal scores         | Restrict access, audit reads                    |
| `PII`          | 👤    | Personally Identifiable Information | Names, addresses, SSN, phone, email     | Encrypt at rest, mask in logs, retention limits |
| `FINANCIAL`    | 💰    | Financial data                      | Amounts, balances, payment info         | Encrypt, audit all access, PCI compliance       |

---

## Sensitivity Levels

| Level      | Description                      | Access Control                             |
| ---------- | -------------------------------- | ------------------------------------------ |
| `LOW`      | Minimal risk if disclosed        | Standard RLS                               |
| `MEDIUM`   | Some risk, internal only         | RLS + role restrictions                    |
| `HIGH`     | Significant risk, regulated data | RLS + audit logging + encryption           |
| `CRITICAL` | Maximum protection required      | RLS + audit + encryption + access approval |

---

## Adding Classifications

### SQL Syntax

Use `COMMENT ON COLUMN` statements in your migrations:

```sql
-- PII Example
COMMENT ON COLUMN public.plaintiffs.email IS
  '{"tag": "PII", "sensitivity": "HIGH", "description": "Primary email address"}';

-- Financial Example
COMMENT ON COLUMN public.judgments.judgment_amount IS
  '{"tag": "FINANCIAL", "sensitivity": "HIGH", "description": "Original judgment amount in USD"}';

-- Public Example
COMMENT ON COLUMN public.judgments.case_number IS
  '{"tag": "PUBLIC", "sensitivity": "LOW", "description": "Court-assigned case number (public record)"}';

-- Internal Example
COMMENT ON COLUMN public.judgments.id IS
  '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "Primary key UUID"}';
```

### Table-Level Comments

Tables should also have classification comments:

```sql
COMMENT ON TABLE public.plaintiffs IS
  '{"description": "Plaintiff master records", "sensitivity": "HIGH", "contains_pii": true}';
```

---

## Validation

### Local Audit

Run the classification auditor locally:

```bash
# Audit core tables only
python -m tools.audit_data_classification --env dev

# Audit all tables
python -m tools.audit_data_classification --env dev --all-tables

# Strict mode (requires sensitivity field)
python -m tools.audit_data_classification --env dev --strict
```

### CI Enforcement

The classification audit runs in CI. Any unclassified columns in core tables will **fail the build**.

```yaml
# .github/workflows/compliance.yml
- name: Audit Data Classification
  run: python -m tools.audit_data_classification --env dev
```

---

## Core Tables

The following tables are subject to mandatory classification:

| Table                             | Contains PII | Contains Financial |
| --------------------------------- | ------------ | ------------------ |
| `public.judgments`                | ✅ Yes       | ✅ Yes             |
| `public.plaintiffs`               | ✅ Yes       | ❌ No              |
| `public.plaintiff_contacts`       | ✅ Yes       | ❌ No              |
| `public.plaintiff_status_history` | ❌ No        | ❌ No              |

---

## Handling Requirements by Tag

### PII Fields

- ✅ Encrypt at rest (Supabase default)
- ✅ Never log raw values
- ✅ Mask in error messages (e.g., `j***@example.com`)
- ✅ Apply retention limits (delete after N years)
- ✅ Include in data subject access requests (DSAR)
- ❌ Never expose in public APIs without authentication

### Financial Fields

- ✅ Encrypt at rest
- ✅ Audit all read/write access
- ✅ Use decimal types (never floating point)
- ✅ Include in financial reconciliation reports
- ❌ Never cache in browser local storage

### Confidential Fields

- ✅ Restrict to authorized roles
- ✅ Audit access patterns
- ❌ Never include in public views

---

## Migration Checklist

When adding a new column to a core table:

- [ ] Add `COMMENT ON COLUMN` with valid JSON classification
- [ ] Set appropriate `tag` (PUBLIC/INTERNAL/CONFIDENTIAL/PII/FINANCIAL)
- [ ] Set `sensitivity` level (LOW/MEDIUM/HIGH/CRITICAL)
- [ ] Add human-readable `description`
- [ ] Run `python -m tools.audit_data_classification --env dev`
- [ ] Verify audit passes before merging

---

## References

- [docs/ARCHITECTURE.md](ARCHITECTURE.md) — System architecture
- [tools/audit_data_classification.py](../tools/audit_data_classification.py) — Audit tool
- [supabase/migrations/20260101000000_compliance_foundation.sql](../supabase/migrations/20260101000000_compliance_foundation.sql) — Initial classifications

---

_Last Updated: January 2026_
_Owner: Dragonfly Data Governance_
