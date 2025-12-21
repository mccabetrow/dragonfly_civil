#!/usr/bin/env python3
"""
Helper script for verify_deployment.ps1
Checks worker heartbeats in the database for matching version.

Usage:
    python check_worker_heartbeat.py <connection_string> <expected_sha>

Output:
    JSON with worker heartbeat information
"""

import json
import sys
from datetime import datetime, timezone


def main():
    if len(sys.argv) < 3:
        print(json.dumps({"error": "Usage: check_worker_heartbeat.py <dsn> <expected_sha>"}))
        sys.exit(1)

    dsn = sys.argv[1]
    expected_sha = sys.argv[2].lower()[:7]

    try:
        import psycopg

        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                # Find workers with recent heartbeat and matching version
                cur.execute(
                    """
                    SELECT
                        worker_id,
                        worker_type,
                        last_seen,
                        metadata->>'version' as version,
                        EXTRACT(EPOCH FROM (NOW() - last_seen)) as age_seconds
                    FROM ops.worker_heartbeats
                    WHERE last_seen > NOW() - INTERVAL '1 minute'
                    ORDER BY last_seen DESC
                """
                )
                rows = cur.fetchall()

                result = {
                    "total_recent": len(rows),
                    "workers": [],
                    "matching": [],
                    "matching_count": 0,
                }

                for row in rows:
                    worker = {
                        "id": row[0],
                        "type": row[1],
                        "version": row[3],
                        "age_seconds": float(row[4]) if row[4] else None,
                    }
                    result["workers"].append(worker)

                    # Check version match
                    if row[3]:
                        normalized = row[3][:7].lower() if len(row[3]) >= 7 else row[3].lower()
                        if normalized == expected_sha:
                            result["matching"].append(worker)

                result["matching_count"] = len(result["matching"])
                print(json.dumps(result))

    except ImportError:
        # Try psycopg2 as fallback
        try:
            import psycopg2

            with psycopg2.connect(dsn) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT
                            worker_id,
                            worker_type,
                            last_seen,
                            metadata->>'version' as version,
                            EXTRACT(EPOCH FROM (NOW() - last_seen)) as age_seconds
                        FROM ops.worker_heartbeats
                        WHERE last_seen > NOW() - INTERVAL '1 minute'
                        ORDER BY last_seen DESC
                    """
                    )
                    rows = cur.fetchall()

                    result = {
                        "total_recent": len(rows),
                        "workers": [],
                        "matching": [],
                        "matching_count": 0,
                    }

                    for row in rows:
                        worker = {
                            "id": row[0],
                            "type": row[1],
                            "version": row[3],
                            "age_seconds": float(row[4]) if row[4] else None,
                        }
                        result["workers"].append(worker)

                        if row[3]:
                            normalized = row[3][:7].lower() if len(row[3]) >= 7 else row[3].lower()
                            if normalized == expected_sha:
                                result["matching"].append(worker)

                    result["matching_count"] = len(result["matching"])
                    print(json.dumps(result))

        except ImportError:
            print(json.dumps({"error": "Neither psycopg nor psycopg2 is installed"}))
            sys.exit(1)

    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
