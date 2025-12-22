#!/usr/bin/env python3
"""
Incident Report Scaffolder

Usage:
    python -m tools.new_incident "Brief Title"
    python -m tools.new_incident "Worker OOM crash" --severity SEV-2

Creates a new incident report from template with auto-generated ID.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# Paths relative to project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = PROJECT_ROOT / "docs" / "templates" / "incident_report.md"
INCIDENTS_DIR = PROJECT_ROOT / "docs" / "incidents"


def slugify(title: str) -> str:
    """Convert title to filesystem-safe slug."""
    # Lowercase, replace spaces/special chars with underscores
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", title.lower())
    # Remove leading/trailing underscores
    slug = slug.strip("_")
    # Truncate to reasonable length
    return slug[:50]


def get_next_incident_id(date_str: str) -> str:
    """
    Generate the next incident ID for a given date.
    Format: YYYY-MM-DD-NN where NN is a zero-padded index.
    """
    INCIDENTS_DIR.mkdir(parents=True, exist_ok=True)

    # Find existing incidents for this date
    pattern = f"{date_str}_*"
    existing = list(INCIDENTS_DIR.glob(pattern))

    # Extract indices
    indices = []
    for path in existing:
        # Filename format: YYYY-MM-DD_NN_title.md
        parts = path.stem.split("_")
        if len(parts) >= 2:
            try:
                indices.append(int(parts[1]))
            except ValueError:
                pass

    # Next index
    next_idx = max(indices, default=0) + 1
    return f"{date_str}-{next_idx:02d}"


def create_incident_report(title: str, severity: str = "SEV-2") -> Path:
    """
    Create a new incident report from template.

    Args:
        title: Brief description of the incident
        severity: SEV-1, SEV-2, or SEV-3

    Returns:
        Path to the created incident report
    """
    # Validate severity
    if severity not in ("SEV-1", "SEV-2", "SEV-3"):
        print(f"⚠️  Invalid severity '{severity}', defaulting to SEV-2")
        severity = "SEV-2"

    # Read template
    if not TEMPLATE_PATH.exists():
        print(f"❌ Template not found: {TEMPLATE_PATH}")
        sys.exit(1)

    template = TEMPLATE_PATH.read_text(encoding="utf-8")

    # Generate metadata
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%Y-%m-%d %H:%M UTC")
    incident_id = get_next_incident_id(date_str)
    slug = slugify(title)

    # Filename format: YYYY-MM-DD_NN_title.md
    idx = incident_id.split("-")[-1]  # Extract the NN part
    filename = f"{date_str}_{idx}_{slug}.md"
    output_path = INCIDENTS_DIR / filename

    # Fill in template
    content = template

    # Replace metadata placeholders using regex for flexibility with whitespace
    content = re.sub(
        r"\| Incident ID \| `YYYY-MM-DD-01`\s*\|",
        f"| Incident ID | `{incident_id}` |",
        content,
    )
    content = re.sub(
        r"\| Severity\s+\| `SEV-1` / `SEV-2` / `SEV-3`\s*\|",
        f"| Severity    | `{severity}` |",
        content,
    )
    content = re.sub(
        r"\| Status\s+\| `Open` / `Resolved`\s*\|",
        "| Status      | `Open` |",
        content,
    )
    content = re.sub(
        r"\| Created\s+\| YYYY-MM-DD HH:MM UTC\s*\|",
        f"| Created     | {time_str} |",
        content,
    )

    # Add title to first timeline entry
    content = re.sub(
        r"\| YYYY-MM-DD HH:MM \| \*\*Detection\*\*: Alert fired / User reported\s*\|",
        f"| {time_str} | **Detection**: {title} |",
        content,
    )

    # Remove the template comment block
    content = re.sub(
        r"<!--\s*TEMPLATE:.*?-->",
        f"<!-- Incident: {title} -->",
        content,
        flags=re.DOTALL,
    )

    # Write the report
    INCIDENTS_DIR.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")

    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create a new incident report",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m tools.new_incident "Queue processing stuck"
  python -m tools.new_incident "Data corruption in plaintiffs" --severity SEV-1
  python -m tools.new_incident "Dashboard slow loading" --severity SEV-3
        """,
    )
    parser.add_argument("title", help="Brief title describing the incident")
    parser.add_argument(
        "--severity",
        "-s",
        choices=["SEV-1", "SEV-2", "SEV-3"],
        default="SEV-2",
        help="Incident severity (default: SEV-2)",
    )

    args = parser.parse_args()

    # Create the report
    report_path = create_incident_report(args.title, args.severity)

    # Output
    relative_path = report_path.relative_to(PROJECT_ROOT)

    severity_emoji = {"SEV-1": "🔴", "SEV-2": "🟠", "SEV-3": "🟡"}
    emoji = severity_emoji.get(args.severity, "🚨")

    print()
    print(f"{emoji} Incident Report Created: {relative_path}")
    print()
    print("📝 Next steps:")
    print("   1. Open the report and log your timeline immediately")
    print("   2. Fill in the Executive Summary")
    print("   3. Work through the 5 Whys as you investigate")
    print()
    print("⚡ Quick open:")
    print(f"   code {relative_path}")
    print()


if __name__ == "__main__":
    main()
