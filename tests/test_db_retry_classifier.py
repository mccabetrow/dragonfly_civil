import pytest

from backend.db import _classify_db_init_error


class DummyError(Exception):
    pass


# ═══════════════════════════════════════════════════════════════════════════
# LOCKOUT ERRORS - server_login_retry / query_wait_timeout
# These trigger the circuit breaker (15-min backoff or worker exit)
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    "message",
    [
        "FATAL:  server_login_retry=3, lockout imminent",
        "server_login_retry exceeded, connection rejected",
        "query_wait_timeout: pool exhausted",
        "connection pool exhausted: query_wait_timeout",
    ],
)
def test_classifies_lockout_errors(message: str) -> None:
    """Lockout errors trigger circuit breaker - 15-min backoff or worker exit."""
    err = DummyError(message)
    assert _classify_db_init_error(err) == "lockout"


# ═══════════════════════════════════════════════════════════════════════════
# AUTH FAILURES - password/role issues that warrant kill-switch
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    "message",
    [
        'FATAL: password authentication failed for user "service_role"',
        "FATAL:  password authentication failed for user",
        'no pg_hba.conf entry for host "1.2.3.4"',
        "authentication failed for user",
        'role "missing_role" does not exist',
    ],
)
def test_classifies_auth_failures(message: str) -> None:
    err = DummyError(message)
    assert _classify_db_init_error(err) == "auth_failure"


def test_classifies_missing_database_as_other() -> None:
    """Missing database is 'other' not 'auth_failure' - may be transient in provisioning."""
    err = DummyError('database "missing_db" does not exist')
    # Missing database is not an auth failure - it's a config issue that might be
    # transient during database provisioning, so we classify as 'other'
    assert _classify_db_init_error(err) == "other"


@pytest.mark.parametrize(
    "message",
    [
        "could not connect to server: Connection refused",
        "connection timed out",
        "timeout expired",
        "network is unreachable",
        'could not translate host name "db.internal" to address: Name or service not known',
    ],
)
def test_classifies_network_errors(message: str) -> None:
    err = DummyError(message)
    assert _classify_db_init_error(err) == "network"


@pytest.mark.parametrize(
    "message",
    [
        'syntax error at or near "SELECT"',
        "unexpected error occurred",
        "some random failure message",
    ],
)
def test_classifies_other_errors(message: str) -> None:
    err = DummyError(message)
    assert _classify_db_init_error(err) == "other"
