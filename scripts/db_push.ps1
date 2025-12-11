<#
.SYNOPSIS
    Thin wrapper to apply Supabase migrations.

.DESCRIPTION
    Delegates to db_migrate.ps1 for the target environment.
    Provides a simple interface for VS Code tasks.

.PARAMETER SupabaseEnv
    Target environment: 'dev' or 'prod'. Required.

.EXAMPLE
    .\scripts\db_push.ps1 -SupabaseEnv dev
    .\scripts\db_push.ps1 -SupabaseEnv prod
#>

param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("dev", "prod")]
    [string]$SupabaseEnv
)

$ErrorActionPreference = 'Stop'
$env:SUPABASE_MODE = $SupabaseEnv

# Delegate to the canonical migration script
& "$PSScriptRoot\db_migrate.ps1" -SupabaseEnv $SupabaseEnv
