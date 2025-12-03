"""
Dragonfly Engine - Core Module

Contains security, configuration extensions, and shared utilities.
"""

from .security import AuthContext, get_current_user, require_auth

__all__ = ["AuthContext", "get_current_user", "require_auth"]
