from tools import prod_gate_helpers as helpers


def test_mask_secret_handles_none_and_empty() -> None:
    assert helpers.mask_secret(None) == "<unset>"
    assert helpers.mask_secret("   ") == "<unset>"


def test_mask_secret_masks_short_values() -> None:
    assert helpers.mask_secret("abcd") == "****"


def test_mask_secret_retains_ends_for_long_values() -> None:
    value = "abcdefghijklmnop"
    assert helpers.mask_secret(value) == "abcd************mnop"


def test_format_banner_pass_default_message() -> None:
    banner = helpers.format_banner("pass", [])
    assert "PROD GATE :: PASS" in banner
    assert "All gates passed." in banner


def test_format_banner_fail_lists_reasons_in_order() -> None:
    banner = helpers.format_banner("fail", ["health down", "readyz 503"])
    assert "PROD GATE :: FAIL" in banner
    assert "[1] health down" in banner
    assert "[2] readyz 503" in banner


def test_format_banner_rejects_invalid_status() -> None:
    try:
        helpers.format_banner("maybe", [])
    except ValueError as exc:
        assert "Invalid status" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Expected ValueError for invalid status")
