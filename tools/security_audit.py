from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, Iterable, List, Sequence, Set

import click
import psycopg
from psycopg.rows import dict_row

from src.supabase_client import get_supabase_db_url, get_supabase_env


@dataclass
class PolicyInfo:
    name: str
    command: str
    roles: Sequence[str]
    permissive: bool
    using: str | None
    check: str | None


@dataclass
class RelationSecurity:
    name: str
    kind: str
    rls_enabled: bool
    rls_forced: bool
    policies: List[PolicyInfo] = field(default_factory=list)
    grants: Dict[str, Set[str]] = field(default_factory=dict)

    @property
    def kind_label(self) -> str:
        return {
            "r": "table",
            "v": "view",
            "m": "materialized view",
        }.get(self.kind, self.kind)


@dataclass(frozen=True)
class KeyTablePolicy:
    write_roles: FrozenSet[str]
    require_rls: bool = False
    force_rls: bool = False


RESTRICTED_TABLES: Set[str] = {
    "import_runs",
    "enforcement_cases",
    "enforcement_events",
    "enforcement_evidence",
}

PIPELINE_VIEWS: Set[str] = {
    "v_case_copilot_latest",
    "v_enforcement_timeline",
    "v_ops_daily_summary",
    "v_plaintiffs_overview",
    "v_judgment_pipeline",
    "v_enforcement_overview",
    "v_enforcement_recent",
    "v_plaintiff_call_queue",
    "v_plaintiff_open_tasks",
}

KEY_TABLE_POLICIES: Dict[str, KeyTablePolicy] = {
    "judgments": KeyTablePolicy(
        write_roles=frozenset({"service_role"}),
        require_rls=True,
        force_rls=True,
    ),
    "plaintiffs": KeyTablePolicy(
        write_roles=frozenset({"service_role"}),
        require_rls=True,
        force_rls=True,
    ),
    "enforcement_cases": KeyTablePolicy(
        write_roles=frozenset({"service_role"}),
        require_rls=True,
        force_rls=True,
    ),
    "enforcement_timeline": KeyTablePolicy(
        write_roles=frozenset({"service_role"}),
        require_rls=True,
        force_rls=True,
    ),
    "enforcement_evidence": KeyTablePolicy(
        write_roles=frozenset({"service_role"}),
        require_rls=True,
        force_rls=True,
    ),
    "plaintiff_tasks": KeyTablePolicy(
        write_roles=frozenset({"service_role"}),
        require_rls=True,
        force_rls=True,
    ),
    "plaintiff_call_attempts": KeyTablePolicy(
        write_roles=frozenset({"service_role"}),
        require_rls=True,
        force_rls=True,
    ),
}

READ_ONLY_PRIVS = {"SELECT"}
WRITE_PRIVS = {"INSERT", "UPDATE", "DELETE", "TRUNCATE"}
AUDITED_ROLES = ("anon", "authenticated", "public", "service_role")


def _resolve_env(requested_env: str | None) -> str:
    if requested_env:
        normalized = requested_env.lower()
        os.environ["SUPABASE_MODE"] = "prod" if normalized == "prod" else "dev"
        return os.environ["SUPABASE_MODE"]
    env = get_supabase_env()
    os.environ["SUPABASE_MODE"] = env
    return env


def _connect(env: str) -> psycopg.Connection:
    db_url = get_supabase_db_url(env)
    return psycopg.connect(
        db_url,
        autocommit=True,
        row_factory=dict_row,
        connect_timeout=10,
    )


def _load_relations(conn: psycopg.Connection) -> Dict[str, RelationSecurity]:
    query = """
        SELECT c.relname AS name,
               c.relkind AS kind,
               c.relrowsecurity AS rls_enabled,
               c.relforcerowsecurity AS rls_forced
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND c.relkind IN ('r', 'v', 'm')
        ORDER BY c.relname;
    """
    relations: Dict[str, RelationSecurity] = {}
    with conn.cursor() as cur:
        cur.execute(query)
        for row in cur.fetchall():
            relations[row["name"]] = RelationSecurity(
                name=row["name"],
                kind=row["kind"],
                rls_enabled=bool(row["rls_enabled"]),
                rls_forced=bool(row["rls_forced"]),
            )
    return relations


def _load_policies(
    conn: psycopg.Connection, relations: Dict[str, RelationSecurity]
) -> None:
    query = """
         SELECT schemaname,
             tablename,
             policyname AS polname,
             cmd,
             permissive,
             roles,
             qual AS using_expr,
             with_check AS check_expr
        FROM pg_policies
        WHERE schemaname = 'public';
    """
    with conn.cursor() as cur:
        cur.execute(query)
        for row in cur.fetchall():
            rel = relations.get(row["tablename"])
            if not rel:
                continue
            rel.policies.append(
                PolicyInfo(
                    name=row["polname"],  # type: ignore[index]
                    command=row["cmd"],
                    roles=tuple((row["roles"] or [])),
                    permissive=bool(row["permissive"]),
                    using=row["using_expr"],
                    check=row["check_expr"],
                )
            )


def _load_grants(
    conn: psycopg.Connection, relations: Dict[str, RelationSecurity]
) -> None:
    query = """
        SELECT table_name,
               grantee,
               privilege_type
        FROM information_schema.table_privileges
        WHERE table_schema = 'public'
          AND grantee IN ('anon', 'authenticated', 'service_role', 'public');
    """
    with conn.cursor() as cur:
        cur.execute(query)
        for row in cur.fetchall():
            rel = relations.get(row["table_name"])
            if not rel:
                continue
            grantee = row["grantee"].lower()
            privilege = row["privilege_type"].upper()
            rel.grants.setdefault(grantee, set()).add(privilege)


def capture_security_snapshot(env: str) -> List[RelationSecurity]:
    with _connect(env) as conn:
        relations = _load_relations(conn)
        if not relations:
            return []
        _load_policies(conn, relations)
        _load_grants(conn, relations)
        return list(relations.values())


def _assert_no_grants(
    violations: List[str], rel: RelationSecurity, roles: Iterable[str]
) -> None:
    for role in roles:
        privs = rel.grants.get(role, set())
        if privs:
            violations.append(
                f"{rel.name}: role '{role}' must not have privileges {sorted(privs)}"
            )


def _collect_write_roles(rel: RelationSecurity) -> Dict[str, Set[str]]:
    write_holders: Dict[str, Set[str]] = {}
    for role, privileges in rel.grants.items():
        writes = privileges & WRITE_PRIVS
        if writes:
            write_holders[role] = writes
    return write_holders


def _enforce_key_table_rules(
    rel: RelationSecurity, config: KeyTablePolicy, violations: List[str]
) -> None:
    require_rls = config.require_rls
    force_rls = config.force_rls
    allowed_roles = set(config.write_roles)

    if require_rls and not rel.rls_enabled:
        violations.append(f"{rel.name}: RLS must be enabled")
    if force_rls and not rel.rls_forced:
        violations.append(f"{rel.name}: RLS must be forced")

    write_holders = _collect_write_roles(rel)
    unexpected = set(write_holders.keys()) - allowed_roles
    if unexpected:
        violations.append(
            f"{rel.name}: unexpected write privileges for roles {sorted(unexpected)}"
        )

    missing = allowed_roles - set(write_holders.keys())
    if missing:
        violations.append(
            f"{rel.name}: missing write privileges for roles {sorted(missing)}"
        )


def evaluate_rules(relations: Sequence[RelationSecurity]) -> List[str]:
    violations: List[str] = []
    for rel in relations:
        config = KEY_TABLE_POLICIES.get(rel.name)
        if config:
            _enforce_key_table_rules(rel, config, violations)

        if rel.name in RESTRICTED_TABLES:
            _assert_no_grants(violations, rel, ("anon", "authenticated", "public"))

        if rel.kind == "v" and rel.name not in PIPELINE_VIEWS:
            _assert_no_grants(violations, rel, ("anon", "authenticated", "public"))

        if rel.name in PIPELINE_VIEWS:
            for role in ("anon", "authenticated"):
                privs = rel.grants.get(role, set())
                invalid = privs - READ_ONLY_PRIVS
                if invalid:
                    violations.append(
                        f"{rel.name}: role '{role}' must only have SELECT but has {sorted(invalid)}"
                    )
            if rel.grants.get("public"):
                violations.append(
                    f"{rel.name}: role 'public' must not have privileges {sorted(rel.grants['public'])}"
                )

    return violations


def _print_relation_details(rel: RelationSecurity) -> None:
    click.echo(
        f"[security_audit] relation={rel.name} kind={rel.kind_label} "
        f"rls={'on' if rel.rls_enabled else 'off'} forced={'yes' if rel.rls_forced else 'no'}"
    )
    if rel.policies:
        click.echo("    policies:")
        for policy in rel.policies:
            roles = ",".join(policy.roles) if policy.roles else "<all>"
            click.echo(
                f"      - {policy.name} cmd={policy.command} roles={roles} permissive={'yes' if policy.permissive else 'no'}"
            )
    else:
        click.echo("    policies: (none)")

    if rel.grants:
        click.echo("    grants:")
        for role in AUDITED_ROLES:
            privs = rel.grants.get(role)
            if privs:
                click.echo(f"      - {role}: {', '.join(sorted(privs))}")
        missing_roles = [role for role in AUDITED_ROLES if role not in rel.grants]
        if missing_roles:
            click.echo(f"      - (no grants for: {', '.join(missing_roles)})")
    else:
        click.echo("    grants: (none)")


def run_audit(env: str) -> List[str]:
    snapshot = capture_security_snapshot(env)
    if not snapshot:
        click.echo("[security_audit] No relations found in public schema.")
        return []

    click.echo(f"[security_audit] auditing {len(snapshot)} relations in env={env}...")
    for rel in sorted(snapshot, key=lambda r: r.name):
        _print_relation_details(rel)

    violations = evaluate_rules(snapshot)
    if violations:
        click.echo("[security_audit] Violations detected:")
        for message in violations:
            click.echo(f"  - {message}")
    else:
        click.echo("[security_audit] No security violations detected.")
    return violations


@click.command()
@click.option(
    "--env",
    "requested_env",
    type=click.Choice(["dev", "prod", "demo"]),
    default=None,
    help="Override Supabase environment (defaults to SUPABASE_MODE).",
)
def main(requested_env: str | None = None) -> None:
    env = _resolve_env(requested_env)
    violations = run_audit(env)
    if violations:
        raise SystemExit(1)
    raise SystemExit(0)


if __name__ == "__main__":
    main()
