import pytest

from backend.db import _classify_db_init_error


class DummyError(Exception):
    pass


@pytest.mark.parametrize(
    "message",
    [
        'FATAL: password authentication failed for user "service_role"',
        "FATAL:  password authentication failed for user",
        "FATAL:  server_login_retry=3, lockout imminent",
        'no pg_hba.conf entry for host "1.2.3.4"',
        "authentication failed for user",
        'role "missing_role" does not exist',
        'database "missing_db" does not exist',
    ],
)
def test_classifies_auth_failures(message: str) -> None:
    err = DummyError(message)
    assert _classify_db_init_error(err) == "auth_failure"


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
