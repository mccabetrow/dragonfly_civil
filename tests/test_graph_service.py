"""
tests/test_graph_service.py
═══════════════════════════════════════════════════════════════════════════════

Unit and integration tests for the Judgment Intelligence Graph service.

Tests cover:
  - Name normalization
  - Entity type inference
  - get_or_create_entity uniqueness
  - End-to-end graph building
"""

import pytest

from backend.services.graph_service import infer_entity_type, normalize_name

# =============================================================================
# Normalization Tests
# =============================================================================


class TestNormalizeName:
    """Tests for the normalize_name function."""

    def test_normalize_basic_name(self):
        """Basic name normalization works."""
        assert normalize_name("John Doe") == "JOHN DOE"

    def test_normalize_trims_whitespace(self):
        """Leading and trailing whitespace is removed."""
        assert normalize_name("  John Doe  ") == "JOHN DOE"

    def test_normalize_collapses_internal_spaces(self):
        """Multiple internal spaces are collapsed to one."""
        assert normalize_name("John    Doe") == "JOHN DOE"

    def test_normalize_handles_tabs_and_newlines(self):
        """Tabs and newlines are treated as spaces."""
        assert normalize_name("John\t\nDoe") == "JOHN DOE"

    def test_normalize_empty_string(self):
        """Empty string returns empty string."""
        assert normalize_name("") == ""

    def test_normalize_none(self):
        """None returns empty string."""
        assert normalize_name(None) == ""

    def test_normalize_whitespace_only(self):
        """Whitespace-only string returns empty string."""
        assert normalize_name("   ") == ""

    def test_normalize_already_uppercase(self):
        """Already uppercase names are unchanged (except spacing)."""
        assert normalize_name("JOHN DOE") == "JOHN DOE"

    def test_normalize_mixed_case(self):
        """Mixed case is uppercased."""
        assert normalize_name("JoHn DoE") == "JOHN DOE"

    def test_normalize_special_characters_preserved(self):
        """Special characters are preserved."""
        assert normalize_name("O'Brien-Smith") == "O'BRIEN-SMITH"

    def test_normalize_numbers_preserved(self):
        """Numbers are preserved."""
        assert normalize_name("Apartment 123") == "APARTMENT 123"


# =============================================================================
# Entity Type Inference Tests
# =============================================================================


class TestInferEntityType:
    """Tests for the infer_entity_type function."""

    def test_person_simple_name(self):
        """Simple names without company indicators are persons."""
        assert infer_entity_type("John Doe") == "person"

    def test_company_llc(self):
        """LLC is detected as company."""
        assert infer_entity_type("Acme LLC") == "company"

    def test_company_llc_dots(self):
        """L.L.C. with dots is detected as company."""
        assert infer_entity_type("Acme L.L.C.") == "company"

    def test_company_inc(self):
        """INC is detected as company."""
        assert infer_entity_type("Acme Inc") == "company"

    def test_company_incorporated(self):
        """INCORPORATED is detected as company."""
        assert infer_entity_type("Acme Incorporated") == "company"

    def test_company_corp(self):
        """CORP is detected as company."""
        assert infer_entity_type("Acme Corp") == "company"

    def test_company_corporation(self):
        """CORPORATION is detected as company."""
        assert infer_entity_type("Acme Corporation") == "company"

    def test_company_ltd(self):
        """LTD is detected as company."""
        assert infer_entity_type("Acme Ltd") == "company"

    def test_company_limited(self):
        """LIMITED is detected as company."""
        assert infer_entity_type("Acme Limited") == "company"

    def test_company_lp(self):
        """LP is detected as company."""
        assert infer_entity_type("Acme Partners LP") == "company"

    def test_company_llp(self):
        """LLP is detected as company."""
        assert infer_entity_type("Acme Law LLP") == "company"

    def test_company_case_insensitive(self):
        """Company detection is case insensitive."""
        assert infer_entity_type("acme llc") == "company"
        assert infer_entity_type("ACME LLC") == "company"
        assert infer_entity_type("Acme Llc") == "company"

    def test_company_holdings(self):
        """HOLDINGS is detected as company."""
        assert infer_entity_type("Acme Holdings") == "company"

    def test_company_group(self):
        """GROUP is detected as company."""
        assert infer_entity_type("Acme Group") == "company"

    def test_company_services(self):
        """SERVICES is detected as company."""
        assert infer_entity_type("Acme Services") == "company"

    def test_company_consulting(self):
        """CONSULTING is detected as company."""
        assert infer_entity_type("Acme Consulting") == "company"

    def test_empty_string_is_person(self):
        """Empty string defaults to person."""
        assert infer_entity_type("") == "person"

    def test_none_is_person(self):
        """None defaults to person."""
        assert infer_entity_type(None) == "person"

    def test_person_with_suffix(self):
        """Names with Jr/Sr/III are persons, not companies."""
        assert infer_entity_type("John Doe Jr.") == "person"
        assert infer_entity_type("John Doe III") == "person"


# =============================================================================
# Integration Tests (require database connection)
# =============================================================================


@pytest.mark.integration
class TestGetOrCreateEntity:
    """Integration tests for get_or_create_entity."""

    @pytest.fixture(autouse=True)
    def _check_db_available(self):
        """Skip if database is not available."""
        try:
            import asyncio

            from backend.db import get_pool

            async def check():
                conn = await get_pool()
                return conn is not None

            # Check synchronously
            if not asyncio.get_event_loop().run_until_complete(check()):
                pytest.skip("Database connection not available")
        except Exception:
            pytest.skip("Database connection not available")

    @pytest.mark.asyncio
    async def test_create_new_entity(self):
        """Creating a new entity returns a UUID."""
        import uuid

        from backend.db import get_pool
        from backend.services.graph_service import get_or_create_entity

        conn = await get_pool()
        if conn is None:
            pytest.skip("Database not available")

        # Use a unique name to avoid conflicts
        unique_name = f"Test Entity {uuid.uuid4()}"

        async with conn.transaction():
            entity_id = await get_or_create_entity(
                name=unique_name,
                entity_type="person",
                conn=conn,
            )

            assert entity_id is not None
            assert isinstance(entity_id, uuid.UUID)

            # Cleanup
            async with conn.cursor() as cur:
                await cur.execute(
                    "DELETE FROM intelligence.entities WHERE id = %s", (entity_id,)
                )

    @pytest.mark.asyncio
    async def test_get_existing_entity(self):
        """Getting an existing entity returns the same UUID."""
        import uuid

        from backend.db import get_pool
        from backend.services.graph_service import get_or_create_entity

        conn = await get_pool()
        if conn is None:
            pytest.skip("Database not available")

        unique_name = f"Test Entity {uuid.uuid4()}"

        async with conn.transaction():
            # Create entity
            entity_id_1 = await get_or_create_entity(
                name=unique_name,
                entity_type="person",
                conn=conn,
            )

            # Get same entity (should return same ID)
            entity_id_2 = await get_or_create_entity(
                name=unique_name,
                entity_type="person",
                conn=conn,
            )

            assert entity_id_1 == entity_id_2

            # Cleanup
            async with conn.cursor() as cur:
                await cur.execute(
                    "DELETE FROM intelligence.entities WHERE id = %s", (entity_id_1,)
                )

    @pytest.mark.asyncio
    async def test_different_types_create_different_entities(self):
        """Same name with different types creates different entities."""
        import uuid

        from backend.db import get_pool
        from backend.services.graph_service import get_or_create_entity

        conn = await get_pool()
        if conn is None:
            pytest.skip("Database not available")

        unique_name = f"Test Entity {uuid.uuid4()}"

        async with conn.transaction():
            # Create as person
            person_id = await get_or_create_entity(
                name=unique_name,
                entity_type="person",
                conn=conn,
            )

            # Create as company (different type)
            company_id = await get_or_create_entity(
                name=unique_name,
                entity_type="company",
                conn=conn,
            )

            assert person_id != company_id

            # Cleanup
            async with conn.cursor() as cur:
                await cur.execute(
                    "DELETE FROM intelligence.entities WHERE id IN (%s, %s)",
                    (person_id, company_id),
                )

    @pytest.mark.asyncio
    async def test_blank_name_returns_none(self):
        """Blank names return None without creating an entity."""
        from backend.db import get_pool
        from backend.services.graph_service import get_or_create_entity

        conn = await get_pool()
        if conn is None:
            pytest.skip("Database not available")

        entity_id = await get_or_create_entity(
            name="",
            entity_type="person",
            conn=conn,
        )

        assert entity_id is None

    @pytest.mark.asyncio
    async def test_none_name_returns_none(self):
        """None names return None without creating an entity."""
        from backend.db import get_pool
        from backend.services.graph_service import get_or_create_entity

        conn = await get_pool()
        if conn is None:
            pytest.skip("Database not available")

        entity_id = await get_or_create_entity(
            name=None,
            entity_type="person",
            conn=conn,
        )

        assert entity_id is None


@pytest.mark.integration
class TestBuildJudgmentGraph:
    """Integration tests for build_judgment_graph."""

    @pytest.fixture(autouse=True)
    def _check_db_available(self):
        """Skip if database is not available."""
        try:
            import asyncio

            from backend.db import get_pool

            async def check():
                conn = await get_pool()
                return conn is not None

            if not asyncio.get_event_loop().run_until_complete(check()):
                pytest.skip("Database connection not available")
        except Exception:
            pytest.skip("Database connection not available")

    @pytest.mark.asyncio
    async def test_build_graph_for_nonexistent_judgment(self):
        """Building graph for nonexistent judgment returns False."""
        from backend.db import get_pool
        from backend.services.graph_service import build_judgment_graph

        conn = await get_pool()
        if conn is None:
            pytest.skip("Database not available")

        # Use a very large ID that shouldn't exist
        result = await build_judgment_graph(999999999, conn)

        assert result is False

    @pytest.mark.asyncio
    async def test_process_judgment_for_graph_handles_errors(self):
        """process_judgment_for_graph never raises, even on error."""
        from backend.services.graph_service import process_judgment_for_graph

        # Should not raise, should return False
        result = await process_judgment_for_graph(999999999)

        assert result is False


@pytest.mark.integration
class TestGetJudgmentGraph:
    """Integration tests for get_judgment_graph."""

    @pytest.mark.asyncio
    async def test_get_graph_for_nonexistent_judgment(self):
        """Getting graph for nonexistent judgment returns empty lists."""
        from backend.services.graph_service import get_judgment_graph

        result = await get_judgment_graph(999999999)

        assert result["judgment_id"] == 999999999
        assert result["entities"] == []
        assert result["relationships"] == []
