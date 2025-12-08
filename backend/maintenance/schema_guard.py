"""
Dragonfly Engine - Schema Guard

Automated schema drift detection and self-healing repair system.
Compares production schema against canonical definitions and triggers
repair scripts when drift is detected.

Usage:
    from backend.maintenance.schema_guard import SchemaGuard

    guard = SchemaGuard()
    drift_detected = await guard.check_schema_drift()
    if drift_detected:
        await guard.check_and_repair()
"""

from __future__ import annotations

import difflib
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from ..config import get_settings
from ..db import get_connection
from ..services.discord_service import DiscordService

logger = logging.getLogger(__name__)

# Path to canonical schema files
PROJECT_ROOT = Path(__file__).parent.parent.parent
RECOVERY_DIR = PROJECT_ROOT / "supabase" / "recovery"

# Schemas to monitor
MONITORED_SCHEMAS = ["public", "ops", "enforcement", "analytics"]


class SchemaGuard:
    """
    Schema drift detection and auto-repair system.

    Monitors production schema against canonical SQL definitions.
    When drift is detected, triggers repair scripts and alerts via Discord.
    """

    def __init__(self):
        """Initialize SchemaGuard."""
        self._settings = get_settings()
        self._last_check: datetime | None = None
        self._last_drift: str | None = None

    # =========================================================================
    # Schema Fetching
    # =========================================================================

    async def _fetch_prod_schema(self) -> list[dict[str, Any]]:
        """
        Fetch current production schema from information_schema.

        Returns:
            List of dicts with table_name, column_name, data_type
        """
        query = """
            SELECT
                table_schema,
                table_name,
                column_name,
                data_type,
                is_nullable,
                column_default
            FROM information_schema.columns
            WHERE table_schema IN ('public', 'ops', 'enforcement', 'analytics')
            ORDER BY table_schema, table_name, ordinal_position
        """

        try:
            async with get_connection() as conn:
                rows = await conn.fetch(query)
                return rows
        except Exception as e:
            logger.error(f"[SchemaGuard] Failed to fetch prod schema: {e}")
            raise

    async def _fetch_prod_views(self) -> list[dict[str, Any]]:
        """
        Fetch current production views.

        Returns:
            List of dicts with table_schema, table_name, view_definition
        """
        query = """
            SELECT
                table_schema,
                table_name,
                LEFT(view_definition, 200) as view_definition_preview
            FROM information_schema.views
            WHERE table_schema IN ('public', 'ops', 'enforcement', 'analytics')
            ORDER BY table_schema, table_name
        """

        try:
            async with get_connection() as conn:
                rows = await conn.fetch(query)
                return rows
        except Exception as e:
            logger.error(f"[SchemaGuard] Failed to fetch prod views: {e}")
            raise

    def _format_schema_snapshot(self, columns: list[dict[str, Any]]) -> str:
        """Format schema columns into comparable text."""
        lines = []
        current_table = ""

        for col in columns:
            table_key = f"{col['table_schema']}.{col['table_name']}"
            if table_key != current_table:
                lines.append(f"\n-- {table_key}")
                current_table = table_key

            nullable = "NULL" if col["is_nullable"] == "YES" else "NOT NULL"
            default = f" DEFAULT {col['column_default']}" if col["column_default"] else ""
            lines.append(f"  {col['column_name']} {col['data_type']} {nullable}{default}")

        return "\n".join(lines)

    def _format_views_snapshot(self, views: list[dict[str, Any]]) -> str:
        """Format views into comparable text."""
        lines = []
        for view in views:
            view_key = f"{view['table_schema']}.{view['table_name']}"
            lines.append(f"VIEW {view_key}")

        return "\n".join(sorted(lines))

    # =========================================================================
    # Expected Schema Loading
    # =========================================================================

    def _load_expected_views(self) -> set[str]:
        """
        Load expected view names from recovery scripts.

        Returns:
            Set of expected view names (schema.view_name format)
        """
        expected_views: set[str] = set()

        # Parse recovery SQL files for CREATE OR REPLACE VIEW statements
        recovery_files = [
            RECOVERY_DIR / "core_schema_repair.sql",
            RECOVERY_DIR / "ops_intake_schema_repair.sql",
            RECOVERY_DIR / "enforcement_schema_repair.sql",
        ]

        for sql_file in recovery_files:
            if not sql_file.exists():
                logger.debug(f"[SchemaGuard] Recovery file not found: {sql_file}")
                continue

            content = sql_file.read_text()

            # Extract view names from CREATE OR REPLACE VIEW statements
            import re

            pattern = r"CREATE\s+OR\s+REPLACE\s+VIEW\s+(\w+\.?\w+)"
            matches = re.findall(pattern, content, re.IGNORECASE)

            for match in matches:
                # Normalize to schema.view format
                if "." not in match:
                    match = f"public.{match}"
                expected_views.add(match.lower())

        logger.debug(f"[SchemaGuard] Expected views: {len(expected_views)}")
        return expected_views

    # =========================================================================
    # Drift Detection
    # =========================================================================

    async def check_schema_drift(self) -> bool:
        """
        Check for schema drift between prod and canonical definitions.

        Returns:
            True if drift detected, False otherwise
        """
        logger.info("[SchemaGuard] Checking for schema drift...")
        self._last_check = datetime.utcnow()

        try:
            # Fetch current prod state
            prod_views = await self._fetch_prod_views()
            prod_view_names = {f"{v['table_schema']}.{v['table_name']}".lower() for v in prod_views}

            # Load expected views
            expected_views = self._load_expected_views()

            # Find missing views
            missing_views = expected_views - prod_view_names

            if missing_views:
                drift_msg = f"Missing views: {', '.join(sorted(missing_views))}"
                logger.warning(f"[SchemaGuard] Drift detected! {drift_msg}")
                self._last_drift = drift_msg
                return True

            # Check for extra views (informational only)
            extra_views = prod_view_names - expected_views
            if extra_views:
                logger.debug(f"[SchemaGuard] Extra views in prod (not in recovery): {extra_views}")

            logger.info("[SchemaGuard] No schema drift detected")
            self._last_drift = None
            return False

        except Exception as e:
            logger.error(f"[SchemaGuard] Error checking drift: {e}")
            # Don't crash - return False but log the error
            return False

    async def get_detailed_drift(self) -> str | None:
        """
        Get detailed drift report if drift was detected.

        Returns:
            Formatted diff string or None if no drift
        """
        if not self._last_drift:
            return None

        try:
            prod_views = await self._fetch_prod_views()
            prod_snapshot = self._format_views_snapshot(prod_views)

            expected_views = self._load_expected_views()
            expected_snapshot = "\n".join(f"VIEW {v}" for v in sorted(expected_views))

            diff = difflib.unified_diff(
                expected_snapshot.splitlines(keepends=True),
                prod_snapshot.splitlines(keepends=True),
                fromfile="expected_views",
                tofile="prod_views",
                lineterm="",
            )

            return "".join(diff)

        except Exception as e:
            logger.error(f"[SchemaGuard] Error generating detailed drift: {e}")
            return self._last_drift

    # =========================================================================
    # Repair Execution
    # =========================================================================

    async def _execute_repair(self) -> dict[str, Any]:
        """
        Execute schema repair scripts.

        Returns:
            Dict with repair results
        """
        from tools.run_schema_repair import run_repair

        logger.info("[SchemaGuard] Executing schema repair...")

        try:
            result = await run_repair()
            logger.info(f"[SchemaGuard] Repair completed: {result}")
            return result
        except Exception as e:
            logger.error(f"[SchemaGuard] Repair failed: {e}")
            return {"success": False, "error": str(e)}

    async def _send_alert(self, title: str, message: str) -> None:
        """Send Discord alert."""
        try:
            async with DiscordService() as discord:
                content = f"🔧 **{title}**\n\n{message}"
                await discord.send_message(content, username="Schema Guard")
        except Exception as e:
            logger.error(f"[SchemaGuard] Failed to send Discord alert: {e}")

    # =========================================================================
    # Main Entry Points
    # =========================================================================

    async def check_and_repair(self) -> dict[str, Any]:
        """
        Check for drift and automatically repair if needed.

        This is the main entry point for scheduled execution.

        Returns:
            Dict with check and repair results
        """
        result = {
            "checked_at": datetime.utcnow().isoformat(),
            "drift_detected": False,
            "repair_triggered": False,
            "repair_result": None,
            "error": None,
        }

        try:
            # Check for drift
            drift_detected = await self.check_schema_drift()
            result["drift_detected"] = drift_detected

            if not drift_detected:
                logger.info("[SchemaGuard] Drift check complete - no action needed")
                return result

            # Get detailed drift for logging
            drift_details = await self.get_detailed_drift()
            logger.warning(f"[SchemaGuard] Drift details:\n{drift_details}")

            # Alert before repair
            await self._send_alert(
                "Schema Drift Detected",
                f"```\n{self._last_drift}\n```\n\nTriggering auto-repair...",
            )

            # Execute repair
            result["repair_triggered"] = True
            repair_result = await self._execute_repair()
            result["repair_result"] = repair_result

            # Alert on result
            if repair_result.get("success"):
                await self._send_alert(
                    "Schema Repair Completed ✅",
                    f"Successfully repaired schema drift.\n\n"
                    f"Files executed: {repair_result.get('files_executed', [])}",
                )
                logger.info("[SchemaGuard] Repair executed successfully")
            else:
                await self._send_alert(
                    "Schema Repair Failed ❌",
                    f"Repair encountered errors.\n\n"
                    f"Error: {repair_result.get('error', 'Unknown')}",
                )
                logger.error("[SchemaGuard] Repair failed")

        except Exception as e:
            result["error"] = str(e)
            logger.exception(f"[SchemaGuard] check_and_repair failed: {e}")

            # Try to alert on failure
            try:
                await self._send_alert(
                    "Schema Guard Error ⚠️",
                    f"Schema guard encountered an error:\n```\n{e}\n```",
                )
            except Exception:
                pass  # Best effort alerting

        return result


# =============================================================================
# Module-level functions for scheduler
# =============================================================================

_guard_instance: SchemaGuard | None = None


def get_schema_guard() -> SchemaGuard:
    """Get or create the SchemaGuard singleton."""
    global _guard_instance
    if _guard_instance is None:
        _guard_instance = SchemaGuard()
    return _guard_instance


async def check_schema_drift() -> bool:
    """
    Module-level function for checking schema drift.

    Returns:
        True if drift detected
    """
    guard = get_schema_guard()
    return await guard.check_schema_drift()


async def check_and_repair() -> dict[str, Any]:
    """
    Module-level function for scheduler integration.

    Returns:
        Dict with check/repair results
    """
    guard = get_schema_guard()
    return await guard.check_and_repair()
