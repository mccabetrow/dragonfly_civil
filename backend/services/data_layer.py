"""
Dragonfly Engine - Hybrid Data Access Layer

POSTGREST-FIRST WITH DIRECT DB FAILOVER
========================================

This module provides a resilient data access layer that:
1. Tries PostgREST (Supabase API) first for optimal performance
2. Automatically detects PGRST002/503 errors
3. Triggers schema cache reload (NOTIFY pgrst) on failure
4. Falls back to Direct SQL via psycopg for critical data

USAGE:
------
    from backend.services.data_layer import HybridDataLayer

    layer = HybridDataLayer()

    # Fetch from view with automatic failover
    rows = await layer.fetch_view("v_plaintiffs_overview", {"tier": "eq.A"})

    # Fetch from table
    rows = await layer.fetch_table("judgments", {"status": "eq.active"}, limit=100)

BENEFITS:
---------
- Dashboard never crashes due to PGRST002 errors
- Self-healing: triggers cache reload automatically
- Transparent: returns same JSON format regardless of source
- Observable: logs access method for debugging
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, Optional

import httpx
import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from ..config import get_settings
from ..db import get_pool
from ..utils.alerting import alert_failover, alert_pgrst_cache_stale

logger = logging.getLogger(__name__)


# Error codes that indicate PostgREST schema cache issues
PGRST_CACHE_ERRORS = {"PGRST002", "PGRST116"}
RETRIABLE_STATUS_CODES = {502, 503, 504}


@dataclass
class FetchResult:
    """Result of a data fetch operation."""

    data: list[dict[str, Any]]
    source: Literal["rest", "direct"]
    latency_ms: float
    cache_reload_triggered: bool = False
    error: str | None = None


@dataclass
class CacheReloadState:
    """Track schema cache reload state to avoid spamming."""

    last_reload_at: datetime | None = None
    reload_count: int = 0
    min_reload_interval_seconds: int = 30

    def should_reload(self) -> bool:
        """Check if enough time has passed since last reload."""
        if self.last_reload_at is None:
            return True
        elapsed = (datetime.now(timezone.utc) - self.last_reload_at).total_seconds()
        return elapsed >= self.min_reload_interval_seconds

    def record_reload(self) -> None:
        """Record that a reload was triggered."""
        self.last_reload_at = datetime.now(timezone.utc)
        self.reload_count += 1


class HybridDataLayer:
    """
    Hybrid data access layer with PostgREST-first and Direct DB failover.

    Provides resilient data fetching that automatically recovers from
    PostgREST schema cache issues (PGRST002).
    """

    def __init__(
        self,
        supabase_url: str | None = None,
        service_key: str | None = None,
        db_url: str | None = None,
    ):
        """
        Initialize the hybrid data layer.

        Args:
            supabase_url: Supabase REST API URL (defaults to settings)
            service_key: Supabase service role key (defaults to settings)
            db_url: PostgreSQL connection URL for direct access (defaults to settings)
        """
        settings = get_settings()
        self._supabase_url = supabase_url or settings.SUPABASE_URL
        self._service_key = service_key or settings.SUPABASE_SERVICE_ROLE_KEY
        self._db_url = db_url or settings.SUPABASE_DB_URL
        self._cache_state = CacheReloadState()
        self._http_client: httpx.AsyncClient | None = None

    async def _get_http_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client for REST API calls."""
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
        """Close HTTP client connections."""
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()
            self._http_client = None

    def _is_pgrst_cache_error(self, response: httpx.Response) -> bool:
        """Check if response indicates a PostgREST cache error."""
        if response.status_code in RETRIABLE_STATUS_CODES:
            try:
                data = response.json()
                code = data.get("code", "")
                return code in PGRST_CACHE_ERRORS
            except Exception:
                pass
            # 503 without parseable body is also likely a cache issue
            return response.status_code == 503
        return False

    async def _trigger_cache_reload(self) -> bool:
        """
        Fire-and-forget: trigger PostgREST schema cache reload.

        Uses NOTIFY pgrst to signal PostgREST to refresh its cache.
        Rate-limited to avoid spamming.
        """
        if not self._cache_state.should_reload():
            logger.debug("Skipping cache reload (rate limited)")
            return False

        try:
            # Run in background - don't block the failover
            asyncio.create_task(self._do_cache_reload())
            return True
        except Exception as e:
            logger.warning(f"Failed to trigger cache reload: {e}")
            return False

    async def _do_cache_reload(self) -> None:
        """Actually perform the cache reload via NOTIFY."""
        try:
            with psycopg.connect(self._db_url, autocommit=True, connect_timeout=5) as conn:
                with conn.cursor() as cur:
                    cur.execute("NOTIFY pgrst, 'reload schema'")

            self._cache_state.record_reload()
            logger.info(f"✅ NOTIFY pgrst sent (reload #{self._cache_state.reload_count})")

            # Fire Discord alert (fire-and-forget)
            asyncio.create_task(
                alert_pgrst_cache_stale(error_code="PGRST002", reload_triggered=True)
            )
        except Exception as e:
            logger.error(f"Failed to send NOTIFY pgrst: {e}")

    async def _fetch_via_rest(
        self,
        endpoint: str,
        filters: dict[str, str] | None = None,
        limit: int | None = None,
        order: str | None = None,
    ) -> tuple[list[dict[str, Any]], float, str | None]:
        """
        Fetch data via Supabase REST API.

        Returns:
            Tuple of (data, latency_ms, error_message)
        """
        import time

        start = time.monotonic()

        # Build query params
        params: dict[str, str] = {}
        if filters:
            params.update(filters)
        if limit:
            params["limit"] = str(limit)
        if order:
            params["order"] = order

        url = f"{self._supabase_url}/rest/v1/{endpoint}"

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
                    error_msg = error_data.get("message", "PostgREST cache error")
                    error_code = error_data.get("code", "UNKNOWN")
                    return [], latency_ms, f"{error_code}: {error_msg}"
                except Exception:
                    return [], latency_ms, f"HTTP {response.status_code}"

            # Other error
            return [], latency_ms, f"HTTP {response.status_code}: {response.text[:200]}"

        except httpx.TimeoutException:
            latency_ms = (time.monotonic() - start) * 1000
            return [], latency_ms, "Request timeout"
        except Exception as e:
            latency_ms = (time.monotonic() - start) * 1000
            return [], latency_ms, f"{type(e).__name__}: {str(e)[:100]}"

    async def _fetch_via_direct(
        self,
        view_or_table: str,
        filters: dict[str, str] | None = None,
        limit: int | None = None,
        order: str | None = None,
    ) -> tuple[list[dict[str, Any]], float, str | None]:
        """
        Fetch data via direct PostgreSQL connection.

        Returns:
            Tuple of (data, latency_ms, error_message)
        """
        import time

        start = time.monotonic()

        # Build SQL query
        # SECURITY: view_or_table should be validated before reaching here
        query = f"SELECT * FROM {view_or_table}"

        where_clauses = []
        params: list[Any] = []

        if filters:
            for key, value in filters.items():
                # Parse PostgREST-style filters: column=eq.value, column=gt.value, etc.
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
                    # Direct equality
                    where_clauses.append(f"{key} = %s")
                    params.append(value)

        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)

        if order:
            # Parse PostgREST-style order: column.desc, column.asc
            order_parts = []
            for part in order.split(","):
                part = part.strip()
                if ".desc" in part:
                    order_parts.append(f"{part.replace('.desc', '')} DESC")
                elif ".asc" in part:
                    order_parts.append(f"{part.replace('.asc', '')} ASC")
                else:
                    order_parts.append(part)
            if order_parts:
                query += " ORDER BY " + ", ".join(order_parts)

        if limit:
            query += f" LIMIT {limit}"

        try:
            pool = await get_pool()
            if pool is None:
                return [], 0, "Database pool not initialized"

            async with pool.connection() as conn:
                async with conn.cursor(row_factory=dict_row) as cur:
                    # Use sql.SQL for safe query composition (trusted internal query)
                    await cur.execute(sql.SQL(query), params or None)  # type: ignore[arg-type]
                    rows = await cur.fetchall()

            latency_ms = (time.monotonic() - start) * 1000
            return [dict(row) for row in rows], latency_ms, None

        except Exception as e:
            latency_ms = (time.monotonic() - start) * 1000
            return [], latency_ms, f"{type(e).__name__}: {str(e)[:100]}"

    async def fetch_view(
        self,
        view_name: str,
        filters: dict[str, str] | None = None,
        limit: int | None = None,
        order: str | None = None,
        fallback_enabled: bool = True,
    ) -> FetchResult:
        """
        Fetch data from a view with automatic failover.

        Args:
            view_name: Name of the database view (e.g., 'v_plaintiffs_overview')
            filters: PostgREST-style filters (e.g., {'tier': 'eq.A'})
            limit: Maximum rows to return
            order: Order clause (e.g., 'created_at.desc')
            fallback_enabled: If False, skip direct DB fallback

        Returns:
            FetchResult with data and metadata
        """
        # Validate view name (prevent SQL injection)
        if not view_name.replace("_", "").isalnum():
            return FetchResult(
                data=[],
                source="rest",
                latency_ms=0,
                error=f"Invalid view name: {view_name}",
            )

        # Attempt 1: REST API
        data, latency_ms, error = await self._fetch_via_rest(view_name, filters, limit, order)

        if error is None:
            logger.debug(f"REST OK: {view_name} ({len(data)} rows, {latency_ms:.0f}ms)")
            return FetchResult(data=data, source="rest", latency_ms=latency_ms)

        # REST failed - check if cache error
        is_cache_error = any(code in (error or "") for code in PGRST_CACHE_ERRORS)
        cache_reload_triggered = False

        if is_cache_error or "503" in (error or ""):
            logger.warning(f"⚠️ PostgREST Unstable ({view_name}): {error}. Switching to Direct DB.")
            cache_reload_triggered = await self._trigger_cache_reload()
        else:
            logger.warning(f"REST failed ({view_name}): {error}")

        if not fallback_enabled:
            return FetchResult(
                data=[],
                source="rest",
                latency_ms=latency_ms,
                cache_reload_triggered=cache_reload_triggered,
                error=error,
            )

        # Attempt 2: Direct SQL
        data, direct_latency, direct_error = await self._fetch_via_direct(
            view_name, filters, limit, order
        )

        if direct_error is None:
            logger.info(f"✅ Direct DB OK: {view_name} ({len(data)} rows, {direct_latency:.0f}ms)")

            # Fire Discord alert for failover (fire-and-forget, rate-limited)
            asyncio.create_task(
                alert_failover(
                    endpoint=f"view/{view_name}",
                    reason=error or "Unknown REST error",
                    latency_ms=latency_ms + direct_latency,
                )
            )

            return FetchResult(
                data=data,
                source="direct",
                latency_ms=latency_ms + direct_latency,
                cache_reload_triggered=cache_reload_triggered,
            )

        # Both failed
        logger.error(f"❌ Both REST and Direct failed for {view_name}: {direct_error}")
        return FetchResult(
            data=[],
            source="direct",
            latency_ms=latency_ms + direct_latency,
            cache_reload_triggered=cache_reload_triggered,
            error=f"REST: {error} | Direct: {direct_error}",
        )

    async def fetch_table(
        self,
        table_name: str,
        filters: dict[str, str] | None = None,
        limit: int | None = None,
        order: str | None = None,
        fallback_enabled: bool = True,
    ) -> FetchResult:
        """
        Fetch data from a table with automatic failover.

        Same as fetch_view but for tables.
        """
        return await self.fetch_view(table_name, filters, limit, order, fallback_enabled)

    async def call_rpc(
        self,
        function_name: str,
        params: dict[str, Any] | None = None,
        fallback_sql: str | None = None,
    ) -> FetchResult:
        """
        Call an RPC function with optional direct SQL fallback.

        Args:
            function_name: Name of the PostgreSQL function
            params: Parameters to pass to the function
            fallback_sql: SQL query to execute if RPC fails

        Returns:
            FetchResult with data and metadata
        """
        import time

        start = time.monotonic()

        # Validate function name
        if not function_name.replace("_", "").isalnum():
            return FetchResult(
                data=[],
                source="rest",
                latency_ms=0,
                error=f"Invalid function name: {function_name}",
            )

        # Attempt 1: REST RPC
        url = f"{self._supabase_url}/rest/v1/rpc/{function_name}"

        try:
            client = await self._get_http_client()
            response = await client.post(url, json=params or {})
            latency_ms = (time.monotonic() - start) * 1000

            if response.status_code == 200:
                data = response.json()
                if not isinstance(data, list):
                    data = [data] if data else []
                return FetchResult(data=data, source="rest", latency_ms=latency_ms)

            # Check for cache error
            if self._is_pgrst_cache_error(response):
                try:
                    error_data = response.json()
                    error = f"{error_data.get('code', 'UNKNOWN')}: {error_data.get('message', 'RPC failed')}"
                except Exception:
                    error = f"HTTP {response.status_code}"

                logger.warning(f"⚠️ PostgREST RPC failed ({function_name}): {error}")
                await self._trigger_cache_reload()

                # Try fallback SQL if provided
                if fallback_sql:
                    return await self._execute_fallback_sql(fallback_sql, params, latency_ms)

                return FetchResult(
                    data=[],
                    source="rest",
                    latency_ms=latency_ms,
                    cache_reload_triggered=True,
                    error=error,
                )

            error = f"HTTP {response.status_code}"
            return FetchResult(data=[], source="rest", latency_ms=latency_ms, error=error)

        except Exception as e:
            latency_ms = (time.monotonic() - start) * 1000
            error = f"{type(e).__name__}: {str(e)[:100]}"

            if fallback_sql:
                return await self._execute_fallback_sql(fallback_sql, params, latency_ms)

            return FetchResult(data=[], source="rest", latency_ms=latency_ms, error=error)

    async def _execute_fallback_sql(
        self,
        query_str: str,
        params: dict[str, Any] | None,
        prior_latency_ms: float,
    ) -> FetchResult:
        """Execute fallback SQL query."""
        import time

        start = time.monotonic()

        try:
            pool = await get_pool()
            if pool is None:
                return FetchResult(
                    data=[],
                    source="direct",
                    latency_ms=prior_latency_ms,
                    error="Database pool not initialized",
                )

            async with pool.connection() as conn:
                async with conn.cursor(row_factory=dict_row) as cur:
                    # Use sql.SQL for safe query composition (trusted internal fallback)
                    await cur.execute(sql.SQL(query_str), params or None)  # type: ignore[arg-type]
                    rows = await cur.fetchall()

            latency_ms = (time.monotonic() - start) * 1000
            logger.info(f"✅ Fallback SQL OK ({len(rows)} rows, {latency_ms:.0f}ms)")

            # Fire Discord alert for RPC fallover (fire-and-forget, rate-limited)
            asyncio.create_task(
                alert_failover(
                    endpoint="rpc/fallback",
                    reason="PostgREST RPC failed, using fallback SQL",
                    latency_ms=prior_latency_ms + latency_ms,
                )
            )

            return FetchResult(
                data=[dict(row) for row in rows],
                source="direct",
                latency_ms=prior_latency_ms + latency_ms,
                cache_reload_triggered=True,
            )

        except Exception as e:
            latency_ms = (time.monotonic() - start) * 1000
            return FetchResult(
                data=[],
                source="direct",
                latency_ms=prior_latency_ms + latency_ms,
                cache_reload_triggered=True,
                error=f"{type(e).__name__}: {str(e)[:100]}",
            )


# Singleton instance
_data_layer: HybridDataLayer | None = None


def get_data_layer() -> HybridDataLayer:
    """Get the singleton HybridDataLayer instance."""
    global _data_layer
    if _data_layer is None:
        _data_layer = HybridDataLayer()
    return _data_layer


async def reset_data_layer() -> None:
    """Reset the data layer (for testing)."""
    global _data_layer
    if _data_layer:
        await _data_layer.close()
        _data_layer = None


# Convenience exports
__all__ = [
    "HybridDataLayer",
    "FetchResult",
    "get_data_layer",
    "reset_data_layer",
]
