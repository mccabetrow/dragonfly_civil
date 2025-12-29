<#
.SYNOPSIS
    Scrub n8n references from environment files.

.DESCRIPTION
    Removes any lines containing N8N_API_KEY or N8N_WEBHOOK_URL from all
    environment template files (.env.dev, .env.prod, .env.example).
    This is part of the strategic pivot to native Golden Path orchestration.

.EXAMPLE
    .\scripts\scrub_n8n_env.ps1

.NOTES
    Dragonfly Civil - Golden Path Migration
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# Load Write-Status helper if available
$statusPath = Join-Path $PSScriptRoot 'Write-Status.ps1'
if (Test-Path $statusPath) {
    . $statusPath
}
else {
    # Fallback if Write-Status.ps1 not found
    function Write-Status { param([string]$Message, [string]$Level = 'INFO') Write-Host $Message }
    function Write-StatusBanner { param([string]$Title) Write-Host "`n=== $Title ===" }
}

Write-StatusBanner 'N8N Environment Scrubber'

$envFiles = @(
    '.env.dev',
    '.env.prod',
    '.env.example'
)

$n8nPattern = '(?i)^[#\s]*(N8N_API_KEY|N8N_WEBHOOK_URL).*$'

$scrubbed = 0

# Get workspace root (parent of scripts directory)
$workspaceRoot = Split-Path $PSScriptRoot -Parent

foreach ($file in $envFiles) {
    $path = Join-Path $workspaceRoot $file
    $fullPath = Resolve-Path $path -ErrorAction SilentlyContinue

    if (-not $fullPath) {
        Write-Status "  SKIP  $file (not found)" -Level 'WARN'
        continue
    }

    $original = Get-Content $fullPath -Raw -ErrorAction SilentlyContinue
    if (-not $original) {
        Write-Status "  SKIP  $file (empty or unreadable)" -Level 'WARN'
        continue
    }

    # Split into lines, filter out n8n lines, rejoin
    $lines = $original -split "`r?`n"
    $filtered = $lines | Where-Object { $_ -notmatch $n8nPattern }

    # Check if any lines were removed
    $removed = $lines.Count - $filtered.Count
    if ($removed -gt 0) {
        $newContent = $filtered -join "`n"
        # Preserve final newline if original had one
        if ($original.EndsWith("`n")) {
            $newContent += "`n"
        }
        Set-Content -Path $fullPath -Value $newContent -NoNewline -Encoding UTF8
        Write-Status "  [OK]  $file ($removed n8n line(s) removed)" -Level 'OK'
        $scrubbed++
    }
    else {
        Write-Status "  [OK]  $file (clean - no n8n references)" -Level 'INFO'
    }
}

Write-Host ''
if ($scrubbed -gt 0) {
    Write-Status "[OK] Scrubbed n8n from $scrubbed environment file(s)." -Level 'OK'
}
else {
    Write-Status "[OK] No n8n references found in environment files." -Level 'OK'
}
