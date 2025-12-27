# SEV-1 Repository History Scrub Commands

> **DANGER ZONE**: These commands rewrite Git history. Coordinate with your team before running.

## Prerequisites

1. **Backup your work**:

   ```powershell
   # Create a backup branch
   git branch backup-before-scrub
   ```

2. **Ensure no one is working on the repo**:
   - Notify team members
   - Lock the repo if possible

---

## Option A: Squash Last N Commits (Recommended if <10 commits to clean)

```powershell
# 1. First, run the gitignore fix
.\scripts\fix_gitignore.ps1

# 2. Install the pre-commit hook
python tools/install_hooks.py

# 3. Interactive rebase to squash last 5 commits
git rebase -i HEAD~5

# In the editor that opens:
# - Change 'pick' to 'squash' (or 's') for all commits EXCEPT the first
# - Save and close
# - Write a new commit message: "chore: consolidated commits (security cleanup)"

# 4. Force push (DANGEROUS - rewrites history)
git push --force-with-lease origin main
```

---

## Option B: BFG Repo Cleaner (Recommended for deep cleaning)

```powershell
# 1. Download BFG from https://rtyley.github.io/bfg-repo-cleaner/
# Save as bfg.jar in your home directory

# 2. Create a file listing secrets to remove
@"
postgresql://postgres
eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9
Actkmt2930
"@ | Out-File -FilePath secrets-to-remove.txt -Encoding utf8

# 3. Clone a fresh mirror
git clone --mirror https://github.com/mccabetrow/dragonfly_civil.git dragonfly_civil_mirror

# 4. Run BFG to replace secrets with ***REMOVED***
java -jar ~/bfg.jar --replace-text secrets-to-remove.txt dragonfly_civil_mirror

# 5. Clean up the mirror
cd dragonfly_civil_mirror
git reflog expire --expire=now --all
git gc --prune=now --aggressive

# 6. Push the cleaned history
git push --force

# 7. Delete the secrets file!
Remove-Item ../secrets-to-remove.txt
```

---

## Option C: git filter-repo (Modern alternative to BFG)

```powershell
# 1. Install git-filter-repo
pip install git-filter-repo

# 2. Create replacement rules
@"
postgresql://postgres.ejiddanxtqcleyswqvkc:Actkmt2930!@==>***REDACTED_DB_URL***
postgresql://postgres.iaketsyhmqbwaabgykux:Actkmt2930!@==>***REDACTED_DB_URL***
eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImVqaWRkYW54dHFjbGV5c3dxdmtjIiwicm9sZSI6InNlcnZpY2Vfcm9sZSI==>***REDACTED_KEY***
"@ | Out-File -FilePath replacements.txt -Encoding utf8

# 3. Run filter-repo
git filter-repo --replace-text replacements.txt --force

# 4. Re-add remote and force push
git remote add origin https://github.com/mccabetrow/dragonfly_civil.git
git push --force --all
git push --force --tags

# 5. Delete the replacements file!
Remove-Item replacements.txt
```

---

## Post-Scrub Checklist

After force-pushing cleaned history:

- [ ] **Rotate ALL credentials** (they're already compromised):

  ```
  - Supabase DB password (both dev and prod)
  - Supabase service role keys (both dev and prod)
  - Any API keys that appeared in history
  ```

- [ ] **Notify GitHub** of the secret exposure:

  - GitHub may have cached the data
  - Visit: https://support.github.com/contact/private-information

- [ ] **Team sync**:

  ```powershell
  # Everyone must run:
  git fetch origin
  git reset --hard origin/main
  ```

- [ ] **Verify the scrub worked**:

  ```powershell
  # Search for secrets in history
  git log -p --all | Select-String "Actkmt2930"
  # Should return nothing
  ```

- [ ] **Document the incident**:
  - Create `docs/incidents/2025-12-22-secret-leak.md`
  - Record timeline, impact, remediation steps

---

## Quick One-Liner (After running fix_gitignore.ps1)

```powershell
# This does a soft reset of last 5 commits, then recommits everything clean
git reset --soft HEAD~5; git add -A; git commit -m "chore: security cleanup - consolidated commits"; git push --force-with-lease
```

⚠️ **WARNING**: Only do this if you're the sole contributor or have coordinated with your team!
