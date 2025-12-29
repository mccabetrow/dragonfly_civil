<#
.SYNOPSIS
    Dual-mode status output helper for cross-version PowerShell compatibility.

.DESCRIPTION
    Outputs formatted status messages with icons that adapt to the PowerShell version:
    - PS 7+: Uses emoji icons (✅, ⚠️, ❌, ℹ️)
    - PS 5.x: Uses ASCII fallbacks ([OK], [WARN], [FAIL], [INFO])
    
    This eliminates mojibake (garbled characters) when running on legacy PowerShell.

.PARAMETER Message
    The status message to display.

.PARAMETER Level
    The status level: OK, WARN, FAIL, or INFO.

.PARAMETER NoNewLine
    If specified, does not append a newline after the message.

.EXAMPLE
    Write-Status -Level OK -Message "Tests passed"
    # PS7:  ✅ Tests passed
    # PS5:  [OK] Tests passed

.EXAMPLE
    Write-Status -Level FAIL -Message "Build failed" 
    # PS7:  ❌ Build failed
    # PS5:  [FAIL] Build failed
#>
function Write-Status {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true, Position = 0)]
        [string]$Message,

        [Parameter(Position = 1)]
        [ValidateSet("OK", "WARN", "FAIL", "INFO")]
        [string]$Level = "INFO",

        [switch]$NoNewLine
    )

    # Detect PowerShell version for icon selection
    $useLegacy = $PSVersionTable.PSVersion.Major -lt 7

    # Icon mapping based on version
    $iconMap = @{
        OK   = if ($useLegacy) { "[OK]" } else { [char]::ConvertFromUtf32(0x2705) }      # ✅
        WARN = if ($useLegacy) { "[WARN]" } else { [char]::ConvertFromUtf32(0x26A0) + [char]::ConvertFromUtf32(0xFE0F) }  # ⚠️
        FAIL = if ($useLegacy) { "[FAIL]" } else { [char]::ConvertFromUtf32(0x274C) }    # ❌
        INFO = if ($useLegacy) { "[INFO]" } else { [char]::ConvertFromUtf32(0x2139) + [char]::ConvertFromUtf32(0xFE0F) }  # ℹ️
    }

    # Color mapping
    $colorMap = @{
        OK   = "Green"
        WARN = "Yellow"
        FAIL = "Red"
        INFO = "Cyan"
    }

    $icon = $iconMap[$Level]
    $color = $colorMap[$Level]

    $params = @{
        Object          = "$icon $Message"
        ForegroundColor = $color
        NoNewline       = $NoNewLine.IsPresent
    }

    Write-Host @params
}

<#
.SYNOPSIS
    Write a section banner with version-adaptive formatting.

.PARAMETER Message
    The banner message.

.PARAMETER Color
    The foreground color for the banner.

.PARAMETER Width
    The width of the banner line (default 70).
#>
function Write-StatusBanner {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true, Position = 0)]
        [string]$Message,

        [Parameter(Position = 1)]
        [string]$Color = "Cyan",

        [Parameter()]
        [int]$Width = 70
    )

    Write-Host ""
    Write-Host ("=" * $Width) -ForegroundColor $Color
    Write-Host "  $Message" -ForegroundColor $Color
    Write-Host ("=" * $Width) -ForegroundColor $Color
    Write-Host ""
}

<#
.SYNOPSIS
    Write a step start marker with consistent formatting.

.PARAMETER Step
    The step identifier (e.g., "DB-CONNECT").

.PARAMETER Description
    A brief description of the step.
#>
function Write-StepStart {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true, Position = 0)]
        [string]$Step,

        [Parameter(Mandatory = $true, Position = 1)]
        [string]$Description
    )

    Write-Host "[$Step] $Description" -ForegroundColor Yellow
    Write-Host ("-" * 50) -ForegroundColor DarkGray
}

<#
.SYNOPSIS
    Write a step pass status with version-adaptive icon.

.PARAMETER Step
    The step identifier that passed.
#>
function Write-StepPass {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true, Position = 0)]
        [string]$Step
    )

    Write-Status -Level OK -Message "[$Step] PASSED"
    Write-Host ""
}

<#
.SYNOPSIS
    Write a step warning status with version-adaptive icon.

.PARAMETER Step
    The step identifier with a warning.

.PARAMETER Reason
    The reason for the warning.
#>
function Write-StepWarn {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true, Position = 0)]
        [string]$Step,

        [Parameter(Mandatory = $true, Position = 1)]
        [string]$Reason
    )

    Write-Status -Level WARN -Message "[$Step] WARNING: $Reason"
    Write-Host ""
}

<#
.SYNOPSIS
    Write a step failure status with version-adaptive icon.

.PARAMETER Step
    The step identifier that failed.

.PARAMETER Reason
    The reason for the failure.
#>
function Write-StepFail {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true, Position = 0)]
        [string]$Step,

        [Parameter(Mandatory = $true, Position = 1)]
        [string]$Reason
    )

    Write-Status -Level FAIL -Message "[$Step] FAILED: $Reason"
    Write-Host ""
}

# Note: Export-ModuleMember only works when loaded as a module (.psm1)
# When dot-sourced, functions are automatically available in the caller's scope
