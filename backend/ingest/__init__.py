# backend/ingest/__init__.py
"""
Ingest Module - North Star Architecture

This module implements the canonical ingest pipeline for Dragonfly.

Architecture:
    - Vercel (UI): Read-Only via authenticated role
    - Railway (API/Worker): Sole Writer via service_role

Components:
    - IngestContract: The "Law" - defines validation rules
    - IngestLogger: Full traceability via ops.ingest_audit_log
    - IngestService: Idempotent file processing

Usage:
    from backend.ingest import IngestContract, IngestLogger, IngestService
"""

from backend.ingest.contract import (
    IngestContract,
    IngestEvent,
    IngestLogger,
    IngestStage,
    compute_dedup_key,
    compute_file_hash,
    validate_row,
)

__all__ = [
    "IngestContract",
    "IngestLogger",
    "IngestStage",
    "IngestEvent",
    "validate_row",
    "compute_file_hash",
    "compute_dedup_key",
]
