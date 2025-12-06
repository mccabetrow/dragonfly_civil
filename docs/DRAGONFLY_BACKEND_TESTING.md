# Dragonfly Civil — Backend Testing Guide

> **Version:** 1.0 | **Last Updated:** December 2025

---

## Overview

This document describes the testing strategy, tools, and conventions for the Dragonfly Civil backend.

---

## Test Stack

| Component     | Tool                            | Purpose                      |
| ------------- | ------------------------------- | ---------------------------- |
| Test Runner   | `pytest`                        | Test discovery and execution |
| Fixtures      | `pytest` fixtures               | Shared test setup            |
| API Testing   | `fastapi.testclient.TestClient` | Synchronous API testing      |
| Mocking       | `unittest.mock`, `monkeypatch`  | Dependency isolation         |
| Type Checking | `mypy`                          | Static type verification     |
| Linting       | `ruff`, `black`, `isort`        | Code style enforcement       |

---

## Running Tests

### Basic Commands

```powershell
# Run all tests
$env:SUPABASE_MODE = 'dev'
.\.venv\Scripts\python.exe -m pytest

# Run with verbose output
.\.venv\Scripts\python.exe -m pytest -v

# Run specific test file
.\.venv\Scripts\python.exe -m pytest tests/test_api_auth.py

# Run specific test class
.\.venv\Scripts\python.exe -m pytest tests/test_api_auth.py::TestCORSConfiguration

# Run integration tests only
.\.venv\Scripts\python.exe -m pytest -m integration
```

### VS Code Tasks

The workspace includes pre-configured tasks:

- **Tests: PyTest** — Run all tests quietly
- **Dev: Full Test Suite** — Full pytest run with dev environment

---

## Test Categories

### 1. Unit Tests

Pure Python logic without database or network dependencies.

```python
def test_compute_tier():
    """Test tier calculation logic."""
    tier = compute_tier(score=85.0, judgment_amount=10000.0)
    assert tier == "A"
```

### 2. API Tests

Test FastAPI endpoints using `TestClient`.

```python
@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("DRAGONFLY_API_KEY", "test-key")
    from backend.main import create_app
    app = create_app()
    return TestClient(app, raise_server_exceptions=False)

def test_health_endpoint(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
```

### 3. Integration Tests

Tests that hit real Supabase dev database. Marked with `@pytest.mark.integration`.

```python
@pytest.mark.integration
def test_create_offer_persists(db_url):
    """Test that offer creation writes to database."""
    # ... test logic
```

---

## Test Environment

### Environment Variables

Tests run against the **dev** Supabase environment by default.

```python
# tests/conftest.py sets this automatically
def pytest_configure(config):
    if "SUPABASE_MODE" not in os.environ:
        os.environ["SUPABASE_MODE"] = "dev"
```

### Required Variables

| Variable            | Source          | Purpose             |
| ------------------- | --------------- | ------------------- |
| `SUPABASE_MODE`     | Set by conftest | `dev` for tests     |
| `SUPABASE_DB_URL`   | `.env`          | Database connection |
| `DRAGONFLY_API_KEY` | Monkeypatched   | API auth testing    |

---

## Test Fixtures

### Shared Fixtures (`tests/conftest.py`)

```python
@pytest.fixture
def supabase_client():
    """Provides a Supabase client for tests."""
    if not _has_db_connection():
        pytest.skip("Database connection not available")
    return create_supabase_client()

@pytest.fixture
def test_env():
    """Ensures SUPABASE_MODE is set."""
    original = os.environ.get("SUPABASE_MODE")
    if not original:
        os.environ["SUPABASE_MODE"] = "dev"
    yield os.environ.get("SUPABASE_MODE")
```

### Skip Decorators

```python
from tests.conftest import skip_if_no_db

@skip_if_no_db
def test_database_query():
    """Skips if database not available."""
    pass
```

---

## FCRA Compliance in Tests

### Cleanup Helpers

FCRA triggers block DELETE on sensitive tables. Use cleanup helpers:

```python
def _cleanup_plaintiff_data(conn, plaintiff_ids):
    """Clean up with FCRA trigger bypass."""
    with conn.cursor() as cur:
        # Disable trigger
        cur.execute(
            "ALTER TABLE public.plaintiff_contacts "
            "DISABLE TRIGGER trg_plaintiff_contacts_block_delete"
        )
        try:
            cur.execute("DELETE FROM public.plaintiff_contacts WHERE plaintiff_id = ANY(%s)", (plaintiff_ids,))
            cur.execute("DELETE FROM public.plaintiffs WHERE id = ANY(%s)", (plaintiff_ids,))
        finally:
            # Re-enable trigger
            cur.execute(
                "ALTER TABLE public.plaintiff_contacts "
                "ENABLE TRIGGER trg_plaintiff_contacts_block_delete"
            )
```

---

## CORS Testing

### Production Origins

Tests verify actual production origins, not just localhost:

```python
class TestCORSConfiguration:
    PROD_ORIGIN = "https://dragonfly-console1.vercel.app"
    PROD_ORIGIN_GIT = "https://dragonfly-console1-git-main-mccabetrow.vercel.app"
    PREVIEW_ORIGIN = "https://dragonfly-console1-hkyvsyq2h.vercel.app"

    def test_cors_preflight_prod_origin(self, cors_client):
        response = cors_client.options(
            "/api/health",
            headers={
                "Origin": self.PROD_ORIGIN,
                "Access-Control-Request-Method": "GET",
            },
        )
        assert response.status_code == 200
        assert response.headers.get("Access-Control-Allow-Origin") == self.PROD_ORIGIN
```

---

## Mocking Patterns

### Monkeypatch Environment

```python
def test_with_api_key(monkeypatch):
    monkeypatch.setenv("DRAGONFLY_API_KEY", "test-key-12345")
    # ... test logic
```

### Mock Supabase Client

```python
class FakeClient:
    def table(self, name):
        return FakeTable(name)

def test_doctor_cli(monkeypatch):
    fake_client = FakeClient()
    monkeypatch.setattr(doctor, "create_supabase_client", lambda: fake_client)
```

### Clear Settings Cache

```python
def test_with_fresh_settings(monkeypatch):
    monkeypatch.setenv("DRAGONFLY_CORS_ORIGINS", "https://example.com")
    from backend.config import get_settings
    get_settings.cache_clear()
    # Now create app with fresh settings
```

---

## Pre-Commit Hooks

The project uses pre-commit hooks that run on every commit:

```yaml
# .pre-commit-config.yaml
- black # Code formatting
- ruff # Fast linting
- isort # Import sorting
- mypy # Type checking
```

### Running Manually

```powershell
# Run all hooks
pre-commit run --all-files

# Run specific hook
pre-commit run mypy --all-files
```

---

## Debugging Failed Tests

### 1. Check Environment

```powershell
$env:SUPABASE_MODE
# Should output: dev
```

### 2. Run Single Test Verbose

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_offers.py::TestOffersAPI::test_create_offer_happy_path -v -s
```

### 3. Check Database Connection

```powershell
.\.venv\Scripts\python.exe -m tools.doctor --env dev
```

### 4. Review Test Logs

```powershell
.\.venv\Scripts\python.exe -m pytest --tb=long
```

---

## CI/CD Integration

Tests run automatically on:

- Pre-commit hooks (local)
- GitHub Actions (planned)
- Railway deploy checks

---

## Best Practices

1. **Always use `SUPABASE_MODE=dev`** for tests
2. **Clean up test data** — Don't leave test rows in database
3. **Use fixtures** — Share setup logic via `conftest.py`
4. **Mark integration tests** — Use `@pytest.mark.integration`
5. **Mock external services** — Don't call real APIs in unit tests
6. **Test error paths** — Verify 4xx/5xx responses
7. **Clear caches** — Call `get_settings.cache_clear()` when changing env vars

---

_For questions, contact Engineering via Slack `#dragonfly-ops`._
