"""Tests for the plaintiff vendor adapter."""

from etl.src.plaintiff_vendor_adapter import CANONICAL_HEADERS, map_vendor_row_to_plaintiff


def test_simplicity_mapping_generates_canonical_row():
    row = {
        "case_number": "SIM-001",
        "title": "Sample Case A",
        "amount_awarded": "4500",
    }

    result = map_vendor_row_to_plaintiff(row, "simplicity")
    assert result is not None

    for header in CANONICAL_HEADERS:
        assert header in result

    assert result["PlaintiffName"] == "Sample Case A"
    assert result["ContactName"] == "Sample Case A"
    assert result["ContactEmail"] == ""
    assert result["FirmName"] == ""
    assert result["TotalJudgmentAmount"] == "4500"


def test_simplicity_mapping_requires_plaintiff_name():
    row = {
        "amount_awarded": "800",
        "contact_email": "missing@example.test",
    }

    assert map_vendor_row_to_plaintiff(row, "simplicity") is None
