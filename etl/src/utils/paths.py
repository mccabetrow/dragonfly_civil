"""Utilities for resolving project-relative paths."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

__all__ = ["repo_root", "data_dir", "AUTH_SESSION_PATH"]


def _discover_git_root(base: Path) -> Optional[Path]:
    for candidate in base.parents:
        if (candidate / ".git").exists():
            return candidate
    return None


@lru_cache(maxsize=1)
def repo_root() -> Path:
    """Return the absolute path to the repository root.

    The root is derived dynamically from the location of this module so that it
    works on both Windows and POSIX systems without relying on the current
    working directory.
    """

    resolved = Path(__file__).resolve()
    git_root = _discover_git_root(resolved)
    if git_root:
        return git_root
    return resolved.parents[3]


def data_dir() -> Path:
    """Return the ``data`` directory, creating it if necessary."""

    target = repo_root() / "data"
    target.mkdir(parents=True, exist_ok=True)
    return target


AUTH_SESSION_PATH: Path = repo_root() / "etl" / "src" / "auth" / "session.json"
"""Canonical path for persisted WebCivil session cookies."""
