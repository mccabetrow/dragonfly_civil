param()

$ErrorActionPreference = 'Stop'

try {
    & python -m tools.smoke
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}
catch {
    Write-Error $_
    exit 1
}
