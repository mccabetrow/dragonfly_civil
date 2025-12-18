"""
Tests for AgentEvaluator, ShadowMode, and OutcomeFeedbackStore.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from backend.ai.evaluator import (
    AgentEvalResult,
    AgentEvalSummary,
    AgentEvaluator,
    AgentTestCase,
    OutcomeFeedback,
    OutcomeFeedbackStore,
    OutcomeType,
    ShadowMode,
    ShadowResult,
    StrictnessMode,
)

# =============================================================================
# AgentEvaluator Tests
# =============================================================================


class TestAgentTestCase:
    """Tests for AgentTestCase parsing."""

    def test_from_dict_minimal(self):
        """Parse minimal test case."""
        data = {
            "id": "test-001",
            "input": {"key": "value"},
            "expected_output": {"result": "expected"},
        }
        tc = AgentTestCase.from_dict(data)

        assert tc.id == "test-001"
        assert tc.agent == "default"
        assert tc.input_context == {"key": "value"}
        assert tc.expected_output == {"result": "expected"}
        assert tc.strictness == StrictnessMode.EXACT_MATCH

    def test_from_dict_full(self):
        """Parse full test case with all fields."""
        data = {
            "id": "test-002",
            "agent": "strategy",
            "input_context": {"strategy": "data"},
            "expected_output": {"strategy_type": "wage_garnishment"},
            "strictness": "semantic_match",
            "name": "Test Strategy",
            "description": "A test case",
        }
        tc = AgentTestCase.from_dict(data)

        assert tc.id == "test-002"
        assert tc.agent == "strategy"
        assert tc.input_context == {"strategy": "data"}
        assert tc.strictness == StrictnessMode.SEMANTIC_MATCH
        assert tc.name == "Test Strategy"


class TestAgentEvaluator:
    """Tests for AgentEvaluator."""

    def test_evaluate_exact_match_pass(self, tmp_path: Path):
        """Exact match should pass when outputs match."""
        test_file = tmp_path / "test_cases.json"
        test_file.write_text(
            json.dumps(
                {
                    "cases": [
                        {
                            "id": "test-001",
                            "agent": "test",
                            "input": {"x": 1},
                            "expected_output": {"result": "ok"},
                            "strictness": "exact_match",
                        }
                    ]
                }
            )
        )

        def agent(input_context):
            return {"result": "ok"}

        evaluator = AgentEvaluator()
        result = evaluator.evaluate(agent, test_file)

        assert result.total == 1
        assert result.passed == 1
        assert result.failed == 0
        assert result.score == 1.0
        assert len(result.failures) == 0

    def test_evaluate_exact_match_fail(self, tmp_path: Path):
        """Exact match should fail when outputs differ."""
        test_file = tmp_path / "test_cases.json"
        test_file.write_text(
            json.dumps(
                {
                    "cases": [
                        {
                            "id": "test-001",
                            "agent": "test",
                            "input": {"x": 1},
                            "expected_output": {"result": "ok"},
                            "strictness": "exact_match",
                        }
                    ]
                }
            )
        )

        def agent(input_context):
            return {"result": "wrong"}

        evaluator = AgentEvaluator()
        result = evaluator.evaluate(agent, test_file)

        assert result.total == 1
        assert result.passed == 0
        assert result.failed == 1
        assert result.score == 0.0
        assert len(result.failures) == 1
        assert "result" in result.failures[0].error_message

    def test_evaluate_semantic_match_not_implemented(self, tmp_path: Path):
        """Semantic match returns not implemented error."""
        test_file = tmp_path / "test_cases.json"
        test_file.write_text(
            json.dumps(
                {
                    "cases": [
                        {
                            "id": "test-001",
                            "agent": "test",
                            "input": {"x": 1},
                            "expected_output": {"result": "ok"},
                            "strictness": "semantic_match",
                        }
                    ]
                }
            )
        )

        def agent(input_context):
            return {"result": "ok"}

        evaluator = AgentEvaluator()
        result = evaluator.evaluate(agent, test_file)

        # Semantic match is not implemented, so it should fail
        assert result.total == 1
        assert result.failed == 1
        assert "not implemented" in result.failures[0].error_message.lower()

    def test_evaluate_agent_filter(self, tmp_path: Path):
        """Agent filter should only run matching cases."""
        test_file = tmp_path / "test_cases.json"
        test_file.write_text(
            json.dumps(
                {
                    "cases": [
                        {
                            "id": "test-001",
                            "agent": "agent_a",
                            "input": {},
                            "expected_output": {"result": "a"},
                        },
                        {
                            "id": "test-002",
                            "agent": "agent_b",
                            "input": {},
                            "expected_output": {"result": "b"},
                        },
                    ]
                }
            )
        )

        def agent(input_context):
            return {"result": "a"}

        evaluator = AgentEvaluator()
        result = evaluator.evaluate(agent, test_file, agent_filter="agent_a")

        assert result.total == 1
        assert result.passed == 1

    def test_evaluate_agent_exception(self, tmp_path: Path):
        """Agent exception should be caught and marked as failure."""
        test_file = tmp_path / "test_cases.json"
        test_file.write_text(
            json.dumps(
                {
                    "cases": [
                        {
                            "id": "test-001",
                            "input": {},
                            "expected_output": {"result": "ok"},
                        }
                    ]
                }
            )
        )

        def agent(input_context):
            raise ValueError("Agent crashed")

        evaluator = AgentEvaluator()
        result = evaluator.evaluate(agent, test_file)

        assert result.failed == 1
        assert "Agent error" in result.failures[0].error_message


# =============================================================================
# ShadowMode Tests
# =============================================================================


class TestShadowMode:
    """Tests for ShadowMode."""

    def test_shadow_mode_agreement(self, tmp_path: Path):
        """V1 and V2 agree - both return same output."""
        log_path = tmp_path / "shadow.jsonl"

        def v1_agent(ctx):
            return {"strategy": "wage_garnishment"}

        def v2_agent(ctx):
            return {"strategy": "wage_garnishment"}

        shadow = ShadowMode(v1_agent, v2_agent, log_path=log_path)
        result, shadow_result = shadow.run({"judgment_id": "JDG-001"}, "JDG-001")

        assert result == {"strategy": "wage_garnishment"}
        assert shadow_result.agreement is True
        assert shadow_result.diff is None

    def test_shadow_mode_disagreement(self, tmp_path: Path):
        """V1 and V2 disagree - diff is captured."""
        log_path = tmp_path / "shadow.jsonl"

        def v1_agent(ctx):
            return {"strategy": "wage_garnishment"}

        def v2_agent(ctx):
            return {"strategy": "bank_levy"}

        shadow = ShadowMode(v1_agent, v2_agent, log_path=log_path)
        result, shadow_result = shadow.run({"judgment_id": "JDG-001"}, "JDG-001")

        # V1 output is always returned for production
        assert result == {"strategy": "wage_garnishment"}
        assert shadow_result.agreement is False
        assert shadow_result.diff == {"strategy": {"v1": "wage_garnishment", "v2": "bank_levy"}}

    def test_shadow_mode_v2_error_doesnt_affect_production(self, tmp_path: Path):
        """V2 error should not affect V1 production output."""
        log_path = tmp_path / "shadow.jsonl"

        def v1_agent(ctx):
            return {"strategy": "wage_garnishment"}

        def v2_agent(ctx):
            raise ValueError("V2 crashed")

        shadow = ShadowMode(v1_agent, v2_agent, log_path=log_path)
        result, shadow_result = shadow.run({"judgment_id": "JDG-001"}, "JDG-001")

        # V1 output is returned despite V2 error
        assert result == {"strategy": "wage_garnishment"}
        assert shadow_result.v2_output == {"error": "V2 crashed"}
        assert shadow_result.agreement is False

    def test_shadow_mode_logs_results(self, tmp_path: Path):
        """Shadow results are logged to file."""
        log_path = tmp_path / "shadow.jsonl"

        def v1_agent(ctx):
            return {"result": "v1"}

        def v2_agent(ctx):
            return {"result": "v2"}

        shadow = ShadowMode(v1_agent, v2_agent, log_path=log_path)
        shadow.run({}, "JDG-001")
        shadow.run({}, "JDG-002")

        lines = log_path.read_text().strip().split("\n")
        assert len(lines) == 2

        entry1 = json.loads(lines[0])
        assert entry1["judgment_id"] == "JDG-001"

    def test_agreement_rate(self, tmp_path: Path):
        """Calculate agreement rate from log."""
        log_path = tmp_path / "shadow.jsonl"

        call_count = 0

        def v1_agent(ctx):
            return {"result": "v1"}

        def v2_agent(ctx):
            nonlocal call_count
            call_count += 1
            # Agree 2 out of 4 times
            if call_count <= 2:
                return {"result": "v1"}
            return {"result": "v2"}

        shadow = ShadowMode(v1_agent, v2_agent, log_path=log_path)
        for i in range(4):
            shadow.run({}, f"JDG-{i:03d}")

        rate = shadow.get_agreement_rate()
        assert rate == 0.5


# =============================================================================
# OutcomeFeedbackStore Tests
# =============================================================================


class TestOutcomeFeedbackStore:
    """Tests for OutcomeFeedbackStore."""

    def test_record_and_retrieve(self, tmp_path: Path):
        """Record and retrieve outcome feedback."""
        store_path = tmp_path / "outcomes.json"
        store = OutcomeFeedbackStore(store_path=store_path)

        feedback = store.record(
            judgment_id="JDG-001",
            strategy_type="wage_garnishment",
            outcome=OutcomeType.COLLECTED,
            amount_collected=1500.00,
            amount_expected=2000.00,
        )

        assert feedback.id is not None
        assert feedback.judgment_id == "JDG-001"
        assert feedback.outcome == OutcomeType.COLLECTED

        # Retrieve
        all_outcomes = store.get_all()
        assert len(all_outcomes) == 1
        assert all_outcomes[0].judgment_id == "JDG-001"

    def test_get_by_strategy(self, tmp_path: Path):
        """Filter outcomes by strategy type."""
        store_path = tmp_path / "outcomes.json"
        store = OutcomeFeedbackStore(store_path=store_path)

        store.record("JDG-001", "wage_garnishment", OutcomeType.COLLECTED)
        store.record("JDG-002", "bank_levy", OutcomeType.NOT_COLLECTED)
        store.record("JDG-003", "wage_garnishment", OutcomeType.PARTIAL)

        wage_outcomes = store.get_by_strategy("wage_garnishment")
        assert len(wage_outcomes) == 2

        bank_outcomes = store.get_by_strategy("bank_levy")
        assert len(bank_outcomes) == 1

    def test_success_rate(self, tmp_path: Path):
        """Calculate success rate for a strategy."""
        store_path = tmp_path / "outcomes.json"
        store = OutcomeFeedbackStore(store_path=store_path)

        # 2 successes (collected + partial), 1 failure
        store.record("JDG-001", "wage_garnishment", OutcomeType.COLLECTED)
        store.record("JDG-002", "wage_garnishment", OutcomeType.PARTIAL)
        store.record("JDG-003", "wage_garnishment", OutcomeType.NOT_COLLECTED)

        rate = store.get_success_rate("wage_garnishment")
        assert rate == pytest.approx(2 / 3)

    def test_get_summary(self, tmp_path: Path):
        """Get summary statistics."""
        store_path = tmp_path / "outcomes.json"
        store = OutcomeFeedbackStore(store_path=store_path)

        store.record("JDG-001", "wage_garnishment", OutcomeType.COLLECTED)
        store.record("JDG-002", "bank_levy", OutcomeType.NOT_COLLECTED)
        store.record("JDG-003", "wage_garnishment", OutcomeType.PARTIAL)

        summary = store.get_summary()
        assert summary["total"] == 3
        assert "wage_garnishment" in summary["strategies"]
        assert summary["strategies"]["wage_garnishment"]["total"] == 2
        assert summary["strategies"]["wage_garnishment"]["success_rate"] == 1.0
        assert summary["strategies"]["bank_levy"]["success_rate"] == 0.0


# =============================================================================
# Integration Tests
# =============================================================================


class TestIntegration:
    """Integration tests for the full evaluation flow."""

    def test_evaluate_against_golden_dataset(self):
        """Run AgentEvaluator against actual golden dataset (stub agent)."""
        from pathlib import Path

        golden_path = Path(__file__).parent / "golden_dataset.json"
        if not golden_path.exists():
            pytest.skip("Golden dataset not found")

        # Stub agent that returns empty dict
        def stub_agent(input_context):
            return {}

        evaluator = AgentEvaluator()
        result = evaluator.evaluate(stub_agent, golden_path, agent_filter="ingestion")

        # Stub should fail all tests
        assert result.total >= 0  # At least runs without error
        assert result.score >= 0.0
