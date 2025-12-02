"""Seed deterministic plaintiffs + call tasks for demo walkthroughs (dev only).

This script writes directly to the Supabase Postgres database so we gate it to the
"dev" credential set (``SUPABASE_MODE``) and offer a ``--reset`` toggle to clean up
prior demo rows before reseeding. The dataset keeps call-queue friendly statuses
(``new``, ``contacted``, ``qualified``) plus open ``plaintiff_tasks`` records so Mom's
call queue and the Task Planner have something to operate on during demos.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Dict, Sequence

import click
import psycopg
from psycopg.types.json import Jsonb

from src.supabase_client import (
    describe_db_url,
    get_supabase_db_url,
    get_supabase_env,
)

SEED_AUTHOR = "demo_plaintiff_seed"
DEMO_SOURCE_SYSTEM = "demo_seed"
ALLOWED_ENV = "dev"


@dataclass(frozen=True)
class ContactSpec:
    name: str
    role: str
    email: str | None = None
    phone: str | None = None


@dataclass(frozen=True)
class StatusSpec:
    status: str
    days_ago: int
    note: str


@dataclass(frozen=True)
class JudgmentSpec:
    case_number: str
    defendant_name: str
    amount: Decimal
    entry_days_ago: int
    priority_level: str
    enforcement_stage: str
    notes: str


@dataclass(frozen=True)
class TaskSpec:
    note: str
    due_in_days: int
    assignee: str
    status: str = "open"
    kind: str = "call"
    metadata: Dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class PlaintiffSpec:
    key: str
    name: str
    firm_name: str
    status: str
    email: str
    phone: str
    contacts: Sequence[ContactSpec]
    statuses: Sequence[StatusSpec]
    judgments: Sequence[JudgmentSpec]
    tasks: Sequence[TaskSpec]


@dataclass
class SeedSummary:
    plaintiffs: int = 0
    contacts: int = 0
    statuses: int = 0
    judgments: int = 0
    tasks: int = 0

    def as_message(self) -> str:
        return (
            f"plaintiffs={self.plaintiffs} contacts={self.contacts} "
            f"statuses={self.statuses} judgments={self.judgments} tasks={self.tasks}"
        )


def _ensure_dev_only(env: str) -> None:
    if env != ALLOWED_ENV:
        raise click.ClickException(
            "seed_demo_plaintiffs may only run with dev credentials (SUPABASE_MODE=dev)."
        )


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _demo_specs(now: datetime) -> list[PlaintiffSpec]:
    return [
        PlaintiffSpec(
            key="summit",
            name="Summit Ridge Capital",
            firm_name="Summit Ridge Capital",
            status="new",
            email="hello@summitridge.demo",
            phone="+12125550101",
            contacts=[
                ContactSpec(
                    name="Maya Ellis",
                    role="Managing Partner",
                    email="maya.ellis@summitridge.demo",
                    phone="+12125550102",
                ),
            ],
            statuses=[
                StatusSpec(
                    status="new",
                    days_ago=2,
                    note="Inbound referral from Empire Finance. Sent overview deck.",
                ),
            ],
            judgments=[
                JudgmentSpec(
                    case_number="DEMO-PF-101",
                    defendant_name="Kingston Holdings LLC",
                    amount=Decimal("38250.00"),
                    entry_days_ago=45,
                    priority_level="high",
                    enforcement_stage="pre_enforcement",
                    notes="Ready for intake quiz once retainer clears.",
                ),
            ],
            tasks=[
                TaskSpec(
                    note="Welcome call to confirm document list.",
                    due_in_days=0,
                    assignee="mom_full_name_or_user_id",
                    metadata={"playbook": "demo_new"},
                ),
            ],
        ),
        PlaintiffSpec(
            key="atlas",
            name="Atlas Judgment Partners",
            firm_name="Atlas Judgment Partners",
            status="contacted",
            email="intake@atlas-demo.com",
            phone="+13475550001",
            contacts=[
                ContactSpec(
                    name="Jordan Price",
                    role="Director of Operations",
                    email="jordan.price@atlas-demo.com",
                    phone="+13475550021",
                )
            ],
            statuses=[
                StatusSpec(
                    status="new", days_ago=21, note="Webinar attendee (Outreach 101)."
                ),
                StatusSpec(
                    status="contacted",
                    days_ago=4,
                    note="Chatted through onboarding steps; waiting on scrub list.",
                ),
            ],
            judgments=[
                JudgmentSpec(
                    case_number="DEMO-PF-201",
                    defendant_name="Riverstone Holdings LLC",
                    amount=Decimal("45250.00"),
                    entry_days_ago=120,
                    priority_level="urgent",
                    enforcement_stage="paperwork_filed",
                    notes="City marshal packet filed; confirm payment wiring.",
                ),
                JudgmentSpec(
                    case_number="DEMO-PF-202",
                    defendant_name="Northpoint Credit LLC",
                    amount=Decimal("18750.00"),
                    entry_days_ago=240,
                    priority_level="high",
                    enforcement_stage="waiting_payment",
                    notes="Awaiting follow-up on payment plan counter.",
                ),
            ],
            tasks=[
                TaskSpec(
                    note="Call Jordan w/ fee worksheet and retainer checklist.",
                    due_in_days=1,
                    assignee="mom_full_name_or_user_id",
                    metadata={"playbook": "demo_contacted"},
                ),
                TaskSpec(
                    note="Confirm scrub list ETA from ops analyst.",
                    due_in_days=5,
                    assignee="mom_full_name_or_user_id",
                    metadata={"playbook": "demo_secondary"},
                ),
            ],
        ),
        PlaintiffSpec(
            key="beacon",
            name="Beacon Litigation Group",
            firm_name="Beacon Litigation Group",
            status="qualified",
            email="team@beacon-demo.com",
            phone="+12125550999",
            contacts=[
                ContactSpec(
                    name="Lena Brooks",
                    role="Managing Attorney",
                    email="lena.brooks@beacon-demo.com",
                    phone="+12125550911",
                ),
                ContactSpec(
                    name="Andre Keller",
                    role="Paralegal",
                    email="andre.keller@beacon-demo.com",
                    phone="+12125550912",
                ),
            ],
            statuses=[
                StatusSpec(
                    status="new", days_ago=40, note="Met at NACM chapter meeting."
                ),
                StatusSpec(
                    status="contacted", days_ago=28, note="Shared pricing deck."
                ),
                StatusSpec(
                    status="qualified",
                    days_ago=9,
                    note="Waiting on signed intake packet for first 5 judgments.",
                ),
            ],
            judgments=[
                JudgmentSpec(
                    case_number="DEMO-PF-301",
                    defendant_name="Ivory Coast Builders",
                    amount=Decimal("9850.00"),
                    entry_days_ago=310,
                    priority_level="normal",
                    enforcement_stage="levy_issued",
                    notes="Marshal levy scheduled; confirm bank response.",
                ),
                JudgmentSpec(
                    case_number="DEMO-PF-302",
                    defendant_name="Greyson Medical PC",
                    amount=Decimal("15800.00"),
                    entry_days_ago=620,
                    priority_level="low",
                    enforcement_stage="pre_enforcement",
                    notes="Needs updated locate per enrichment run.",
                ),
            ],
            tasks=[
                TaskSpec(
                    note="Call Lena w/ follow-up script for levy notice.",
                    due_in_days=3,
                    assignee="mom_full_name_or_user_id",
                    metadata={"playbook": "demo_qualified"},
                ),
                TaskSpec(
                    note="Schedule onboarding huddle once packet signed.",
                    due_in_days=10,
                    assignee="mom_full_name_or_user_id",
                    metadata={"playbook": "demo_qualified"},
                ),
            ],
        ),
    ]


def _reset_demo_rows(
    conn: psycopg.Connection, specs: Sequence[PlaintiffSpec]
) -> Dict[str, int]:
    removed = {
        "plaintiffs": 0,
        "contacts": 0,
        "statuses": 0,
        "tasks": 0,
        "judgments": 0,
    }
    names = [spec.name for spec in specs]
    case_numbers = [
        judgment.case_number for spec in specs for judgment in spec.judgments
    ]

    with conn.cursor() as cur:
        if case_numbers:
            cur.execute(
                "delete from public.judgments where case_number = any(%s)",
                (case_numbers,),
            )
            removed["judgments"] += cur.rowcount or 0

        cur.execute(
            "select id from public.plaintiffs where source_system = %s",
            (DEMO_SOURCE_SYSTEM,),
        )
        plaintiff_ids = {row[0] for row in cur.fetchall()}

        if names:
            cur.execute(
                "select id from public.plaintiffs where name = any(%s)",
                (names,),
            )
            plaintiff_ids.update(row[0] for row in cur.fetchall())

        if not plaintiff_ids:
            return removed

        id_list = list(plaintiff_ids)

        cur.execute(
            "delete from public.plaintiff_tasks where plaintiff_id = any(%s)",
            (id_list,),
        )
        removed["tasks"] = cur.rowcount or 0

        cur.execute(
            "delete from public.plaintiff_status_history where plaintiff_id = any(%s)",
            (id_list,),
        )
        removed["statuses"] = cur.rowcount or 0

        cur.execute(
            "delete from public.plaintiff_contacts where plaintiff_id = any(%s)",
            (id_list,),
        )
        removed["contacts"] = cur.rowcount or 0

        cur.execute(
            "delete from public.judgments where plaintiff_id = any(%s)",
            (id_list,),
        )
        removed["judgments"] += cur.rowcount or 0

        cur.execute(
            "delete from public.plaintiffs where id = any(%s)",
            (id_list,),
        )
        removed["plaintiffs"] = cur.rowcount or 0

    return removed


def _upsert_plaintiff(cur: psycopg.Cursor, spec: PlaintiffSpec) -> tuple[str, bool]:
    cur.execute(
        "select id from public.plaintiffs where lower(name) = lower(%s) limit 1",
        (spec.name,),
    )
    row = cur.fetchone()
    if row:
        plaintiff_id = row[0]
        cur.execute(
            """
            update public.plaintiffs
            set firm_name = %s,
                email = %s,
                phone = %s,
                status = %s,
                source_system = %s,
                updated_at = timezone('utc', now())
            where id = %s
            """,
            (
                spec.firm_name,
                spec.email,
                spec.phone,
                spec.status,
                DEMO_SOURCE_SYSTEM,
                plaintiff_id,
            ),
        )
        return plaintiff_id, False

    cur.execute(
        """
        insert into public.plaintiffs (name, firm_name, email, phone, status, source_system)
        values (%s, %s, %s, %s, %s, %s)
        returning id
        """,
        (
            spec.name,
            spec.firm_name,
            spec.email,
            spec.phone,
            spec.status,
            DEMO_SOURCE_SYSTEM,
        ),
    )
    row = cur.fetchone()
    if row is None:  # pragma: no cover - defensive guard
        raise click.ClickException("Unable to insert demo plaintiff record.")
    new_id = row[0]
    return new_id, True


def _replace_contacts(
    cur: psycopg.Cursor, plaintiff_id: str, contacts: Sequence[ContactSpec]
) -> int:
    cur.execute(
        "delete from public.plaintiff_contacts where plaintiff_id = %s",
        (plaintiff_id,),
    )
    inserted = 0
    for contact in contacts:
        cur.execute(
            """
            insert into public.plaintiff_contacts (plaintiff_id, name, email, phone, role)
            values (%s, %s, %s, %s, %s)
            """,
            (plaintiff_id, contact.name, contact.email, contact.phone, contact.role),
        )
        inserted += 1
    return inserted


def _replace_status_history(
    cur: psycopg.Cursor,
    plaintiff_id: str,
    statuses: Sequence[StatusSpec],
    now: datetime,
) -> int:
    cur.execute(
        "delete from public.plaintiff_status_history where plaintiff_id = %s",
        (plaintiff_id,),
    )
    inserted = 0
    for status in statuses:
        changed_at = now - timedelta(days=status.days_ago)
        cur.execute(
            """
            insert into public.plaintiff_status_history (plaintiff_id, status, note, changed_at, changed_by)
            values (%s, %s, %s, %s, %s)
            """,
            (
                plaintiff_id,
                status.status,
                status.note,
                changed_at,
                SEED_AUTHOR,
            ),
        )
        inserted += 1
    return inserted


def _replace_tasks(
    cur: psycopg.Cursor,
    plaintiff_id: str,
    tasks: Sequence[TaskSpec],
    now: datetime,
) -> int:
    cur.execute(
        "delete from public.plaintiff_tasks where plaintiff_id = %s and created_by = %s",
        (plaintiff_id, SEED_AUTHOR),
    )
    inserted = 0
    for task in tasks:
        cur.execute(
            """
            delete from public.plaintiff_tasks
            where plaintiff_id = %s
              and kind = %s
              and status = %s
            """,
            (plaintiff_id, task.kind, task.status),
        )
        due_at = now + timedelta(days=task.due_in_days)
        cur.execute(
            """
            insert into public.plaintiff_tasks (
                plaintiff_id,
                kind,
                status,
                due_at,
                note,
                assignee,
                created_by,
                metadata
            )
            values (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                plaintiff_id,
                task.kind,
                task.status,
                due_at,
                task.note,
                task.assignee,
                SEED_AUTHOR,
                Jsonb(task.metadata or {}),
            ),
        )
        inserted += 1
    return inserted


def _upsert_judgments(
    cur: psycopg.Cursor,
    plaintiff_id: str,
    plaintiff_name: str,
    judgments: Sequence[JudgmentSpec],
    now: datetime,
) -> int:
    inserted = 0
    for judgment in judgments:
        entry_date = (now - timedelta(days=judgment.entry_days_ago)).date()
        cur.execute(
            """
            insert into public.judgments (
                case_number,
                plaintiff_name,
                defendant_name,
                judgment_amount,
                entry_date,
                status,
                notes,
                priority_level,
                priority_level_updated_at,
                plaintiff_id,
                enforcement_stage,
                enforcement_stage_updated_at
            )
            values (%s, %s, %s, %s, %s, %s, %s, %s, timezone('utc', now()), %s, %s, timezone('utc', now()))
            on conflict (case_number) do update
            set plaintiff_name = excluded.plaintiff_name,
                defendant_name = excluded.defendant_name,
                judgment_amount = excluded.judgment_amount,
                entry_date = excluded.entry_date,
                status = excluded.status,
                notes = excluded.notes,
                priority_level = excluded.priority_level,
                priority_level_updated_at = timezone('utc', now()),
                plaintiff_id = excluded.plaintiff_id,
                enforcement_stage = excluded.enforcement_stage,
                enforcement_stage_updated_at = timezone('utc', now()),
                updated_at = timezone('utc', now())
            """,
            (
                judgment.case_number,
                plaintiff_name,
                judgment.defendant_name,
                judgment.amount,
                entry_date,
                "Open",
                judgment.notes,
                judgment.priority_level,
                plaintiff_id,
                judgment.enforcement_stage,
            ),
        )
        inserted += 1
    return inserted


def _seed_dataset(
    conn: psycopg.Connection, specs: Sequence[PlaintiffSpec], now: datetime
) -> SeedSummary:
    summary = SeedSummary()
    with conn.cursor() as cur:
        for spec in specs:
            plaintiff_id, _ = _upsert_plaintiff(cur, spec)
            summary.plaintiffs += 1
            summary.contacts += _replace_contacts(cur, plaintiff_id, spec.contacts)
            summary.statuses += _replace_status_history(
                cur, plaintiff_id, spec.statuses, now
            )
            summary.tasks += _replace_tasks(cur, plaintiff_id, spec.tasks, now)
            summary.judgments += _upsert_judgments(
                cur, plaintiff_id, spec.name, spec.judgments, now
            )
    return summary


@click.command()
@click.option(
    "--reset/--no-reset",
    default=False,
    help="Delete existing demo plaintiffs before seeding.",
    show_default=True,
)
@click.option(
    "--reset-only",
    is_flag=True,
    help="Only run the cleanup step (implies --reset) and skip inserts.",
)
def main(reset: bool, reset_only: bool) -> None:
    if reset_only:
        reset = True

    env = get_supabase_env()
    _ensure_dev_only(env)

    try:
        db_url = get_supabase_db_url(env)
    except RuntimeError as exc:  # pragma: no cover - configuration guard
        raise click.ClickException(f"Unable to resolve Supabase db url: {exc}") from exc

    host, dbname, user = describe_db_url(db_url)
    click.echo(f"[seed_demo_plaintiffs] env={env} host={host} db={dbname} user={user}")

    specs = _demo_specs(_now())

    try:
        with psycopg.connect(db_url, autocommit=False) as conn:
            if reset:
                removed = _reset_demo_rows(conn, specs)
                click.echo(
                    "[seed_demo_plaintiffs] reset "
                    f"plaintiffs={removed['plaintiffs']} contacts={removed['contacts']} "
                    f"statuses={removed['statuses']} tasks={removed['tasks']} "
                    f"judgments={removed['judgments']}"
                )
                if reset_only:
                    click.echo(
                        "[seed_demo_plaintiffs] reset-only complete; no inserts run."
                    )
                    return

            summary = _seed_dataset(conn, specs, _now())
    except psycopg.Error as exc:  # pragma: no cover - connection safety
        raise click.ClickException(f"Database error: {exc}") from exc

    click.echo(f"[seed_demo_plaintiffs] seeded {summary.as_message()}")


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    main()
