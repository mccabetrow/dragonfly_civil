"""Bridge module to insert rows into core_judgments from legacy importers.

This module provides helpers to:
1. Normalize and transform legacy judgment data to core_judgments schema
2. Idempotently insert into core_judgments using ON CONFLICT
3. Log ETL runs to import_runs table

The core_judgments table has a trigger (trg_core_judgments_enqueue_enrich) that
automatically enqueues judgment_enrich jobs when rows are inserted, so the
enrichment pipeline starts automatically.

Usage:
    from etl.src.importers.core_judgment_bridge import CoreJudgmentBridge

    bridge = CoreJudgmentBridge(conn)
    inserted = bridge.insert_judgment(
        case_index_number="NYC-2024-001234",
        debtor_name="John Doe",
        original_creditor="ABC Corp",
        judgment_date=date(2024, 1, 15),
        principal_amount=Decimal("5000.00"),
        court_name="Supreme Court",
        county="New York",
    )
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CoreJudgmentInsertResult:
    """Result of a core_judgment insert operation."""

    judgment_id: Optional[str] = None
    inserted: bool = False
    skipped: bool = False
    error: Optional[str] = None


@dataclass
class CoreJudgmentBridgeStats:
    """Statistics for a bridge session."""

    total_attempts: int = 0
    inserted: int = 0
    skipped_existing: int = 0
    errors: int = 0
    error_details: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Normalization helpers (aligned with ingest_judgments.py)
# ---------------------------------------------------------------------------


def _clean(value: Any) -> str:
    """Normalize a cell value to a stripped string."""
    if value is None:
        return ""
    return str(value).strip()


def _parse_amount(raw: Any) -> Optional[float]:
    """Parse a currency/decimal string to a float, or None if empty/invalid."""
    cleaned = _clean(raw)
    if not cleaned:
        return None
    try:
        # Remove currency symbols and commas
        normalized = cleaned.replace("$", "").replace(",", "").replace(" ", "")
        return float(Decimal(normalized))
    except (InvalidOperation, ValueError):
        return None


def _parse_date(raw: Any) -> Optional[date]:
    """Parse a date string to a date object, supporting YYYY-MM-DD and MM/DD/YYYY."""
    if isinstance(raw, date):
        return raw
    if isinstance(raw, datetime):
        return raw.date()

    cleaned = _clean(raw)
    if not cleaned:
        return None

    # Try ISO format first (YYYY-MM-DD)
    try:
        return date.fromisoformat(cleaned)
    except ValueError:
        pass

    # Try MM/DD/YYYY explicitly
    try:
        parts = cleaned.split("/")
        if len(parts) == 3:
            month, day, year = int(parts[0]), int(parts[1]), int(parts[2])
            return date(year, month, day)
    except (ValueError, IndexError):
        pass

    # Try DD/MM/YYYY as fallback
    try:
        parts = cleaned.split("/")
        if len(parts) == 3:
            day, month, year = int(parts[0]), int(parts[1]), int(parts[2])
            if month <= 12:
                return date(year, month, day)
    except (ValueError, IndexError):
        pass

    return None


def _normalize_case_index(raw: Any) -> Optional[str]:
    """Normalize a case index number."""
    cleaned = _clean(raw)
    if not cleaned:
        return None
    # Remove excessive whitespace, keep structure
    normalized = re.sub(r"\s+", " ", cleaned).upper()
    return normalized


class CoreJudgmentBridge:
    """Bridge to insert judgments into core_judgments from legacy importers.

    The bridge provides idempotent inserts using ON CONFLICT on case_index_number.
    Each insert fires the trigger that enqueues a judgment_enrich job.
    """

    def __init__(self, conn: psycopg.Connection):
        self._conn = conn
        self.stats = CoreJudgmentBridgeStats()

    def insert_judgment(
        self,
        *,
        case_index_number: str,
        debtor_name: Optional[str] = None,
        original_creditor: Optional[str] = None,
        judgment_date: Optional[date] = None,
        principal_amount: Optional[Decimal] = None,
        court_name: Optional[str] = None,
        county: Optional[str] = None,
        interest_rate: Optional[Decimal] = None,
    ) -> CoreJudgmentInsertResult:
        """Insert a single judgment into core_judgments.

        This is idempotent - if a row with the same case_index_number exists,
        the insert is skipped and the existing ID is returned.

        Args:
            case_index_number: Court-assigned docket/index number (required, unique key)
            debtor_name: Primary debtor name
            original_creditor: Original judgment creditor
            judgment_date: Date judgment was entered
            principal_amount: Original judgment amount
            court_name: Full court name
            county: NY county
            interest_rate: Interest rate (default 9.0 in DB)

        Returns:
            CoreJudgmentInsertResult with judgment_id and insert status.
        """
        self.stats.total_attempts += 1
        result = CoreJudgmentInsertResult()

        # Normalize case index
        normalized_index = _normalize_case_index(case_index_number)
        if not normalized_index:
            result.error = "case_index_number is required"
            self.stats.errors += 1
            self.stats.error_details.append(result.error)
            return result

        # Normalize dates
        parsed_date = _parse_date(judgment_date) if judgment_date else None

        # Normalize amount
        parsed_amount = None
        if principal_amount is not None:
            if isinstance(principal_amount, Decimal):
                parsed_amount = float(principal_amount)
            else:
                parsed_amount = _parse_amount(principal_amount)

        try:
            # Use ON CONFLICT to make idempotent
            # Note: The trigger fires only on INSERT, so if we skip via conflict,
            # no enrichment job is enqueued (which is correct - already exists)
            with self._conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO public.core_judgments (
                        case_index_number,
                        debtor_name,
                        original_creditor,
                        judgment_date,
                        principal_amount,
                        court_name,
                        county,
                        interest_rate
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, COALESCE(%s, 9.0))
                    ON CONFLICT (case_index_number) DO NOTHING
                    RETURNING id
                    """,
                    (
                        normalized_index,
                        _clean(debtor_name) or None,
                        _clean(original_creditor) or None,
                        parsed_date,
                        parsed_amount,
                        _clean(court_name) or None,
                        _clean(county) or None,
                        float(interest_rate) if interest_rate else None,
                    ),
                )

                row = cur.fetchone()
                if row:
                    # New row inserted
                    result.judgment_id = str(row[0])
                    result.inserted = True
                    self.stats.inserted += 1
                    logger.debug(
                        "core_judgment_inserted case_index=%s judgment_id=%s",
                        normalized_index,
                        result.judgment_id,
                    )
                else:
                    # Conflict - row already exists
                    cur.execute(
                        """
                        SELECT id FROM public.core_judgments
                        WHERE case_index_number = %s
                        """,
                        (normalized_index,),
                    )
                    existing = cur.fetchone()
                    if existing:
                        result.judgment_id = str(existing[0])
                    result.skipped = True
                    self.stats.skipped_existing += 1
                    logger.debug(
                        "core_judgment_skipped case_index=%s exists judgment_id=%s",
                        normalized_index,
                        result.judgment_id,
                    )

        except Exception as exc:
            result.error = str(exc)
            self.stats.errors += 1
            self.stats.error_details.append(f"{normalized_index}: {exc}")
            logger.warning(
                "core_judgment_insert_failed case_index=%s error=%s",
                normalized_index,
                exc,
            )

        return result

    def insert_batch(
        self,
        rows: List[Dict[str, Any]],
    ) -> List[CoreJudgmentInsertResult]:
        """Insert multiple judgments in a batch.

        Each row dict should contain keys matching insert_judgment params:
        - case_index_number (required)
        - debtor_name, original_creditor, judgment_date, principal_amount, etc.

        Returns:
            List of CoreJudgmentInsertResult, one per input row.
        """
        results = []
        for row in rows:
            result = self.insert_judgment(
                case_index_number=row.get("case_index_number", ""),
                debtor_name=row.get("debtor_name"),
                original_creditor=row.get("original_creditor"),
                judgment_date=row.get("judgment_date"),
                principal_amount=row.get("principal_amount"),
                court_name=row.get("court_name"),
                county=row.get("county"),
                interest_rate=row.get("interest_rate"),
            )
            results.append(result)
        return results

    def summary(self) -> Dict[str, Any]:
        """Return a summary dict of bridge statistics."""
        return {
            "total_attempts": self.stats.total_attempts,
            "inserted": self.stats.inserted,
            "skipped_existing": self.stats.skipped_existing,
            "errors": self.stats.errors,
            "error_count": len(self.stats.error_details),
        }
