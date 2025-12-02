from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from textwrap import dedent
from typing import Any, cast

import pytest

from etl.src.importers.jbi_900 import parse_jbi_900_csv
from etl.src.plaintiff_importer import aggregate_plaintiffs


@pytest.fixture()
def sample_csv(tmp_path: Path) -> Path:
    content = dedent(
        """\
        PlaintiffName,TotalJudgmentAmount,JudgmentDate,Status,Phone,Email,ContactName,LeadSource,County,State,CaseNumber
        Acme Collections,12500.00,2024-01-15,Enforcement Pending,(212) 555-0100,team@acme.com,Sarah North,Import,Queens,NY,NYC-123
        Acme Collections,9800.50,2024-02-01,Outreach Ready,(212) 555-0100,team@acme.com,Sarah North,Import,Queens,NY,NYC-456
        """
    )
    csv_path = tmp_path / "plaintiffs.csv"
    csv_path.write_text(content, encoding="utf-8")
    return csv_path


def test_aggregate_combines_rows(sample_csv: Path) -> None:
    aggregates = aggregate_plaintiffs(sample_csv)
    assert len(aggregates) == 1

    aggregate = cast(Any, aggregates[0])
    assert aggregate.name == "Acme Collections"
    assert len(aggregate.row_numbers) == 2
    assert aggregate.total_judgment_amount == Decimal("22300.50")
    assert aggregate.preview_contact == "Sarah North"

    contacts = aggregate.contacts
    assert contacts
    primary_contact = contacts[0]
    assert primary_contact.name == "Sarah North"
    assert primary_contact.email is None


def test_invalid_amount_is_ignored(tmp_path: Path) -> None:
    content = dedent(
        """\
        PlaintiffName,TotalJudgmentAmount,Status,ContactName
        River Finance,not-a-number,Open,Ben Harper
        """
    )
    csv_path = tmp_path / "invalid_amount.csv"
    csv_path.write_text(content, encoding="utf-8")

    aggregates = aggregate_plaintiffs(csv_path)
    assert len(aggregates) == 1
    first = cast(Any, aggregates[0])
    assert first.total_judgment_amount == Decimal("0")
    assert len(first.row_numbers) == 1


def test_jbi_parser_accepts_plaintiff_name_header(tmp_path: Path) -> None:
    content = dedent(
        """\
        case_number,plaintiff_name,judgment_amount
        DF-2025-0001,Empire Funding LLC,18750.00
        """
    )
    csv_path = tmp_path / "jbi_sample.csv"
    csv_path.write_text(content, encoding="utf-8")

    rows = parse_jbi_900_csv(str(csv_path))
    assert len(rows) == 1
    row = rows[0]
    assert row.case_number == "DF-2025-0001"
    assert row.plaintiff_name == "Empire Funding LLC"
