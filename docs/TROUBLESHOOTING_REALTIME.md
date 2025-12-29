# Supabase Realtime Troubleshooting

Quick reference for diagnosing and fixing Supabase Realtime websocket authentication failures.

---

## Symptoms

- Browser console shows: `WebSocket connection failed`, `401 Unauthorized`, or `auth` errors
- Dashboard banner appears: **"Realtime disconnected (auth failed)"**
- Live updates stop working, but polling/refresh still works

---

## Common Causes & Fixes

### 1. Wrong API Key

| Problem                              | Solution                         |
| ------------------------------------ | -------------------------------- |
| Using `service_role` key in frontend | Use the **anon/public** key only |
| Key has extra whitespace or newlines | Trim all whitespace when copying |
| Key is from wrong Supabase project   | Verify project ref matches URL   |

**How to verify:**

```bash
# Anon keys contain "anon" in the decoded payload
# Service role keys contain "service_role"
# Decode at jwt.io to check the "role" claim
```

### 2. Wrong URL Format

| Problem                                  | Solution                                      |
| ---------------------------------------- | --------------------------------------------- |
| Using pooler URL (`pooler.supabase.com`) | Use REST API URL: `https://<ref>.supabase.co` |
| URL has trailing slash                   | Remove trailing `/` or `/api`                 |
| Missing `https://`                       | Always include the protocol                   |

**Correct format:**

```
VITE_SUPABASE_URL=https://iaketsyhmqbwaabgykux.supabase.co
```

**Wrong formats:**

```
# ❌ Pooler URL (for direct DB connections only)
https://aws-0-us-east-1.pooler.supabase.com

# ❌ Direct DB host (for migrations only)
db.iaketsyhmqbwaabgykux.supabase.co

# ❌ Trailing slash
https://iaketsyhmqbwaabgykux.supabase.co/
```

### 3. Environment Variable Not Set

| Platform | Where to check                             |
| -------- | ------------------------------------------ |
| Vercel   | Project → Settings → Environment Variables |
| Local    | `.env.local` or `.env.development`         |
| Railway  | Service → Variables tab                    |

**Required frontend variables:**

```bash
VITE_SUPABASE_URL=https://<ref>.supabase.co
VITE_SUPABASE_ANON_KEY=eyJ...  # ~200 chars, NOT service_role
```

### 4. Realtime Not Enabled

Supabase Realtime requires explicit table enablement:

```sql
-- In Supabase SQL Editor or migration
ALTER PUBLICATION supabase_realtime ADD TABLE public.judgments;
ALTER PUBLICATION supabase_realtime ADD TABLE ops.job_queue;
ALTER PUBLICATION supabase_realtime ADD TABLE enforcement.draft_packets;
```

**Verify current tables:**

```sql
SELECT * FROM pg_publication_tables WHERE pubname = 'supabase_realtime';
```

### 5. RLS Blocking Subscriptions

Realtime respects Row Level Security. If RLS blocks reads, realtime won't work.

```sql
-- Check if RLS is enabled
SELECT tablename, rowsecurity FROM pg_tables WHERE schemaname = 'public';

-- Ensure anon role can read
GRANT SELECT ON public.judgments TO anon;
```

---

## Diagnostic Steps

### Step 1: Check Console Logs

Open browser DevTools → Console. Look for:

- `[Dragonfly Config]` - Shows resolved config values
- `[Supabase]` - Client initialization
- `[Realtime]` - Connection status

### Step 2: Verify Config at /debug/config

Navigate to `/debug/config` (dev mode only) to see:

- Resolved Supabase URL
- Key preview (last 8 chars)
- Demo mode status

### Step 3: Test Connection Manually

```javascript
// In browser console
const { supabaseUrl, supabaseAnonKey } = await import("/src/config/runtime.ts");
console.log("URL:", supabaseUrl);
console.log("Key ends with:", supabaseAnonKey.slice(-8));

// Test REST API
fetch(`${supabaseUrl}/rest/v1/judgments?limit=1`, {
  headers: { apikey: supabaseAnonKey },
})
  .then((r) => r.json())
  .then(console.log);
```

### Step 4: Check Supabase Dashboard

1. Go to [Supabase Dashboard](https://supabase.com/dashboard)
2. Select your project → Settings → API
3. Verify:
   - Project URL matches `VITE_SUPABASE_URL`
   - `anon` key matches `VITE_SUPABASE_ANON_KEY`

---

## Graceful Degradation

Even when realtime fails, the dashboard continues working:

| Feature          | Without Realtime           |
| ---------------- | -------------------------- |
| Data display     | ✅ Works via REST API      |
| Auto-refresh     | ✅ Polling every 30s       |
| Manual refresh   | ✅ Refresh button works    |
| Live updates     | ⚠️ Delayed until next poll |
| Flash animations | ❌ Won't trigger           |

The app displays a **dismissable banner** when auth fails, but never crashes.

---

## Quick Fixes

```bash
# 1. Redeploy with correct vars
vercel env pull
# Edit .env.local
vercel deploy --prod

# 2. Clear browser cache
# Chrome: DevTools → Application → Storage → Clear site data

# 3. Hard refresh
# Windows: Ctrl+Shift+R
# Mac: Cmd+Shift+R
```

---

## Related Files

- [src/config/runtime.ts](../dragonfly-dashboard/src/config/runtime.ts) - Environment validation
- [src/lib/supabaseClient.ts](../dragonfly-dashboard/src/lib/supabaseClient.ts) - Client initialization
- [src/context/RealtimeContext.tsx](../dragonfly-dashboard/src/context/RealtimeContext.tsx) - Connection state
- [src/components/RealtimeStatusBanner.tsx](../dragonfly-dashboard/src/components/RealtimeStatusBanner.tsx) - User banner
