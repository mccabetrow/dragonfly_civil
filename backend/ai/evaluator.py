"""
Dragonfly Engine - AI/ML Evaluator

Regression testing framework for ingestion normalization, strategy selection, and agent evaluation.
Loads golden dataset cases and validates that production logic matches expected outputs.

Usage:
    python -m backend.ai.evaluator
    python -m backend.ai.evaluator --strict  # Exit 1 if any failures
    python -m backend.ai.evaluator --agents  # Run agent evaluations

Components:
    - GoldenDataset: Loads and parses golden_dataset.json
    - Evaluator: Runs test cases and compares results (legacy)
    - AgentEvaluator: Runs agent callables against test files
    - EvalResult: Contains pass/fail status and scoring
    - ShadowMode: V2 runs side-by-side without affecting production
    - OutcomeFeedbackStore: Structured store for collections/no-collections feedback

Decision Tree Reference (Strategy):
    1. IF employer found → Wage Garnishment
    2. ELIF bank_name found → Bank Levy
    3. ELIF home_ownership = 'owner' → Property Lien
    4. ELSE → Surveillance
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional, Protocol, TypeVar

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.core.logging import configure_worker_logging
from backend.workers.ingest_processor import (
    _clean_currency,
    _map_simplicity_row,
    _parse_simplicity_date,
)
from backend.workers.smart_strategy import (
    DebtorIntelligence,
    SmartStrategy,
    StrategyDecision,
    StrategyType,
)

# Configure logging (INFO->stdout, WARNING+->stderr)
logger = configure_worker_logging("evaluator")

# Path to golden dataset
GOLDEN_DATASET_PATH = Path(__file__).parent.parent.parent / "tests" / "ai" / "golden_dataset.json"

# Path to outcome feedback store
OUTCOME_STORE_PATH = Path(__file__).parent.parent.parent / "state" / "outcome_feedback.json"


# =============================================================================
# Enums and Types
# =============================================================================


class StrictnessMode(str, Enum):
    """Comparison strictness for test cases."""

    EXACT_MATCH = "exact_match"
    SEMANTIC_MATCH = "semantic_match"


class OutcomeType(str, Enum):
    """Outcome types for collections feedback."""

    COLLECTED = "collected"
    NOT_COLLECTED = "not_collected"
    PARTIAL = "partial"
    PENDING = "pending"


# Type alias for agent callables
AgentCallable = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass
class CaseResult:
    """Result of evaluating a single test case."""

    case_id: str
    case_name: str
    category: str
    passed: bool
    expected: Any
    actual: Any
    error_message: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "case_name": self.case_name,
            "category": self.category,
            "passed": self.passed,
            "expected": self.expected,
            "actual": self.actual,
            "error_message": self.error_message,
        }


@dataclass
class EvalResult:
    """Aggregated evaluation results."""

    total_cases: int
    passed_cases: int
    failed_cases: int
    score: float  # 0.0 to 1.0
    case_results: list[CaseResult] = field(default_factory=list)
    run_timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    )

    @property
    def all_passed(self) -> bool:
        return self.failed_cases == 0 and self.total_cases > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_cases": self.total_cases,
            "passed_cases": self.passed_cases,
            "failed_cases": self.failed_cases,
            "score": self.score,
            "all_passed": self.all_passed,
            "run_timestamp": self.run_timestamp,
            "case_results": [c.to_dict() for c in self.case_results],
        }

    def summary(self) -> str:
        """Generate human-readable summary."""
        lines = [
            "=" * 60,
            "GOLDEN DATASET EVALUATION RESULTS",
            "=" * 60,
            f"Timestamp: {self.run_timestamp}",
            f"Total Cases: {self.total_cases}",
            f"Passed: {self.passed_cases}",
            f"Failed: {self.failed_cases}",
            f"Score: {self.score:.2%}",
            "-" * 60,
        ]

        for result in self.case_results:
            status = "PASS" if result.passed else "FAIL"
            lines.append(f"[{status}] {result.case_id}: {result.case_name}")
            if not result.passed and result.error_message:
                lines.append(f"       Error: {result.error_message}")

        lines.append("=" * 60)
        return "\n".join(lines)


class GoldenDataset:
    """Loader and parser for golden_dataset.json."""

    def __init__(self, path: Path = GOLDEN_DATASET_PATH):
        self.path = path
        self._data: Optional[dict] = None

    def load(self) -> dict:
        """Load the golden dataset from JSON."""
        if self._data is None:
            if not self.path.exists():
                raise FileNotFoundError(f"Golden dataset not found: {self.path}")

            with open(self.path, "r", encoding="utf-8") as f:
                self._data = json.load(f)

        return self._data

    @property
    def cases(self) -> list[dict]:
        """Get all test cases."""
        return self.load().get("cases", [])

    @property
    def metadata(self) -> dict:
        """Get dataset metadata."""
        return self.load().get("metadata", {})

    def get_cases_by_category(self, category: str) -> list[dict]:
        """Filter cases by category (ingestion, strategy)."""
        return [c for c in self.cases if c.get("category") == category]


class Evaluator:
    """
    Golden Dataset Evaluator

    Runs production logic against golden dataset cases and computes pass/fail scores.
    """

    def __init__(self, dataset: Optional[GoldenDataset] = None):
        self.dataset = dataset or GoldenDataset()

    def evaluate_all(self) -> EvalResult:
        """Run all test cases and return aggregated results."""
        case_results: list[CaseResult] = []

        for case in self.dataset.cases:
            try:
                result = self._evaluate_case(case)
                case_results.append(result)
            except Exception as e:
                # Unexpected error - mark as failed
                case_results.append(
                    CaseResult(
                        case_id=case.get("id", "unknown"),
                        case_name=case.get("name", "unknown"),
                        category=case.get("category", "unknown"),
                        passed=False,
                        expected=case.get("expected_output"),
                        actual=None,
                        error_message=f"Evaluation error: {e}",
                    )
                )

        passed = sum(1 for r in case_results if r.passed)
        failed = len(case_results) - passed
        score = passed / len(case_results) if case_results else 0.0

        return EvalResult(
            total_cases=len(case_results),
            passed_cases=passed,
            failed_cases=failed,
            score=score,
            case_results=case_results,
        )

    def _evaluate_case(self, case: dict) -> CaseResult:
        """Evaluate a single test case."""
        category = case.get("category", "")

        if category == "ingestion":
            return self._evaluate_ingestion_case(case)
        elif category == "strategy":
            return self._evaluate_strategy_case(case)
        else:
            return CaseResult(
                case_id=case.get("id", "unknown"),
                case_name=case.get("name", "unknown"),
                category=category,
                passed=False,
                expected=case.get("expected_output"),
                actual=None,
                error_message=f"Unknown category: {category}",
            )

    def _evaluate_ingestion_case(self, case: dict) -> CaseResult:
        """Evaluate an ingestion normalization case."""
        import pandas as pd

        case_id = case.get("id", "unknown")
        case_name = case.get("name", "unknown")
        expected = case.get("expected_output", {})
        input_data = case.get("input", {})
        csv_row = input_data.get("csv_row", {})

        try:
            # Create a pandas Series from the CSV row
            row = pd.Series(csv_row)

            # Run the actual ingestion mapper
            actual = _map_simplicity_row(row)

            # Convert Decimal to string for comparison
            if "judgment_amount" in actual and actual["judgment_amount"] is not None:
                actual["judgment_amount"] = str(actual["judgment_amount"])

            # Compare expected vs actual
            passed, error_msg = self._compare_ingestion_output(expected, actual)

            return CaseResult(
                case_id=case_id,
                case_name=case_name,
                category="ingestion",
                passed=passed,
                expected=expected,
                actual=actual,
                error_message=error_msg,
            )

        except Exception as e:
            return CaseResult(
                case_id=case_id,
                case_name=case_name,
                category="ingestion",
                passed=False,
                expected=expected,
                actual=None,
                error_message=str(e),
            )

    def _compare_ingestion_output(self, expected: dict, actual: dict) -> tuple[bool, Optional[str]]:
        """Compare expected vs actual ingestion output."""
        mismatches = []

        for key, expected_val in expected.items():
            actual_val = actual.get(key)

            # Handle None comparisons
            if expected_val is None:
                if actual_val is not None:
                    mismatches.append(f"{key}: expected None, got {actual_val!r}")
                continue

            if actual_val is None:
                mismatches.append(f"{key}: expected {expected_val!r}, got None")
                continue

            # String comparison
            if str(expected_val) != str(actual_val):
                mismatches.append(f"{key}: expected {expected_val!r}, got {actual_val!r}")

        if mismatches:
            return False, "; ".join(mismatches)

        return True, None

    def _evaluate_strategy_case(self, case: dict) -> CaseResult:
        """Evaluate a strategy selection case."""
        from unittest.mock import MagicMock

        case_id = case.get("id", "unknown")
        case_name = case.get("name", "unknown")
        expected = case.get("expected_output", {})
        input_data = case.get("input", {})
        intel_data = input_data.get("debtor_intelligence", {})

        try:
            # Create DebtorIntelligence from input data
            intel = DebtorIntelligence(
                judgment_id=intel_data.get("judgment_id", "test-id"),
                employer_name=intel_data.get("employer_name"),
                employer_address=intel_data.get("employer_address"),
                income_band=intel_data.get("income_band"),
                bank_name=intel_data.get("bank_name"),
                bank_address=intel_data.get("bank_address"),
                home_ownership=intel_data.get("home_ownership"),
                has_benefits_only_account=intel_data.get("has_benefits_only_account", False),
            )

            # Create SmartStrategy with mock connection (we only test decide(), not DB ops)
            mock_conn = MagicMock()
            strategy = SmartStrategy(mock_conn)

            # Run the decision logic
            decision = strategy.decide(intel, intel.judgment_id)

            actual = {
                "strategy_type": decision.strategy_type.value,
                "strategy_reason": decision.strategy_reason,
            }

            # Compare expected vs actual
            passed, error_msg = self._compare_strategy_output(expected, actual)

            return CaseResult(
                case_id=case_id,
                case_name=case_name,
                category="strategy",
                passed=passed,
                expected=expected,
                actual=actual,
                error_message=error_msg,
            )

        except Exception as e:
            return CaseResult(
                case_id=case_id,
                case_name=case_name,
                category="strategy",
                passed=False,
                expected=expected,
                actual=None,
                error_message=str(e),
            )

    def _compare_strategy_output(self, expected: dict, actual: dict) -> tuple[bool, Optional[str]]:
        """Compare expected vs actual strategy output."""
        errors = []

        # Check strategy_type exactly
        expected_type = expected.get("strategy_type")
        actual_type = actual.get("strategy_type")
        if expected_type and expected_type != actual_type:
            errors.append(f"strategy_type: expected {expected_type!r}, got {actual_type!r}")

        # Check strategy_reason_contains (partial match)
        reason_contains = expected.get("strategy_reason_contains", [])
        actual_reason = actual.get("strategy_reason", "")
        for substring in reason_contains:
            if substring.lower() not in actual_reason.lower():
                errors.append(f"strategy_reason missing: {substring!r}")

        if errors:
            return False, "; ".join(errors)

        return True, None


# =============================================================================
# AgentEvaluator - Generic agent evaluation framework
# =============================================================================


@dataclass
class AgentTestCase:
    """A single test case for agent evaluation."""

    id: str
    agent: str
    input_context: dict[str, Any]
    expected_output: dict[str, Any]
    strictness: StrictnessMode = StrictnessMode.EXACT_MATCH
    name: Optional[str] = None
    description: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentTestCase":
        """Parse from golden dataset JSON."""
        return cls(
            id=data["id"],
            agent=data.get("agent", "default"),
            # Support both 'input_context' and legacy 'input'
            input_context=data.get("input_context") or data.get("input", {}),
            expected_output=data.get("expected_output", {}),
            strictness=StrictnessMode(data.get("strictness", "exact_match")),
            name=data.get("name"),
            description=data.get("description"),
        )


@dataclass
class AgentEvalResult:
    """Result of evaluating a single agent test case."""

    case_id: str
    agent: str
    passed: bool
    expected: dict[str, Any]
    actual: Optional[dict[str, Any]]
    strictness: StrictnessMode
    error_message: Optional[str] = None
    execution_time_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "agent": self.agent,
            "passed": self.passed,
            "expected": self.expected,
            "actual": self.actual,
            "strictness": self.strictness.value,
            "error_message": self.error_message,
            "execution_time_ms": self.execution_time_ms,
        }


@dataclass
class AgentEvalSummary:
    """Aggregated results from agent evaluation."""

    total: int
    passed: int
    failed: int
    score: float
    failures: list[AgentEvalResult]
    all_results: list[AgentEvalResult] = field(default_factory=list)
    run_timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "score": self.score,
            "failures": [f.to_dict() for f in self.failures],
            "run_timestamp": self.run_timestamp,
        }


class AgentEvaluator:
    """
    Generic agent evaluation framework.

    Evaluates any agent callable against a test file (golden dataset JSON).
    Supports exact_match and semantic_match comparison modes.

    Usage:
        evaluator = AgentEvaluator()

        def my_agent(input_context: dict) -> dict:
            # Agent implementation
            return {"result": "value"}

        result = evaluator.evaluate(my_agent, "tests/ai/golden_dataset.json")
        print(f"Score: {result.score:.2%}")
    """

    def evaluate(
        self,
        agent_callable: AgentCallable,
        test_file: str | Path,
        agent_filter: Optional[str] = None,
    ) -> AgentEvalSummary:
        """
        Evaluate an agent against a test file.

        Args:
            agent_callable: Function that takes input_context dict and returns output dict
            test_file: Path to JSON file with test cases
            agent_filter: Optional agent name to filter test cases

        Returns:
            AgentEvalSummary with score and failures
        """
        import time

        test_path = Path(test_file)
        if not test_path.exists():
            raise FileNotFoundError(f"Test file not found: {test_path}")

        with open(test_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        cases = data.get("cases", [])
        test_cases = [AgentTestCase.from_dict(c) for c in cases]

        # Filter by agent if specified
        if agent_filter:
            test_cases = [tc for tc in test_cases if tc.agent == agent_filter]

        results: list[AgentEvalResult] = []
        for tc in test_cases:
            start = time.perf_counter()
            try:
                actual = agent_callable(tc.input_context)
                exec_time = (time.perf_counter() - start) * 1000

                passed, error = self._compare(tc.expected_output, actual, tc.strictness)
                results.append(
                    AgentEvalResult(
                        case_id=tc.id,
                        agent=tc.agent,
                        passed=passed,
                        expected=tc.expected_output,
                        actual=actual,
                        strictness=tc.strictness,
                        error_message=error,
                        execution_time_ms=exec_time,
                    )
                )
            except Exception as e:
                exec_time = (time.perf_counter() - start) * 1000
                results.append(
                    AgentEvalResult(
                        case_id=tc.id,
                        agent=tc.agent,
                        passed=False,
                        expected=tc.expected_output,
                        actual=None,
                        strictness=tc.strictness,
                        error_message=f"Agent error: {e}",
                        execution_time_ms=exec_time,
                    )
                )

        passed_count = sum(1 for r in results if r.passed)
        failed_count = len(results) - passed_count
        score = passed_count / len(results) if results else 0.0
        failures = [r for r in results if not r.passed]

        return AgentEvalSummary(
            total=len(results),
            passed=passed_count,
            failed=failed_count,
            score=score,
            failures=failures,
            all_results=results,
        )

    def _compare(
        self,
        expected: dict[str, Any],
        actual: dict[str, Any],
        strictness: StrictnessMode,
    ) -> tuple[bool, Optional[str]]:
        """Compare expected vs actual output based on strictness mode."""
        if strictness == StrictnessMode.EXACT_MATCH:
            return self._exact_match(expected, actual)
        elif strictness == StrictnessMode.SEMANTIC_MATCH:
            return self._semantic_match(expected, actual)
        else:
            return False, f"Unknown strictness mode: {strictness}"

    def _exact_match(
        self, expected: dict[str, Any], actual: dict[str, Any]
    ) -> tuple[bool, Optional[str]]:
        """Perform exact key-by-key comparison."""
        mismatches: list[str] = []

        for key, expected_val in expected.items():
            actual_val = actual.get(key)

            # Handle None comparisons
            if expected_val is None:
                if actual_val is not None:
                    mismatches.append(f"{key}: expected None, got {actual_val!r}")
                continue

            if actual_val is None:
                mismatches.append(f"{key}: expected {expected_val!r}, got None")
                continue

            # Handle _contains suffix for partial match
            if key.endswith("_contains") and isinstance(expected_val, list):
                base_key = key[:-9]  # Remove "_contains"
                actual_str = str(actual.get(base_key, ""))
                for substring in expected_val:
                    if str(substring).lower() not in actual_str.lower():
                        mismatches.append(f"{base_key} missing: {substring!r}")
                continue

            # Standard comparison (convert to string for consistent comparison)
            if str(expected_val) != str(actual_val):
                mismatches.append(f"{key}: expected {expected_val!r}, got {actual_val!r}")

        if mismatches:
            return False, "; ".join(mismatches)
        return True, None

    def _semantic_match(
        self, expected: dict[str, Any], actual: dict[str, Any]
    ) -> tuple[bool, Optional[str]]:
        """
        Semantic comparison (placeholder).

        TODO: Implement semantic similarity using embeddings or LLM.
        For now, returns 'not implemented' to avoid fake scoring.
        """
        return (
            False,
            "semantic_match not implemented - use exact_match or implement semantic comparison",
        )


# =============================================================================
# Shadow Mode - V2 runs side-by-side without affecting production
# =============================================================================


@dataclass
class ShadowResult:
    """Result of a shadow mode comparison."""

    judgment_id: str
    v1_output: dict[str, Any]
    v2_output: dict[str, Any]
    agreement: bool
    diff: Optional[dict[str, Any]] = None
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "judgment_id": self.judgment_id,
            "v1_output": self.v1_output,
            "v2_output": self.v2_output,
            "agreement": self.agreement,
            "diff": self.diff,
            "timestamp": self.timestamp,
        }


class ShadowMode:
    """
    Shadow Mode Runner.

    Runs V2 agent side-by-side with V1 without affecting production decisions.
    V1 output is always used for production; V2 output is logged for comparison.

    Usage:
        shadow = ShadowMode(v1_agent, v2_agent)
        result, shadow_result = shadow.run(input_context, judgment_id)
        # 'result' is always from V1
    """

    def __init__(
        self,
        v1_agent: AgentCallable,
        v2_agent: AgentCallable,
        log_path: Optional[Path] = None,
    ):
        self.v1_agent = v1_agent
        self.v2_agent = v2_agent
        self.log_path = log_path or Path("state/shadow_log.jsonl")
        self._ensure_log_dir()

    def _ensure_log_dir(self) -> None:
        """Ensure log directory exists."""
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def run(
        self, input_context: dict[str, Any], judgment_id: str
    ) -> tuple[dict[str, Any], ShadowResult]:
        """
        Run both V1 and V2 agents, return V1 result for production.

        Args:
            input_context: Input data for agents
            judgment_id: Identifier for logging

        Returns:
            Tuple of (v1_result for production, ShadowResult for logging)
        """
        # Always run V1 first (production)
        try:
            v1_output = self.v1_agent(input_context)
        except Exception as e:
            logger.error(f"V1 agent error for {judgment_id}: {e}")
            v1_output = {"error": str(e)}

        # Run V2 in shadow (errors don't affect production)
        try:
            v2_output = self.v2_agent(input_context)
        except Exception as e:
            logger.warning(f"V2 shadow agent error for {judgment_id}: {e}")
            v2_output = {"error": str(e)}

        # Compare outputs
        agreement = v1_output == v2_output
        diff = self._compute_diff(v1_output, v2_output) if not agreement else None

        shadow_result = ShadowResult(
            judgment_id=judgment_id,
            v1_output=v1_output,
            v2_output=v2_output,
            agreement=agreement,
            diff=diff,
        )

        # Log shadow result
        self._log_result(shadow_result)

        # Return V1 output for production (V2 is shadow only)
        return v1_output, shadow_result

    def _compute_diff(self, v1: dict[str, Any], v2: dict[str, Any]) -> dict[str, Any]:
        """Compute diff between V1 and V2 outputs."""
        diff: dict[str, Any] = {}
        all_keys = set(v1.keys()) | set(v2.keys())

        for key in all_keys:
            v1_val = v1.get(key)
            v2_val = v2.get(key)
            if v1_val != v2_val:
                diff[key] = {"v1": v1_val, "v2": v2_val}

        return diff

    def _log_result(self, result: ShadowResult) -> None:
        """Append shadow result to log file."""
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(result.to_dict()) + "\n")
        except Exception as e:
            logger.warning(f"Failed to log shadow result: {e}")

    def get_agreement_rate(self, limit: int = 100) -> float:
        """Calculate agreement rate from recent shadow results."""
        if not self.log_path.exists():
            return 0.0

        results: list[dict] = []
        with open(self.log_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    results.append(json.loads(line))

        recent = results[-limit:] if len(results) > limit else results
        if not recent:
            return 0.0

        agreements = sum(1 for r in recent if r.get("agreement", False))
        return agreements / len(recent)


# =============================================================================
# Outcome Feedback Store - Structured store for strategy tuning
# =============================================================================


@dataclass
class OutcomeFeedback:
    """
    Outcome feedback for collections strategy tuning.

    Records whether a strategy decision led to successful collection,
    enabling future model/logic improvements.
    """

    id: str
    judgment_id: str
    strategy_type: str
    outcome: OutcomeType
    amount_collected: Optional[float] = None
    amount_expected: Optional[float] = None
    collection_date: Optional[str] = None
    notes: Optional[str] = None
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    )
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "judgment_id": self.judgment_id,
            "strategy_type": self.strategy_type,
            "outcome": self.outcome.value,
            "amount_collected": self.amount_collected,
            "amount_expected": self.amount_expected,
            "collection_date": self.collection_date,
            "notes": self.notes,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OutcomeFeedback":
        return cls(
            id=data["id"],
            judgment_id=data["judgment_id"],
            strategy_type=data["strategy_type"],
            outcome=OutcomeType(data["outcome"]),
            amount_collected=data.get("amount_collected"),
            amount_expected=data.get("amount_expected"),
            collection_date=data.get("collection_date"),
            notes=data.get("notes"),
            created_at=data.get("created_at", ""),
            metadata=data.get("metadata", {}),
        )


class OutcomeFeedbackStore:
    """
    Persistent store for outcome feedback.

    Stores collections/no-collections outcomes for strategy tuning.
    File-based for simplicity; can be extended to use database.

    Usage:
        store = OutcomeFeedbackStore()

        # Record an outcome
        store.record(
            judgment_id="JDG-001",
            strategy_type="wage_garnishment",
            outcome=OutcomeType.COLLECTED,
            amount_collected=1500.00,
            amount_expected=2000.00,
        )

        # Get outcomes for analysis
        outcomes = store.get_by_strategy("wage_garnishment")
        success_rate = store.get_success_rate("wage_garnishment")
    """

    def __init__(self, store_path: Optional[Path] = None):
        self.store_path = store_path or OUTCOME_STORE_PATH
        self._ensure_store()

    def _ensure_store(self) -> None:
        """Ensure store file and directory exist."""
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.store_path.exists():
            with open(self.store_path, "w", encoding="utf-8") as f:
                json.dump({"version": "1.0", "outcomes": []}, f)

    def _load(self) -> dict[str, Any]:
        """Load store data."""
        with open(self.store_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _save(self, data: dict[str, Any]) -> None:
        """Save store data."""
        with open(self.store_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def record(
        self,
        judgment_id: str,
        strategy_type: str,
        outcome: OutcomeType,
        amount_collected: Optional[float] = None,
        amount_expected: Optional[float] = None,
        collection_date: Optional[str] = None,
        notes: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> OutcomeFeedback:
        """
        Record an outcome feedback entry.

        Args:
            judgment_id: Judgment identifier
            strategy_type: Strategy used (e.g., 'wage_garnishment')
            outcome: Collection outcome
            amount_collected: Amount actually collected
            amount_expected: Expected collection amount
            collection_date: Date of collection (ISO format)
            notes: Optional notes
            metadata: Additional metadata

        Returns:
            Created OutcomeFeedback entry
        """
        feedback = OutcomeFeedback(
            id=str(uuid.uuid4()),
            judgment_id=judgment_id,
            strategy_type=strategy_type,
            outcome=outcome,
            amount_collected=amount_collected,
            amount_expected=amount_expected,
            collection_date=collection_date,
            notes=notes,
            metadata=metadata or {},
        )

        data = self._load()
        data["outcomes"].append(feedback.to_dict())
        self._save(data)

        logger.info(f"Recorded outcome feedback: {feedback.id} for {judgment_id}")
        return feedback

    def get_all(self) -> list[OutcomeFeedback]:
        """Get all outcome feedback entries."""
        data = self._load()
        return [OutcomeFeedback.from_dict(o) for o in data.get("outcomes", [])]

    def get_by_judgment(self, judgment_id: str) -> list[OutcomeFeedback]:
        """Get outcomes for a specific judgment."""
        return [o for o in self.get_all() if o.judgment_id == judgment_id]

    def get_by_strategy(self, strategy_type: str) -> list[OutcomeFeedback]:
        """Get outcomes for a specific strategy type."""
        return [o for o in self.get_all() if o.strategy_type == strategy_type]

    def get_success_rate(self, strategy_type: str) -> float:
        """
        Calculate success rate for a strategy type.

        Success = COLLECTED or PARTIAL
        Returns 0.0 if no outcomes exist.
        """
        outcomes = self.get_by_strategy(strategy_type)
        if not outcomes:
            return 0.0

        successes = sum(
            1 for o in outcomes if o.outcome in (OutcomeType.COLLECTED, OutcomeType.PARTIAL)
        )
        return successes / len(outcomes)

    def get_summary(self) -> dict[str, Any]:
        """Get summary statistics for all strategies."""
        outcomes = self.get_all()
        if not outcomes:
            return {"total": 0, "strategies": {}}

        by_strategy: dict[str, list[OutcomeFeedback]] = {}
        for o in outcomes:
            if o.strategy_type not in by_strategy:
                by_strategy[o.strategy_type] = []
            by_strategy[o.strategy_type].append(o)

        summary = {
            "total": len(outcomes),
            "strategies": {},
        }

        for strategy, strat_outcomes in by_strategy.items():
            collected = sum(1 for o in strat_outcomes if o.outcome == OutcomeType.COLLECTED)
            partial = sum(1 for o in strat_outcomes if o.outcome == OutcomeType.PARTIAL)
            not_collected = sum(1 for o in strat_outcomes if o.outcome == OutcomeType.NOT_COLLECTED)
            pending = sum(1 for o in strat_outcomes if o.outcome == OutcomeType.PENDING)

            summary["strategies"][strategy] = {
                "total": len(strat_outcomes),
                "collected": collected,
                "partial": partial,
                "not_collected": not_collected,
                "pending": pending,
                "success_rate": (collected + partial) / len(strat_outcomes),
            }

        return summary


# =============================================================================
# CLI Main
# =============================================================================


def main():
    """CLI entry point for the evaluator."""
    parser = argparse.ArgumentParser(
        description="Run golden dataset evaluation for Dragonfly AI/ML logic"
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with code 1 if any test fails (score < 1.0)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON instead of human-readable summary",
    )
    parser.add_argument(
        "--category",
        choices=["ingestion", "strategy"],
        help="Run only cases from a specific category",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=1.0,
        help="Minimum score threshold (0.0-1.0). Default: 1.0",
    )

    args = parser.parse_args()

    # Load dataset
    try:
        dataset = GoldenDataset()
        logger.info(f"Loaded golden dataset from {dataset.path}")
        logger.info(f"Total cases: {len(dataset.cases)}")
    except FileNotFoundError as e:
        logger.error(f"Failed to load golden dataset: {e}")
        sys.exit(1)

    # Filter by category if specified
    if args.category:
        # Create a filtered dataset
        filtered_cases = dataset.get_cases_by_category(args.category)
        logger.info(f"Filtered to {len(filtered_cases)} cases in category '{args.category}'")

        # Override cases for filtered evaluation
        dataset._data["cases"] = filtered_cases

    # Run evaluation
    evaluator = Evaluator(dataset)
    result = evaluator.evaluate_all()

    # Output results
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(result.summary())

    # Exit with appropriate code based on threshold
    if args.strict and result.score < args.threshold:
        logger.error(f"Score {result.score:.2%} below threshold {args.threshold:.2%}")
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
