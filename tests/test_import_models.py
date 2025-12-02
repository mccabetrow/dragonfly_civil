from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from etl.src.importers.simplicity_plaintiffs import (
    LAST_PARSE_ERRORS,
    ParseIssue,
    SimplicityImportRow,
    parse_simplicity_csv,
)


def _write_csv(tmp_path: Path, filename: str, rows: list[str]) -> Path:
    csv_path = tmp_path / filename
    csv_path.write_text("\n".join(rows), encoding="utf-8")
    return csv_path


def test_parse_simplicity_csv_returns_models(tmp_path: Path) -> None:
    csv_rows = [
        "LeadID,LeadSource,Court,IndexNumber,JudgmentDate,JudgmentAmount,County,State,PlaintiffName,PlaintiffAddress,Phone,Email,BestContactMethod",
        '101,Import,Queens Supreme Court,QSC-2023-1234,03/15/2023,15000.00,Queens,NY,ABC Collections,"123 Main St, Queens, NY",(718) 555-1111,collections@example.com,Phone',
    ]
    csv_path = _write_csv(tmp_path, "simplicity.csv", csv_rows)

    rows = parse_simplicity_csv(str(csv_path))

    assert LAST_PARSE_ERRORS == []
    assert len(rows) == 1
    payload = rows[0]
    assert isinstance(payload, SimplicityImportRow)
    assert payload.plaintiff_name == "ABC Collections"
    assert payload.plaintiff_state == "NY"
    assert payload.plaintiff_phone == "7185551111"
    assert payload.judgment_amount == Decimal("15000.00")
    assert payload.judgment_date == date(2023, 3, 15)
    assert payload.judgment_number == "QSC-2023-1234"
    assert payload.best_contact_method == "Phone"


def test_parse_simplicity_csv_records_validation_errors(tmp_path: Path) -> None:
    csv_rows = [
        "LeadID,LeadSource,Court,IndexNumber,JudgmentDate,JudgmentAmount,County,State,PlaintiffName,PlaintiffAddress,Phone,Email,BestContactMethod",
        '101,Import,Queens Supreme Court,QSC-2023-1234,03/15/2023,15000.00,Queens,NY,ABC Collections,"123 Main St, Queens, NY",(718) 555-1111,collections@example.com,Phone',
        '102,Import,Kings County Court,,03/15/2023,not-a-number,Kings,New York,XYZ Recovery,"789 Court St, Brooklyn, NY",555-1000,bad-email,Email',
    ]
    csv_path = _write_csv(tmp_path, "simplicity_invalid.csv", csv_rows)

    rows = parse_simplicity_csv(str(csv_path))

    assert len(rows) == 1
    assert len(LAST_PARSE_ERRORS) == 1
    issue: ParseIssue = LAST_PARSE_ERRORS[0]
    assert issue.row_number == 3
    assert isinstance(issue.error, str)
    assert "invalid judgment amount" in issue.error.lower()


def test_simplicity_import_row_rejects_bad_phone() -> None:
    with pytest.raises(Exception):
        SimplicityImportRow.model_validate(
            {
                "plaintiff_name": "Example",
                "judgment_number": "IDX-1",
                "judgment_amount": "1000.00",
                "judgment_date": "2024-01-01",
                "plaintiff_phone": "12",
            }
        )
