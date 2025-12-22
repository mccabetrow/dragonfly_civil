<#
.SYNOPSIS
    Removes secret files from Git tracking while preserving local copies.

.DESCRIPTION
    This script is part of the SEV-1 incident response for "Postgres URI Leak".
    It removes .env files from Git's index (cache) so they are no longer tracked,
    while keeping the actual files on disk.

.NOTES
    Created: 2025-12-22
    Incident: Postgres URI Leak in GitHub
#>

param(
    [switch]$DryRun
)

$ErrorActionPreference = 'Continue'
Set-StrictMode -Version Latest

Write-Host ""
Write-Host "═══════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  SECRET FILE CLEANUP - Incident Response" -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""

# Files to remove from tracking
$secretFiles = @(
    ".env",
    ".env.dev",
    ".env.prod",
    ".env.local",
    ".env.staging",
    "dragonfly-dashboard/.env",
    "dragonfly-dashboard/.env.local",
    "judgment_ingestor/.env"
)

$removed = 0
$notTracked = 0

foreach ($file in $secretFiles) {
    # Check if file exists and is tracked
    $isTracked = git ls-files --error-unmatch $file 2>$null
    
    if ($LASTEXITCODE -eq 0) {
        if ($DryRun) {
            Write-Host "  [DRY RUN] Would remove from tracking: $file" -ForegroundColor Yellow
        } else {
            git rm --cached $file 2>$null
            if ($LASTEXITCODE -eq 0) {
                Write-Host "  ✅ Removed from tracking: $file" -ForegroundColor Green
                $removed++
            }
        }
    } else {
        Write-Host "  ⏭️  Not tracked (already safe): $file" -ForegroundColor DarkGray
        $notTracked++
    }
}

Write-Host ""
Write-Host "───────────────────────────────────────────────────────────────" -ForegroundColor Cyan
Write-Host "  Summary" -ForegroundColor Cyan
Write-Host "───────────────────────────────────────────────────────────────" -ForegroundColor Cyan
Write-Host "  Files removed from tracking: $removed" -ForegroundColor $(if ($removed -gt 0) { "Green" } else { "Gray" })
Write-Host "  Files already safe:          $notTracked" -ForegroundColor Gray
Write-Host ""

if ($removed -gt 0) {
    Write-Host "✅ Secrets removed from Git tracking (but kept locally)." -ForegroundColor Green
    Write-Host ""
    Write-Host "Next steps:" -ForegroundColor Yellow
    Write-Host "  1. git add .gitignore" -ForegroundColor White
    Write-Host "  2. git commit -m 'security: remove secrets from tracking'" -ForegroundColor White
    Write-Host "  3. Consider history scrub if secrets were in prior commits" -ForegroundColor White
} else {
    Write-Host "✅ All secret files are already safe (not tracked by Git)." -ForegroundColor Green
}

Write-Host ""
