import pytest

from etl.collector_intel import CollectorIntelEngine, CollectorSignals


def test_evaluate_signals_rich_profile() -> None:
    signals = CollectorSignals(
        addresses=[
            "123 Main St, Albany NY 12207",
            "Suite 500, 1 W 34th St NY 10001",
        ],
        phones=["(555) 123-7890", "+1 917 555 0000"],
        employer_indicators=[
            "Employer verified payroll contact",
            "Stage advanced to wage garnishment",
        ],
        bank_indicators=[
            "Bank levy executed and confirmed",
            "Account freeze confirmed",
        ],
        enforcement_indicators=["Collected payment in full via turnover"],
    )
    breakdown = CollectorIntelEngine.evaluate_signals(signals)

    assert breakdown["address_quality"] == pytest.approx(20.0)
    assert breakdown["phone_validity"] == pytest.approx(20.0)
    assert breakdown["employer_signals"] == pytest.approx(12.0)
    assert breakdown["bank_signals"] == pytest.approx(13.0)
    assert breakdown["enforcement_success"] == pytest.approx(20.0)
    assert breakdown["collectability_score"] == pytest.approx(85.0)


def test_evaluate_signals_sparse_profile() -> None:
    signals = CollectorSignals(
        addresses=["PO Box 732"],
        phones=["55512"],
        employer_indicators=[],
        bank_indicators=[],
        enforcement_indicators=[],
    )
    breakdown = CollectorIntelEngine.evaluate_signals(signals)

    assert breakdown["address_quality"] == pytest.approx(8.0)
    assert breakdown["phone_validity"] == pytest.approx(5.0)
    assert breakdown["employer_signals"] == pytest.approx(0.0)
    assert breakdown["bank_signals"] == pytest.approx(5.0)
    assert breakdown["enforcement_success"] == pytest.approx(6.0)
    assert breakdown["collectability_score"] == pytest.approx(24.0)
