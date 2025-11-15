from etl.src.enrichment_bundle import build_stub_enrichment


def test_build_stub_enrichment_uses_snapshot_data():
    snapshot = {
        "case_id": "case-123",
        "case_number": "CN-123",
        "judgment_amount": "4500",
        "age_days": 120,
        "collectability_tier": "A",
    }
    payload = {"case_number": "CN-123"}

    result = build_stub_enrichment("case-123", snapshot, job_payload=payload)

    assert result.summary.startswith("Collectability tier A")
    raw = result.raw
    assert raw["bundle"] == "stub:v1"
    assert raw["case_number"] == "CN-123"
    assert raw["tier_hint"] == "A"
    assert raw["metrics"]["judgment_amount"] == "4500.00"
    assert raw["metrics"]["age_days"] == 120
    assert raw["signals"]["amount_bucket"] == "high"
    assert raw["signals"]["age_bucket"] == "fresh"
    assert raw["source_payload"] == payload


def test_build_stub_enrichment_handles_missing_data():
    result = build_stub_enrichment("case-xyz", {}, job_payload={})

    assert result.raw["case_number"] == "case-xyz"
    assert result.raw["metrics"]["judgment_amount"] is None
    assert result.raw["tier_hint"] == "C"
    assert result.raw["signals"]["amount_bucket"] == "unknown"
    assert result.raw["signals"]["age_bucket"] == "unknown"
    assert result.raw["source_payload"] == {}
    assert result.summary.endswith("(stub)")
