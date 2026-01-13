"""Tests to guard against raw SQL writes to protected tables.

These tests use AST analysis and string scanning to detect raw INSERT/UPDATE/DELETE
statements in worker code. If workers bypass RPCClient and write directly to
protected tables (ops.*, job_queue), these tests will fail.

The security model enforces:
- Workers connect as dragonfly_app role (least privilege)
- dragonfly_app has SELECT-only on tables
- All writes go through SECURITY DEFINER RPCs
- This test catches violations at dev time before they reach prod

Fail Condition (from Perfect Deployment spec):
- If regex matches (INSERT|UPDATE|DELETE) followed by ops.
- OR (INSERT|UPDATE|DELETE) followed by job_queue
- (ignoring comments)

Goal: Prevent any future code from bypassing RPCs.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import NamedTuple

import pytest

# EXACT FORBIDDEN PATTERNS from Perfect Deployment spec:
# - (INSERT|UPDATE|DELETE)\s+.*ops\.
# - (INSERT|UPDATE|DELETE)\s+.*job_queue
FORBIDDEN_PATTERNS = [
    re.compile(r"(INSERT|UPDATE|DELETE)\s+.*ops\.", re.IGNORECASE),
    re.compile(r"(INSERT|UPDATE|DELETE)\s+.*job_queue", re.IGNORECASE),
]

# Protected tables that should NEVER have raw SQL writes
PROTECTED_TABLES = [
    # ops schema (critical)
    "ops.job_queue",
    "ops.intake_logs",
    "ops.ingest_batches",
    "ops.worker_heartbeats",
    "ops.import_errors",
    "ops.data_discrepancies",
    "ops.ingest_audit_log",
    "ops.entity_audit_log",
    # intake schema
    "intake.foil_datasets",
    "intake.foil_raw_rows",
    "intake.foil_quarantine",
    "intake.simplicity_batches",
    "intake.simplicity_raw_rows",
    "intake.simplicity_validated_rows",
    # public schema critical tables
    "public.judgments",
    "public.plaintiffs",
    "public.enforcement_cases",
    "public.enforcement_events",
]

# Worker files to scan
WORKER_FILES = [
    "backend/workers/ingest_processor.py",
    "backend/workers/enforcement_engine.py",
    "backend/workers/simplicity_ingest_worker.py",
]

# Allowed patterns (RPCs and SELECT statements)
ALLOWED_PATTERNS = [
    r"SELECT\s+.*FROM\s+ops\.",  # SELECT from ops is OK
    r"SELECT\s+.*FROM\s+intake\.",  # SELECT from intake is OK
    r"SELECT\s+ops\.\w+\(",  # Calling ops.function() is OK (RPC)
    r"SELECT\s+intake\.\w+\(",  # Calling intake.function() is OK (RPC)
    r"SELECT\s+enforcement\.\w+\(",  # Calling enforcement.function() is OK (RPC)
    r"SELECT\s+\*\s+FROM\s+ops\.\w+\(",  # SELECT * FROM ops.function() is OK
    r"SELECT\s+\*\s+FROM\s+intake\.\w+\(",  # SELECT * FROM intake.function() is OK
]


class SQLViolation(NamedTuple):
    """A detected raw SQL write violation."""

    file: str
    line: int
    table: str
    operation: str
    snippet: str


def find_raw_sql_writes(file_path: Path) -> list[SQLViolation]:
    """
    Scan a Python file for raw SQL INSERT/UPDATE/DELETE against protected tables.

    Returns a list of violations found.
    """
    violations = []
    content = file_path.read_text(encoding="utf-8")
    lines = content.split("\n")

    # Patterns for raw SQL writes
    write_patterns = [
        (r"INSERT\s+INTO\s+(\w+\.?\w*)", "INSERT"),
        (r"UPDATE\s+(\w+\.?\w*)\s+SET", "UPDATE"),
        (r"DELETE\s+FROM\s+(\w+\.?\w*)", "DELETE"),
    ]

    for line_num, line in enumerate(lines, 1):
        # Skip comments
        stripped = line.strip()
        if stripped.startswith("#"):
            continue

        # Check if this line is inside a string (crude heuristic)
        # Look for SQL patterns in triple-quoted strings or regular strings
        for pattern, operation in write_patterns:
            matches = re.finditer(pattern, line, re.IGNORECASE)
            for match in matches:
                table_name = match.group(1).lower()

                # Check if it's a protected table
                is_protected = any(
                    table_name == t.lower() or table_name == t.split(".")[-1].lower()
                    for t in PROTECTED_TABLES
                )

                if is_protected:
                    # Check if it's an allowed pattern (RPC call)
                    is_allowed = any(
                        re.search(allowed, line, re.IGNORECASE) for allowed in ALLOWED_PATTERNS
                    )

                    if not is_allowed:
                        violations.append(
                            SQLViolation(
                                file=str(file_path),
                                line=line_num,
                                table=table_name,
                                operation=operation,
                                snippet=stripped[:100],
                            )
                        )

    return violations


def find_cur_execute_with_raw_sql(file_path: Path) -> list[SQLViolation]:
    """
    Use AST to find cur.execute() calls that contain raw SQL writes.

    This is more accurate than regex as it understands Python syntax.
    """
    violations = []
    content = file_path.read_text(encoding="utf-8")

    try:
        tree = ast.parse(content)
    except SyntaxError:
        return violations  # Skip files with syntax errors

    class CurExecuteVisitor(ast.NodeVisitor):
        def visit_Call(self, node: ast.Call) -> None:
            # Look for cur.execute(...) or cursor.execute(...)
            if isinstance(node.func, ast.Attribute):
                if node.func.attr == "execute":
                    # Check if the first argument is a string with SQL
                    if node.args:
                        sql_arg = node.args[0]
                        sql_text = ""

                        if isinstance(sql_arg, ast.Constant) and isinstance(sql_arg.value, str):
                            sql_text = sql_arg.value
                        elif isinstance(sql_arg, ast.JoinedStr):
                            # f-string - extract string parts
                            for value in sql_arg.values:
                                if isinstance(value, ast.Constant):
                                    sql_text += str(value.value)

                        if sql_text:
                            # Check for raw writes
                            for pattern, operation in [
                                (r"INSERT\s+INTO\s+(\w+\.?\w*)", "INSERT"),
                                (r"UPDATE\s+(\w+\.?\w*)\s+SET", "UPDATE"),
                                (r"DELETE\s+FROM\s+(\w+\.?\w*)", "DELETE"),
                            ]:
                                matches = re.finditer(pattern, sql_text, re.IGNORECASE)
                                for match in matches:
                                    table_name = match.group(1).lower()

                                    is_protected = any(
                                        table_name == t.lower()
                                        or table_name == t.split(".")[-1].lower()
                                        for t in PROTECTED_TABLES
                                    )

                                    if is_protected:
                                        # Verify it's not an RPC call
                                        is_rpc = any(
                                            re.search(allowed, sql_text, re.IGNORECASE)
                                            for allowed in ALLOWED_PATTERNS
                                        )

                                        if not is_rpc:
                                            violations.append(
                                                SQLViolation(
                                                    file=str(file_path),
                                                    line=node.lineno,
                                                    table=table_name,
                                                    operation=operation,
                                                    snippet=sql_text[:100].replace("\n", " "),
                                                )
                                            )

            self.generic_visit(node)

    CurExecuteVisitor().visit(tree)
    return violations


class TestRawSQLGuard:
    """Test suite to detect raw SQL writes to protected tables."""

    @pytest.fixture
    def project_root(self) -> Path:
        """Get project root directory."""
        # This test file is in tests/, so go up one level
        return Path(__file__).parent.parent

    def test_no_raw_sql_in_ingest_processor(self, project_root: Path) -> None:
        """Verify ingest_processor.py has no raw SQL writes to protected tables."""
        file_path = project_root / "backend" / "workers" / "ingest_processor.py"
        if not file_path.exists():
            pytest.skip(f"File not found: {file_path}")

        violations = find_cur_execute_with_raw_sql(file_path)

        if violations:
            msg = "Raw SQL writes detected in ingest_processor.py:\n"
            for v in violations:
                msg += f"  Line {v.line}: {v.operation} on {v.table}\n"
                msg += f"    {v.snippet}\n"
            pytest.fail(msg)

    def test_no_raw_sql_in_enforcement_engine(self, project_root: Path) -> None:
        """Verify enforcement_engine.py has no raw SQL writes to protected tables."""
        file_path = project_root / "backend" / "workers" / "enforcement_engine.py"
        if not file_path.exists():
            pytest.skip(f"File not found: {file_path}")

        violations = find_cur_execute_with_raw_sql(file_path)

        if violations:
            msg = "Raw SQL writes detected in enforcement_engine.py:\n"
            for v in violations:
                msg += f"  Line {v.line}: {v.operation} on {v.table}\n"
                msg += f"    {v.snippet}\n"
            pytest.fail(msg)

    def test_no_raw_sql_in_simplicity_worker(self, project_root: Path) -> None:
        """Verify simplicity_ingest_worker.py has no raw SQL writes."""
        file_path = project_root / "backend" / "workers" / "simplicity_ingest_worker.py"
        if not file_path.exists():
            pytest.skip(f"File not found: {file_path}")

        violations = find_cur_execute_with_raw_sql(file_path)

        if violations:
            msg = "Raw SQL writes detected in simplicity_ingest_worker.py:\n"
            for v in violations:
                msg += f"  Line {v.line}: {v.operation} on {v.table}\n"
                msg += f"    {v.snippet}\n"
            pytest.fail(msg)

    def test_no_raw_sql_in_any_worker(self, project_root: Path) -> None:
        """Scan all worker files for raw SQL writes to protected tables."""
        workers_dir = project_root / "backend" / "workers"
        if not workers_dir.exists():
            pytest.skip("Workers directory not found")

        # Files allowed to use raw SQL (ETL/orchestration code with intentional direct DB access)
        allowlisted_files = {
            "rpc_client.py",  # It's supposed to contain SQL
            "orchestrator.py",  # Batch orchestration requires direct DB access
            "collectability.py",  # Score updates to judgments table
            "ingest_worker.py",  # Bulk upserts with exactly-once semantics
        }

        all_violations = []

        for py_file in workers_dir.glob("*.py"):
            # Skip __init__.py and test files
            if py_file.name.startswith("_") or py_file.name.startswith("test_"):
                continue

            # Skip allowlisted files
            if py_file.name in allowlisted_files:
                continue

            violations = find_cur_execute_with_raw_sql(py_file)
            all_violations.extend(violations)

        if all_violations:
            msg = "Raw SQL writes detected in worker files:\n"
            for v in all_violations:
                msg += f"  {v.file}:{v.line} - {v.operation} on {v.table}\n"
                msg += f"    {v.snippet}\n"
            pytest.fail(msg)


class TestRPCClientCompleteness:
    """Verify RPCClient has methods for all protected table operations."""

    def test_rpc_client_has_judgment_upsert(self) -> None:
        """Verify RPCClient has upsert_judgment method."""
        from backend.workers.rpc_client import RPCClient

        assert hasattr(RPCClient, "upsert_judgment")
        assert hasattr(RPCClient, "upsert_judgment_extended")

    def test_rpc_client_has_intake_log(self) -> None:
        """Verify RPCClient has log_intake_event method."""
        from backend.workers.rpc_client import RPCClient

        assert hasattr(RPCClient, "log_intake_event")

    def test_rpc_client_has_job_operations(self) -> None:
        """Verify RPCClient has job queue methods."""
        from backend.workers.rpc_client import RPCClient

        assert hasattr(RPCClient, "claim_pending_job")
        assert hasattr(RPCClient, "update_job_status")
        assert hasattr(RPCClient, "queue_job")

    def test_rpc_client_has_heartbeat(self) -> None:
        """Verify RPCClient has heartbeat method."""
        from backend.workers.rpc_client import RPCClient

        assert hasattr(RPCClient, "register_heartbeat")

    def test_rpc_client_has_foil_dataset_methods(self) -> None:
        """Verify RPCClient has FOIL dataset methods."""
        from backend.workers.rpc_client import RPCClient

        assert hasattr(RPCClient, "create_foil_dataset")
        assert hasattr(RPCClient, "update_foil_dataset_mapping")
        assert hasattr(RPCClient, "update_foil_dataset_status")
        assert hasattr(RPCClient, "finalize_foil_dataset")
        assert hasattr(RPCClient, "store_foil_raw_rows_bulk")
        assert hasattr(RPCClient, "update_foil_raw_row_status")
        assert hasattr(RPCClient, "quarantine_foil_row")

    def test_rpc_client_has_ingest_batch_methods(self) -> None:
        """Verify RPCClient has ingest batch methods."""
        from backend.workers.rpc_client import RPCClient

        assert hasattr(RPCClient, "create_ingest_batch")
        assert hasattr(RPCClient, "finalize_ingest_batch")


class TestForbiddenPatterns:
    """Test using the EXACT forbidden patterns from Perfect Deployment spec.

    Fail Condition (from spec):
    - If regex matches (INSERT|UPDATE|DELETE)\\s+.*ops\\.
    - OR (INSERT|UPDATE|DELETE)\\s+.*job_queue
    (ignoring comments)
    """

    @pytest.fixture
    def project_root(self) -> Path:
        """Get project root directory."""
        return Path(__file__).parent.parent

    def _strip_comments(self, content: str) -> str:
        """Remove Python comments from content."""
        lines = []
        for line in content.split("\n"):
            # Remove inline comments
            stripped = line.split("#")[0]
            lines.append(stripped)
        return "\n".join(lines)

    def test_no_forbidden_patterns_in_workers(self, project_root: Path) -> None:
        """Scan all backend/workers/*.py for forbidden patterns.

        This test implements the EXACT spec:
        - Fail if (INSERT|UPDATE|DELETE)\\s+.*ops\\. matches
        - Fail if (INSERT|UPDATE|DELETE)\\s+.*job_queue matches
        - Skip comments
        """
        workers_dir = project_root / "backend" / "workers"
        if not workers_dir.exists():
            pytest.skip("Workers directory not found")

        violations = []

        # Files allowed to use raw SQL patterns (ETL/orchestration code)
        allowlisted_files = {
            "rpc_client.py",  # It's the authorized RPC layer
            "orchestrator.py",  # Batch orchestration requires direct DB access
            "collectability.py",  # Score updates to judgments table
        }

        for py_file in workers_dir.glob("*.py"):
            # Skip __init__.py and test files
            if py_file.name.startswith("_") or py_file.name.startswith("test_"):
                continue

            # Skip allowlisted files
            if py_file.name in allowlisted_files:
                continue

            content = py_file.read_text(encoding="utf-8")
            content_no_comments = self._strip_comments(content)

            for pattern in FORBIDDEN_PATTERNS:
                for match in pattern.finditer(content_no_comments):
                    # Get line number
                    line_start = content_no_comments.rfind("\n", 0, match.start()) + 1
                    line_num = content_no_comments[: match.start()].count("\n") + 1
                    snippet = content_no_comments[line_start : line_start + 100].strip()

                    violations.append(
                        {
                            "file": py_file.name,
                            "line": line_num,
                            "pattern": pattern.pattern,
                            "match": match.group(),
                            "snippet": snippet[:80],
                        }
                    )

        if violations:
            msg = "FORBIDDEN PATTERNS detected - workers bypassing RPCs:\n"
            for v in violations:
                msg += f"  {v['file']}:{v['line']} - {v['match']}\n"
                msg += f"    Pattern: {v['pattern']}\n"
                msg += f"    Context: {v['snippet']}...\n"
            msg += "\nWorkers MUST use RPCClient methods, not raw SQL.\n"
            msg += "See: backend/workers/rpc_client.py for approved patterns."
            pytest.fail(msg)
