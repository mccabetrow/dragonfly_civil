from __future__ import annotations

from tools import schema_guard


def _catalog_with_rpcs(rpc_names: set[str]):
    return schema_guard.SchemaCatalog(schemas={}, rpcs={"public": set(rpc_names)})


def _catalog_with_tables(table_names: set[str]):
    schemas = {
        "public": {
            "tables": set(table_names),
            "views": set(),
            "materialized_views": set(),
        }
    }
    return schema_guard.SchemaCatalog(schemas=schemas, rpcs={})


def test_diff_catalog_ignores_extension_noise():
    expected = _catalog_with_rpcs({"queue_job"})
    actual = _catalog_with_rpcs({"queue_job", "gin_trgm_consistent", "similarity"})

    diff = schema_guard.diff_catalog(expected, actual)

    assert diff.extra_rpcs == []
    assert diff.missing_rpcs == []


def test_diff_catalog_flags_missing_dragonfly_rpc():
    expected = _catalog_with_rpcs({"queue_job"})
    actual = _catalog_with_rpcs(set())

    diff = schema_guard.diff_catalog(expected, actual)

    assert diff.missing_rpcs == ["public.queue_job"]
    assert diff.extra_rpcs == []


def test_diff_catalog_flags_missing_table():
    expected = _catalog_with_tables({"judgments"})
    actual = _catalog_with_tables(set())

    diff = schema_guard.diff_catalog(expected, actual)

    assert diff.missing_relations == ["public.judgments (tables)"]
    assert diff.extra_relations == []
