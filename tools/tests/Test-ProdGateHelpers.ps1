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

Describe 'Mask-OutputLine' {
    It 'masks DSNs embedded in output' {
        $line = 'DATABASE_URL=postgresql://user:super-secret@db.supabase.co:5432/postgres'
        (Mask-OutputLine -Line $line) | Should Be 'DATABASE_URL=postgresql://****@db.supabase.co:5432/postgres'
    }

    It 'masks known secret keys' {
        $line = 'SUPABASE_SERVICE_ROLE_KEY=super-secret-token'
        (Mask-OutputLine -Line $line) | Should Be 'SUPABASE_SERVICE_ROLE_KEY=supe***en'
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
        $payload = '{"database_ready": true, "dsn_identity": "postgresql://user:pass@host/db", "env": "prod", "sha_short": "abc123"}'
        $result = Parse-WhoAmIJson -Json $payload
        $result.DatabaseReady | Should Be $true
        $result.DsnIdentity | Should Be 'postgresql://user:pass@host/db'
        $result.Env | Should Be 'prod'
        $result.ShaShort | Should Be 'abc123'
    }

    It 'throws on invalid json' {
        { Parse-WhoAmIJson -Json 'not-json' } | Should Throw
    }

    It 'throws when env is missing' {
        $payload = '{"database_ready": true, "sha_short": "abc123"}'
        { Parse-WhoAmIJson -Json $payload } | Should Throw
    }

    It 'throws when sha_short is missing' {
        $payload = '{"database_ready": true, "env": "prod"}'
        { Parse-WhoAmIJson -Json $payload } | Should Throw
    }

    It 'throws when database_ready is missing' {
        $payload = '{"env": "prod", "sha_short": "abc123"}'
        { Parse-WhoAmIJson -Json $payload } | Should Throw
    }
}
