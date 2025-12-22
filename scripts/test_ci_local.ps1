<#
.SYNOPSIS
    Local CI Test Runner for Dragonfly Civil.

.DESCRIPTION
    Orchestrates a complete local integration test run using Docker containers.
    This script:
    1. Starts PostgreSQL and PostgREST containers
    2. Waits for health checks to pass
    3. Applies database migrations
    4. Runs integration tests (pytest -m integration)
    5. Tears down containers

.PARAMETER KeepContainers
    If specified, containers are not torn down after tests complete.

.PARAMETER SkipMigrations
    Skip migration step (use if database is already migrated).

.PARAMETER TestFilter
    Additional pytest filter expression.

.NOTES
    Exit Codes: 0=passed, 1=failed, 2=infrastructure error
#>

[CmdletBinding()]
param(
    [switch]$KeepContainers,
    [switch]$SkipMigrations,
    [string]$TestFilter = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$ComposeFile = Join-Path $ProjectRoot "docker-compose.test.yml"
$MigrationsDir = Join-Path (Join-Path $ProjectRoot "supabase") "migrations"
$VenvPython = Join-Path (Join-Path (Join-Path $ProjectRoot ".venv") "Scripts") "python.exe"

$TestDbHost = "localhost"
$TestDbPort = 5433
$TestDbUser = "postgres"
$TestDbPass = "postgres"
$TestDbName = "postgres_test"
$TestDbUrl = "postgresql://${TestDbUser}:${TestDbPass}@${TestDbHost}:${TestDbPort}/${TestDbName}"
$PostgRESTUrl = "http://localhost:3001"
$HealthCheckTimeoutSec = 120
$HealthCheckIntervalSec = 2

function Write-Step { param([string]$Message); Write-Host "`n$('=' * 60)" -ForegroundColor Cyan; Write-Host "  $Message" -ForegroundColor Cyan; Write-Host "$('=' * 60)" -ForegroundColor Cyan }
function Write-Success { param([string]$Message); Write-Host "[OK] $Message" -ForegroundColor Green }
function Write-Failure { param([string]$Message); Write-Host "[FAIL] $Message" -ForegroundColor Red }
function Test-Command { param([string]$Command); $null = Get-Command $Command -ErrorAction SilentlyContinue; return $? }

function Test-Prerequisites {
    Write-Step "Checking Prerequisites"
    if (-not (Test-Command "docker")) { Write-Failure "Docker not found"; return $false }
    Write-Success "Docker found"
    if (-not (Test-Path $ComposeFile)) { Write-Failure "docker-compose.test.yml not found"; return $false }
    Write-Success "docker-compose.test.yml found"
    if (-not (Test-Path $VenvPython)) { Write-Failure "Python venv not found"; return $false }
    Write-Success "Python venv found"
    return $true
}

function Start-TestContainers {
    Write-Step "Starting Test Containers"
    Push-Location $ProjectRoot
    try {
        Write-Host "Pulling container images..."
        docker-compose -f $ComposeFile pull 2>&1 | Out-Null
        Write-Host "Starting containers..."
        docker-compose -f $ComposeFile up -d 2>&1
        if ($LASTEXITCODE -ne 0) { Write-Failure "Failed to start containers"; return $false }
        Write-Success "Containers started"
        return $true
    }
    finally { Pop-Location }
}

function Stop-TestContainers {
    Write-Step "Stopping Test Containers"
    Push-Location $ProjectRoot
    try { docker-compose -f $ComposeFile down -v 2>&1 | Out-Null; Write-Success "Containers stopped" }
    finally { Pop-Location }
}

function Wait-ForHealthChecks {
    Write-Step "Waiting for Health Checks"
    $deadline = (Get-Date).AddSeconds($HealthCheckTimeoutSec)
    Write-Host "Waiting for PostgreSQL..."
    while ((Get-Date) -lt $deadline) {
        $result = docker exec dragonfly_test_postgres pg_isready -U postgres -d postgres_test 2>&1
        if ($LASTEXITCODE -eq 0) { Write-Success "PostgreSQL is ready"; break }
        Start-Sleep -Seconds $HealthCheckIntervalSec
    }
    if ((Get-Date) -ge $deadline) { Write-Failure "PostgreSQL health check timed out"; return $false }
    Write-Host "Waiting for PostgREST..."
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri $PostgRESTUrl -UseBasicParsing -TimeoutSec 5 -ErrorAction SilentlyContinue
            if ($response.StatusCode -eq 200) { Write-Success "PostgREST is ready"; return $true }
        }
        catch { }
        Start-Sleep -Seconds $HealthCheckIntervalSec
    }
    Write-Failure "PostgREST health check timed out"
    return $false
}

function Invoke-Migrations {
    Write-Step "Applying Database Migrations"
    if (-not (Test-Path $MigrationsDir)) { Write-Host "No migrations directory"; return $true }
    $migrations = Get-ChildItem -Path $MigrationsDir -Filter "*.sql" | Sort-Object Name
    Write-Host "Applying $($migrations.Count) migrations..."
    
    $schemaSetup = @'
CREATE SCHEMA IF NOT EXISTS ops;
CREATE SCHEMA IF NOT EXISTS intake;
DO $body$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN CREATE ROLE anon NOLOGIN; END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN CREATE ROLE authenticated NOLOGIN; END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN CREATE ROLE service_role NOLOGIN; END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dragonfly_worker') THEN CREATE ROLE dragonfly_worker NOLOGIN; END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dragonfly_app') THEN CREATE ROLE dragonfly_app NOLOGIN; END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dragonfly_readonly') THEN CREATE ROLE dragonfly_readonly NOLOGIN; END IF;
END
$body$;
GRANT USAGE ON SCHEMA ops TO anon, authenticated, service_role, dragonfly_worker, dragonfly_app;
GRANT USAGE ON SCHEMA intake TO anon, authenticated, service_role, dragonfly_worker, dragonfly_app;
GRANT USAGE ON SCHEMA public TO anon, authenticated, service_role, dragonfly_worker, dragonfly_app;
'@
    $result = $schemaSetup | docker exec -i dragonfly_test_postgres psql -U postgres -d postgres_test 2>&1
    if ($LASTEXITCODE -ne 0) { Write-Failure "Failed to set up schemas"; return $false }
    Write-Success "Schemas and roles created"
    
    foreach ($migration in $migrations) {
        if ($migration.Name -match "^rollback|template") { continue }
        Write-Host "  Applying: $($migration.Name)..."
        $content = Get-Content -Path $migration.FullName -Raw
        $result = $content | docker exec -i dragonfly_test_postgres psql -U postgres -d postgres_test 2>&1
    }
    Write-Success "Migrations applied"
    return $true
}

function Invoke-IntegrationTests {
    Write-Step "Running Integration Tests"
    $env:DATABASE_URL = $TestDbUrl
    $env:SUPABASE_DB_URL = $TestDbUrl
    $env:POSTGREST_URL = $PostgRESTUrl
    $env:SUPABASE_MODE = "test"
    Push-Location $ProjectRoot
    try {
        $pytestArgs = @("-m", "integration", "-v", "--tb=short")
        if ($TestFilter) { $pytestArgs += $TestFilter.Split(" ") }
        Write-Host "Running: pytest $($pytestArgs -join ' ')"
        & $VenvPython -m pytest @pytestArgs
        $testExitCode = $LASTEXITCODE
        if ($testExitCode -eq 0) { Write-Success "All integration tests passed" }
        elseif ($testExitCode -eq 5) { Write-Host "No integration tests found"; $testExitCode = 0 }
        else { Write-Failure "Integration tests failed" }
        return $testExitCode
    }
    finally { Pop-Location }
}

function Main {
    Write-Host "`nDRAGONFLY CIVIL - LOCAL CI TEST RUNNER`n" -ForegroundColor Magenta
    if (-not (Test-Prerequisites)) { return 2 }
    if (-not (Start-TestContainers)) { return 2 }
    try {
        if (-not (Wait-ForHealthChecks)) { return 2 }
        if (-not $SkipMigrations) { if (-not (Invoke-Migrations)) { return 2 } }
        $testResult = Invoke-IntegrationTests
        Write-Step "Test Run Complete"
        if ($testResult -eq 0) { Write-Host "`n  ALL TESTS PASSED" -ForegroundColor Green }
        else { Write-Host "`n  TESTS FAILED" -ForegroundColor Red }
        return $testResult
    }
    finally {
        if (-not $KeepContainers) { Stop-TestContainers }
        else { Write-Host "Containers left running. Stop with: docker-compose -f docker-compose.test.yml down -v" }
    }
}

$exitCode = Main
exit $exitCode
