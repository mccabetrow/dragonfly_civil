from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Mapping, Sequence, Set

import psycopg

from src.supabase_client import get_supabase_db_url

SCHEMA_FREEZE_PATH = Path("state/schema_freeze.json")
RELATION_CATEGORIES: tuple[str, ...] = ("tables", "views", "materialized_views")
RELKIND_TO_CATEGORY: Dict[str, str] = {
    "r": "tables",
    "p": "tables",
    "v": "views",
    "m": "materialized_views",
}
DEFAULT_RELATION_SCHEMAS: tuple[str, ...] = ("public",)
DEFAULT_RPC_SCHEMAS: tuple[str, ...] = ("public",)
IGNORED_RPC_PREFIXES: tuple[str, ...] = (
    "gin_",
    "gtrgm_",
    "similarity",
    "word_similarity",
    "strict_word_similarity",
    "show_trgm",
    "show_limit",
    "set_limit",
)


@dataclass(frozen=True)
class SchemaCatalog:
    schemas: Dict[str, Dict[str, Set[str]]]
    rpcs: Dict[str, Set[str]]


@dataclass(frozen=True)
class SchemaDiff:
    missing_relations: list[str]
    extra_relations: list[str]
    missing_rpcs: list[str]
    extra_rpcs: list[str]

    def is_clean(self) -> bool:
        return not (
            self.missing_relations or self.extra_relations or self.missing_rpcs or self.extra_rpcs
        )


def _empty_schema_bucket() -> Dict[str, Set[str]]:
    return {category: set() for category in RELATION_CATEGORIES}


def is_trackable_rpc(name: str | None, extension: str | None = None) -> bool:
    if not name:
        return False
    if extension:
        # Functions shipped by extensions should not be included in our freeze.
        return False
    lowered = name.strip().lower()
    if not lowered:
        return False
    return not any(lowered.startswith(prefix) for prefix in IGNORED_RPC_PREFIXES)


def _upgrade_legacy_payload(payload: dict[str, object]) -> dict[str, object]:
    relations = payload.get("relations")
    if not isinstance(relations, list):
        raise ValueError("schema freeze is missing both schemas and relations keys")

    schema_bucket: Dict[str, Dict[str, list[str]]] = {
        "public": {category: [] for category in RELATION_CATEGORIES}
    }
    for relation in relations:
        kind = relation.get("kind")
        name = relation.get("name")
        category = RELKIND_TO_CATEGORY.get(str(kind))
        if not category or not isinstance(name, str):
            continue
        schema_bucket["public"][category].append(name)

    upgraded = dict(payload)
    upgraded["schemas"] = schema_bucket
    upgraded.setdefault("rpcs", {})
    return upgraded


def load_schema_freeze(path: Path = SCHEMA_FREEZE_PATH) -> dict[str, object]:
    raw = json.loads(path.read_text())
    if "schemas" not in raw:
        raw = _upgrade_legacy_payload(raw)
    raw.setdefault("rpcs", {})
    return raw


def _normalize_names(values: Iterable[str]) -> Set[str]:
    return {str(value).strip() for value in values if value}


def normalize_freeze(raw: Mapping[str, object]) -> SchemaCatalog:
    schemas_raw = raw.get("schemas")
    if not isinstance(schemas_raw, Mapping):
        raise ValueError("schema freeze must include a schemas mapping")

    schemas: Dict[str, Dict[str, Set[str]]] = {}
    for schema_name, categories in schemas_raw.items():
        if not isinstance(schema_name, str) or not isinstance(categories, Mapping):
            continue
        bucket = _empty_schema_bucket()
        for category in RELATION_CATEGORIES:
            names = categories.get(category, []) if isinstance(categories, Mapping) else []
            if isinstance(names, Sequence):
                bucket[category] = _normalize_names(names)
        schemas[schema_name] = bucket

    rpcs_raw = raw.get("rpcs", {})
    rpcs: Dict[str, Set[str]] = {}
    if isinstance(rpcs_raw, Mapping):
        for schema_name, names in rpcs_raw.items():
            if isinstance(schema_name, str) and isinstance(names, Sequence):
                filtered = {value for value in _normalize_names(names) if is_trackable_rpc(value)}
                rpcs[schema_name] = filtered

    return SchemaCatalog(schemas=schemas, rpcs=rpcs)


def capture_catalog(
    conn: psycopg.Connection,
    relation_schemas: Iterable[str] | None = None,
    rpc_schemas: Iterable[str] | None = None,
) -> SchemaCatalog:
    relation_targets = tuple(relation_schemas or DEFAULT_RELATION_SCHEMAS)
    rpc_targets = tuple(rpc_schemas or DEFAULT_RPC_SCHEMAS)

    schemas: Dict[str, Dict[str, Set[str]]] = {}
    if relation_targets:
        rel_query = """
            SELECT n.nspname, c.relname, c.relkind
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = ANY(%s)
              AND c.relkind = ANY(%s)
        """
        relkinds = tuple(RELKIND_TO_CATEGORY.keys())
        with conn.cursor() as cur:
            cur.execute(rel_query, (list(relation_targets), list(relkinds)))
            for schema_name, relname, kind in cur.fetchall():
                if not isinstance(schema_name, str) or not isinstance(relname, str):
                    continue
                bucket = schemas.setdefault(schema_name, _empty_schema_bucket())
                category = RELKIND_TO_CATEGORY.get(str(kind))
                if not category:
                    continue
                bucket[category].add(relname)

    rpcs: Dict[str, Set[str]] = {}
    if rpc_targets:
        fn_query = """
            SELECT n.nspname, p.proname, ext.extname
            FROM pg_proc p
            JOIN pg_namespace n ON n.oid = p.pronamespace
            LEFT JOIN pg_depend d
              ON d.classid = 'pg_proc'::regclass
             AND d.objid = p.oid
             AND d.deptype = 'e'
            LEFT JOIN pg_extension ext ON ext.oid = d.refobjid
            WHERE n.nspname = ANY(%s)
              AND p.prokind = 'f'
        """
        with conn.cursor() as cur:
            cur.execute(fn_query, (list(rpc_targets),))
            for schema_name, fn_name, extension_name in cur.fetchall():
                if not isinstance(schema_name, str) or not isinstance(fn_name, str):
                    continue
                if not is_trackable_rpc(fn_name, extension=extension_name):
                    continue
                rpcs.setdefault(schema_name, set()).add(fn_name)

    return SchemaCatalog(schemas=schemas, rpcs=rpcs)


def catalog_to_snapshot(catalog: SchemaCatalog) -> dict[str, object]:
    return {
        "schemas": {
            schema: {
                category: sorted(bucket.get(category, set())) for category in RELATION_CATEGORIES
            }
            for schema, bucket in catalog.schemas.items()
        },
        "rpcs": {schema: sorted(names) for schema, names in catalog.rpcs.items()},
    }


def compute_snapshot_hash(snapshot: Mapping[str, object]) -> str:
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode("utf-8")).hexdigest()


def diff_catalog(expected: SchemaCatalog, actual: SchemaCatalog) -> SchemaDiff:
    missing_relations: list[str] = []
    extra_relations: list[str] = []

    schema_names = set(expected.schemas.keys()) | set(actual.schemas.keys())
    for schema in sorted(schema_names):
        expected_bucket = expected.schemas.get(schema, _empty_schema_bucket())
        actual_bucket = actual.schemas.get(schema, _empty_schema_bucket())
        for category in RELATION_CATEGORIES:
            expected_names = expected_bucket.get(category, set())
            actual_names = actual_bucket.get(category, set())
            missing_relations.extend(
                f"{schema}.{name} ({category})" for name in sorted(expected_names - actual_names)
            )
            extra_relations.extend(
                f"{schema}.{name} ({category})" for name in sorted(actual_names - expected_names)
            )

    missing_rpcs: list[str] = []
    extra_rpcs: list[str] = []
    rpc_schemas = set(expected.rpcs.keys()) | set(actual.rpcs.keys())
    for schema in sorted(rpc_schemas):
        expected_names = {
            name for name in expected.rpcs.get(schema, set()) if is_trackable_rpc(name)
        }
        actual_names = {name for name in actual.rpcs.get(schema, set()) if is_trackable_rpc(name)}
        missing_rpcs.extend(f"{schema}.{name}" for name in sorted(expected_names - actual_names))
        extra_rpcs.extend(f"{schema}.{name}" for name in sorted(actual_names - expected_names))

    return SchemaDiff(
        missing_relations=missing_relations,
        extra_relations=extra_relations,
        missing_rpcs=missing_rpcs,
        extra_rpcs=extra_rpcs,
    )


def format_drift(drift: SchemaDiff) -> list[str]:
    messages: list[str] = []
    for rel in drift.missing_relations:
        messages.append(f"missing relation: {rel}")
    for rel in drift.extra_relations:
        messages.append(f"unexpected relation: {rel}")
    for rpc in drift.missing_rpcs:
        messages.append(f"missing rpc: {rpc}")
    for rpc in drift.extra_rpcs:
        messages.append(f"unexpected rpc: {rpc}")
    return messages


def diff_connection_against_freeze(
    conn: psycopg.Connection,
    freeze_data: Mapping[str, object] | None = None,
    *,
    freeze_path: Path = SCHEMA_FREEZE_PATH,
) -> SchemaDiff:
    freeze = freeze_data or load_schema_freeze(freeze_path)
    expected = normalize_freeze(freeze)
    relation_schemas = expected.schemas.keys() or DEFAULT_RELATION_SCHEMAS
    rpc_schemas = expected.rpcs.keys() or DEFAULT_RPC_SCHEMAS
    actual = capture_catalog(conn, relation_schemas, rpc_schemas)
    return diff_catalog(expected, actual)


def diff_env_against_freeze(
    env: str,
    *,
    freeze_path: Path = SCHEMA_FREEZE_PATH,
) -> SchemaDiff:
    db_url = get_supabase_db_url(env)
    with psycopg.connect(db_url, connect_timeout=5) as conn:
        return diff_connection_against_freeze(conn, freeze_path=freeze_path)
