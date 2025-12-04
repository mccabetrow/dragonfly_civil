<#
.SYNOPSIS
    Legacy wrapper - calls db_migrate.ps1

.DESCRIPTION
    This script is deprecated. Use db_migrate.ps1 directly:
      .\scripts\db_migrate.ps1 -Env dev
      .\scripts\db_migrate.ps1 -Env prod

.PARAMETER IncludeAll
    Ignored. Kept for backward compatibility.
#>

param(
  [switch]$IncludeAll = $false
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "[DEPRECATED] db_push.ps1 is deprecated. Use db_migrate.ps1 instead." -ForegroundColor Yellow
Write-Host ""

# Call the new canonical script
& (Join-Path $ScriptDir 'db_migrate.ps1') -Env dev
