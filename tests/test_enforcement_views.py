"""
tests/test_enforcement_views.py
═══════════════════════════════════════════════════════════════════════════════

Integration tests for the enforcement/ops views:
  - enforcement.v_radar
  - ops.v_enrichment_health

These tests connect to the dev database and verify that the views are present,
have the expected columns, and return sane data after the seed batch has run.

Note: These tests require the views to have been created via migrations:
  - 20251205001000_enrichment_jobs.sql (creates ops.job_queue)
  - 20251205101000_fix_enforcement_radar_views.sql (creates the views)

Strategy:
  - If migrations haven't been applied → pytest.skip (clean CI skip)
  - If migrations are applied but views are missing → fail with clear assertion
"""

import psycopg
import pytest

from src.supabase_client import get_supabase_db_url, get_supabase_env

pytestmark = pytest.mark.legacy  # Requires enforcement views from migrations

# Expected columns for v_radar (subset - we only check the required ones)
REQUIRED_V_RADAR_COLUMNS = {
    "id",
    "plaintiff_name",
    "defendant_name",
    "judgment_amount",
    "collectability_score",
    "offer_strategy",
}

# Valid offer_strategy values per the view definition
VALID_OFFER_STRATEGIES = {
    "BUY_CANDIDATE",
    "CONTINGENCY",
    "ENRICHMENT_PENDING",
    "LOW_PRIORITY",
}

# Migration name patterns to check in supabase_migrations.schema_migrations
ENRICHMENT_JOBS_MIGRATION_PATTERN = "%enrichment_jobs%"
ENFORCEMENT_RADAR_MIGRATION_PATTERN = "%enforcement_radar%"


def _get_connection_url() -> str:
    """Return the database connection URL for the current environment."""
    env = get_supabase_env()
    return get_supabase_db_url(env)


def _view_exists(cur: psycopg.Cursor, schema: str, view_name: str) -> bool:
    """Check if a view exists in the given schema."""
    cur.execute(
        """
        SELECT 1
        FROM pg_views
        WHERE schemaname = %s
          AND viewname = %s
        """,
        (schema, view_name),
    )
    return cur.fetchone() is not None


def _migration_applied(cur: psycopg.Cursor, pattern: str) -> bool:
    """Check if a migration matching the pattern has been applied.

    Checks supabase_migrations.schema_migrations for rows where name LIKE pattern.
    Returns False if the table doesn't exist (fresh DB with no migrations).
    """
    # First check if the migrations table exists
    cur.execute(
        """
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'supabase_migrations'
          AND table_name = 'schema_migrations'
        """
    )
    if cur.fetchone() is None:
        return False

    # Check for matching migration
    cur.execute(
        """
        SELECT 1
        FROM supabase_migrations.schema_migrations
        WHERE name LIKE %s
        LIMIT 1
        """,
        (pattern,),
    )
    return cur.fetchone() is not None


def _check_migrations_or_skip(cur: psycopg.Cursor) -> None:
    """Skip tests if required migrations haven't been applied.

    Raises pytest.skip if enrichment_jobs or enforcement_radar migrations
    are missing from supabase_migrations.schema_migrations.
    """
    missing_migrations = []

    if not _migration_applied(cur, ENRICHMENT_JOBS_MIGRATION_PATTERN):
        missing_migrations.append("enrichment_jobs")

    if not _migration_applied(cur, ENFORCEMENT_RADAR_MIGRATION_PATTERN):
        missing_migrations.append("enforcement_radar")

    if missing_migrations:
        pytest.skip(
            f"Required migrations not applied: {', '.join(missing_migrations)}. "
            "Run `scripts/db_push.ps1` to apply pending migrations."
        )


@pytest.mark.integration
class TestEnforcementRadarView:
    """Tests for enforcement.v_radar view."""

    @pytest.fixture(autouse=True)
    def _check_prerequisites(self):
        """Check migrations and view existence.

        - Missing migrations → skip
        - Migrations applied but view missing → fail
        """
        url = _get_connection_url()
        with psycopg.connect(url) as conn:
            with conn.cursor() as cur:
                # First check if migrations have been applied
                _check_migrations_or_skip(cur)

                # Migrations are applied - view MUST exist or it's a failure
                if not _view_exists(cur, "enforcement", "v_radar"):
                    pytest.fail(
                        "Expected view enforcement.v_radar to exist. "
                        "Migrations are applied but view is missing - check migration files."
                    )

    def test_v_radar_exists_in_pg_views(self):
        """Verify enforcement.v_radar is registered in pg_views."""
        url = _get_connection_url()
        with psycopg.connect(url) as conn:
            with conn.cursor() as cur:
                assert _view_exists(
                    cur, "enforcement", "v_radar"
                ), "enforcement.v_radar not found in pg_views"

    def test_v_radar_has_required_columns(self):
        """Verify v_radar exposes the required columns."""
        url = _get_connection_url()
        with psycopg.connect(url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'enforcement'
                      AND table_name = 'v_radar'
                    """
                )
                actual_columns = {row[0] for row in cur.fetchall()}

        missing = REQUIRED_V_RADAR_COLUMNS - actual_columns
        assert not missing, f"v_radar missing columns: {missing}"

    def test_v_radar_returns_rows_after_seed(self):
        """Verify v_radar returns at least one row when seed batch has run."""
        url = _get_connection_url()
        with psycopg.connect(url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM enforcement.v_radar")
                row = cur.fetchone()
                assert row is not None
                count = row[0]
                # If seed has run, we expect at least one row; otherwise skip gracefully
                if count == 0:
                    pytest.skip("No rows in enforcement.v_radar; seed batch may not have run")
                assert count >= 1, f"Expected at least 1 row, got {count}"

    def test_v_radar_offer_strategy_values_valid(self):
        """Verify all offer_strategy values are in the allowed set."""
        url = _get_connection_url()
        with psycopg.connect(url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT DISTINCT offer_strategy
                    FROM enforcement.v_radar
                    """
                )
                strategies = {row[0] for row in cur.fetchall()}

        if not strategies:
            pytest.skip("No data in v_radar to validate offer_strategy values")

        invalid = strategies - VALID_OFFER_STRATEGIES
        assert not invalid, (
            f"Invalid offer_strategy values found: {invalid}. "
            f"Expected one of {VALID_OFFER_STRATEGIES}"
        )


@pytest.mark.integration
class TestEnrichmentHealthView:
    """Tests for ops.v_enrichment_health view."""

    @pytest.fixture(autouse=True)
    def _check_prerequisites(self):
        """Check migrations and view existence.

        - Missing migrations → skip
        - Migrations applied but view missing → fail
        """
        url = _get_connection_url()
        with psycopg.connect(url) as conn:
            with conn.cursor() as cur:
                # First check if migrations have been applied
                _check_migrations_or_skip(cur)

                # Migrations are applied - view MUST exist or it's a failure
                if not _view_exists(cur, "ops", "v_enrichment_health"):
                    pytest.fail(
                        "Expected view ops.v_enrichment_health to exist. "
                        "Migrations are applied but view is missing - check migration files."
                    )

    def test_v_enrichment_health_exists_in_pg_views(self):
        """Verify ops.v_enrichment_health is registered in pg_views."""
        url = _get_connection_url()
        with psycopg.connect(url) as conn:
            with conn.cursor() as cur:
                assert _view_exists(
                    cur, "ops", "v_enrichment_health"
                ), "ops.v_enrichment_health not found in pg_views"

    def test_v_enrichment_health_has_expected_columns(self):
        """Verify v_enrichment_health has the job count columns."""
        expected_columns = {
            "pending_jobs",
            "processing_jobs",
            "failed_jobs",
            "completed_jobs",
        }
        url = _get_connection_url()
        with psycopg.connect(url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'ops'
                      AND table_name = 'v_enrichment_health'
                    """
                )
                actual_columns = {row[0] for row in cur.fetchall()}

        missing = expected_columns - actual_columns
        assert not missing, f"v_enrichment_health missing columns: {missing}"

    def test_v_enrichment_health_returns_single_row(self):
        """Verify v_enrichment_health returns exactly one aggregated row."""
        url = _get_connection_url()
        with psycopg.connect(url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM ops.v_enrichment_health")
                row = cur.fetchone()
                assert row is not None
                count = row[0]
                assert count == 1, f"Expected exactly 1 row from v_enrichment_health, got {count}"

    def test_v_enrichment_health_counts_are_non_negative(self):
        """Verify all job counts are non-negative integers."""
        url = _get_connection_url()
        with psycopg.connect(url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT pending_jobs, processing_jobs, failed_jobs, completed_jobs
                    FROM ops.v_enrichment_health
                    """
                )
                row = cur.fetchone()
                assert row is not None, "v_enrichment_health returned no rows"

                pending, processing, failed, completed = row
                assert pending >= 0, f"pending_jobs is negative: {pending}"
                assert processing >= 0, f"processing_jobs is negative: {processing}"
                assert failed >= 0, f"failed_jobs is negative: {failed}"
                assert completed >= 0, f"completed_jobs is negative: {completed}"
