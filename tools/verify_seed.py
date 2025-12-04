"""Verify the seeded judgments in dev."""

import asyncio
import os
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

os.environ.setdefault("SUPABASE_MODE", "dev")


async def check():
    from backend.db import get_connection

    async with get_connection() as conn:
        rows = await conn.fetch(
            """
            SELECT case_number, plaintiff_name, defendant_name, 
                   judgment_amount, entry_date, source_file
            FROM public.judgments
            WHERE case_number LIKE '2024-CV-%'
            ORDER BY judgment_amount DESC
        """
        )

        print("\n=== SEEDED JUDGMENTS ===")
        print("-" * 120)
        print(
            f"{'Case #':15} | {'Plaintiff':30} | {'Defendant':20} | {'Amount':>12} | {'Date':10} | Source"
        )
        print("-" * 120)
        for r in rows:
            amt = f"${r['judgment_amount']:,.2f}" if r["judgment_amount"] else "N/A"
            print(
                f"{r['case_number']:15} | {(r['plaintiff_name'] or '')[:30]:30} | {(r['defendant_name'] or '')[:20]:20} | {amt:>12} | {str(r['entry_date'])[:10]:10} | {r['source_file']}"
            )
        print("-" * 120)
        print(f"Total: {len(rows)} rows")


if __name__ == "__main__":
    asyncio.run(check())
