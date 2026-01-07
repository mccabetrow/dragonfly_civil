"""
backend/services/data_service.py - Centralized Data Service

UNIFIED RESILIENT DATA ACCESS
=============================

This service implements the "Try REST -> Heal -> Failover to DB" pattern
for all read operations. It ensures user-critical operations are NEVER
blocked by PostgREST health issues.

Policy: "Never block a user-critical operation on PostgREST health."

Pattern:
    1. Attempt REST API (fast, uses PostgREST)
    2. If PGRST002/503 detected: trigger NOTIFY pgrst (heal)
    3. Fallback to Direct DB (always available)
    4. Return data with source metadata

Usage:
    from backend.services.data_service import DataService

    service = DataService()
    data = await service.fetch_view("v_plaintiffs_overview", limit=100)
    data = await service.fetch_view("ops.v_batch_performance", filters={"status": "eq.active"})

Dependencies:
    - backend.db (Direct SQL via psycopg pool)
    - backend.core.config (Settings)
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

import httpx
import psycopg
from psycopg.rows import dict_row

from backend.config import get_settings
from backend.db import get_pool
from backend.utils.discord import alert_failover_active

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════
# CONCURRENCY CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════
# Limit concurrent Direct DB fallback queries to protect the pool.
# This ensures critical ingest workers always have connections available.

MAX_CONCURRENT_FALLBACK_QUERIES = 5


# PostgREST error codes that indicate schema cache issues
PGRST_CACHE_ERRORS = {"PGRST002", "PGRST116"}
RETRIABLE_STATUS_CODES = {502, 503, 504}


@dataclass
class FetchMetadata:
    """Metadata about a data fetch operation."""

    source: Literal["rest", "direct_db"]
    latency_ms: float
    timestamp: str
    cache_reload_triggered: bool = False
    rest_error: str | None = None


@dataclass
class DataServiceResult:
    """Result from DataService fetch operations."""

    data: list[dict[str, Any]]
    metadata: FetchMetadata

    @property
    def success(self) -> bool:
        return len(self.data) > 0 or self.metadata.rest_error is None


@dataclass
class CacheReloadState:
    """Track cache reload attempts to avoid spamming."""

    last_reload_at: datetime | None = None
    reload_count: int = 0
    min_interval_seconds: int = 30

    def should_reload(self) -> bool:
        if self.last_reload_at is None:
            return True
        elapsed = (datetime.now(timezone.utc) - self.last_reload_at).total_seconds()
        return elapsed >= self.min_interval_seconds

    def record_reload(self) -> None:
        self.last_reload_at = datetime.now(timezone.utc)
        self.reload_count += 1


class DataService:
    """
    Centralized data service with automatic REST-to-DB failover.

    Implements the resilient data access pattern:
    1. Try REST API first (PostgREST)
    2. On PGRST002/503: trigger cache reload (heal)
    3. Fall back to direct PostgreSQL connection
    4. Never fail a user request due to PostgREST issues

    Concurrency Protection:
    - Direct DB fallback is throttled via semaphore
    - Ensures ingest workers always have pool connections available
    """

    _instance: "DataService | None" = None
    _cache_state: CacheReloadState = field(default_factory=CacheReloadState)
    _db_semaphore: asyncio.Semaphore = asyncio.Semaphore(MAX_CONCURRENT_FALLBACK_QUERIES)

    def __init__(self):
        settings = get_settings()
        self._supabase_url = settings.SUPABASE_URL
        self._service_key = settings.SUPABASE_SERVICE_ROLE_KEY
        self._db_url = settings.SUPABASE_DB_URL
        self._cache_state = CacheReloadState()
        self._http_client: httpx.AsyncClient | None = None

    @classmethod
    def get_instance(cls) -> "DataService":
        """Get singleton instance of DataService."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def _get_http_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client for REST calls."""
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0, connect=10.0),
                headers={
                    "apikey": self._service_key,
                    "Authorization": f"Bearer {self._service_key}",
                    "Content-Type": "application/json",
                    "Prefer": "return=representation",
                },
            )
        return self._http_client

    async def close(self) -> None:
        """Clean up HTTP client."""
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()
            self._http_client = None

    def _is_pgrst_cache_error(self, response: httpx.Response) -> bool:
        """Detect if response indicates PostgREST cache error."""
        if response.status_code in RETRIABLE_STATUS_CODES:
            try:
                data = response.json()
                code = data.get("code", "")
                return code in PGRST_CACHE_ERRORS
            except Exception:
                pass
            # 503 without body is also likely cache issue
            return response.status_code == 503
        return False

    async def _trigger_cache_reload(self) -> bool:
        """
        Trigger PostgREST schema cache reload via NOTIFY.

        Fire-and-forget with rate limiting to avoid spam.
        """
        if not self._cache_state.should_reload():
            logger.debug("Cache reload rate-limited, skipping")
            return False

        try:
            # Fire and forget - don't block the failover path
            asyncio.create_task(self._do_cache_reload())
            return True
        except Exception as e:
            logger.warning(f"Failed to schedule cache reload: {e}")
            return False

    async def _do_cache_reload(self) -> None:
        """Execute the NOTIFY pgrst command."""
        try:
            # Short wait before notify to let the request complete
            await asyncio.sleep(0.5)

            with psycopg.connect(self._db_url, autocommit=True, connect_timeout=5) as conn:
                with conn.cursor() as cur:
                    cur.execute("NOTIFY pgrst, 'reload schema'")

            self._cache_state.record_reload()
            logger.info(f"✅ NOTIFY pgrst sent (reload #{self._cache_state.reload_count})")

        except Exception as e:
            logger.error(f"Failed to send NOTIFY pgrst: {e}")

    async def _fetch_via_rest(
        self,
        view_name: str,
        filters: dict[str, str] | None = None,
        limit: int = 100,
    ) -> tuple[list[dict[str, Any]], float, str | None]:
        """
        Attempt 1: Fetch via REST API.

        Returns:
            (data, latency_ms, error_message)
        """
        start = time.monotonic()

        # Handle schema-qualified names: ops.v_batch_performance -> ops/v_batch_performance
        endpoint = view_name.replace(".", "/") if "." in view_name else view_name
        url = f"{self._supabase_url}/rest/v1/{endpoint}"

        params: dict[str, str] = {"limit": str(limit)}
        if filters:
            params.update(filters)

        try:
            client = await self._get_http_client()
            response = await client.get(url, params=params)
            latency_ms = (time.monotonic() - start) * 1000

            if response.status_code == 200:
                return response.json(), latency_ms, None

            # Check for cache errors
            if self._is_pgrst_cache_error(response):
                try:
                    error_data = response.json()
                    code = error_data.get("code", "PGRST_ERROR")
                    msg = error_data.get("message", "Unknown error")
                    return [], latency_ms, f"{code}: {msg}"
                except Exception:
                    return [], latency_ms, f"HTTP {response.status_code}"

            return [], latency_ms, f"HTTP {response.status_code}: {response.text[:200]}"

        except httpx.TimeoutException:
            latency_ms = (time.monotonic() - start) * 1000
            return [], latency_ms, "Request timeout"
        except Exception as e:
            latency_ms = (time.monotonic() - start) * 1000
            return [], latency_ms, f"{type(e).__name__}: {str(e)[:100]}"

    async def _fetch_via_direct_db(
        self,
        view_name: str,
        filters: dict[str, str] | None = None,
        limit: int = 100,
    ) -> tuple[list[dict[str, Any]], float, str | None]:
        """
        Attempt 2: Fetch via direct PostgreSQL connection.

        Returns:
            (data, latency_ms, error_message)
        """
        start = time.monotonic()

        # Parse schema.view_name or default to public
        if "." in view_name:
            schema, view = view_name.split(".", 1)
        else:
            schema, view = "public", view_name

        # Build SQL query
        query = f"SELECT * FROM {schema}.{view}"

        where_clauses = []
        params: list[Any] = []

        if filters:
            for key, value in filters.items():
                # Parse PostgREST-style filters: column=eq.value
                if "." in value:
                    op, val = value.split(".", 1)
                    if op == "eq":
                        where_clauses.append(f"{key} = %s")
                        params.append(val)
                    elif op == "gt":
                        where_clauses.append(f"{key} > %s")
                        params.append(val)
                    elif op == "gte":
                        where_clauses.append(f"{key} >= %s")
                        params.append(val)
                    elif op == "lt":
                        where_clauses.append(f"{key} < %s")
                        params.append(val)
                    elif op == "lte":
                        where_clauses.append(f"{key} <= %s")
                        params.append(val)
                    elif op == "neq":
                        where_clauses.append(f"{key} != %s")
                        params.append(val)
                    elif op == "like":
                        where_clauses.append(f"{key} LIKE %s")
                        params.append(val)
                    elif op == "ilike":
                        where_clauses.append(f"{key} ILIKE %s")
                        params.append(val)
                    elif op == "is":
                        if val.lower() == "null":
                            where_clauses.append(f"{key} IS NULL")
                        elif val.lower() == "true":
                            where_clauses.append(f"{key} IS TRUE")
                        elif val.lower() == "false":
                            where_clauses.append(f"{key} IS FALSE")
                else:
                    where_clauses.append(f"{key} = %s")
                    params.append(value)

        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)

        query += f" LIMIT {limit}"

        try:
            pool = await get_pool()
            if pool is None:
                return [], 0, "Database pool not initialized"

            async with pool.connection() as conn:
                async with conn.cursor(row_factory=dict_row) as cur:
                    await cur.execute(query, params or None)
                    rows = await cur.fetchall()

            latency_ms = (time.monotonic() - start) * 1000

            # Convert to plain dicts for JSON serialization
            return [dict(row) for row in rows], latency_ms, None

        except Exception as e:
            latency_ms = (time.monotonic() - start) * 1000
            logger.exception(f"Direct DB query failed: {view_name}")
            return [], latency_ms, f"{type(e).__name__}: {str(e)[:100]}"

    async def fetch_view(
        self,
        view_name: str,
        limit: int = 100,
        filters: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Fetch data from a view with automatic failover.

        This is the main entry point for dashboard data access.
        Implements: Try REST -> Heal -> Fallback to DB

        Args:
            view_name: View name (e.g., 'v_plaintiffs_overview' or 'ops.v_batch_performance')
            limit: Maximum rows to return (default 100)
            filters: PostgREST-style filters (e.g., {'tier': 'eq.A'})

        Returns:
            List of dicts (rows from the view)

        Raises:
            RuntimeError: If both REST and direct DB fail
        """
        # Validate view name (basic SQL injection prevention)
        clean_name = view_name.replace(".", "_")
        if not clean_name.replace("_", "").isalnum():
            raise ValueError(f"Invalid view name: {view_name}")

        # ===== ATTEMPT 1: REST API =====
        data, rest_latency, rest_error = await self._fetch_via_rest(view_name, filters, limit)

        if rest_error is None:
            logger.debug(f"REST OK: {view_name} ({len(data)} rows, {rest_latency:.0f}ms)")
            return data

        # ===== DETECTION: Cache Error? =====
        is_cache_error = (
            any(code in rest_error for code in PGRST_CACHE_ERRORS) or "503" in rest_error
        )

        if is_cache_error:
            logger.warning(f"⚠️ PostgREST Unstable ({view_name}). Initiating Failover.")
            # ===== HEAL: Trigger cache reload =====
            await self._trigger_cache_reload()
            # ===== ALERT: Notify operations =====
            try:
                env = get_settings().SUPABASE_MODE or "unknown"
                alert_failover_active(env, view_name, rest_error)
            except Exception:
                pass  # Never block on alerting
        else:
            logger.warning(f"REST failed ({view_name}): {rest_error}")

        # ===== ATTEMPT 2: Direct DB Fallback (Throttled) =====
        logger.info(f"🛡️ Serving {view_name} via Direct DB connection.")

        # Throttle concurrent fallback queries to protect pool for ingest workers
        async with self._db_semaphore:
            data, db_latency, db_error = await self._fetch_via_direct_db(view_name, filters, limit)

        if db_error is None:
            logger.info(f"Direct DB OK: {view_name} ({len(data)} rows, {db_latency:.0f}ms)")
            return data

        # ===== BOTH FAILED =====
        logger.error(f"❌ CRITICAL: Both REST and Direct DB failed for {view_name}")
        logger.error(f"   REST Error: {rest_error}")
        logger.error(f"   DB Error: {db_error}")

        raise RuntimeError(f"Data fetch failed for {view_name}: REST={rest_error}, DB={db_error}")

    async def fetch_view_with_metadata(
        self,
        view_name: str,
        limit: int = 100,
        filters: dict[str, str] | None = None,
    ) -> DataServiceResult:
        """
        Fetch data with full metadata about the fetch operation.

        Use this when you need to know whether data came from REST or DB.

        Returns:
            DataServiceResult with data and metadata
        """
        # Validate view name
        clean_name = view_name.replace(".", "_")
        if not clean_name.replace("_", "").isalnum():
            return DataServiceResult(
                data=[],
                metadata=FetchMetadata(
                    source="rest",
                    latency_ms=0,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    rest_error=f"Invalid view name: {view_name}",
                ),
            )

        # Attempt REST
        data, rest_latency, rest_error = await self._fetch_via_rest(view_name, filters, limit)

        if rest_error is None:
            return DataServiceResult(
                data=data,
                metadata=FetchMetadata(
                    source="rest",
                    latency_ms=rest_latency,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                ),
            )

        # Cache error detection and heal
        is_cache_error = (
            any(code in rest_error for code in PGRST_CACHE_ERRORS) or "503" in rest_error
        )
        cache_reload_triggered = False

        if is_cache_error:
            cache_reload_triggered = await self._trigger_cache_reload()

        # Fallback to direct DB
        data, db_latency, db_error = await self._fetch_via_direct_db(view_name, filters, limit)

        if db_error is None:
            return DataServiceResult(
                data=data,
                metadata=FetchMetadata(
                    source="direct_db",
                    latency_ms=rest_latency + db_latency,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    cache_reload_triggered=cache_reload_triggered,
                    rest_error=rest_error,
                ),
            )

        # Both failed
        return DataServiceResult(
            data=[],
            metadata=FetchMetadata(
                source="direct_db",
                latency_ms=rest_latency + db_latency,
                timestamp=datetime.now(timezone.utc).isoformat(),
                cache_reload_triggered=cache_reload_triggered,
                rest_error=f"REST: {rest_error}, DB: {db_error}",
            ),
        )


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------


def get_data_service() -> DataService:
    """Get the singleton DataService instance."""
    return DataService.get_instance()


async def fetch_view(
    view_name: str,
    limit: int = 100,
    filters: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """
    Convenience function to fetch view data.

    Example:
        data = await fetch_view("v_plaintiffs_overview", limit=50)
        data = await fetch_view("ops.v_batch_performance", filters={"status": "eq.completed"})
    """
    service = get_data_service()
    return await service.fetch_view(view_name, limit, filters)
