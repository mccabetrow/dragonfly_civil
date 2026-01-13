"""Thread-safe context helpers for request-scoped metadata."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Iterator, Optional

_request_id: ContextVar[Optional[str]] = ContextVar("request_id", default=None)


def get_request_id() -> Optional[str]:
    """Return the current request ID, if any."""
    return _request_id.get()


def set_request_id(request_id: Optional[str]) -> Token:
    """Set the current request ID and return the context token."""
    return _request_id.set(request_id)


def reset_request_id(token: Token | None = None) -> None:
    """Reset the request ID context using the provided token or clear it."""
    if token is not None:
        _request_id.reset(token)
    else:
        _request_id.set(None)


@contextmanager
def request_id_context(request_id: Optional[str]) -> Iterator[None]:
    """Context manager that ensures the request ID is restored afterwards."""
    token = set_request_id(request_id)
    try:
        yield
    finally:
        reset_request_id(token)


__all__ = [
    "get_request_id",
    "reset_request_id",
    "request_id_context",
    "set_request_id",
]
