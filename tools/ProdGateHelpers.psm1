Set-StrictMode -Version Latest

function Mask-SensitiveValue {
    [CmdletBinding()]
    param(
        [string]$Value
    )

    if ([string]::IsNullOrWhiteSpace($Value)) {
        return ''
    }

    $trimmed = $Value.Trim()
    if ($trimmed.Length -le 4) {
        return '****'
    }

    $dsnPattern = '^(?<proto>[^:]+://)(?<creds>[^@]+)@(?<rest>.+)$'
    if ($trimmed -match $dsnPattern) {
        $proto = $Matches['proto']
        $rest = $Matches['rest']
        return "${proto}****@${rest}"
    }

    $start = $trimmed.Substring(0, [Math]::Min(4, $trimmed.Length))
    $end = $trimmed.Substring($trimmed.Length - [Math]::Min(2, $trimmed.Length))
    return "$start***$end"
}

function Test-RailwayFallbackHeader {
    [CmdletBinding()]
    param(
        [Parameter(ValueFromPipeline)]
        [object]$Headers
    )

    if (-not $Headers) {
        return $false
    }

    $value = $Headers['X-Railway-Fallback']
    if (-not $value) {
        return $false
    }

    return ($value.ToString().Trim().ToLowerInvariant() -eq 'true')
}

function Parse-WhoAmIJson {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$Json
    )

    if ([string]::IsNullOrWhiteSpace($Json)) {
        throw "whoami payload is empty"
    }

    try {
        $data = $Json | ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        throw "Unable to parse whoami payload: $($_.Exception.Message)"
    }

    return [pscustomobject]@{
        DatabaseReady = [bool]$data.database_ready
        DsnIdentity   = [string]$data.dsn_identity
    }
}

function Get-ProdGatePythonPath {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$WorkspaceRoot
    )

    $venvPython = Join-Path -Path $WorkspaceRoot -ChildPath '.venv/Scripts/python.exe'
    if (Test-Path $venvPython) {
        return (Resolve-Path $venvPython).Path
    }

    $pythonCmd = Get-Command python -ErrorAction Stop
    return $pythonCmd.Source
}

Export-ModuleMember -Function Mask-SensitiveValue, Test-RailwayFallbackHeader, Parse-WhoAmIJson, Get-ProdGatePythonPath
