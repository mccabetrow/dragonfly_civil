from __future__ import annotations

import pytest

from tools.security_audit import PIPELINE_VIEWS, RESTRICTED_TABLES, RelationSecurity, evaluate_rules

# =============================================================================
# MARKERS
# =============================================================================

pytestmark = pytest.mark.security  # Security gate marker


def _mk_relation(
    name: str,
    kind: str = "r",
    *,
    rls_enabled: bool = True,
    rls_forced: bool = False,
) -> RelationSecurity:
    return RelationSecurity(
        name=name,
        kind=kind,
        rls_enabled=rls_enabled,
        rls_forced=rls_forced,
    )


def test_restricted_tables_disallow_any_grants():
    rel = _mk_relation("import_runs")
    rel.grants["authenticated"] = {"SELECT"}

    violations = evaluate_rules([rel])

    assert any("import_runs" in message for message in violations)


def test_pipeline_views_allow_only_select():
    view_name = next(iter(PIPELINE_VIEWS))
    rel = _mk_relation(view_name, kind="v")
    rel.grants["authenticated"] = {"SELECT"}
    rel.grants["anon"] = {"SELECT"}

    assert evaluate_rules([rel]) == []


def test_pipeline_views_flag_extra_privileges():
    view_name = next(iter(PIPELINE_VIEWS))
    rel = _mk_relation(view_name, kind="v")
    rel.grants["authenticated"] = {"SELECT", "INSERT"}

    violations = evaluate_rules([rel])

    assert any("must only have SELECT" in message for message in violations)


def test_other_views_cannot_be_granted():
    rel = _mk_relation("v_internal_debug", kind="v")
    rel.grants["anon"] = {"SELECT"}

    violations = evaluate_rules([rel])

    assert any("v_internal_debug" in message for message in violations)


def test_public_role_is_treated_as_violation():
    restricted_name = next(iter(RESTRICTED_TABLES))
    rel = _mk_relation(restricted_name)
    rel.grants["public"] = {"SELECT"}

    violations = evaluate_rules([rel])

    assert any("role 'public'" in message for message in violations)


def test_key_table_allows_expected_writers():
    rel = _mk_relation("plaintiff_tasks", rls_forced=True)
    rel.grants["service_role"] = {"SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE"}

    assert evaluate_rules([rel]) == []


def test_key_table_missing_service_role_write_is_violation():
    rel = _mk_relation("plaintiff_tasks", rls_forced=True)

    violations = evaluate_rules([rel])

    assert any("missing write privileges" in message for message in violations)


def test_key_table_rejects_unexpected_writers():
    rel = _mk_relation("plaintiff_tasks", rls_forced=True)
    rel.grants["service_role"] = {"SELECT", "INSERT", "UPDATE", "DELETE"}
    rel.grants["authenticated"] = {"SELECT", "INSERT"}

    violations = evaluate_rules([rel])

    assert any("unexpected write privileges" in message for message in violations)


def test_key_table_requires_forced_rls():
    rel = _mk_relation("plaintiff_call_attempts", rls_forced=False)
    rel.grants["service_role"] = {"SELECT", "INSERT", "UPDATE", "DELETE"}

    violations = evaluate_rules([rel])

    assert any("RLS must be forced" in message for message in violations)


def test_truncate_privileges_flagged_for_non_allowed_role():
    rel = _mk_relation("plaintiff_tasks", rls_forced=True)
    rel.grants["service_role"] = {"SELECT", "INSERT", "UPDATE", "DELETE"}
    rel.grants["authenticated"] = {"TRUNCATE"}

    violations = evaluate_rules([rel])

    assert any("unexpected write privileges" in message for message in violations)
