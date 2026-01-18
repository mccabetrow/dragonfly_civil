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

function Mask-OutputLine {
    [CmdletBinding()]
    param(
        [string]$Line
    )

    if ([string]::IsNullOrWhiteSpace($Line)) {
        return $Line
    }

    $masked = $Line

    $dsnPattern = '(?i)postgres(?:ql)?://\S+'
    $masked = [regex]::Replace($masked, $dsnPattern, {
            param($match)
            Mask-SensitiveValue -Value $match.Value
        })

    $secretKeys = 'DATABASE_URL|SUPABASE_DB_URL|SUPABASE_SERVICE_ROLE_KEY|SUPABASE_ANON_KEY|SUPABASE_JWT_SECRET|OPENAI_API_KEY|AZURE_OPENAI_API_KEY|ANTHROPIC_API_KEY|RAILWAY_TOKEN|SUPABASE_ACCESS_TOKEN'
    $kvPattern = "(?i)\b($secretKeys)\b\s*[:=]\s*([^\s]+)"
    $masked = [regex]::Replace($masked, $kvPattern, {
            param($match)
            "{0}={1}" -f $match.Groups[1].Value, (Mask-SensitiveValue -Value $match.Groups[2].Value)
        })

    return $masked
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

    if ([string]::IsNullOrWhiteSpace([string]$data.env)) {
        throw "whoami payload missing env"
    }
    if ([string]::IsNullOrWhiteSpace([string]$data.sha_short)) {
        throw "whoami payload missing sha_short"
    }
    if ($null -eq $data.database_ready) {
        throw "whoami payload missing database_ready"
    }

    return [pscustomobject]@{
        Env           = [string]$data.env
        ShaShort      = [string]$data.sha_short
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

Export-ModuleMember -Function Mask-SensitiveValue, Mask-OutputLine, Test-RailwayFallbackHeader, Parse-WhoAmIJson, Get-ProdGatePythonPath
