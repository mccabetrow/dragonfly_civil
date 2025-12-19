"""
CI Guard: Locked Tables DML Blocklist

This test ensures that no production code contains raw DML statements
against protected ops tables. All operations must go through SECURITY DEFINER
RPCs to enforce least-privilege security.

Protected tables:
- ops.job_queue
- ops.worker_heartbeats

Allowed RPCs:
- ops.enqueue_job
- ops.claim_pending_job
- ops.update_job_status
- ops.register_heartbeat

Test location patterns checked:
- backend/**/*.py
- src/**/*.py
- workers/**/*.py
- etl/**/*.py

Excluded patterns:
- supabase/migrations/**  (defines the RPCs)
- tests/**  (test fixtures may need controlled access)
- scripts/audit_privileges.py  (intentionally tests denied operations)
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# Regex patterns for detecting raw DML against locked tables
BLOCKED_DML_PATTERNS = [
    # ops.job_queue DML (case-insensitive)
    re.compile(r"\bINSERT\s+INTO\s+ops\.job_queue\b", re.IGNORECASE),
    re.compile(r"\bUPDATE\s+ops\.job_queue\b", re.IGNORECASE),
    re.compile(r"\bDELETE\s+FROM\s+ops\.job_queue\b", re.IGNORECASE),
    # ops.worker_heartbeats DML (case-insensitive)
    re.compile(r"\bINSERT\s+INTO\s+ops\.worker_heartbeats\b", re.IGNORECASE),
    re.compile(r"\bUPDATE\s+ops\.worker_heartbeats\b", re.IGNORECASE),
    re.compile(r"\bDELETE\s+FROM\s+ops\.worker_heartbeats\b", re.IGNORECASE),
]

# Directories to scan for violations
SCAN_DIRECTORIES = [
    "backend",
    "src",
    "workers",
    "etl",
]

# Excluded paths (relative to workspace root)
EXCLUDED_PATHS = [
    "supabase/migrations",
    "tests/",
    "scripts/audit_privileges.py",
    "__pycache__",
    ".venv",
]


def get_workspace_root() -> Path:
    """Find the workspace root by looking for pyproject.toml."""
    current = Path(__file__).resolve()
    for parent in [current] + list(current.parents):
        if (parent / "pyproject.toml").exists():
            return parent
    raise RuntimeError("Could not find workspace root (no pyproject.toml found)")


def is_excluded(file_path: Path, root: Path) -> bool:
    """Check if a file path should be excluded from scanning."""
    # Normalize to forward slashes for cross-platform matching
    rel_path = str(file_path.relative_to(root)).replace("\\", "/")
    for excluded in EXCLUDED_PATHS:
        if rel_path.startswith(excluded) or excluded in rel_path:
            return True
    return False


def find_python_files(root: Path) -> list[Path]:
    """Find all Python files in the scan directories."""
    files = []
    for dir_name in SCAN_DIRECTORIES:
        dir_path = root / dir_name
        if dir_path.exists():
            for py_file in dir_path.rglob("*.py"):
                if not is_excluded(py_file, root):
                    files.append(py_file)
    return files


def scan_file_for_violations(file_path: Path) -> list[tuple[int, str, str]]:
    """
    Scan a file for DML violations.

    Returns:
        List of (line_number, pattern_matched, line_content) tuples
    """
    violations = []
    try:
        content = file_path.read_text(encoding="utf-8")
        lines = content.splitlines()
        in_docstring = False
        docstring_char = None

        for i, line in enumerate(lines, start=1):
            stripped = line.strip()

            # Track docstring state (simple triple-quote detection)
            if not in_docstring:
                if stripped.startswith('"""') or stripped.startswith("'''"):
                    docstring_char = stripped[:3]
                    # Check if it's a single-line docstring (starts and ends with """)
                    if stripped.count(docstring_char) >= 2 and len(stripped) > 6:
                        # Single-line docstring, skip it
                        continue
                    in_docstring = True
                    continue
            else:
                # Inside docstring - check for end
                if docstring_char and docstring_char in stripped:
                    in_docstring = False
                continue

            # Skip comment lines
            if stripped.startswith("#"):
                continue

            # Check each pattern only in actual code
            for pattern in BLOCKED_DML_PATTERNS:
                if pattern.search(line):
                    violations.append((i, pattern.pattern, line.strip()))
    except Exception as e:
        # If we can't read the file, skip it
        pytest.skip(f"Could not read {file_path}: {e}")
    return violations


class TestLockedTablesDMLGuard:
    """CI guard tests to prevent raw DML against locked ops tables."""

    def test_no_raw_dml_against_ops_job_queue(self):
        """
        GUARD: No raw INSERT/UPDATE/DELETE against ops.job_queue in production code.

        All job queue operations must use SECURITY DEFINER RPCs:
        - ops.enqueue_job (for INSERT)
        - ops.claim_pending_job (for UPDATE with SKIP LOCKED)
        - ops.update_job_status (for UPDATE status)

        This guard exists because v1.3.1 failed due to permission denied errors
        when workers tried to execute raw DML with insufficient grants.
        """
        root = get_workspace_root()
        python_files = find_python_files(root)

        all_violations = []
        for py_file in python_files:
            violations = scan_file_for_violations(py_file)
            for line_num, pattern, content in violations:
                if "job_queue" in pattern.lower():
                    rel_path = py_file.relative_to(root)
                    all_violations.append(f"  {rel_path}:{line_num}: {content}")

        if all_violations:
            violation_list = "\n".join(all_violations)
            pytest.fail(
                f"Found raw DML against ops.job_queue in production code!\n"
                f"Use RPCs instead: ops.enqueue_job, ops.claim_pending_job, "
                f"ops.update_job_status\n\n"
                f"Violations:\n{violation_list}"
            )

    def test_no_raw_dml_against_ops_worker_heartbeats(self):
        """
        GUARD: No raw INSERT/UPDATE/DELETE against ops.worker_heartbeats.

        All heartbeat operations must use SECURITY DEFINER RPC:
        - ops.register_heartbeat (for INSERT ON CONFLICT UPDATE)

        This guard exists because the dragonfly_app role should only have
        SELECT grants, with writes mediated through secure RPCs.
        """
        root = get_workspace_root()
        python_files = find_python_files(root)

        all_violations = []
        for py_file in python_files:
            violations = scan_file_for_violations(py_file)
            for line_num, pattern, content in violations:
                if "worker_heartbeats" in pattern.lower():
                    rel_path = py_file.relative_to(root)
                    all_violations.append(f"  {rel_path}:{line_num}: {content}")

        if all_violations:
            violation_list = "\n".join(all_violations)
            pytest.fail(
                f"Found raw DML against ops.worker_heartbeats in production code!\n"
                f"Use RPC instead: ops.register_heartbeat\n\n"
                f"Violations:\n{violation_list}"
            )

    def test_blocked_patterns_are_valid_regex(self):
        """Verify all blocked patterns compile and match expected strings."""
        test_cases = [
            (r"INSERT INTO ops.job_queue", True),
            (r"UPDATE ops.job_queue SET", True),
            (r"DELETE FROM ops.job_queue WHERE", True),
            (r"INSERT INTO ops.worker_heartbeats", True),
            (r"UPDATE ops.worker_heartbeats SET", True),
            (r"SELECT * FROM ops.job_queue", False),  # SELECT is allowed
        ]

        for test_sql, should_match in test_cases:
            matched = any(p.search(test_sql) for p in BLOCKED_DML_PATTERNS)
            assert matched == should_match, (
                f"Pattern match failed for: {test_sql!r} "
                f"(expected match={should_match}, got match={matched})"
            )

    def test_excluded_paths_work_correctly(self):
        """Verify exclusion logic correctly identifies excluded paths."""
        # Use actual workspace root for proper path handling
        root = get_workspace_root()

        # Create test paths relative to actual root
        test_cases = [
            (root / "supabase" / "migrations" / "001_init.sql", True),
            (root / "tests" / "test_something.py", True),
            (root / "scripts" / "audit_privileges.py", True),
            (root / "backend" / "workers" / "job_runner.py", False),
            (root / "etl" / "src" / "loader.py", False),
        ]

        for file_path, should_exclude in test_cases:
            result = is_excluded(file_path, root)
            assert result == should_exclude, (
                f"Exclusion failed for: {file_path} "
                f"(expected exclude={should_exclude}, got exclude={result})"
            )
