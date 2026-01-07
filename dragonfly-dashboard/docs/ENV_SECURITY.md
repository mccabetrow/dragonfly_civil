# Dragonfly Dashboard - Environment Variables Security Guide

## Overview

The Dragonfly Dashboard uses Vite for builds. **Any environment variable prefixed with `VITE_` is embedded into the JavaScript bundle and exposed to the browser.** This is by design—Vite replaces `import.meta.env.VITE_*` at build time.

This means:

- ✅ **Public values** (URLs, anon keys, feature flags) are safe to use with `VITE_` prefix
- ❌ **Secrets** (service role keys, API secrets, passwords) must **NEVER** use `VITE_` prefix

## Build-Time Security Scan

A security scanner runs automatically before every build (`npm run build`) and will **fail the build** if it detects:

1. **Forbidden patterns** in `.env` files or source code:

   - `service_role` keys (Supabase admin access)
   - `OPENAI_API_KEY`, `sk-...` patterns
   - AWS credentials (`AKIA...`, `AWS_SECRET_ACCESS_KEY`)
   - Private keys or certificates
   - Database connection strings with embedded passwords
   - Any `VITE_*SECRET*`, `VITE_*PASSWORD*`, `VITE_*PRIVATE*` variables

2. **Missing required variables** in production (Vercel/CI):
   - `VITE_API_BASE_URL`
   - `VITE_SUPABASE_URL`
   - `VITE_SUPABASE_ANON_KEY`

### Running Manually

```bash
# Run security scan without building
npm run security:scan

# Full build (includes security scan via prebuild hook)
npm run build
```

---

## Required Environment Variables

### ✅ Vercel Dashboard (Production)

These must be set in Vercel → Project Settings → Environment Variables:

| Variable                 | Required | Description                               | Example                             |
| ------------------------ | -------- | ----------------------------------------- | ----------------------------------- |
| `VITE_API_BASE_URL`      | ✅ Yes   | Railway backend API URL                   | `https://dragonfly.railway.app/api` |
| `VITE_SUPABASE_URL`      | ✅ Yes   | Supabase project URL                      | `https://xxxx.supabase.co`          |
| `VITE_SUPABASE_ANON_KEY` | ✅ Yes   | Supabase **anon** key (NOT service_role!) | `eyJhbGciOiJIUzI1NiI...`            |
| `VITE_DRAGONFLY_API_KEY` | ✅ Yes   | API key for backend auth                  | `df_prod_xxx...`                    |
| `VITE_DEMO_MODE`         | ❌ No    | Set to `"true"` to lock mutations         | `true`                              |

### Local Development (.env.local)

Copy `.env.example` to `.env.local` and fill in values:

```bash
cp .env.example .env.local
```

---

## Forbidden Environment Variables

### ❌ NEVER Set These in Vercel

These secrets must **NEVER** be added to the frontend. They belong only on the backend (Railway):

| Variable                    | Where It Belongs | Why It's Forbidden in Frontend      |
| --------------------------- | ---------------- | ----------------------------------- |
| `SUPABASE_SERVICE_ROLE_KEY` | Railway only     | Bypasses RLS, grants full DB access |
| `SUPABASE_DB_URL`           | Railway only     | Direct database connection string   |
| `OPENAI_API_KEY`            | Railway only     | AI API billing credentials          |
| `ANTHROPIC_API_KEY`         | Railway only     | AI API billing credentials          |
| `AWS_SECRET_ACCESS_KEY`     | Railway only     | Cloud infrastructure credentials    |
| `DRAGONFLY_JWT_SECRET`      | Railway only     | Token signing secret                |
| Any `*_PASSWORD`            | Railway only     | Passwords are secrets               |
| Any `*_SECRET`              | Railway only     | Secrets are secrets                 |
| Any `*_PRIVATE_KEY`         | Railway only     | Private keys are secrets            |

### ❌ NEVER Use These VITE\_ Prefixes

These patterns will cause the build to fail:

```bash
# ❌ These will FAIL the build:
VITE_SUPABASE_SERVICE_ROLE_KEY=xxx    # Exposes admin key to browser!
VITE_SECRET_KEY=xxx                    # Any VITE_*SECRET* is blocked
VITE_DATABASE_PASSWORD=xxx             # Any VITE_*PASSWORD* is blocked
VITE_PRIVATE_KEY=xxx                   # Any VITE_*PRIVATE* is blocked
```

---

## How the Scanner Works

The scanner (`scripts/security-scan.mjs`) runs before `npm run build`:

1. **Scans `.env*` files** (except `.env.example`) for:

   - Forbidden patterns in variable names
   - Forbidden patterns in variable values
   - Unknown `VITE_` variables (warns, doesn't fail)

2. **Scans `src/**/\*.{ts,tsx,js,jsx}`\*\* for:

   - Hardcoded secrets or API keys
   - Suspicious high-entropy strings

3. **Checks environment in CI/Vercel** for:
   - Required variables are present
   - No forbidden variables are exposed

### Exit Codes

| Code | Meaning                                    |
| ---- | ------------------------------------------ |
| `0`  | All checks passed, build may proceed       |
| `1`  | Security violation detected, build blocked |
| `2`  | Script error                               |

---

## Adding New VITE\_ Variables

If you need to add a new `VITE_` variable:

1. **Verify it's safe for browsers** - no secrets, passwords, or admin keys
2. **Add to allowed list** in `scripts/security-scan.mjs`:

```javascript
const ALLOWED_VITE_VARS = [
  // ... existing vars ...
  "VITE_YOUR_NEW_VAR", // Add description
];
```

3. **Update `.env.example`** with documentation
4. **Update this guide** if the variable is required in production

---

## Troubleshooting

### Build fails with "SECURITY VIOLATIONS"

```
❌ SECURITY VIOLATIONS (1):

   .env.local:14
      Match: VITE_SERVICE_ROLE_KEY
      Reason: VITE_ variable containing "SERVICE_ROLE" - this grants admin access
```

**Fix:** Remove the offending variable from your `.env` file. If it's a legitimate public variable, add it to `ALLOWED_VITE_VARS` in the scanner script.

### Build fails with "Missing required environment variables"

```
❌ SECURITY VIOLATIONS (1):

   environment:0
      Match: VITE_API_BASE_URL, VITE_SUPABASE_URL
      Reason: Missing required environment variables for production build
```

**Fix:** Add the missing variables in Vercel → Project Settings → Environment Variables.

### Warning about unknown VITE\_ variable

```
⚠️  WARNINGS (1):

   .env.local:20
      Match: VITE_CUSTOM_FLAG
      Reason: Unknown VITE_ variable: VITE_CUSTOM_FLAG - add to ALLOWED_VITE_VARS if intentional
```

**Fix:** Either remove the variable or add it to `ALLOWED_VITE_VARS` in the scanner script.

---

## Security Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         BROWSER (Public)                            │
│                                                                     │
│  ✅ Safe to expose:                                                 │
│     • VITE_API_BASE_URL (just a URL)                               │
│     • VITE_SUPABASE_URL (just a URL)                               │
│     • VITE_SUPABASE_ANON_KEY (RLS-protected, meant for browser)    │
│     • VITE_DRAGONFLY_API_KEY (auth token, rotatable)               │
│                                                                     │
└────────────────────────────────┬────────────────────────────────────┘
                                 │ HTTPS
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       BACKEND - Railway (Private)                   │
│                                                                     │
│  ❌ Never expose:                                                   │
│     • SUPABASE_SERVICE_ROLE_KEY (full DB access)                   │
│     • SUPABASE_DB_URL (direct connection)                          │
│     • OPENAI_API_KEY (billing)                                     │
│     • All *_SECRET, *_PASSWORD, *_PRIVATE_KEY vars                 │
│                                                                     │
└────────────────────────────────┬────────────────────────────────────┘
                                 │ PostgreSQL (port 6543)
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       SUPABASE (Database)                           │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Quick Reference

| Question                                    | Answer                                           |
| ------------------------------------------- | ------------------------------------------------ |
| Can I use `VITE_SUPABASE_SERVICE_ROLE_KEY`? | ❌ **NO** - Never expose service role to browser |
| Can I use `VITE_SUPABASE_ANON_KEY`?         | ✅ Yes - Anon key is designed for browser use    |
| Can I hardcode an API key in source?        | ❌ **NO** - Use environment variables            |
| Where do backend secrets go?                | Railway environment variables only               |
| Where do frontend config vars go?           | Vercel environment variables (VITE\_\* prefix)   |
| How do I test the scanner?                  | `npm run security:scan`                          |
