# Secret Leak Response Runbook

> **Severity**: SEV-1 (Critical)  
> **Response Time**: Immediate (within 15 minutes of detection)

## Quick Reference

| Secret Type                            | Where to Rotate                          | Affected Services               |
| -------------------------------------- | ---------------------------------------- | ------------------------------- |
| `SUPABASE_DB_URL`                      | Supabase Dashboard → Settings → Database | All backend workers, migrations |
| `SUPABASE_SERVICE_ROLE_KEY`            | Supabase Dashboard → Settings → API      | All API endpoints, workers      |
| `DISCORD_WEBHOOK_URL`                  | Discord Server Settings → Integrations   | Alerting only                   |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | Provider dashboard                       | AI features only                |

---

## Incident Response Checklist

### 1. Immediate Actions (0-15 minutes)

- [ ] **STOP** - Do not push any more commits
- [ ] **Identify** - What secret was leaked? When? In which commit?
- [ ] **Assess** - Is this in a public repo? Has the commit been pushed to origin?
- [ ] **Rotate** - Start credential rotation immediately (see below)

### 2. Credential Rotation by Type

#### Supabase Database Password

```powershell
# 1. Generate new password (do NOT commit this!)
$newPassword = [System.Web.Security.Membership]::GeneratePassword(32, 8)
Write-Host "New password: $newPassword"

# 2. Go to Supabase Dashboard:
#    Settings → Database → Connection String → Reset Password

# 3. Update local .env files (NEVER commit these)
# .env.dev and .env.prod - update SUPABASE_DB_URL and SUPABASE_MIGRATE_DB_URL

# 4. Update GitHub Secrets:
#    Settings → Secrets → Actions → Update SUPABASE_DB_URL

# 5. Update Railway/Production:
#    Railway Dashboard → Variables → Update SUPABASE_DB_URL

# 6. Verify connectivity
.\scripts\load_env.ps1 -Mode dev
python -m tools.doctor --env dev
```

#### Supabase Service Role Key

```powershell
# 1. Go to Supabase Dashboard:
#    Settings → API → Service Role Key → Regenerate

# 2. Update all locations:
#    - .env.dev / .env.prod (local, never commit)
#    - GitHub Secrets: SUPABASE_SERVICE_ROLE_KEY
#    - Railway/Vercel: SUPABASE_SERVICE_ROLE_KEY
#    - n8n workflows (if applicable)

# 3. Verify
.\scripts\load_env.ps1 -Mode dev
python -m tools.smoke --env dev
```

#### Discord Webhook URL

```powershell
# 1. Discord Server → Settings → Integrations → Webhooks
# 2. Delete the leaked webhook
# 3. Create new webhook with same name
# 4. Update DISCORD_WEBHOOK_URL in:
#    - .env files (local)
#    - Railway/production environment
```

### 3. Git History Cleanup

**If the commit has NOT been pushed:**

```powershell
# Remove the secret from the last commit
git reset HEAD~1
# Edit the file to remove the secret
git add .
git commit -m "fix: Remove accidentally added secret"
```

**If the commit HAS been pushed:**

> ⚠️ WARNING: Rewriting history affects all collaborators

```powershell
# Option 1: Use BFG Repo Cleaner (recommended)
# Download from: https://rtyley.github.io/bfg-repo-cleaner/

# Create a file with the secret pattern
echo "your-leaked-secret" > secrets.txt

# Run BFG
java -jar bfg.jar --replace-text secrets.txt

# Force push (coordinate with team first!)
git push --force
```

**If the repo is PUBLIC:**

1. Consider the secret **permanently compromised**
2. Rotation is mandatory regardless of cleanup
3. Monitor for unauthorized access in Supabase logs
4. Consider GitHub's secret scanning alerts

### 4. Post-Incident Actions

- [ ] Document the incident in `docs/incidents/YYYY-MM-DD-secret-leak.md`
- [ ] Verify gitleaks pre-commit hook is installed: `pre-commit install`
- [ ] Run full security audit: `python -m tools.security_audit --env dev`
- [ ] Review Supabase auth logs for suspicious activity
- [ ] Update this runbook if new secret types were involved

---

## Prevention Measures

### Pre-Commit Hooks (Already Configured)

```powershell
# Ensure hooks are installed
pre-commit install

# Test gitleaks locally
pre-commit run gitleaks --all-files
```

### Environment File Discipline

```powershell
# NEVER commit .env files
# .gitignore already covers:
# - .env
# - .env.*
# - .env.dev
# - .env.prod

# Always use .env.example for templates
# Verify gitignore is working:
git status --ignored | Select-String "\.env"
```

### CI Protection

The CI pipeline includes:

- `secrets-scan` job runs gitleaks on every push
- Blocks merge if secrets are detected
- Uses `.gitleaks.toml` for custom Dragonfly patterns

---

## Emergency Contacts

| Role             | Contact             | When to Escalate              |
| ---------------- | ------------------- | ----------------------------- |
| On-Call Engineer | (your contact)      | Any secret leak               |
| Supabase Support | support@supabase.io | Database compromise suspected |
| GitHub Security  | security@github.com | Public repo exposure          |

---

## Related Documentation

- [SECURITY_EXCEPTIONS.md](SECURITY_EXCEPTIONS.md) - Documented security exceptions
- [Zero Trust Architecture](../supabase/migrations/20251222102730_zero_trust_finish.sql) - RLS policies
- [Supabase Security Best Practices](https://supabase.com/docs/guides/auth/row-level-security)
