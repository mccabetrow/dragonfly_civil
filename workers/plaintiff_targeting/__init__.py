"""
Plaintiff Targeting Worker

Transforms raw judgments into scored, prioritized plaintiff leads.
"""

from .main import main, run, run_sync

__all__ = ["main", "run", "run_sync"]
