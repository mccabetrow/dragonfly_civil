"""Skip-trace vendor abstraction layer.

This module provides a clean interface for enrichment vendors,
allowing workers to switch between mock and real implementations.

Usage:
    from src.vendors import SkipTraceVendor, SkipTraceResult, MockIdiCORE

"""

from __future__ import annotations

from .base import SkipTraceResult, SkipTraceVendor
from .mock_idicore import MockIdiCORE

__all__ = [
    "SkipTraceResult",
    "SkipTraceVendor",
    "MockIdiCORE",
]
