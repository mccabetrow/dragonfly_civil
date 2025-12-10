from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Sequence, Set, Tuple
from urllib.parse import unquote, urlparse

import psycopg

from src.supabase_client import get_supabase_db_url, get_supabase_env


@dataclass(frozen=True)
class FlowReference:
    flow_path: Path
    kind: str  # "rpc" or "relation"
    name: str
    normalized_name: str
    node_name: str
    is_stub_flow: bool = False
    allow_missing: bool = False


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m tools.validate_n8n_flows",
        description="Validate that n8n flows reference existing Supabase objects.",
    )
    parser.add_argument(
        "--env",
        type=str,
        default=None,
        help="Override SUPABASE_MODE / get_supabase_env().",
    )
    parser.add_argument(
        "--flow-dir",
        type=str,
        default="n8n/flows",
        help="Directory containing n8n flow JSON files (default: n8n/flows).",
    )
    return parser.parse_args(argv)


def _iter_flow_files(flow_dir: Path) -> Iterable[Path]:
    if not flow_dir.exists():
        return []
    return sorted(p for p in flow_dir.glob("*.json") if p.is_file())


def _clean_identifier(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = unquote(value).strip()
    if not cleaned:
        return None
    return cleaned


def _extract_from_url(url: str | None, flow_path: Path, node_name: str) -> List[FlowReference]:
    if not url or "/rest/v1" not in url:
        return []

    parsed = urlparse(url)
    path = parsed.path or ""
    marker = "/rest/v1"
    idx = path.lower().find(marker)
    if idx == -1:
        return []
    remainder = path[idx + len(marker) :].lstrip("/")
    if not remainder:
        return []

    remainder = remainder.split("?", 1)[0]
    remainder = remainder.strip("/")
    if not remainder:
        return []

    parts = remainder.split("/", 1)
    head = _clean_identifier(parts[0])
    if not head:
        return []

    references: List[FlowReference] = []
    if head.lower() == "rpc" and len(parts) > 1:
        rpc_name = _clean_identifier(parts[1].split("/", 1)[0])
        if rpc_name:
            references.append(
                FlowReference(
                    flow_path=flow_path,
                    kind="rpc",
                    name=rpc_name,
                    normalized_name=_normalize_reference_name(rpc_name),
                    node_name=node_name,
                )
            )
    else:
        references.append(
            FlowReference(
                flow_path=flow_path,
                kind="relation",
                name=head,
                normalized_name=_normalize_reference_name(head),
                node_name=node_name,
            )
        )
    return references


def _extract_from_supabase_node(node: dict, flow_path: Path, node_name: str) -> List[FlowReference]:
    params = node.get("parameters", {})
    table = params.get("table")
    if isinstance(table, str):
        cleaned = _clean_identifier(table)
        if cleaned and not cleaned.startswith("={{"):
            return [
                FlowReference(
                    flow_path=flow_path,
                    kind="relation",
                    name=cleaned,
                    normalized_name=_normalize_reference_name(cleaned),
                    node_name=node_name,
                )
            ]
    return []


def _normalize_reference_name(value: str) -> str:
    normalized = value.strip().lower()
    if normalized.startswith("public."):
        return normalized[len("public.") :]
    return normalized


def collect_flow_references(flow_dir: Path) -> List[FlowReference]:
    references: List[FlowReference] = []
    seen: Set[Tuple[Path, str, str]] = set()

    for flow_file in _iter_flow_files(flow_dir):
        with flow_file.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        is_stub = data.get("dragonfly_stub", False) if isinstance(data, dict) else False
        meta = data.get("meta", {}) if isinstance(data, dict) else {}
        allow_missing = False
        if isinstance(meta, dict):
            allow_missing = bool(meta.get("allow_missing"))
        nodes = data.get("nodes", []) if isinstance(data, dict) else []
        for node in nodes:
            node_name = node.get("name") or node.get("id") or "unknown"
            params = node.get("parameters", {}) if isinstance(node, dict) else {}
            node_refs: List[FlowReference] = []

            if isinstance(params, dict):
                node_refs.extend(_extract_from_url(params.get("url"), flow_file, node_name))
            if node.get("type") == "n8n-nodes-base.supabase":
                node_refs.extend(_extract_from_supabase_node(node, flow_file, node_name))

            for ref in node_refs:
                key = (ref.flow_path, ref.kind, ref.normalized_name)
                if key in seen:
                    continue
                seen.add(key)
                # Attach stub flag to the reference
                references.append(
                    FlowReference(
                        flow_path=ref.flow_path,
                        kind=ref.kind,
                        name=ref.name,
                        normalized_name=ref.normalized_name,
                        node_name=ref.node_name,
                        is_stub_flow=is_stub,
                        allow_missing=allow_missing,
                    )
                )

    return references


def _fetch_relations(env: str) -> Set[str]:
    db_url = get_supabase_db_url(env)
    query = """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
        UNION
        SELECT table_name
        FROM information_schema.views
        WHERE table_schema = 'public';
    """
    with psycopg.connect(db_url, connect_timeout=10) as conn:
        with conn.cursor() as cur:
            cur.execute(query)
            return {row[0].lower() for row in cur.fetchall() if row[0]}


def _fetch_rpcs(env: str) -> Set[str]:
    db_url = get_supabase_db_url(env)
    query = """
        SELECT p.proname
        FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'public';
    """
    with psycopg.connect(db_url, connect_timeout=10) as conn:
        with conn.cursor() as cur:
            cur.execute(query)
            return {row[0].lower() for row in cur.fetchall() if row[0]}


def evaluate_references(
    references: Sequence[FlowReference],
    relations: Set[str],
    rpcs: Set[str],
) -> List[Tuple[FlowReference, bool]]:
    results: List[Tuple[FlowReference, bool]] = []
    for ref in references:
        exists = ref.normalized_name in (rpcs if ref.kind == "rpc" else relations)
        results.append((ref, exists))
    return results


def _print_report(findings: Sequence[Tuple[FlowReference, bool]]) -> None:
    if not findings:
        print("[validate_n8n_flows] No Supabase references detected in n8n flows.")
        return

    for ref, exists in findings:
        if exists:
            status = "OK"
        elif ref.is_stub_flow or ref.allow_missing:
            status = "WARN"
        else:
            status = "MISSING"
        subject = f"{ref.kind} {ref.name}"
        print(
            f"[{status}] {subject} referenced by flow {ref.flow_path.name} (node: {ref.node_name})"
        )


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    env = args.env or get_supabase_env()
    flow_dir = Path(args.flow_dir)

    references = collect_flow_references(flow_dir)
    relations = _fetch_relations(env)
    rpcs = _fetch_rpcs(env)
    findings = evaluate_references(references, relations, rpcs)
    _print_report(findings)

    # Only count non-stub missing references as failures
    missing = [
        ref
        for ref, exists in findings
        if not exists and not ref.is_stub_flow and not ref.allow_missing
    ]
    warned = [
        ref for ref, exists in findings if not exists and (ref.is_stub_flow or ref.allow_missing)
    ]

    if warned:
        print(
            f"[validate_n8n_flows] {len(warned)} stub flow warning(s) (non-blocking).",
        )

    if missing:
        print(
            f"[validate_n8n_flows] {len(missing)} missing reference(s) detected.",
        )
        return 1

    print("[validate_n8n_flows] All referenced RPCs and relations exist.")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
