<#
.SYNOPSIS
    Safe Python Execution Template for PowerShell
.DESCRIPTION
    Demonstrates the "Here-String" pattern for executing complex Python code
    within PowerShell without quoting/escaping issues.
    
    CRITICAL: The closing "@ must be at column 0 (no indentation).
.EXAMPLE
    .\scripts\safe_python_template.ps1
#>

[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

# ============================================================================
# STEP 1: Define the Python script using Here-String
# ============================================================================
# The @" ... "@ syntax preserves:
#   - Indentation
#   - Quotes (single and double)
#   - Special characters
#   - Multi-line structure
#
# CRITICAL: The closing "@ MUST be at column 0 (start of line, no spaces)
# ============================================================================

# Using @' ... '@ (literal here-string) since we don't need PowerShell variable expansion
# Use @" ... "@ if you need to embed $env:VARNAME or other PS variables
$PyScript = @'
import sys
import os

def main():
    """Complex logic with quotes and indentation is now safe."""
    try:
        print(f"Running in: {sys.executable}")
        print(f"Python version: {sys.version}")
        
        # Example: Check for error condition
        if os.environ.get("SEVERE_ERROR"):
            print("SEVERE_ERROR detected in environment")
            sys.exit(1)
        
        # Example: Complex string with quotes
        message = "This has 'single' and \"double\" quotes"
        print(f"Message: {message}")
        
        # Example: Dictionary with complex structure
        config = {
            "name": "dragonfly",
            "version": "1.0.0",
            "features": ["intake", "enforcement", "analytics"]
        }
        print(f"Config: {config}")
        
        print("Python executed safely.")
        sys.exit(0)
        
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
'@

# ============================================================================
# STEP 2: Detect Python Virtual Environment
# ============================================================================

function Get-PythonExecutable {
    $locations = @(
        ".\.venv\Scripts\python.exe",
        ".\venv\Scripts\python.exe",
        ".\.env\Scripts\python.exe"
    )
    
    foreach ($loc in $locations) {
        if (Test-Path $loc) {
            return $loc
        }
    }
    
    # Fallback to system Python
    return "python"
}

$PyCmd = Get-PythonExecutable
Write-Host "Using Python: $PyCmd" -ForegroundColor Cyan

# ============================================================================
# STEP 3: Execute with proper error handling
# ============================================================================

# IMPORTANT: PowerShell 5.1 mangles quotes when passing to -c directly.
# Solution: Pipe the script to Python's stdin using the '-' argument.

try {
    # Pipe script to stdin - this preserves all quotes and special characters
    $output = $PyScript | & $PyCmd - 2>&1
    $exitCode = $LASTEXITCODE
    
    # Display output
    $output | ForEach-Object {
        if ($_ -is [System.Management.Automation.ErrorRecord]) {
            Write-Host $_.Exception.Message -ForegroundColor Red
        }
        else {
            Write-Host $_
        }
    }
    
    # Check exit code
    if ($exitCode -ne 0) {
        Write-Error "Python script failed with exit code $exitCode"
        exit $exitCode
    }
    
    Write-Host "`nScript completed successfully" -ForegroundColor Green
    
}
catch {
    Write-Error "Failed to execute Python script: $_"
    exit 1
}

# ============================================================================
# PATTERN SUMMARY
# ============================================================================
<#
The Here-String + Stdin Pattern (PowerShell 5.1 Safe):

1. Define Python code using LITERAL here-string (no PS variable expansion):
   $PyScript = @'
   import sys
   print("Quotes are preserved!")
   '@

   Or use EXPANDABLE here-string if you need PS variables:
   $PyScript = @"
   import os
   path = "$($env:USERPROFILE)"
   "@

2. CRITICAL: The closing '@ or "@ MUST be at column 0 (no indentation)

3. Execute by PIPING to stdin (avoids quote-mangling):
   $PyScript | & $PyCmd -
   
   DO NOT USE: & $PyCmd -c $PyScript  # Quotes get stripped in PS 5.1!

4. Check result:
   if ($LASTEXITCODE -ne 0) { exit 1 }

Common Mistakes:
- Indenting the closing '@  -> BROKEN
- Using -c instead of piping to stdin -> Quotes stripped
- Not checking $LASTEXITCODE -> Silent failures
- Using @" when you have $ in Python f-strings -> PS tries to expand them
#>
