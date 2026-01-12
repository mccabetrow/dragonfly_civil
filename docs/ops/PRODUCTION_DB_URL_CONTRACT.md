# Production Database URL Contract

> **Status**: MANDATORY | **Last Updated**: 2026-01-12 | **Owner**: Platform Engineering

## Purpose

This document defines the **non-negotiable contract** for database connection strings in Dragonfly production environments. Violations cause `server_login_retry` lockouts, connection exhaustion, and cascading service failures.

---

## The Contract

### ✅ CORRECT Production DSN Format

```
postgresql://postgres.[PROJECT_REF]:[SERVICE_ROLE_PASSWORD]@aws-0-[REGION].pooler.supabase.com:6543/postgres?sslmode=require
```

### Anatomy of a Valid URL

| Component    | Required Value           | Why                                                    |
| ------------ | ------------------------ | ------------------------------------------------------ |
| **Username** | `postgres.[PROJECT_REF]` | Transaction pooler requires project-qualified username |
| **Host**     | `*.pooler.supabase.com`  | Must route through Supavisor transaction pooler        |
| **Port**     | `6543`                   | Transaction pooler port (NOT 5432, NOT 6432)           |
| **sslmode**  | `require`                | Encrypted connections mandatory in production          |
| **Database** | `postgres`               | Default Supabase database                              |

---

## ❌ Common Misconfigurations (All FATAL)

### 1. Direct Host (Bypasses Pooler)

```
❌ postgresql://postgres:xxx@db.abcd1234.supabase.co:5432/postgres
```

**Symptom**: Connection exhaustion after ~60 connections  
**Log**: `too many connections for role "postgres"`

### 2. Wrong Port (Session Pooler or Direct)

```
❌ postgresql://postgres.ref:xxx@aws-0-us-east-1.pooler.supabase.com:5432/postgres
❌ postgresql://postgres.ref:xxx@aws-0-us-east-1.pooler.supabase.com:6432/postgres
```

**Symptom**: `server_login_retry` lockout within 5 failed attempts  
**Log**: `FATAL: password authentication failed`

### 3. Missing sslmode

```
❌ postgresql://postgres.ref:xxx@aws-0-us-east-1.pooler.supabase.com:6543/postgres
```

**Symptom**: Connection rejected or man-in-the-middle vulnerability  
**Log**: `SSL connection is required`

### 4. Wrong Username Format

```
❌ postgresql://postgres:xxx@aws-0-us-east-1.pooler.supabase.com:6543/postgres
```

**Symptom**: Auth failure, account lockout  
**Log**: `password authentication failed for user "postgres"`

---

## Pre-Deploy Checklist

Before deploying any service that connects to the database:

| #   | Check                                | Command/Action                                    | Expected    |
| --- | ------------------------------------ | ------------------------------------------------- | ----------- |
| 1   | Host contains `.pooler.supabase.com` | `echo $SUPABASE_DB_URL \| grep pooler`            | Match found |
| 2   | Port is exactly `6543`               | `echo $SUPABASE_DB_URL \| grep :6543`             | Match found |
| 3   | Username format is `postgres.[ref]`  | `echo $SUPABASE_DB_URL \| grep 'postgres\.'`      | Match found |
| 4   | sslmode=require present              | `echo $SUPABASE_DB_URL \| grep 'sslmode=require'` | Match found |
| 5   | NOT using SUPABASE_MIGRATE_DB_URL    | `echo $SUPABASE_MIGRATE_DB_URL`                   | Empty/unset |

---

## Environment Variable Separation

| Variable                  | Purpose                            | Port | When Used                 |
| ------------------------- | ---------------------------------- | ---- | ------------------------- |
| `SUPABASE_DB_URL`         | Runtime connections (API, Workers) | 6543 | Always in prod runtime    |
| `SUPABASE_MIGRATE_DB_URL` | Schema migrations only             | 5432 | Only in migration scripts |

**CRITICAL**: `SUPABASE_MIGRATE_DB_URL` must NEVER be set in Railway service variables. It exposes direct database credentials to the runtime tier.

---

## Log Signatures

### ✅ Correct Configuration

```
[BOOT] Mode: PROD | Config Source: SYSTEM_ENV | SHA: abc123
[CONFIG_GUARD] ✅ DB URL validated: pooler=true, port=6543, ssl=require
INFO: Uvicorn running on http://0.0.0.0:8000
```

### ❌ Incorrect Configuration

```
[CONFIG_GUARD] ⛔ SUPABASE_DB_URL invalid for prod runtime
  violations: host=db.xxx.supabase.co, port=5432, sslmode=missing
Application startup blocked.
```

### ❌ Auth Failure (Lockout Imminent)

```
FATAL: password authentication failed for user "postgres"
[CONFIG_GUARD] 🔴 AUTH FAILURE DETECTED - Exiting immediately to prevent lockout
```

---

## Validation Code Reference

The contract is enforced in `backend/core/config_guard.py`:

```python
def _enforce_prod_pooler_contract() -> None:
    """Exit immediately if production runtime DB URL violates pooler contract."""

    if not (_is_production() and is_runtime_mode()):
        return  # Only enforce in production runtime

    db_url = os.environ.get("SUPABASE_DB_URL")

    violations = []
    if ".pooler.supabase.com" not in host:
        violations.append(f"host={host}")
    if port != 6543:
        violations.append(f"port={port}")
    if sslmode != "require":
        violations.append(f"sslmode={sslmode or 'missing'}")

    if violations:
        sys.exit(f"⛔ SUPABASE_DB_URL invalid: {violations}")
```

---

## Quick Reference Card

```
┌─────────────────────────────────────────────────────────────────┐
│  PRODUCTION DB URL CONTRACT                                      │
├─────────────────────────────────────────────────────────────────┤
│  ✅ Host:     *.pooler.supabase.com                              │
│  ✅ Port:     6543 (transaction pooler)                          │
│  ✅ User:     postgres.[project-ref]                             │
│  ✅ SSL:      sslmode=require                                    │
│  ✅ Variable: SUPABASE_DB_URL only                               │
├─────────────────────────────────────────────────────────────────┤
│  ❌ NEVER:    db.*.supabase.co (direct host)                     │
│  ❌ NEVER:    port 5432 or 6432                                  │
│  ❌ NEVER:    SUPABASE_MIGRATE_DB_URL in runtime                 │
│  ❌ NEVER:    sslmode=disable or missing                         │
└─────────────────────────────────────────────────────────────────┘
```
