<#
.SYNOPSIS
    Print effective configuration with secrets redacted.

.DESCRIPTION
    Loads the unified Settings from src/config.py and displays which
    environment variables are in use. Secrets are redacted for safety.

.EXAMPLE
    .\scripts\print_effective_config.ps1

.EXAMPLE
    .\scripts\print_effective_config.ps1 -ShowDeprecated
#>

param(
    [switch]$ShowDeprecated,
    [switch]$JsonOutput
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

# Activate virtual environment
$venvPath = Join-Path $PSScriptRoot "..\\.venv\\Scripts\\Activate.ps1"
if (Test-Path $venvPath) {
    & $venvPath
}

$pythonScript = @'
import json
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core_config import get_settings, get_deprecated_keys_used, print_effective_config

# Get effective config
config = print_effective_config(redact_secrets=True)

# Output as JSON
print(json.dumps(config, indent=2, default=str))
'@

Write-Host ""
Write-Host "=" * 70 -ForegroundColor Cyan
Write-Host "  DRAGONFLY EFFECTIVE CONFIGURATION" -ForegroundColor Cyan
Write-Host "  (Secrets redacted for safety)" -ForegroundColor DarkGray
Write-Host "=" * 70 -ForegroundColor Cyan
Write-Host ""

try {
    $result = python -c $pythonScript 2>&1
    
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] Failed to load configuration:" -ForegroundColor Red
        Write-Host $result -ForegroundColor Red
        exit 1
    }
    
    $config = $result | ConvertFrom-Json
    
    if ($JsonOutput) {
        Write-Host $result
        exit 0
    }
    
    # Core Configuration
    Write-Host "CORE SUPABASE" -ForegroundColor Yellow
    Write-Host "-------------" -ForegroundColor Yellow
    Write-Host "  SUPABASE_URL:              $($config.SUPABASE_URL)"
    Write-Host "  SUPABASE_SERVICE_ROLE_KEY: $($config.SUPABASE_SERVICE_ROLE_KEY)"
    Write-Host "  SUPABASE_DB_URL:           $($config.SUPABASE_DB_URL)"
    Write-Host ""
    
    # Environment
    Write-Host "ENVIRONMENT" -ForegroundColor Yellow
    Write-Host "-----------" -ForegroundColor Yellow
    Write-Host "  ENVIRONMENT:   $($config.ENVIRONMENT)"
    Write-Host "  SUPABASE_MODE: $($config.SUPABASE_MODE)"
    Write-Host "  LOG_LEVEL:     $($config.LOG_LEVEL)"
    Write-Host ""
    
    # Computed values
    if ($config._computed) {
        Write-Host "COMPUTED VALUES" -ForegroundColor Yellow
        Write-Host "---------------" -ForegroundColor Yellow
        Write-Host "  supabase_mode:       $($config._computed.supabase_mode)"
        Write-Host "  is_production:       $($config._computed.is_production)"
        Write-Host "  cors_allowed_origins: $($config._computed.cors_allowed_origins -join ', ')"
        Write-Host ""
    }
    
    # Optional integrations
    Write-Host "INTEGRATIONS" -ForegroundColor Yellow
    Write-Host "------------" -ForegroundColor Yellow
    $integrations = @(
        @("DRAGONFLY_API_KEY", $config.DRAGONFLY_API_KEY),
        @("OPENAI_API_KEY", $config.OPENAI_API_KEY),
        @("DISCORD_WEBHOOK_URL", $config.DISCORD_WEBHOOK_URL),
        @("SENDGRID_API_KEY", $config.SENDGRID_API_KEY),
        @("TWILIO_ACCOUNT_SID", $config.TWILIO_ACCOUNT_SID),
        @("PROOF_API_KEY", $config.PROOF_API_KEY)
    )
    
    foreach ($item in $integrations) {
        $name = $item[0]
        $value = $item[1]
        $status = if ($value -and $value -ne "null") { "[SET]" } else { "[NOT SET]" }
        $color = if ($value -and $value -ne "null") { "Green" } else { "DarkGray" }
        Write-Host "  ${name}: " -NoNewline
        Write-Host $status -ForegroundColor $color
    }
    Write-Host ""
    
    # Deprecated keys
    if ($config._deprecated_keys_used -and $config._deprecated_keys_used.Count -gt 0) {
        Write-Host "WARNING: DEPRECATED KEYS IN USE" -ForegroundColor Yellow -BackgroundColor DarkRed
        Write-Host "-------------------------------" -ForegroundColor Yellow
        foreach ($key in $config._deprecated_keys_used) {
            Write-Host "  - $key" -ForegroundColor Yellow
        }
        Write-Host ""
        Write-Host "  See docs/env_contract.md for migration guide." -ForegroundColor DarkGray
        Write-Host ""
    }
    elseif ($ShowDeprecated) {
        Write-Host "DEPRECATED KEYS" -ForegroundColor Green
        Write-Host "---------------" -ForegroundColor Green
        Write-Host "  None detected - configuration is using canonical keys!" -ForegroundColor Green
        Write-Host ""
    }
    
    Write-Host "=" * 70 -ForegroundColor Cyan
    Write-Host "  Configuration loaded successfully" -ForegroundColor Green
    Write-Host "=" * 70 -ForegroundColor Cyan
    
}
catch {
    Write-Host "[ERROR] Failed to parse configuration:" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
