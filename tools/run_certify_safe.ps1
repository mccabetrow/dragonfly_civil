# tools/run_certify_safe.ps1

Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "   DRAGONFLY PRODUCTION CERTIFICATION (SAFE MODE)"       -ForegroundColor Cyan
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "This script will temporarily set production environment variables"
Write-Host "for the current session only. Credentials are masked."
Write-Host ""

# 1. Helper Function to Read Secure Input
function Get-SecureInput {
    param([string]$Prompt)
    $secureString = Read-Host -Prompt $Prompt -AsSecureString
    $bstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureString)
    try {
        return [System.Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    }
    finally {
        [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
}

# 2. Clear Existing Interference
$varsToClear = @("ENV_FILE", "SUPABASE_DB_URL", "DATABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_ANON_KEY")
foreach ($var in $varsToClear) {
    if (Test-Path Env:\$var) {
        Remove-Item Env:\$var -ErrorAction SilentlyContinue
    }
}

try {
    # 3. Prompt for Credentials (Masked)
    Write-Host "Please enter credentials (input will be masked):" -ForegroundColor Yellow
    
    $rawPassword = Get-SecureInput -Prompt "Enter DB Password (Raw)"
    if ([string]::IsNullOrWhiteSpace($rawPassword)) {
        throw "Password cannot be empty."
    }

    $anonKey = Get-SecureInput -Prompt "Enter Supabase Anon Key"
    if ([string]::IsNullOrWhiteSpace($anonKey)) {
        throw "Anon Key cannot be empty."
    }

    $serviceKey = Get-SecureInput -Prompt "Enter Supabase Service Role Key"
    if ([string]::IsNullOrWhiteSpace($serviceKey)) {
        throw "Service Role Key cannot be empty."
    }

    # 4. URL Encode Password (Powershell .NET method)
    # This handles special chars like @, !, %, etc. safely
    $encodedPassword = [System.Net.WebUtility]::UrlEncode($rawPassword)

    # 5. Construct DSN
    # HARDCODED: Production Project Ref based on your requirement (iaketsyhmqbwaabgykux)
    $prodHost = "db.iaketsyhmqbwaabgykux.supabase.co"
    $prodPort = "6543"
    $prodUser = "dragonfly_app" # Can change to 'postgres' if you haven't migrated yet
    
    $dsn = "postgresql://$($prodUser):$($encodedPassword)@$($prodHost):$($prodPort)/postgres?sslmode=require"

    Write-Host "`nGenerated DSN for: $prodUser @ $prodHost" -ForegroundColor Gray

    # 6. Set Environment Variables (Process Scope Only)
    $env:DATABASE_URL = $dsn
    $env:SUPABASE_DB_URL = $dsn # Set both for compatibility
    $env:ENVIRONMENT = "prod"
    $env:SUPABASE_MODE = "prod"
    $env:ENV = "prod"
    $env:SUPABASE_URL = "https://iaketsyhmqbwaabgykux.supabase.co"
    $env:SUPABASE_ANON_KEY = $anonKey
    $env:SUPABASE_SERVICE_ROLE_KEY = $serviceKey

    # 7. Execute Certification
    Write-Host "`n🚀 Launching Certification Tool..." -ForegroundColor Green
    Write-Host "--------------------------------------------------------"
    
    # Run the Python module
    $prodUrl = "https://dragonfly-api-production.up.railway.app"
    python -m tools.certify_prod --url $prodUrl --env prod
    
    # Capture exit code
    $exitCode = $LASTEXITCODE

}
catch {
    Write-Host "`n🛑 Error: $_" -ForegroundColor Red
    $exitCode = 1
}
finally {
    # 8. Cleanup (CRITICAL)
    Write-Host "`n🧹 Cleaning up sensitive environment variables..." -ForegroundColor Cyan
    
    Remove-Item Env:\DATABASE_URL -ErrorAction SilentlyContinue
    Remove-Item Env:\SUPABASE_DB_URL -ErrorAction SilentlyContinue
    Remove-Item Env:\SUPABASE_ANON_KEY -ErrorAction SilentlyContinue
    Remove-Item Env:\SUPABASE_SERVICE_ROLE_KEY -ErrorAction SilentlyContinue
    
    # Clear variables from memory
    $rawPassword = $null
    $encodedPassword = $null
    $dsn = $null
    $anonKey = $null
    $serviceKey = $null
    
    # Force Garbage Collection to clear strings from RAM
    [System.GC]::Collect()

    if ($exitCode -eq 0) {
        Write-Host "✅ Done. Environment is clean." -ForegroundColor Green
    }
    else {
        Write-Host "⚠️ Done with errors. Environment is clean." -ForegroundColor Yellow
    }
}
