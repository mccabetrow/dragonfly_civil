# Runbook: Copying Supabase Transaction Pooler DSN

**When to use:** Setting up `SUPABASE_DB_URL` for production API/workers.

---

## ⚠️ CRITICAL: Direct Connection is FORBIDDEN

Production requires the **Transaction Pooler** connection string, NOT the Direct Connection.

| Connection Type       | Host Pattern            | Port | Production?   |
| --------------------- | ----------------------- | ---- | ------------- |
| ❌ Direct             | `db.<ref>.supabase.co`  | 5432 | **FORBIDDEN** |
| ❌ Session Pooler     | `*.pooler.supabase.com` | 5432 | **FORBIDDEN** |
| ✅ Transaction Pooler | `*.pooler.supabase.com` | 6543 | **REQUIRED**  |

---

## Step-by-Step: Get the Transaction Pooler DSN

### 1. Open Supabase Dashboard

Navigate to your project at `https://supabase.com/dashboard/project/<your-ref>`

### 2. Go to Settings → Database

In the left sidebar:

- Click **Settings** (gear icon)
- Click **Database**

### 3. Scroll to "Connection string"

Look for the **Connection string** section. You will see a dropdown with these options:

- `URI` / `JDBC` / `psql` (format selector)
- `Direct connection` / `Session pooler` / `Transaction pooler` (mode selector)

### 4. Select "Transaction pooler" mode

**Click the dropdown and select "Transaction pooler"**

You should see a connection string like:

```
postgresql://postgres.<ref>:[YOUR-PASSWORD]@aws-0-us-east-1.pooler.supabase.com:6543/postgres
```

**Verify:**

- ✅ Host contains `.pooler.supabase.com`
- ✅ Port is `6543`
- ❌ Host does NOT start with `db.`

### 5. Copy and add sslmode

Copy the connection string and **append `?sslmode=require`**:

```
postgresql://postgres.<ref>:[YOUR-PASSWORD]@aws-0-us-east-1.pooler.supabase.com:6543/postgres?sslmode=require
```

### 6. Set in Railway

1. Railway Dashboard → Your Service → Variables
2. Set `SUPABASE_DB_URL` to the full connection string
3. **Redeploy**

---

## Validation

After deployment, check logs for:

✅ **SUCCESS:**

```
Configuration validated OK (env=prod, pooler=True, port=6543, ssl=require)
```

❌ **FAILURE (will block startup):**

```
⛔ FATAL: PRODUCTION DSN CONTRACT VIOLATION
host='db.xyz.supabase.co' is DIRECT connection (FORBIDDEN in prod)
```

---

## Common Mistakes

| Mistake                         | What You See              | Fix                                        |
| ------------------------------- | ------------------------- | ------------------------------------------ |
| Copied Direct instead of Pooler | `host='db.*.supabase.co'` | Re-copy with "Transaction pooler" selected |
| Wrong port                      | `port=5432`               | Change to `6543`                           |
| Missing sslmode                 | `sslmode='missing'`       | Append `?sslmode=require`                  |
| Copied Session Pooler           | `port=5432` (pooler host) | Select "Transaction pooler" (port 6543)    |

---

## Why Transaction Pooler?

1. **Connection efficiency** - Reuses connections, prevents exhaustion
2. **Supabase limits** - Direct connections have strict limits
3. **Production stability** - Pooler handles connection spikes gracefully
4. **Port 6543** - Transaction mode for short-lived queries (ideal for API)

Session pooler (port 5432) is for long-lived connections (e.g., migrations) - NOT for API runtime.
