"""
tools/load_test_rpc.py

Load Test Script for ops.claim_pending_job RPC.

This script stress-tests the claim_job RPC with concurrent threads to measure
latency distributions and identify performance bottlenecks under load.

USAGE:
======
    python -m tools.load_test_rpc [--threads N] [--iterations N] [--env dev|prod]

OPTIONS:
========
    --threads N      Number of concurrent threads (default: 20)
    --iterations N   Iterations per thread (default: 50)
    --env            Environment to test against (default: dev)
    --p95-budget     P95 latency budget in ms (default: 200)

OUTPUT:
=======
    Prints latency distribution statistics:
    - p50 (median)
    - p95
    - p99
    - min/max
    - total calls
    - error rate

EXIT CODES:
===========
    0 - Success (p95 under budget)
    1 - Failure (p95 exceeds budget or errors occurred)

REQUIREMENTS:
=============
    - psycopg v3
    - Database connection with RPC execute permissions
    - ops.job_queue table accessible

WARNING:
========
    This script creates actual database connections and executes real RPCs.
    Use against dev environment for load testing. Never run against prod
    without explicit approval.
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any

try:
    import psycopg
except ImportError:
    print("ERROR: psycopg v3 is required. Install with: pip install psycopg[binary]")
    sys.exit(1)


# =============================================================================
# CONFIGURATION
# =============================================================================

DEFAULT_THREADS = 20
DEFAULT_ITERATIONS = 50
DEFAULT_P95_BUDGET_MS = 200.0


# =============================================================================
# DATA STRUCTURES
# =============================================================================


@dataclass
class CallResult:
    """Result of a single RPC call."""

    thread_id: int
    iteration: int
    latency_ms: float
    success: bool
    error: str | None = None


@dataclass
class LoadTestStats:
    """Aggregated statistics from load test."""

    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    latencies_ms: list[float] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def error_rate(self) -> float:
        if self.total_calls == 0:
            return 0.0
        return (self.failed_calls / self.total_calls) * 100

    @property
    def p50(self) -> float:
        if not self.latencies_ms:
            return 0.0
        return statistics.median(self.latencies_ms)

    @property
    def p95(self) -> float:
        if not self.latencies_ms:
            return 0.0
        return statistics.quantiles(self.latencies_ms, n=20)[18]  # 95th percentile

    @property
    def p99(self) -> float:
        if not self.latencies_ms:
            return 0.0
        return statistics.quantiles(self.latencies_ms, n=100)[98]  # 99th percentile

    @property
    def min_latency(self) -> float:
        return min(self.latencies_ms) if self.latencies_ms else 0.0

    @property
    def max_latency(self) -> float:
        return max(self.latencies_ms) if self.latencies_ms else 0.0

    @property
    def mean_latency(self) -> float:
        return statistics.mean(self.latencies_ms) if self.latencies_ms else 0.0


# =============================================================================
# LOAD TEST WORKER
# =============================================================================


def get_db_url(env: str = "dev") -> str:
    """Get database URL for the specified environment."""
    # Try environment-specific variables first
    if env == "prod":
        url = os.environ.get("SUPABASE_DB_URL_PROD")
    else:
        url = os.environ.get("SUPABASE_DB_URL_DEV") or os.environ.get("SUPABASE_DB_URL")

    if not url:
        url = os.environ.get("DATABASE_URL")

    if not url:
        raise ValueError(
            f"No database URL found for env={env}. " "Set SUPABASE_DB_URL or SUPABASE_DB_URL_{ENV}."
        )

    return url


def run_claim_job(
    db_url: str,
    thread_id: int,
    iteration: int,
    worker_id: str,
) -> CallResult:
    """
    Execute a single claim_pending_job RPC call and measure latency.

    Uses a unique worker_id per thread to simulate realistic concurrent workers.
    """
    try:
        start_time = time.perf_counter()

        with psycopg.connect(db_url, autocommit=True) as conn:
            with conn.cursor() as cur:
                # Call the RPC with test parameters
                cur.execute(
                    """
                    SELECT * FROM ops.claim_pending_job(
                        %s::text[],
                        %s::integer,
                        %s::text
                    )
                    """,
                    (
                        ["load_test_job"],  # job_types
                        1,  # limit
                        worker_id,  # worker_id
                    ),
                )
                # Consume result
                cur.fetchall()

        end_time = time.perf_counter()
        latency_ms = (end_time - start_time) * 1000

        return CallResult(
            thread_id=thread_id,
            iteration=iteration,
            latency_ms=latency_ms,
            success=True,
        )

    except Exception as e:
        end_time = time.perf_counter()
        latency_ms = (end_time - start_time) * 1000

        return CallResult(
            thread_id=thread_id,
            iteration=iteration,
            latency_ms=latency_ms,
            success=False,
            error=str(e),
        )


def worker_thread(
    db_url: str,
    thread_id: int,
    iterations: int,
    results: list[CallResult],
    lock: threading.Lock,
) -> None:
    """
    Worker thread that runs multiple RPC iterations.

    Each thread simulates a single worker process making repeated claims.
    """
    worker_id = f"load_test_worker_{thread_id}"

    for i in range(iterations):
        result = run_claim_job(db_url, thread_id, i, worker_id)

        with lock:
            results.append(result)


# =============================================================================
# LOAD TEST ORCHESTRATOR
# =============================================================================


def run_load_test(
    db_url: str,
    num_threads: int,
    iterations_per_thread: int,
) -> LoadTestStats:
    """
    Run the load test with specified concurrency.

    Args:
        db_url: Database connection URL
        num_threads: Number of concurrent threads
        iterations_per_thread: Number of RPC calls per thread

    Returns:
        LoadTestStats with aggregated results
    """
    results: list[CallResult] = []
    lock = threading.Lock()

    print(f"\n{'=' * 60}")
    print("LOAD TEST: ops.claim_pending_job")
    print(f"{'=' * 60}")
    print(f"  Threads:            {num_threads}")
    print(f"  Iterations/thread:  {iterations_per_thread}")
    print(f"  Total calls:        {num_threads * iterations_per_thread}")
    print(f"{'=' * 60}\n")

    start_time = time.perf_counter()

    # Use ThreadPoolExecutor for concurrent execution
    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = []
        for thread_id in range(num_threads):
            future = executor.submit(
                worker_thread,
                db_url,
                thread_id,
                iterations_per_thread,
                results,
                lock,
            )
            futures.append(future)

        # Wait for all threads to complete
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as e:
                print(f"Thread error: {e}")

    end_time = time.perf_counter()
    total_duration = end_time - start_time

    # Aggregate results
    stats = LoadTestStats()
    for result in results:
        stats.total_calls += 1
        if result.success:
            stats.successful_calls += 1
            stats.latencies_ms.append(result.latency_ms)
        else:
            stats.failed_calls += 1
            if result.error:
                stats.errors.append(result.error)

    print(f"Completed in {total_duration:.2f}s")
    print(f"Throughput: {stats.total_calls / total_duration:.2f} calls/sec\n")

    return stats


def print_stats(stats: LoadTestStats, p95_budget: float) -> bool:
    """
    Print load test statistics and return whether p95 is under budget.

    Returns:
        True if p95 is under budget, False otherwise
    """
    print(f"{'=' * 60}")
    print("RESULTS")
    print(f"{'=' * 60}")
    print(f"  Total calls:     {stats.total_calls}")
    print(f"  Successful:      {stats.successful_calls}")
    print(f"  Failed:          {stats.failed_calls}")
    print(f"  Error rate:      {stats.error_rate:.2f}%")
    print()
    print("LATENCY DISTRIBUTION")
    print(f"{'=' * 60}")
    print(f"  Min:     {stats.min_latency:>8.2f} ms")
    print(f"  Mean:    {stats.mean_latency:>8.2f} ms")
    print(f"  p50:     {stats.p50:>8.2f} ms")
    print(f"  p95:     {stats.p95:>8.2f} ms")
    print(f"  p99:     {stats.p99:>8.2f} ms")
    print(f"  Max:     {stats.max_latency:>8.2f} ms")
    print(f"{'=' * 60}")

    # Check budget
    p95_ok = stats.p95 <= p95_budget
    status = "✅ PASS" if p95_ok else "❌ FAIL"
    print(f"\nP95 Budget Check: {status}")
    print(f"  p95 = {stats.p95:.2f}ms vs budget = {p95_budget:.2f}ms")

    if stats.errors:
        print(f"\nSample Errors ({len(stats.errors)} total):")
        for err in stats.errors[:5]:
            print(f"  - {err[:80]}...")

    return p95_ok


# =============================================================================
# CLI
# =============================================================================


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Load test ops.claim_pending_job RPC",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=DEFAULT_THREADS,
        help=f"Number of concurrent threads (default: {DEFAULT_THREADS})",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=DEFAULT_ITERATIONS,
        help=f"Iterations per thread (default: {DEFAULT_ITERATIONS})",
    )
    parser.add_argument(
        "--env",
        choices=["dev", "prod"],
        default="dev",
        help="Environment to test against (default: dev)",
    )
    parser.add_argument(
        "--p95-budget",
        type=float,
        default=DEFAULT_P95_BUDGET_MS,
        help=f"P95 latency budget in ms (default: {DEFAULT_P95_BUDGET_MS})",
    )

    args = parser.parse_args()

    # Safety check for prod
    if args.env == "prod":
        print("⚠️  WARNING: Running load test against PRODUCTION!")
        print("    This will create real database load.")
        response = input("    Continue? [y/N]: ")
        if response.lower() != "y":
            print("Aborted.")
            return 1

    try:
        db_url = get_db_url(args.env)
    except ValueError as e:
        print(f"ERROR: {e}")
        return 1

    # Run the load test
    stats = run_load_test(
        db_url=db_url,
        num_threads=args.threads,
        iterations_per_thread=args.iterations,
    )

    # Print results and check budget
    p95_ok = print_stats(stats, args.p95_budget)

    # Exit with appropriate code
    if not p95_ok:
        print("\n❌ Load test FAILED: p95 exceeds budget")
        return 1

    if stats.error_rate > 5.0:
        print(f"\n❌ Load test FAILED: Error rate {stats.error_rate:.2f}% > 5%")
        return 1

    print("\n✅ Load test PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
