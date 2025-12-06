# backend/asyncio_compat.py
"""
Windows asyncio compatibility helpers.

psycopg3 async connections are incompatible with the default ProactorEventLoop
on Windows. This module forces the older but compatible WindowsSelectorEventLoopPolicy
whenever we're on Windows.
"""

from __future__ import annotations

import asyncio
import sys


def ensure_selector_policy_on_windows() -> None:
    """
    Force WindowsSelectorEventLoopPolicy on Windows.

    psycopg3's async connections fail with ProactorEventLoop (Windows default).
    This function swaps to SelectorEventLoop policy which is compatible.

    Safe to call multiple times - only acts once if needed.
    """
    if not sys.platform.startswith("win"):
        return

    # Only swap if we are on the Proactor policy
    policy = asyncio.get_event_loop_policy()

    # Older Pythons expose WindowsProactorEventLoopPolicy; in 3.13 it's still there.
    proactor_cls = getattr(asyncio, "WindowsProactorEventLoopPolicy", None)
    selector_cls = getattr(asyncio, "WindowsSelectorEventLoopPolicy", None)

    if proactor_cls is None or selector_cls is None:
        return

    if isinstance(policy, proactor_cls):
        asyncio.set_event_loop_policy(selector_cls())
