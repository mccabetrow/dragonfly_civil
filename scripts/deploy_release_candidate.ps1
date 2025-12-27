[CmdletBinding()]
param(
    [ValidateSet("dev", "prod")]
    [string]$Mode = "dev",
    [switch]$DryRun,
    [switch]$SkipDeploy,
    [switch]$SkipGate,
    [switch]$InitialDeploy
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$PythonExe = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$Timestamp = Get-Date -Format "yyyyMMdd-HHmm"

function Write-Section([string]$Title) {
    Write-Host ""
    Write-Host ("=" * 70) -ForegroundColor Cyan
    Write-Host "  $Title" -ForegroundColor Cyan
    Write-Host ("=" * 70) -ForegroundColor Cyan
}

function Write-Success([string]$Message) {
    Write-Host "[OK] $Message" -ForegroundColor Green
}

function Write-Failure([string]$Message) {
    Write-Host "[FAIL] $Message" -ForegroundColor Red
}

function Require-File([string]$Path) {
    $fullPath = Join-Path $RepoRoot $Path
    if (-not (Test-Path $fullPath)) {
        throw "Required file not found: $Path"
    }
}

function Require-EnvVar([string]$Name) {
    $val = [Environment]::GetEnvironmentVariable($Name)
    if ([string]::IsNullOrWhiteSpace($val)) {
        throw "Required environment variable not set: $Name"
    }
}

$startTime = Get-Date

Write-Host ""
Write-Host ("*" * 70) -ForegroundColor Yellow
Write-Host "     DRAGONFLY RELEASE CANDIDATE" -ForegroundColor Yellow
Write-Host "     Mode: $($Mode.ToUpper())" -ForegroundColor Yellow
Write-Host "     Time: $Timestamp" -ForegroundColor Yellow
if ($DryRun) { Write-Host "     [DRY RUN MODE]" -ForegroundColor Magenta }
Write-Host ("*" * 70) -ForegroundColor Yellow

Write-Section "PREFLIGHT VALIDATION"
Require-File "scripts\load_env.ps1"
Require-File "scripts\gate_preflight.ps1"
Require-File "scripts\db_push.ps1"
Require-File ".venv\Scripts\python.exe"
Write-Success "All required files present"

$envFile = Join-Path $RepoRoot ".env.$Mode"
if (-not (Test-Path $envFile)) {
    throw "Environment file not found: .env.$Mode"
}

Write-Section "STEP 1/6: LOAD ENVIRONMENT"
. (Join-Path $RepoRoot "scripts\load_env.ps1") -EnvPath $envFile -Mode $Mode
$env:SUPABASE_MODE = $Mode
Require-EnvVar "SUPABASE_MIGRATE_DB_URL"
Require-EnvVar "SUPABASE_URL"
Require-EnvVar "SUPABASE_SERVICE_ROLE_KEY"
Write-Success "Environment loaded and validated"

Write-Section "STEP 2/6: HARD GATE"
if ($SkipGate) {
    Write-Host "[WARN] Skipping gate (-SkipGate). DANGEROUS!" -ForegroundColor Yellow
}
elseif (-not $DryRun) {
    if ($InitialDeploy) {
        Write-Host "[INFO] Initial Deploy mode - relaxed health checks" -ForegroundColor Yellow
        & (Join-Path $RepoRoot "scripts\gate_preflight.ps1") -InitialDeploy
    }
    else {
        & (Join-Path $RepoRoot "scripts\gate_preflight.ps1")
    }
    if ($LASTEXITCODE -ne 0) {
        Write-Failure "HARD GATE FAILED"
        exit 1
    }
    Write-Success "Gate passed"
}
else {
    Write-Host "[DRY RUN] Would run gate_preflight.ps1" -ForegroundColor Magenta
}

Write-Section "STEP 3/6: MIGRATIONS"
if (-not $DryRun) {
    & (Join-Path $RepoRoot "scripts\db_push.ps1") -SupabaseEnv $Mode -Force
    if ($LASTEXITCODE -ne 0) {
        Write-Failure "Migration failed"
        exit 1
    }
    Write-Success "Migrations applied"
}
else {
    Write-Host "[DRY RUN] Would run db_push.ps1 -SupabaseEnv $Mode" -ForegroundColor Magenta
}

Write-Section "STEP 4/6: CONTRACT VERIFICATION"
if (-not $DryRun) {
    & $PythonExe -m tools.verify_contract --env $Mode
    if ($LASTEXITCODE -ne 0) {
        Write-Failure "Contract verification failed"
        exit 1
    }
    Write-Success "Contract verified"
}
else {
    Write-Host "[DRY RUN] Would run verify_contract" -ForegroundColor Magenta
}

Write-Section "STEP 5/6: HEALTH CHECKS"
. (Join-Path $RepoRoot "scripts\load_env.ps1") -EnvPath $envFile -Mode $Mode
$env:SUPABASE_MODE = $Mode
if (-not $DryRun) {
    # Temporarily allow errors - doctor_all may have warnings that write to stderr
    $prevErrorAction = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    
    & $PythonExe -m tools.doctor_all --env $Mode 2>&1 | ForEach-Object { Write-Host $_ }
    $healthExitCode = $LASTEXITCODE
    
    $ErrorActionPreference = $prevErrorAction
    
    if ($healthExitCode -ne 0) {
        if ($InitialDeploy) {
            Write-Host "[INFO] Initial Deploy mode - health check warnings are expected" -ForegroundColor Yellow
        }
        else {
            Write-Host "[WARN] Health checks had issues" -ForegroundColor Yellow
        }
    }
    else {
        Write-Success "Health checks passed"
    }
}
else {
    Write-Host "[DRY RUN] Would run doctor_all" -ForegroundColor Magenta
}

Write-Section "STEP 6/6: DEPLOYMENT"
if ($SkipDeploy) {
    Write-Host "[INFO] Skipping deployment (-SkipDeploy)" -ForegroundColor Cyan
}
elseif (-not $DryRun) {
    $railwayCli = Get-Command railway -ErrorAction SilentlyContinue
    if (-not $railwayCli) {
        Write-Host "[WARN] Railway CLI not found. Install: npm i -g @railway/cli" -ForegroundColor Yellow
    }
    else {
        # Deploy API first
        Write-Host "[INFO] Deploying API service..." -ForegroundColor Cyan
        railway up --service dragonfly-api
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[ERROR] API deployment failed" -ForegroundColor Red
            exit 1
        }
        Write-Success "API deployed"

        # Deploy workers with liveness verification
        Write-Host "[INFO] Deploying workers with liveness verification..." -ForegroundColor Cyan
        $workerScript = Join-Path $RepoRoot "scripts\deploy_workers.ps1"
        & $workerScript -Service "dragonfly-workers" -Timeout 90 -MinWorkers 1 -Verbose
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[ERROR] Worker deployment or verification failed" -ForegroundColor Red
            exit 1
        }
        Write-Success "Workers deployed and verified"
    }
}
else {
    Write-Host "[DRY RUN] Would deploy API + workers with liveness verification" -ForegroundColor Magenta
}

Write-Section "SMOKE TESTS"
. (Join-Path $RepoRoot "scripts\load_env.ps1") -EnvPath $envFile -Mode $Mode
$env:SUPABASE_MODE = $Mode
if (-not $DryRun) {
    # Temporarily allow errors - smoke tests may write to stderr
    $prevErrorAction = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    
    & $PythonExe -m tools.smoke_intake --verbose 2>&1 | ForEach-Object { Write-Host $_ }
    $smokeExitCode = $LASTEXITCODE
    
    $ErrorActionPreference = $prevErrorAction
    
    if ($smokeExitCode -eq 0) {
        Write-Success "Smoke tests passed"
    }
    else {
        Write-Host "[WARN] Smoke test had issues" -ForegroundColor Yellow
    }
}
else {
    Write-Host "[DRY RUN] Would run smoke tests" -ForegroundColor Magenta
}

$duration = (Get-Date) - $startTime
$durationStr = "{0:mm\:ss}" -f $duration

Write-Host ""
Write-Host ("*" * 70) -ForegroundColor Green
Write-Host "     RELEASE CANDIDATE COMPLETE" -ForegroundColor Green
Write-Host ("*" * 70) -ForegroundColor Green
Write-Host "  Environment:  $($Mode.ToUpper())"
Write-Host "  Duration:     $durationStr"
Write-Host "  Release Tag:  release-$Timestamp"
Write-Host ""
