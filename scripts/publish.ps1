param(
  [switch]$Origin,
  [switch]$NoValidate
)

$ErrorActionPreference = "Stop"

function Run($cmd) {
  Write-Host "[RUN] $cmd"
  $p = Start-Process -FilePath "powershell" -ArgumentList "-NoLogo -NoProfile -Command $cmd" -Wait -PassThru
  if ($p.ExitCode -ne 0) { throw "Command failed: $cmd (rc=$($p.ExitCode))" }
}

# 1) Ensure gh
try { gh --version | Out-Null } catch {
  Write-Host "[INFO] Installing GitHub CLI via winget..."
  Run 'winget install --id GitHub.cli -e --accept-package-agreements --accept-source-agreements'
}

# 2) gh auth
try {
  gh auth status | Out-Null
} catch {
  Write-Host "[INFO] Logging into GitHub CLI..."
  Run 'gh auth login --hostname github.com --git-protocol https --web'
}

# 3) Ensure fork remote if not using origin
if (-not $Origin) {
  $remotes = git remote -v
  if ($remotes -notmatch "^fork\s+") {
    Write-Host "[INFO] Creating/adding fork remote..."
    Run 'gh repo fork mccabetrow/dragonfly_civil --remote=true --clone=false'
  }
}

# 4) Validate
if (-not $NoValidate) {
  Write-Host "[INFO] Running validation..."
  python -m validate_simplicity
  if ($LASTEXITCODE -ne 0) { throw "[ERR] Validation failed. See validation_*.txt." }
}

# 5) Commit the new validation log (if any)
git add validation_*.txt 2>$null
git commit -m "chore: validation log (auto)" 2>$null | Out-Null
Write-Host "[OK] Commit step complete (or nothing to commit)."

# 6) Push
if ($Origin) {
  Write-Host "[INFO] Pushing to origin..."
  git push --set-upstream origin main
  if ($LASTEXITCODE -ne 0) {
    Write-Host "[WARN] Push to origin failed. If 403, re-auth or use PAT with Git Credential Manager and retry."
    exit 1
  }
} else {
  Write-Host "[INFO] Pushing to fork..."
  git push --set-upstream fork main
  if ($LASTEXITCODE -ne 0) {
    Write-Host "[WARN] First push failed; attempting rebase pull then re-push..."
    git pull --rebase fork main
    if ($LASTEXITCODE -ne 0) { throw "[ERR] Rebase pull failed." }
    git push --set-upstream fork main
    if ($LASTEXITCODE -ne 0) { throw "[ERR] Push to fork failed after rebase." }
  }
}

# 7) Summary
$up = git rev-parse --abbrev-ref --symbolic-full-name '@{u}'
$head = git log -1 --oneline
$log = Get-ChildItem validation_*.txt | Sort-Object LastWriteTime -Descending | Select-Object -First 1
Write-Host "[OK] Upstream: $up"
Write-Host "[OK] HEAD: $head"
if ($log) { Write-Host "[OK] Validation log: $($log.Name)" } else { Write-Host "[OK] No validation log found." }
