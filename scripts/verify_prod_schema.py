"""Verify prod schema and reload PostgREST."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import psycopg  # noqa: E402

from src.supabase_client import get_supabase_db_url  # noqa: E402


def main() -> int:
    db_url = get_supabase_db_url("prod")

    with psycopg.connect(db_url, connect_timeout=30) as conn:
        with conn.cursor() as cur:
            # Reload PostgREST schema cache
            cur.execute("NOTIFY pgrst, 'reload schema'")
            conn.commit()
            print("[OK] PostgREST schema reload triggered")

            # Verify key views
            checks = [
                "v_metrics_intake_daily",
                "v_metrics_pipeline",
                "v_enforcement_pipeline_status",
                "v_offer_stats",
                "v_radar",
                "v_enrichment_health",
                "events",
                "v_plaintiffs_overview",
                "v_enforcement_overview",
                "v_plaintiff_call_queue",
                "v_judgment_pipeline",
                "v_collectability_snapshot",
            ]

            print("\nView existence check:")
            missing = []
            for name in checks:
                cur.execute(
                    "SELECT to_regclass(%s) IS NOT NULL",
                    (f"public.{name}",),
                )
                exists = cur.fetchone()[0]
                status = "OK" if exists else "MISSING"
                print(f"  [{status}] {name}")
                if not exists:
                    missing.append(name)

            if missing:
                print(
                    f"\n[WARN] {len(missing)} view(s) still missing: {', '.join(missing)}"
                )
                return 1
            else:
                print("\n[OK] All critical views exist in prod")
                return 0


if __name__ == "__main__":
    raise SystemExit(main())
