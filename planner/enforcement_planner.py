from __future__ import annotations

"""Deterministic enforcement task planner + Supabase RPC integration."""

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterable, Sequence

from src.supabase_client import SupabaseEnv, create_supabase_client, get_supabase_env

UTC = timezone.utc


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class TaskDefinition:
    task_code: str
    kind: str
    severity: str
    offset_days: int
    note: str
    category: str
    frequency_days: int | None
    rule: str

    def build(self, planned_at: datetime) -> "PlannedTask":
        due_at = planned_at + timedelta(days=self.offset_days)
        metadata: dict[str, object] = {
            "task_code": self.task_code,
            "category": self.category,
            "frequency_days": self.frequency_days,
            "rule": self.rule,
            "planned_at": planned_at.isoformat(),
        }
        return PlannedTask(
            task_code=self.task_code,
            kind=self.kind,
            severity=self.severity,
            due_at=due_at,
            note=self.note,
            metadata=metadata,
        )


@dataclass(frozen=True)
class PlannedTask:
    task_code: str
    kind: str
    severity: str
    due_at: datetime
    note: str
    metadata: dict[str, object]


TASK_DEFINITIONS: tuple[TaskDefinition, ...] = (
    TaskDefinition(
        task_code="enforcement_phone_attempt",
        kind="enforcement_phone_attempt",
        severity="medium",
        offset_days=0,
        note="Place immediate enforcement phone call to confirm borrower contact info.",
        category="phone",
        frequency_days=7,
        rule="follow_up_7_days",
    ),
    TaskDefinition(
        task_code="enforcement_phone_follow_up",
        kind="enforcement_phone_follow_up",
        severity="medium",
        offset_days=7,
        note="Follow up on phone outreach (7-day rule).",
        category="phone",
        frequency_days=7,
        rule="follow_up_7_days",
    ),
    TaskDefinition(
        task_code="enforcement_mailer",
        kind="enforcement_mailer",
        severity="low",
        offset_days=7,
        note="Send enforcement mailer packet to borrower and employer.",
        category="mail",
        frequency_days=None,
        rule="follow_up_7_days",
    ),
    TaskDefinition(
        task_code="enforcement_demand_letter",
        kind="enforcement_demand_letter",
        severity="high",
        offset_days=14,
        note="Prepare and send demand letter (14-day escalation).",
        category="legal",
        frequency_days=None,
        rule="escalation_14_days",
    ),
    TaskDefinition(
        task_code="enforcement_wage_garnishment_prep",
        kind="enforcement_wage_garnishment_prep",
        severity="high",
        offset_days=14,
        note="Gather payroll intel for wage garnishment filing.",
        category="legal",
        frequency_days=None,
        rule="escalation_14_days",
    ),
    TaskDefinition(
        task_code="enforcement_bank_levy_prep",
        kind="enforcement_bank_levy_prep",
        severity="high",
        offset_days=14,
        note="Review assets and prepare bank levy paperwork.",
        category="legal",
        frequency_days=None,
        rule="escalation_14_days",
    ),
    TaskDefinition(
        task_code="enforcement_skiptrace_refresh",
        kind="enforcement_skiptrace_refresh",
        severity="medium",
        offset_days=30,
        note="Refresh skiptrace data (30-day cycle).",
        category="research",
        frequency_days=30,
        rule="refresh_30_days",
    ),
)


class EnforcementPlanner:
    """Stateless helper that converts existing queue state into planned tasks."""

    def __init__(self, *, now_fn: Callable[[], datetime] | None = None) -> None:
        self._now_fn = now_fn or _utcnow

    def plan(self, existing_task_codes: Iterable[str] | None = None) -> list[PlannedTask]:
        existing = {code for code in (existing_task_codes or []) if code}
        planned_at = self._now_fn()
        planned: list[PlannedTask] = []
        for definition in TASK_DEFINITIONS:
            if definition.task_code in existing:
                continue
            planned.append(definition.build(planned_at))
        return planned


class PlannerService:
    """Wraps Supabase interactions for enforcement planner runs."""

    def __init__(self, env: SupabaseEnv | None = None) -> None:
        supabase_env = env or get_supabase_env()
        self.env = supabase_env
        self.client = create_supabase_client(supabase_env)
        self.planner = EnforcementPlanner()

    def fetch_existing_codes(self, case_id: str) -> set[str]:
        response = (
            self.client.table("plaintiff_tasks")
            .select("task_code,status")
            .eq("case_id", case_id)
            .in_("status", ["open", "in_progress"])
            .execute()
        )
        data = getattr(response, "data", None) or []
        codes: set[str] = set()
        if isinstance(data, Sequence):
            for entry in data:
                if isinstance(entry, dict):
                    code = entry.get("task_code")
                    if isinstance(code, str) and code:
                        codes.add(code)
        return codes

    def run_for_case(
        self, case_id: str, *, commit: bool
    ) -> tuple[set[str], list[PlannedTask], list[dict]]:
        existing = self.fetch_existing_codes(case_id)
        plan = self.planner.plan(existing_task_codes=existing)
        if not commit or not plan:
            return existing, plan, []
        response = self.client.rpc("generate_enforcement_tasks", {"case_id": case_id}).execute()
        error = getattr(response, "error", None)
        if error:
            raise RuntimeError(f"Supabase RPC error: {error}")
        inserted = getattr(response, "data", None) or []
        if not isinstance(inserted, list):
            inserted = []
        return existing, plan, inserted


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m planner.enforcement_planner",
        description="Generate enforcement tasks and optionally persist via Supabase RPC.",
    )
    parser.add_argument(
        "case_id",
        nargs="+",
        help="One or more enforcement case UUIDs",
    )
    parser.add_argument(
        "--env",
        dest="env",
        default=None,
        help="Override Supabase env (defaults to SUPABASE_MODE).",
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Persist tasks by calling generate_enforcement_tasks (default: dry-run)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    env = args.env or get_supabase_env()
    service = PlannerService(env)
    overall_mode = "COMMIT" if args.commit else "DRY-RUN"
    print(f"[enforcement_planner] env={env} mode={overall_mode} cases={len(args.case_id)}")

    total_planned = 0
    total_inserted = 0

    for case_id in args.case_id:
        try:
            existing, planned, inserted = service.run_for_case(case_id, commit=args.commit)
        except Exception as exc:  # pragma: no cover - runtime safety for CLI
            print(f"  - case={case_id} ERROR: {exc}")
            continue
        total_planned += len(planned)
        total_inserted += len(inserted)
        if planned:
            print(
                f"  - case={case_id} planned={len(planned)} inserted={len(inserted)} existing_skip={len(existing)}"
            )
        else:
            print(f"  - case={case_id} planned=0 (all tasks already present)")

    print(
        f"[enforcement_planner] summary planned={total_planned} inserted={total_inserted} mode={overall_mode}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    raise SystemExit(main())
