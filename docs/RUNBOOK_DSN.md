# RUNBOOK: Database Authentication Chain of Custody

> **Audience:** Operators deploying Dragonfly Civil to production  
> **Purpose:** Prove that a DSN is correct before wiring it to Railway  
> **Toolbox:** `build_pooler_dsn`, `validate_dsn`, `probe_db`

---

## Quick Reference

| Tool               | Purpose                                   | Exit Codes                   |
| ------------------ | ----------------------------------------- | ---------------------------- |
| `build_pooler_dsn` | Build a pooler-safe DSN with URL encoding | 0=success, 1=error           |
| `validate_dsn`     | Validate DSN structure (no DB connection) | 0=valid, 1=invalid, 2=no DSN |
| `probe_db`         | Test actual DB connectivity               | 0=PASS, 1=FAIL, 2=no DSN     |

---

## 1. Generate a Production DSN

### Option A: Interactive Mode (Recommended for First-Time Setup)

```powershell
# Run from project root
.venv\Scripts\python.exe -m tools.build_pooler_dsn --interactive
```

The tool will prompt for:

- **Pooler host** (e.g., `aws-0-us-east-1.pooler.supabase.com`)
- **Username** (e.g., `dragonfly_app.abcdefgh123`)
- **Password** (hidden input, will be URL-encoded automatically)

Output:

```
=== DSN Builder for Supabase Pooler ===
Pooler host: aws-0-us-east-1.pooler.supabase.com
Username: dragonfly_app.abcdefgh123
Password: ********

✓ Detected: SHARED pooler (transaction mode)

Built DSN (password redacted):
postgresql://dragonfly_app.abcdefgh123:****@aws-0-us-east-1.pooler.supabase.com:6543/postgres?sslmode=require

Full DSN (for Railway):
postgresql://dragonfly_app.abcdefgh123:P%40ssw0rd%21@aws-0-us-east-1.pooler.supabase.com:6543/postgres?sslmode=require
```

### Option B: CLI Mode (For Scripts/Automation)

```powershell
# Password from command line (use for testing only)
.venv\Scripts\python.exe -m tools.build_pooler_dsn `
    --host aws-0-us-east-1.pooler.supabase.com `
    --user dragonfly_app.abcdefgh123 `
    --password "MyP@ssword!"

# Password from environment variable (recommended)
$env:DB_PASSWORD = "MyP@ssword!"
.venv\Scripts\python.exe -m tools.build_pooler_dsn `
    --host aws-0-us-east-1.pooler.supabase.com `
    --user dragonfly_app.abcdefgh123 `
    --password-env DB_PASSWORD
```

### Option C: Quiet Mode (Output DSN Only)

```powershell
# For piping to clipboard or env file
.venv\Scripts\python.exe -m tools.build_pooler_dsn `
    --host aws-0-us-east-1.pooler.supabase.com `
    --user dragonfly_app.abcdefgh123 `
    --password "MyP@ssword!" `
    --quiet
```

---

## 2. Validate DSN Structure

Before connecting, verify the DSN meets Supabase pooler requirements:

```powershell
# From command line
.venv\Scripts\python.exe -m tools.validate_dsn "postgresql://user:pass@host:6543/postgres?sslmode=require"

# From environment variable
$env:SUPABASE_DB_URL = "postgresql://user:pass@host:6543/postgres?sslmode=require"
.venv\Scripts\python.exe -m tools.validate_dsn
```

### Validation Rules

| Rule        | Requirement                 | Why                                                                 |
| ----------- | --------------------------- | ------------------------------------------------------------------- |
| **Port**    | Must be `6543`              | Transaction pooler port (5432 = direct connection, blocked in prod) |
| **sslmode** | Must be `require`           | Supabase enforces TLS; any other mode fails                         |
| **Host**    | Should match pooler pattern | Detects shared vs dedicated pooler                                  |

### Example Output (Valid)

```
Validating DSN (password redacted):
postgresql://dragonfly_app.abc:****@aws-0-us-east-1.pooler.supabase.com:6543/postgres?sslmode=require

✓ PORT is correct: 6543 (transaction pooler)
✓ SSLMODE is correct: require
✓ HOST is a Supabase SHARED pooler (transaction mode)

Result: ✓ VALID - DSN meets production requirements
```

### Example Output (Invalid)

```
Validating DSN (password redacted):
postgresql://user:****@db.abc.supabase.co:5432/postgres

✗ PORT is incorrect: 5432 (must be 6543 for pooler)
✗ SSLMODE is missing or invalid (must be 'require')

HINT: If password contains special characters (@, #, !, %, etc.),
      ensure they are URL-encoded. Use build_pooler_dsn to encode automatically.

Result: ✗ INVALID - 2 errors found
```

---

## 3. Probe Database Connectivity

After validation, test actual connectivity:

```powershell
# From command line
.venv\Scripts\python.exe -m tools.probe_db "postgresql://user:pass@host:6543/postgres?sslmode=require"

# From environment variable
$env:SUPABASE_DB_URL = "postgresql://user:pass@host:6543/postgres?sslmode=require"
.venv\Scripts\python.exe -m tools.probe_db
```

### Output

```
# Success
PASS: Connected to aws-0-us-east-1.pooler.supabase.com:6543 as dragonfly_app

# Failure
FAIL: Connection refused (is the pooler host correct?)

# No DSN
ERROR: No DSN provided. Set SUPABASE_DB_URL or pass as argument.
```

### Exit Codes

| Code | Meaning                                                     |
| ---- | ----------------------------------------------------------- |
| 0    | PASS - Connection successful                                |
| 1    | FAIL - Connection failed (wrong credentials, network, etc.) |
| 2    | ERROR - No DSN provided                                     |

---

## 4. Complete Workflow: New App User Setup

### Step 1: Apply the Migration

```powershell
# Apply dragonfly_app role migration to prod
$env:SUPABASE_MODE = "prod"
.\scripts\db_push.ps1 -SupabaseEnv prod
```

### Step 2: Set the Password in Supabase SQL Editor

Navigate to: **Supabase Dashboard → SQL Editor**

```sql
-- Set the password for dragonfly_app
ALTER ROLE dragonfly_app WITH PASSWORD 'YourSecureP@ssword!';
```

> ⚠️ **Do NOT run this in a terminal or commit to version control!**

### Step 3: Build the DSN

```powershell
.venv\Scripts\python.exe -m tools.build_pooler_dsn `
    --host aws-0-us-east-1.pooler.supabase.com `
    --user dragonfly_app.abcdefgh123 `
    --password "YourSecureP@ssword!" `
    --quiet > dsn_temp.txt

# Copy to clipboard (Windows)
Get-Content dsn_temp.txt | Set-Clipboard
Remove-Item dsn_temp.txt
```

### Step 4: Validate the DSN

```powershell
.venv\Scripts\python.exe -m tools.validate_dsn (Get-Clipboard)
```

### Step 5: Probe the Database

```powershell
.venv\Scripts\python.exe -m tools.probe_db (Get-Clipboard)
```

### Step 6: Wire Railway

If probe returns `PASS`, deploy to Railway:

1. Open Railway dashboard
2. Navigate to your service → Variables
3. Add/update `DATABASE_URL` with the DSN from your clipboard
4. Redeploy the service

---

## 5. Wire Railway Shared Variables

For multi-service deployments, use Railway's shared variables:

### Create Shared Variable Group

1. Railway Dashboard → Shared Variables
2. Create group: `dragonfly-db-prod`
3. Add variable: `DATABASE_URL` = (your validated DSN)

### Reference in Services

Each service should reference the shared variable:

```
DATABASE_URL = ${shared.dragonfly-db-prod.DATABASE_URL}
```

### Services That Need DATABASE_URL

| Service               | Uses DSN | Notes                         |
| --------------------- | -------- | ----------------------------- |
| `backend`             | Yes      | Main API server               |
| `workers`             | Yes      | Background job processors     |
| `dragonfly-dashboard` | No       | Frontend only (uses REST API) |

---

## 6. Troubleshooting

### "Connection refused" or "timeout"

1. Verify host is correct (`aws-0-...pooler.supabase.com`, not `db....supabase.co`)
2. Verify port is `6543` (not `5432`)
3. Check if IP is allowlisted in Supabase network restrictions

### "Password authentication failed"

1. Verify password is URL-encoded (use `build_pooler_dsn`)
2. Verify username matches the role + project ref:
   - Format: `dragonfly_app.PROJECT_REF`
   - Example: `dragonfly_app.abcdefgh123`
3. Verify password was set correctly in SQL Editor

### "SSL connection required"

1. Verify `sslmode=require` is in the DSN
2. Verify no proxy/firewall is stripping TLS

### Password Contains `@` and Connection Fails

The `@` symbol must be URL-encoded as `%40`. Example:

- Raw password: `P@ssword123`
- URL-encoded: `P%40ssword123`

Use `build_pooler_dsn` to handle this automatically:

```powershell
.venv\Scripts\python.exe -m tools.build_pooler_dsn --password "P@ssword123"
```

---

## 7. Security Checklist

Before deploying:

- [ ] Password was set in SQL Editor (never in terminal/git)
- [ ] DSN validated with `validate_dsn` (exit code 0)
- [ ] Database probed with `probe_db` (exit code 0)
- [ ] Railway variable is in a shared group (not per-service)
- [ ] Old postgres superuser DSN is removed from Railway
- [ ] Local `.env` files do NOT contain production credentials

---

## Appendix: URL Encoding Reference

| Character | Encoded      |
| --------- | ------------ |
| `@`       | `%40`        |
| `!`       | `%21`        |
| `#`       | `%23`        |
| `$`       | `%24`        |
| `%`       | `%25`        |
| `^`       | `%5E`        |
| `&`       | `%26`        |
| `*`       | `%2A`        |
| `(`       | `%28`        |
| `)`       | `%29`        |
| `+`       | `%2B`        |
| `=`       | `%3D`        |
| `/`       | `%2F`        |
| `?`       | `%3F`        |
| `:`       | `%3A`        |
| `;`       | `%3B`        |
| `<space>` | `%20` or `+` |
