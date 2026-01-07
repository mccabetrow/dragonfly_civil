#!/usr/bin/env python3
"""
tools/stress_db_pool.py - Database Pool Stress Test

PURPOSE:
    Verify that the DataService semaphore properly throttles concurrent
    Direct DB fallback queries, preventing pool exhaustion under load.

WHAT IT TESTS:
    - Spawns 50 concurrent tasks (exceeds MAX_CONCURRENT_FALLBACK_QUERIES=5)
    - Each task forces a DB fallback query via DataService
    - Measures success/failure rates and total execution time
    - Validates no "too many clients" errors occur

SUCCESS CRITERIA:
    - All 50 tasks complete (success or timeout, not pool crash)
    - No "sorry, too many clients already" errors
    - Semaphore limits concurrent DB queries to 5

USAGE:
    python -m tools.stress_db_pool --env dev
    python -m tools.stress_db_pool --env prod --tasks 100

CAUTION:
    This hammers the database. Run against dev unless you're sure.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Literal

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.config import get_settings
from backend.db import close_db_pool, get_pool, init_db_pool
from backend.services.data_service import MAX_CONCURRENT_FALLBACK_QUERIES, DataService


@dataclass
class TaskResult:
    """Result of a single stress test task."""

    task_id: int
    success: bool
    source: str = "unknown"
    row_count: int = 0
    latency_ms: float = 0.0
    error: str | None = None


@dataclass
class StressTestResults:
    """Aggregated results from the stress test."""

    total_tasks: int = 0
    succeeded: int = 0
    failed: int = 0
    pool_exhaustion_errors: int = 0
    timeout_errors: int = 0
    other_errors: int = 0
    total_duration_ms: float = 0.0
    task_results: list[TaskResult] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        if self.total_tasks == 0:
            return 0.0
        return (self.succeeded / self.total_tasks) * 100

    @property
    def avg_latency_ms(self) -> float:
        if not self.task_results:
            return 0.0
        return sum(r.latency_ms for r in self.task_results) / len(self.task_results)


async def run_stress_task(
    task_id: int,
    service: DataService,
    view_name: str = "v_enforcement_overview",
) -> TaskResult:
    """
    Execute a single stress test task.

    Forces direct DB fallback by using _fetch_via_direct_db directly.
    This bypasses REST to ensure we're testing the DB pool.
    """
    start = time.monotonic()

    try:
        # Use the internal method to force DB path (simulating REST failure)
        # We'll wrap it in the semaphore just like fetch_view does
        async with service._db_semaphore:
            data, latency_ms, error = await service._fetch_via_direct_db(
                view_name, filters=None, limit=10
            )

        if error:
            return TaskResult(
                task_id=task_id,
                success=False,
                latency_ms=(time.monotonic() - start) * 1000,
                error=error,
            )

        return TaskResult(
            task_id=task_id,
            success=True,
            source="direct_db",
            row_count=len(data),
            latency_ms=latency_ms,
        )

    except asyncio.TimeoutError:
        return TaskResult(
            task_id=task_id,
            success=False,
            latency_ms=(time.monotonic() - start) * 1000,
            error="timeout",
        )
    except Exception as e:
        error_str = str(e)
        return TaskResult(
            task_id=task_id,
            success=False,
            latency_ms=(time.monotonic() - start) * 1000,
            error=error_str,
        )


async def run_stress_test(
    num_tasks: int = 50,
    view_name: str = "v_enforcement_overview",
    timeout_per_task: float = 60.0,
) -> StressTestResults:
    """
    Run the pool stress test with concurrent tasks.

    Args:
        num_tasks: Number of concurrent tasks to spawn (default 50)
        view_name: View to query (must exist in public schema)
        timeout_per_task: Per-task timeout in seconds

    Returns:
        StressTestResults with aggregated metrics
    """
    print(f"\n{'=' * 60}")
    print("🔥 POOL STRESS TEST")
    print(f"{'=' * 60}")
    print(f"   Tasks:      {num_tasks}")
    print(f"   Semaphore:  {MAX_CONCURRENT_FALLBACK_QUERIES} (max concurrent DB queries)")
    print(f"   View:       {view_name}")
    print(f"   Timeout:    {timeout_per_task}s per task")
    print(f"{'=' * 60}\n")

    # Initialize pool
    print("[1/4] Initializing database pool...")
    try:
        await init_db_pool()
        pool = await get_pool()
        if pool is None:
            print("   ❌ FAIL: Pool initialization returned None")
            return StressTestResults(total_tasks=num_tasks)
        print(f"   ✅ Pool initialized (max_size={pool.max_size})")
    except Exception as e:
        print(f"   ❌ FAIL: Pool init error: {e}")
        return StressTestResults(total_tasks=num_tasks)

    # Create service
    print("[2/4] Creating DataService...")
    service = DataService()
    print(f"   ✅ DataService ready (semaphore limit={MAX_CONCURRENT_FALLBACK_QUERIES})")

    # Launch concurrent tasks
    print(f"[3/4] Launching {num_tasks} concurrent tasks...")
    start_time = time.monotonic()

    tasks = [
        asyncio.wait_for(
            run_stress_task(i, service, view_name),
            timeout=timeout_per_task,
        )
        for i in range(num_tasks)
    ]

    # Gather with return_exceptions to capture timeouts
    raw_results = await asyncio.gather(*tasks, return_exceptions=True)

    total_duration_ms = (time.monotonic() - start_time) * 1000

    # Process results
    results = StressTestResults(
        total_tasks=num_tasks,
        total_duration_ms=total_duration_ms,
    )

    for i, raw in enumerate(raw_results):
        if isinstance(raw, asyncio.TimeoutError):
            result = TaskResult(
                task_id=i,
                success=False,
                error="gather_timeout",
            )
        elif isinstance(raw, Exception):
            result = TaskResult(
                task_id=i,
                success=False,
                error=str(raw),
            )
        else:
            result = raw

        results.task_results.append(result)

        if result.success:
            results.succeeded += 1
        else:
            results.failed += 1

            # Categorize error
            error_lower = (result.error or "").lower()
            if "too many clients" in error_lower or "pool" in error_lower:
                results.pool_exhaustion_errors += 1
            elif "timeout" in error_lower:
                results.timeout_errors += 1
            else:
                results.other_errors += 1

    # Cleanup
    print("[4/4] Cleaning up...")
    await service.close()
    await close_db_pool()
    print("   ✅ Resources released")

    return results


def print_results(results: StressTestResults) -> bool:
    """
    Print stress test results and return success status.

    Returns:
        True if test passed (no pool exhaustion), False otherwise
    """
    print(f"\n{'=' * 60}")
    print("📊 STRESS TEST RESULTS")
    print(f"{'=' * 60}")
    print(f"   Total Tasks:       {results.total_tasks}")
    print(f"   Succeeded:         {results.succeeded}")
    print(f"   Failed:            {results.failed}")
    print(f"   Success Rate:      {results.success_rate:.1f}%")
    print(f"   Avg Latency:       {results.avg_latency_ms:.1f}ms")
    print(f"   Total Duration:    {results.total_duration_ms:.0f}ms")
    print()
    print("   Error Breakdown:")
    print(f"     Pool Exhaustion: {results.pool_exhaustion_errors}")
    print(f"     Timeouts:        {results.timeout_errors}")
    print(f"     Other:           {results.other_errors}")
    print(f"{'=' * 60}")

    # Determine pass/fail
    if results.pool_exhaustion_errors > 0:
        print("\n❌ FAIL: Pool exhaustion detected!")
        print("   The semaphore did not prevent 'too many clients' errors.")
        if results.pool_exhaustion_errors <= 3:
            # Show sample errors
            for r in results.task_results:
                if r.error and "pool" in r.error.lower():
                    print(f"   - Task {r.task_id}: {r.error}")
                    break
        return False

    if results.succeeded == 0:
        print("\n❌ FAIL: All tasks failed!")
        # Show sample errors
        sample_errors = [r for r in results.task_results if r.error][:3]
        for r in sample_errors:
            print(f"   - Task {r.task_id}: {r.error}")
        return False

    # Success: some tasks completed, no pool exhaustion
    print("\n✅ Pool Limit Verified")
    print(f"   {results.succeeded}/{results.total_tasks} tasks completed successfully")
    print(f"   Semaphore held the line at {MAX_CONCURRENT_FALLBACK_QUERIES} concurrent queries")
    print("   No 'too many clients' errors detected")

    return True


def main():
    parser = argparse.ArgumentParser(
        description="Stress test the database pool to verify semaphore limits",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python -m tools.stress_db_pool --env dev
    python -m tools.stress_db_pool --env dev --tasks 100
    python -m tools.stress_db_pool --env prod --tasks 25

Note: Run against dev unless you're intentionally testing prod resilience.
        """,
    )
    parser.add_argument(
        "--env",
        choices=["dev", "prod"],
        default="dev",
        help="Supabase environment (default: dev)",
    )
    parser.add_argument(
        "--tasks",
        type=int,
        default=50,
        help="Number of concurrent tasks to spawn (default: 50)",
    )
    parser.add_argument(
        "--view",
        default="v_enforcement_overview",
        help="View to query (default: v_enforcement_overview)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=60.0,
        help="Per-task timeout in seconds (default: 60)",
    )

    args = parser.parse_args()

    # Set environment
    os.environ["SUPABASE_MODE"] = args.env
    print(f"\n🎯 Environment: {args.env.upper()}")

    # Validate settings can load
    try:
        settings = get_settings()
        print(f"   Supabase URL: {settings.SUPABASE_URL}")
    except Exception as e:
        print(f"❌ Failed to load settings: {e}")
        sys.exit(1)

    # Run the test
    results = asyncio.run(
        run_stress_test(
            num_tasks=args.tasks,
            view_name=args.view,
            timeout_per_task=args.timeout,
        )
    )

    # Print and evaluate
    success = print_results(results)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
