"""
Dummy Intake CSV Generator

Generates realistic-looking Simplicity-style CSV files for testing
the Intake Fortress end-to-end without touching real data.

Usage:
    python -m tools.generate_dummy_intake           # Generate 5 rows (default)
    python -m tools.generate_dummy_intake --rows 10 # Generate 10 rows
    python -m tools.generate_dummy_intake --help

Output:
    Creates `data_in/dummy_intake.csv` with Simplicity-compatible headers.
"""

from __future__ import annotations

import argparse
import csv
import random
from datetime import date, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Use exact headers that SIMPLICITY_MAPPING expects (first variant)
CSV_HEADERS = [
    "CaseNo",
    "Plaintiff",
    "Defendant",
    "JudgmentAmount",
    "JudgmentDate",
    "Court",
    "County",
]

# Sample data pools
PLAINTIFFS = [
    "ACME Collections LLC",
    "Empire Funding Corp",
    "Capital Recovery Associates",
    "Premier Credit Services",
    "Allied Financial Group",
    "Metro Judgment Solutions",
    "Sunrise Asset Recovery",
    "Ironclad Collections Inc",
    "Liberty Debt Buyers LLC",
    "Guardian Financial Services",
]

DEFENDANTS_FIRST = [
    "John",
    "Maria",
    "Michael",
    "Jennifer",
    "David",
    "Jessica",
    "Robert",
    "Ashley",
    "William",
    "Amanda",
    "James",
    "Sarah",
    "Christopher",
    "Emily",
    "Daniel",
]

DEFENDANTS_LAST = [
    "Smith",
    "Johnson",
    "Williams",
    "Brown",
    "Jones",
    "Garcia",
    "Miller",
    "Davis",
    "Rodriguez",
    "Martinez",
    "Lopez",
    "Hernandez",
    "Gonzalez",
    "Wilson",
    "Anderson",
]

COURTS = [
    "Queens Civil Court",
    "Kings Supreme Court",
    "Nassau District Court",
    "Suffolk County Court",
    "Bronx Civil Court",
    "Richmond Civil Court",
    "Westchester County Court",
    "New York Civil Court",
]

COUNTIES = [
    "Queens",
    "Kings",
    "Nassau",
    "Suffolk",
    "Bronx",
    "Richmond",
    "Westchester",
    "New York",
]

CASE_PREFIXES = ["CV", "A", "SC", "DC", ""]


# ---------------------------------------------------------------------------
# Generator Functions
# ---------------------------------------------------------------------------


def generate_case_number(year: int) -> str:
    """Generate a realistic NY civil case number."""
    prefix = random.choice(CASE_PREFIXES)
    number = random.randint(1000, 999999)

    patterns = [
        f"{prefix}-{year}-{number:05d}",  # CV-2023-00123
        f"{prefix}{number:03d}-{year}",  # A123-2024
        f"{number}/{year}",  # 702345/2022
        f"{year}-{number:06d}",  # 2023-001234
    ]
    return random.choice(patterns)


def generate_defendant_name() -> str:
    """Generate a random defendant name."""
    first = random.choice(DEFENDANTS_FIRST)
    last = random.choice(DEFENDANTS_LAST)
    return f"{first} {last}"


def generate_judgment_amount(*, ensure_high: bool = False) -> str:
    """
    Generate a realistic judgment amount.

    Args:
        ensure_high: If True, generate a high-value judgment (25k+)
    """
    if ensure_high:
        amount = random.uniform(25000, 45000)
    else:
        # Mix of amounts: most between 2,500-15,000, some higher
        if random.random() < 0.2:
            amount = random.uniform(15000, 30000)
        else:
            amount = random.uniform(2500, 15000)

    return f"{amount:.2f}"


def generate_judgment_date() -> str:
    """Generate a date in the last 5-7 years in ISO format."""
    today = date.today()
    days_back = random.randint(365, 365 * 7)  # 1-7 years ago
    judgment_date = today - timedelta(days=days_back)
    return judgment_date.isoformat()


def generate_row(*, ensure_high_amount: bool = False) -> dict[str, str]:
    """Generate a single dummy intake row."""
    # Random year for case number (2018-2024)
    year = random.randint(2018, 2024)

    # Pick matching court and county
    idx = random.randint(0, len(COURTS) - 1)
    court = COURTS[idx]
    county = COUNTIES[idx]

    return {
        "CaseNo": generate_case_number(year),
        "Plaintiff": random.choice(PLAINTIFFS),
        "Defendant": generate_defendant_name(),
        "JudgmentAmount": generate_judgment_amount(ensure_high=ensure_high_amount),
        "JudgmentDate": generate_judgment_date(),
        "Court": court,
        "County": county,
    }


def generate_dummy_csv(output_path: Path, num_rows: int = 5) -> list[dict[str, str]]:
    """
    Generate a dummy intake CSV file.

    Args:
        output_path: Path to write the CSV file
        num_rows: Number of rows to generate (default 5)

    Returns:
        List of generated rows
    """
    rows: list[dict[str, str]] = []

    for i in range(num_rows):
        # Ensure at least one high-value judgment
        ensure_high = i == 0
        rows.append(generate_row(ensure_high_amount=ensure_high))

    # Write CSV
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
        writer.writeheader()
        writer.writerows(rows)

    return rows


# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate dummy Simplicity-style intake CSV for testing.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python -m tools.generate_dummy_intake            # 5 rows
    python -m tools.generate_dummy_intake --rows 20  # 20 rows
        """,
    )
    parser.add_argument(
        "--rows",
        "-n",
        type=int,
        default=5,
        help="Number of rows to generate (default: 5)",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help="Output file path (default: data_in/dummy_intake.csv)",
    )

    args = parser.parse_args()

    # Determine output path
    if args.output:
        output_path = args.output
    else:
        # Default to data_in/ directory (consistent with other intake files)
        repo_root = Path(__file__).resolve().parent.parent
        output_path = repo_root / "data_in" / "dummy_intake.csv"

    # Generate the file
    rows = generate_dummy_csv(output_path, num_rows=args.rows)

    # Print summary
    example = rows[0]
    example_amount = float(example["JudgmentAmount"])
    print(f"✓ Wrote {output_path.name} with {len(rows)} rows.")
    print(f"  Location: {output_path}")
    print(f"  Example: {example['CaseNo']} – ${example_amount:,.2f}")


if __name__ == "__main__":
    main()
