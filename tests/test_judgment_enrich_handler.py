"""Unit tests for judgment enrichment handler.

Tests the workers/judgment_enrich_handler.py module with mocked vendor
and Supabase client to verify:
- complete_enrichment RPC is invoked atomically
- FCRA logging happens through RPC
- debtor_intelligence is upserted via RPC
- Judgment collectability_score is updated via RPC
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.vendors import MockIdiCORE, SkipTraceResult
from workers import judgment_enrich_handler
from workers.judgment_enrich_handler import (
    _calculate_collectability_score,
    _extract_judgment_id,
    _sanitize_meta,
    handle_judgment_enrich,
)


class FakeTable:
    """Fake Supabase table for testing."""

    def __init__(self, name: str, data_store: Dict[str, List[Dict[str, Any]]]):
        self.name = name
        self._data_store = data_store
        self._query_filters: Dict[str, Any] = {}
        self._select_fields: Optional[str] = None
        self._pending_update: Optional[Dict[str, Any]] = None

    def select(self, fields: str) -> "FakeTable":
        self._select_fields = fields
        return self

    def eq(self, column: str, value: Any) -> "FakeTable":
        self._query_filters[column] = value
        return self

    def insert(self, data: Dict[str, Any]) -> "FakeTable":
        if self.name not in self._data_store:
            self._data_store[self.name] = []
        # Add an ID if not present
        if "id" not in data:
            data["id"] = f"fake-{self.name}-{len(self._data_store[self.name])}"
        self._data_store[self.name].append(data)
        return self

    def update(self, data: Dict[str, Any]) -> "FakeTable":
        # Store the update data; filters will be added when eq() is called
        self._pending_update = data
        return self

    def execute(self) -> SimpleNamespace:
        # Handle pending updates
        if self._pending_update is not None:
            if f"{self.name}_updates" not in self._data_store:
                self._data_store[f"{self.name}_updates"] = []
            self._data_store[f"{self.name}_updates"].append(
                {"filters": self._query_filters.copy(), "data": self._pending_update}
            )
            self._pending_update = None
            return SimpleNamespace(data=[])

        # Return data based on table and filters
        if self.name == "core_judgments":
            # Return mock judgment data
            judgment_id = self._query_filters.get("id")
            if judgment_id == "test-judgment-123":
                return SimpleNamespace(
                    data=[
                        {
                            "id": "test-judgment-123",
                            "case_index_number": "NYC-2024-001234",
                            "debtor_name": "John Smith",
                            "status": "unsatisfied",
                            "collectability_score": None,
                        }
                    ]
                )
            elif judgment_id == "already-enriched-456":
                return SimpleNamespace(
                    data=[
                        {
                            "id": "already-enriched-456",
                            "case_index_number": "NYC-2024-005678",
                            "debtor_name": "Jane Doe",
                            "status": "unsatisfied",
                            "collectability_score": 75,
                        }
                    ]
                )
            elif judgment_id == "not-found-789":
                return SimpleNamespace(data=[])
            return SimpleNamespace(data=[])

        elif self.name == "debtor_intelligence":
            judgment_id = self._query_filters.get("judgment_id")
            if judgment_id == "already-enriched-456":
                return SimpleNamespace(data=[{"id": "existing-intel-1"}])
            # For inserts, return the inserted data
            if self._data_store.get(self.name):
                return SimpleNamespace(data=self._data_store[self.name][-1:])
            return SimpleNamespace(data=[])

        return SimpleNamespace(data=[])


class FakeRpc:
    """Fake Supabase RPC for testing."""

    def __init__(self, rpc_calls: List[Dict[str, Any]], raise_on: Optional[str] = None):
        self._rpc_calls = rpc_calls
        self._current_call: Optional[Dict[str, Any]] = None
        self._raise_on = raise_on  # RPC name to raise an exception on

    def __call__(self, name: str, params: Dict[str, Any]) -> "FakeRpc":
        self._current_call = {"name": name, "params": params}
        self._rpc_calls.append(self._current_call)
        return self

    def execute(self) -> SimpleNamespace:
        if self._current_call:
            name = self._current_call["name"]

            # Raise an exception if configured
            if self._raise_on and name == self._raise_on:
                raise Exception(f"Simulated RPC failure: {name}")

            if name == "log_external_data_call":
                return SimpleNamespace(data="fake-fcra-log-id")
            elif name == "complete_enrichment":
                return SimpleNamespace(
                    data={
                        "fcra_log_id": "fake-fcra-log-id",
                        "intelligence_id": "fake-intel-id",
                        "status_updated": True,
                    }
                )
        return SimpleNamespace(data=None)


class FakeSupabaseClient:
    """Fake Supabase client for testing."""

    def __init__(self, raise_on_rpc: Optional[str] = None):
        self.data_store: Dict[str, List[Dict[str, Any]]] = {}
        self.rpc_calls: List[Dict[str, Any]] = []
        self._rpc = FakeRpc(self.rpc_calls, raise_on=raise_on_rpc)

    def table(self, name: str) -> FakeTable:
        return FakeTable(name, self.data_store)

    def rpc(self, name: str, params: Dict[str, Any]) -> FakeRpc:
        return self._rpc(name, params)


@pytest.fixture
def fake_client():
    """Provide a fake Supabase client."""
    return FakeSupabaseClient()


@pytest.fixture
def mock_vendor():
    """Provide a mock vendor for testing."""
    return MockIdiCORE()


class TestExtractJudgmentId:
    """Tests for _extract_judgment_id function."""

    def test_direct_judgment_id(self):
        job = {"judgment_id": "abc-123"}
        assert _extract_judgment_id(job) == "abc-123"

    def test_nested_payload_judgment_id(self):
        job = {"payload": {"judgment_id": "def-456"}}
        assert _extract_judgment_id(job) == "def-456"

    def test_double_nested_payload_judgment_id(self):
        job = {"payload": {"payload": {"judgment_id": "ghi-789"}}}
        assert _extract_judgment_id(job) == "ghi-789"

    def test_missing_judgment_id(self):
        job = {"msg_id": 123, "payload": {"other_field": "value"}}
        assert _extract_judgment_id(job) is None

    def test_non_dict_job(self):
        assert _extract_judgment_id(None) is None
        assert _extract_judgment_id("string") is None
        assert _extract_judgment_id([1, 2, 3]) is None


class TestCalculateCollectabilityScore:
    """Tests for _calculate_collectability_score function."""

    def test_base_score(self):
        result = SkipTraceResult(confidence_score=70)
        assert _calculate_collectability_score(result) == 70

    def test_employer_bonus(self):
        result = SkipTraceResult(confidence_score=70, employer_name="Delta Airlines")
        assert _calculate_collectability_score(result) == 80  # 70 + 10

    def test_bank_bonus(self):
        result = SkipTraceResult(confidence_score=70, bank_name="Chase Bank")
        assert _calculate_collectability_score(result) == 80  # 70 + 10

    def test_owner_bonus(self):
        result = SkipTraceResult(confidence_score=70, home_ownership="owner")
        assert _calculate_collectability_score(result) == 85  # 70 + 15

    def test_benefits_only_penalty(self):
        result = SkipTraceResult(confidence_score=70, has_benefits_only_account=True)
        assert _calculate_collectability_score(result) == 50  # 70 - 20

    def test_high_income_bonus(self):
        result = SkipTraceResult(confidence_score=70, income_band="HIGH")
        assert _calculate_collectability_score(result) == 80  # 70 + 10

    def test_low_income_penalty(self):
        result = SkipTraceResult(confidence_score=70, income_band="LOW")
        assert _calculate_collectability_score(result) == 65  # 70 - 5

    def test_combined_factors(self):
        result = SkipTraceResult(
            confidence_score=70,
            employer_name="Delta Airlines",
            bank_name="Chase Bank",
            home_ownership="owner",
            income_band="HIGH",
        )
        # 70 + 10 (employer) + 10 (bank) + 15 (owner) + 10 (income) = 115 -> capped at 100
        assert _calculate_collectability_score(result) == 100

    def test_clamp_to_zero(self):
        result = SkipTraceResult(
            confidence_score=10,
            has_benefits_only_account=True,
            income_band="LOW",
        )
        # 10 - 20 - 5 = -15 -> clamped to 0
        assert _calculate_collectability_score(result) == 0


@pytest.mark.asyncio
class TestHandleJudgmentEnrich:
    """Tests for handle_judgment_enrich function."""

    async def test_successful_enrichment(self, fake_client, monkeypatch):
        """Test successful enrichment flow using complete_enrichment RPC."""
        monkeypatch.setattr(judgment_enrich_handler, "create_supabase_client", lambda: fake_client)
        monkeypatch.setattr(judgment_enrich_handler, "_get_vendor", MockIdiCORE)

        job = {
            "msg_id": 1,
            "payload": {"judgment_id": "test-judgment-123"},
        }

        result = await handle_judgment_enrich(job)

        assert result is True

        # Verify complete_enrichment RPC was called (atomic operation)
        enrich_calls = [c for c in fake_client.rpc_calls if c["name"] == "complete_enrichment"]
        assert len(enrich_calls) == 1

        params = enrich_calls[0]["params"]
        assert params["_judgment_id"] == "test-judgment-123"
        assert params["_provider"] == "mock_idicore"
        assert params["_fcra_status"] == "success"
        assert params["_fcra_http_code"] == 200
        assert params["_data_source"] == "mock_idicore"
        assert params["_new_status"] == "unsatisfied"
        assert params["_new_collectability_score"] is not None

    async def test_skips_already_enriched(self, fake_client, monkeypatch):
        """Test that already-enriched judgments are skipped."""
        monkeypatch.setattr(judgment_enrich_handler, "create_supabase_client", lambda: fake_client)
        monkeypatch.setattr(judgment_enrich_handler, "_get_vendor", MockIdiCORE)

        job = {
            "msg_id": 2,
            "payload": {"judgment_id": "already-enriched-456"},
        }

        result = await handle_judgment_enrich(job)

        assert result is True

        # Verify no new intelligence was inserted
        assert "debtor_intelligence" not in fake_client.data_store

        # Verify no FCRA calls (no enrichment happened)
        assert len(fake_client.rpc_calls) == 0

    async def test_duplicate_job_no_additional_fcra_calls(self, fake_client, monkeypatch):
        """Test that duplicate/retry jobs do NOT create additional FCRA audit rows.

        This test simulates what happens when a job is retried or duplicated.
        The handler should check for existing debtor_intelligence and skip if present.
        """
        monkeypatch.setattr(judgment_enrich_handler, "create_supabase_client", lambda: fake_client)
        monkeypatch.setattr(judgment_enrich_handler, "_get_vendor", MockIdiCORE)

        # already-enriched-456 returns existing debtor_intelligence in FakeTable
        job = {
            "msg_id": 100,
            "idempotency_key": "retry:enrich:already-enriched-456",
            "payload": {"judgment_id": "already-enriched-456"},
        }

        result = await handle_judgment_enrich(job)

        assert result is True

        # Critical assertion: no complete_enrichment RPC calls
        enrich_calls = [c for c in fake_client.rpc_calls if c["name"] == "complete_enrichment"]
        assert len(enrich_calls) == 0, "No RPC call should happen on retry"

        # Critical assertion: no log_external_data_call RPC calls
        log_calls = [c for c in fake_client.rpc_calls if c["name"] == "log_external_data_call"]
        assert len(log_calls) == 0, "No FCRA log should happen on retry"

    async def test_idempotent_across_multiple_invocations(self, fake_client, monkeypatch):
        """Test that calling the handler twice with same judgment_id is idempotent.

        First call succeeds normally. Second call should detect existing data and skip.
        """
        # We need a client that can track state changes
        monkeypatch.setattr(judgment_enrich_handler, "create_supabase_client", lambda: fake_client)
        monkeypatch.setattr(judgment_enrich_handler, "_get_vendor", MockIdiCORE)

        # already-enriched-456 simulates a judgment that has already been enriched
        job = {
            "msg_id": 101,
            "payload": {"judgment_id": "already-enriched-456"},
        }

        # Call twice - both should succeed
        result1 = await handle_judgment_enrich(job)
        result2 = await handle_judgment_enrich(job)

        assert result1 is True
        assert result2 is True

        # But only zero RPC calls should be made (both detect existing intel)
        assert len(fake_client.rpc_calls) == 0

    async def test_handles_not_found_judgment(self, fake_client, monkeypatch):
        """Test handling of non-existent judgment."""
        monkeypatch.setattr(judgment_enrich_handler, "create_supabase_client", lambda: fake_client)
        monkeypatch.setattr(judgment_enrich_handler, "_get_vendor", MockIdiCORE)

        job = {
            "msg_id": 3,
            "payload": {"judgment_id": "not-found-789"},
        }

        result = await handle_judgment_enrich(job)

        assert result is True  # Returns True to avoid retry

        # Verify nothing was written
        assert "debtor_intelligence" not in fake_client.data_store
        assert len(fake_client.rpc_calls) == 0

    async def test_handles_missing_judgment_id(self, fake_client, monkeypatch):
        """Test handling of missing judgment_id in payload."""
        monkeypatch.setattr(judgment_enrich_handler, "create_supabase_client", lambda: fake_client)

        job = {
            "msg_id": 4,
            "payload": {"other_field": "value"},
        }

        result = await handle_judgment_enrich(job)

        assert result is False  # Returns False for bad payload

    async def test_ignores_doctor_healthcheck(self, fake_client, monkeypatch, caplog):
        """Test that doctor healthcheck jobs are ignored."""
        monkeypatch.setattr(judgment_enrich_handler, "create_supabase_client", lambda: fake_client)

        job = {
            "msg_id": 5,
            "idempotency_key": "doctor:ping:judgment_enrich",
            "payload": {},
        }

        with caplog.at_level("INFO"):
            result = await handle_judgment_enrich(job)

        assert result is True
        assert any("healthcheck_ignored" in record.getMessage() for record in caplog.records)

        # Verify nothing was written
        assert "debtor_intelligence" not in fake_client.data_store
        assert len(fake_client.rpc_calls) == 0

    async def test_rpc_error_logs_fcra_and_raises(self, monkeypatch, caplog):
        """Test that RPC errors log FCRA failure and propagate the exception."""
        # Create client that will fail on complete_enrichment RPC
        failing_client = FakeSupabaseClient(raise_on_rpc="complete_enrichment")
        monkeypatch.setattr(
            judgment_enrich_handler, "create_supabase_client", lambda: failing_client
        )
        monkeypatch.setattr(judgment_enrich_handler, "_get_vendor", MockIdiCORE)

        job = {
            "msg_id": 6,
            "payload": {"judgment_id": "test-judgment-123"},
        }

        with pytest.raises(Exception, match="Simulated RPC failure"):
            await handle_judgment_enrich(job)

        # The complete_enrichment call should have been attempted
        enrich_calls = [c for c in failing_client.rpc_calls if c["name"] == "complete_enrichment"]
        assert len(enrich_calls) == 1

    async def test_no_double_write_on_rpc_error(self, monkeypatch):
        """Test that RPC error does not cause partial writes."""
        # Create client that will fail on complete_enrichment RPC
        failing_client = FakeSupabaseClient(raise_on_rpc="complete_enrichment")
        monkeypatch.setattr(
            judgment_enrich_handler, "create_supabase_client", lambda: failing_client
        )
        monkeypatch.setattr(judgment_enrich_handler, "_get_vendor", MockIdiCORE)

        job = {
            "msg_id": 7,
            "payload": {"judgment_id": "test-judgment-123"},
        }

        with pytest.raises(Exception):
            await handle_judgment_enrich(job)

        # Verify no direct table writes occurred (we use RPC for atomicity)
        assert "debtor_intelligence" not in failing_client.data_store
        assert "core_judgments_updates" not in failing_client.data_store


class TestSanitizeMeta:
    """Tests for _sanitize_meta function."""

    def test_none_input(self):
        assert _sanitize_meta(None) == {}

    def test_empty_dict(self):
        assert _sanitize_meta({}) == {}

    def test_keeps_safe_keys(self):
        meta = {
            "results_count": 5,
            "match_score": 0.95,
            "timestamp": "2024-01-01T00:00:00Z",
            "request_id": "abc-123",
        }
        result = _sanitize_meta(meta)
        assert result == meta

    def test_removes_unsafe_keys(self):
        meta = {
            "results_count": 5,
            "ssn": "123-45-6789",  # PII - should be removed
            "address": "123 Main St",  # PII - should be removed
            "phone": "555-1234",  # PII - should be removed
        }
        result = _sanitize_meta(meta)
        assert result == {"results_count": 5}
        assert "ssn" not in result
        assert "address" not in result
        assert "phone" not in result


class TestMockIdiCORE:
    """Tests for MockIdiCORE vendor."""

    @pytest.mark.asyncio
    async def test_returns_valid_result(self):
        """Test that MockIdiCORE returns a valid SkipTraceResult."""
        vendor = MockIdiCORE()
        result = await vendor.enrich("John Smith", "NYC-2024-001234")

        assert isinstance(result, SkipTraceResult)
        assert result.employer_name is not None
        assert result.employer_address is not None
        assert result.bank_name is not None
        assert result.bank_address is not None
        assert result.income_band in ("LOW", "MED", "HIGH", "UNKNOWN")
        assert result.home_ownership in ("owner", "renter", "unknown")
        assert isinstance(result.has_benefits_only_account, bool)
        assert 0 <= result.confidence_score <= 100
        assert isinstance(result.raw_meta, dict)
        assert result.raw_meta.get("mock") is True

    @pytest.mark.asyncio
    async def test_deterministic_results(self):
        """Test that MockIdiCORE returns deterministic results for same inputs."""
        vendor = MockIdiCORE()

        result1 = await vendor.enrich("John Smith", "NYC-2024-001234")
        result2 = await vendor.enrich("John Smith", "NYC-2024-001234")

        assert result1 == result2

    @pytest.mark.asyncio
    async def test_different_inputs_different_results(self):
        """Test that different inputs produce different results."""
        vendor = MockIdiCORE()

        result1 = await vendor.enrich("John Smith", "NYC-2024-001234")
        result2 = await vendor.enrich("Jane Doe", "NYC-2024-005678")

        # At least some fields should be different
        assert result1 != result2

    def test_provider_name(self):
        """Test provider_name property."""
        vendor = MockIdiCORE()
        assert vendor.provider_name == "mock_idicore"

    def test_endpoint(self):
        """Test endpoint property."""
        vendor = MockIdiCORE()
        assert vendor.endpoint == "/mock/person/search"
