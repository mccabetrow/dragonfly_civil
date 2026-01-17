#!/usr/bin/env python3
"""
Network Connectivity Checker

Diagnoses network connectivity to Supabase pooler endpoints
using raw TCP handshake tests.

This helps identify whether connection timeouts are caused by:
- Network/firewall issues (TCP fails)
- Database/authentication issues (TCP succeeds but Postgres fails)

Usage:
    python -m tools.check_network
    python -m tools.check_network --host aws-0-us-east-1.pooler.supabase.com
    python -m tools.check_network --ref iaketsyhmqbwaabgykux --pooler dedicated

Exit Codes:
    0 = All endpoints reachable
    1 = One or more endpoints unreachable
    2 = Configuration error
"""

from __future__ import annotations

import argparse
import socket
import sys
from dataclasses import dataclass
from typing import Optional

# =============================================================================
# Constants
# =============================================================================

DEFAULT_PORT = 6543
DEFAULT_TIMEOUT = 5

# Project refs
PROD_PROJECT_REF = "iaketsyhmqbwaabgykux"
DEV_PROJECT_REF = "ejiddanxtqcleyswqvkc"

# Pooler host templates
SHARED_POOLER_TEMPLATE = "aws-0-{region}.pooler.supabase.com"
DEDICATED_POOLER_TEMPLATE = "db.{ref}.supabase.co"

# Known regions
REGIONS = ["us-east-1", "us-west-1", "eu-central-1", "ap-southeast-1"]

# Exit codes
EXIT_SUCCESS = 0
EXIT_UNREACHABLE = 1
EXIT_CONFIG_ERROR = 2


# =============================================================================
# Data Structures
# =============================================================================


@dataclass
class ProbeResult:
    """Result of a network probe."""

    host: str
    port: int
    reachable: bool
    latency_ms: Optional[float] = None
    error: Optional[str] = None


# =============================================================================
# Network Probing
# =============================================================================


def probe_tcp(host: str, port: int, timeout: float = DEFAULT_TIMEOUT) -> ProbeResult:
    """
    Attempt a raw TCP handshake with a host.

    Args:
        host: Hostname to connect to
        port: Port number
        timeout: Connection timeout in seconds

    Returns:
        ProbeResult with reachability status
    """
    import time

    start = time.perf_counter()

    try:
        # Attempt TCP connection
        sock = socket.create_connection((host, port), timeout=timeout)
        latency_ms = (time.perf_counter() - start) * 1000
        sock.close()

        return ProbeResult(
            host=host,
            port=port,
            reachable=True,
            latency_ms=round(latency_ms, 1),
        )

    except socket.timeout:
        return ProbeResult(
            host=host,
            port=port,
            reachable=False,
            error="TCP Timeout (Check Firewall/Status)",
        )

    except socket.gaierror as e:
        return ProbeResult(
            host=host,
            port=port,
            reachable=False,
            error=f"DNS Resolution Failed: {e}",
        )

    except ConnectionRefusedError:
        return ProbeResult(
            host=host,
            port=port,
            reachable=False,
            error="Connection Refused (Port not listening)",
        )

    except OSError as e:
        return ProbeResult(
            host=host,
            port=port,
            reachable=False,
            error=f"Network Error: {e}",
        )


def get_shared_pooler_host(region: str) -> str:
    """Get shared pooler hostname for region."""
    return SHARED_POOLER_TEMPLATE.format(region=region)


def get_dedicated_pooler_host(project_ref: str) -> str:
    """Get dedicated pooler hostname for project."""
    return DEDICATED_POOLER_TEMPLATE.format(ref=project_ref)


# =============================================================================
# CLI
# =============================================================================


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Diagnose network connectivity to Supabase pooler endpoints",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Check default endpoints (shared + dedicated for prod)
    python -m tools.check_network

    # Check specific host
    python -m tools.check_network --host aws-0-us-east-1.pooler.supabase.com

    # Check dedicated pooler for project
    python -m tools.check_network --ref iaketsyhmqbwaabgykux --pooler dedicated

    # Check shared pooler for specific region
    python -m tools.check_network --region eu-central-1

    # Check all known regions
    python -m tools.check_network --all-regions
""",
    )

    parser.add_argument(
        "--host",
        help="Specific host to check",
    )

    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Port to check (default: {DEFAULT_PORT})",
    )

    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help=f"Connection timeout in seconds (default: {DEFAULT_TIMEOUT})",
    )

    parser.add_argument(
        "--ref",
        default=PROD_PROJECT_REF,
        help=f"Supabase project reference (default: {PROD_PROJECT_REF})",
    )

    parser.add_argument(
        "--region",
        default="us-east-1",
        help="AWS region for shared pooler (default: us-east-1)",
    )

    parser.add_argument(
        "--pooler",
        choices=["shared", "dedicated", "both"],
        default="both",
        help="Which pooler type to check (default: both)",
    )

    parser.add_argument(
        "--all-regions",
        action="store_true",
        help="Check shared pooler in all known regions",
    )

    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Minimal output (just pass/fail)",
    )

    return parser


def print_result(result: ProbeResult, quiet: bool = False) -> None:
    """Print a probe result."""
    if result.reachable:
        if quiet:
            print(f"✅ {result.host}:{result.port}")
        else:
            print(f"✅ TCP Reachable: {result.host}:{result.port} ({result.latency_ms}ms)")
    else:
        if quiet:
            print(f"❌ {result.host}:{result.port}")
        else:
            print(f"❌ TCP Timeout: {result.host}:{result.port}")
            print(f"   Error: {result.error}")


def main() -> int:
    """Main entry point."""
    parser = build_parser()
    args = parser.parse_args()

    results: list[ProbeResult] = []

    if not args.quiet:
        print("=" * 70)
        print("SUPABASE NETWORK CONNECTIVITY CHECK")
        print("=" * 70)
        print()
        print(f"Timeout: {args.timeout}s")
        print()

    # =================================================================
    # Determine hosts to check
    # =================================================================
    hosts_to_check: list[tuple[str, int]] = []

    if args.host:
        # Specific host
        hosts_to_check.append((args.host, args.port))

    elif args.all_regions:
        # All known regions
        for region in REGIONS:
            host = get_shared_pooler_host(region)
            hosts_to_check.append((host, args.port))

    else:
        # Based on pooler type
        if args.pooler in ("shared", "both"):
            host = get_shared_pooler_host(args.region)
            hosts_to_check.append((host, args.port))

        if args.pooler in ("dedicated", "both"):
            host = get_dedicated_pooler_host(args.ref)
            hosts_to_check.append((host, args.port))

    # =================================================================
    # Probe each host
    # =================================================================
    for host, port in hosts_to_check:
        if not args.quiet:
            print(f"Probing {host}:{port}...")

        result = probe_tcp(host, port, timeout=args.timeout)
        results.append(result)
        print_result(result, quiet=args.quiet)

        if not args.quiet:
            print()

    # =================================================================
    # Summary
    # =================================================================
    reachable_count = sum(1 for r in results if r.reachable)
    total_count = len(results)

    if not args.quiet:
        print("=" * 70)
        print("SUMMARY")
        print("=" * 70)
        print()
        print(f"Reachable: {reachable_count}/{total_count}")
        print()

        if reachable_count == total_count:
            print("✅ All endpoints are network-reachable.")
            print()
            print("If you're still having connection issues, the problem is likely:")
            print("  - Authentication (wrong password)")
            print("  - Database/pooler configuration")
            print("  - Supabase service issue (check https://status.supabase.com/)")
        else:
            print("❌ Some endpoints are NOT reachable.")
            print()
            print("Possible causes:")
            print("  - Firewall blocking outbound port 6543")
            print("  - VPN/proxy interference")
            print("  - ISP blocking the connection")
            print("  - Supabase regional outage")
            print()
            print("Troubleshooting steps:")
            print("  1. Try a different network (mobile hotspot)")
            print("  2. Check corporate firewall rules")
            print("  3. Verify VPN is not interfering")
            print("  4. Check https://status.supabase.com/")

    return EXIT_SUCCESS if reachable_count == total_count else EXIT_UNREACHABLE


if __name__ == "__main__":
    sys.exit(main())
