Set-StrictMode -Version Latest

$modulePath = Join-Path -Path (Split-Path -Parent $PSScriptRoot) -ChildPath 'ProdGateHelpers.psm1'
Import-Module $modulePath -Force

Describe 'Mask-SensitiveValue' {
    It 'masks long tokens' {
        (Mask-SensitiveValue -Value 'abcdefghijklmno') | Should Be 'abcd***no'
    }

    It 'masks DSN credentials' {
        $dsn = 'postgresql://postgres:super-secret@db.supabase.co:5432/postgres'
        (Mask-SensitiveValue -Value $dsn) | Should Be 'postgresql://****@db.supabase.co:5432/postgres'
    }

    It 'handles empty strings' {
        (Mask-SensitiveValue -Value '') | Should Be ''
    }
}

Describe 'Test-RailwayFallbackHeader' {
    It 'detects fallback header' {
        $headers = @{ 'X-Railway-Fallback' = 'true' }
        (Test-RailwayFallbackHeader -Headers $headers) | Should Be $true
    }

    It 'ignores missing header' {
        (Test-RailwayFallbackHeader -Headers @{}) | Should Be $false
    }
}

Describe 'Parse-WhoAmIJson' {
    It 'parses valid payload' {
        $payload = '{"database_ready": true, "dsn_identity": "postgresql://user:pass@host/db"}'
        $result = Parse-WhoAmIJson -Json $payload
        $result.DatabaseReady | Should Be $true
        $result.DsnIdentity | Should Be 'postgresql://user:pass@host/db'
    }

    It 'throws on invalid json' {
        { Parse-WhoAmIJson -Json 'not-json' } | Should Throw
    }
}
