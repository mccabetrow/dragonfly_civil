from __future__ import annotations

"""Nightly task planner for plaintiff_tasks queues."""

import json
import logging
import math
import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Mapping, Optional, Protocol, Sequence

import click
import psycopg
import yaml
from psycopg.types.json import Jsonb

from src.supabase_client import get_supabase_db_url, get_supabase_env

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def normalize_tier(value: str | None) -> str:
    if not value:
        return "unranked"
    slug = re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")
    return slug or "unranked"


def _coerce_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_bool(value, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return default


@dataclass(frozen=True)
class PlannerConfig:
    tier_targets: Dict[str, int] = field(default_factory=dict)
    enable_followups: Optional[bool] = None
    followup_threshold_days: int = 14
    follow_up_note_template: str = "Follow-up auto-scheduled after {days} days without new status"
    research_note_template: str = "Research task queued because status is {status}"
    call_note_template: str = "Auto-call scheduled to keep tier {tier} fresh"
    research_statuses: tuple[str, ...] = ("qualified", "sent_agreement", "signed")
    assignment_overrides: Dict[str, str] = field(default_factory=dict)
    default_assignee: str = "mom_full_name_or_user_id"
    max_candidates: int = 200
    backlog_warning_threshold: int = 1500
    stale_task_warning_days: int = 21
    created_by: str = "task_planner"

    def normalized_targets(self) -> Dict[str, int]:
        return {
            normalize_tier(key): int(value)
            for key, value in self.tier_targets.items()
            if _coerce_int(value, 0) > 0
        }


DEFAULT_CONFIG = PlannerConfig(
    tier_targets={"tier_a": 10, "tier_b": 7, "tier_c": 4},
)


def load_config(path: str | None = None) -> PlannerConfig:
    base = DEFAULT_CONFIG
    candidates = []
    if path:
        candidates.append(Path(path))
    else:
        candidates.append(Path("config/task_planner.yaml"))
    for candidate in candidates:
        if candidate and candidate.is_file():
            data = yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
            if isinstance(data, Mapping):
                return merge_config(base, data)
    return base


def merge_config(base: PlannerConfig, overrides: Mapping[str, object]) -> PlannerConfig:
    tier_targets = dict(base.tier_targets)
    raw_tiers = overrides.get("tier_targets")
    if isinstance(raw_tiers, Mapping):
        for key, value in raw_tiers.items():
            try:
                tier_targets[normalize_tier(str(key))] = int(value)
            except (TypeError, ValueError):
                logger.warning("[task_planner] Ignoring invalid tier target override for %s", key)

    assignment_overrides = dict(base.assignment_overrides)
    raw_assign = overrides.get("assignment_overrides")
    if isinstance(raw_assign, Mapping):
        for source, target in raw_assign.items():
            source_key = str(source or "").strip()
            target_key = str(target or "").strip()
            if source_key and target_key:
                assignment_overrides[source_key] = target_key

    research_statuses = base.research_statuses
    raw_statuses = overrides.get("research_statuses")
    if isinstance(raw_statuses, Sequence) and not isinstance(raw_statuses, (str, bytes)):
        research_statuses = tuple(
            str(status).strip().lower() for status in raw_statuses if str(status).strip()
        )

    return replace(
        base,
        tier_targets=tier_targets,
        assignment_overrides=assignment_overrides,
        enable_followups=(
            _coerce_bool(
                overrides.get("enable_followups"),
                base.enable_followups if base.enable_followups is not None else False,
            )
            if "enable_followups" in overrides
            else base.enable_followups
        ),
        followup_threshold_days=_coerce_int(
            overrides.get("followup_threshold_days", overrides.get("stale_contact_days")),
            base.followup_threshold_days,
        ),
        follow_up_note_template=str(
            overrides.get("follow_up_note_template", base.follow_up_note_template)
            or base.follow_up_note_template
        ),
        research_note_template=str(
            overrides.get("research_note_template", base.research_note_template)
            or base.research_note_template
        ),
        call_note_template=str(
            overrides.get("call_note_template", base.call_note_template) or base.call_note_template
        ),
        research_statuses=research_statuses,
        default_assignee=str(
            overrides.get("default_assignee", base.default_assignee) or base.default_assignee
        ),
        max_candidates=_coerce_int(overrides.get("max_candidates"), base.max_candidates),
        backlog_warning_threshold=_coerce_int(
            overrides.get("backlog_warning_threshold"),
            base.backlog_warning_threshold,
        ),
        stale_task_warning_days=_coerce_int(
            overrides.get("stale_task_warning_days"), base.stale_task_warning_days
        ),
        created_by=str(overrides.get("created_by", base.created_by) or base.created_by),
    )


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CandidateSnapshot:
    plaintiff_id: str
    collectability_tier: str | None
    priority_level: str | None
    tier_rank: float | None
    plaintiff_status: str | None
    last_contacted_at: datetime | None
    open_kinds: frozenset[str]
    total_open_tasks: int
    call_assignee: str | None


@dataclass
class PlannedTask:
    plaintiff_id: str
    kind: str
    note: str
    due_at: datetime
    assignee: str | None
    metadata: Mapping[str, object]
    created_by: str


@dataclass(frozen=True)
class AssignmentResult:
    source: str
    target: str
    updated: int


@dataclass
class PlannerOutcome:
    planned_tasks: list[PlannedTask]
    inserted_tasks: int
    tier_counts: Dict[str, int]
    warnings: list[str]
    assignment_results: list[AssignmentResult]
    backlog_count: int


# ---------------------------------------------------------------------------
# Repository interface + concrete DB implementation
# ---------------------------------------------------------------------------


class TaskPlannerRepository(Protocol):
    def fetch_open_call_counts(self) -> Dict[str, int]: ...

    def fetch_candidates(self, limit: int) -> Sequence[CandidateSnapshot]: ...

    def insert_tasks(self, tasks: Sequence[PlannedTask]) -> int: ...

    def reassign_open_tasks(self, *, source: str, target: str) -> int: ...

    def count_stale_open_call_tasks(self, stale_days: int) -> int: ...


class DatabaseTaskPlannerRepository(TaskPlannerRepository):
    def __init__(self, env: str) -> None:
        db_url = get_supabase_db_url(env)
        self.conn = psycopg.connect(db_url, autocommit=False, connect_timeout=10)

    def __enter__(self) -> DatabaseTaskPlannerRepository:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001 - context protocol
        try:
            if exc:
                self.conn.rollback()
        finally:
            self.conn.close()

    def fetch_open_call_counts(self) -> Dict[str, int]:
        # Sanity checks (PowerShell):
        #   cd C:\Users\mccab\dragonfly_civil
        #   $env:SUPABASE_MODE='dev'; .\.venv\Scripts\python.exe -m pytest tests/test_task_planner.py -q
        #   $env:SUPABASE_MODE='dev'; .\.venv\Scripts\python.exe -m tools.run_task_planner --env dev
        #   $env:SUPABASE_MODE='prod'; .\.venv\Scripts\python.exe -m tools.run_task_planner --env prod

        query = """
            with normalized_tiers as (
                select j.plaintiff_id,
                       case
                           when cs.collectability_tier is null
                                or btrim(cs.collectability_tier) = '' then 'Unranked'
                           when upper(cs.collectability_tier) in ('A', 'B', 'C') then
                               'Tier ' || upper(cs.collectability_tier)
                           else cs.collectability_tier
                       end as tier_label
                from public.judgments j
                left join public.v_collectability_snapshot cs
                    on cs.case_number = j.case_number
                where j.plaintiff_id is not null
            ),
            tier_lookup as (
                select plaintiff_id,
                       min(tier_label) as tier_label
                from normalized_tiers
                group by plaintiff_id
            )
            select coalesce(tl.tier_label, 'Unranked') as tier_label,
                   count(*)
            from public.plaintiff_tasks t
            left join tier_lookup tl on tl.plaintiff_id = t.plaintiff_id
            where t.kind = 'call'
              and t.status in ('open', 'in_progress')
            group by tier_label
        """
        counts: Dict[str, int] = {}
        with self.conn.cursor() as cur:
            cur.execute(query)
            for tier_label, total in cur.fetchall():
                counts[normalize_tier(tier_label)] = int(total)
        return counts

    def fetch_candidates(self, limit: int) -> Sequence[CandidateSnapshot]:
        query = """
            with raw_judgments as (
                select
                    j.id as judgment_id,
                    j.plaintiff_id,
                    coalesce(cs.collectability_tier, '') as raw_collectability_tier,
                    upper(nullif(regexp_replace(cs.collectability_tier, '[^a-zA-Z]', '', 'g'), '')) as tier_code,
                    coalesce(j.judgment_amount, 0) as judgment_amount,
                    lower(coalesce(nullif(j.priority_level, ''), 'normal')) as priority_level,
                    p.status as plaintiff_status
                from public.judgments j
                left join public.v_collectability_snapshot cs on cs.case_number = j.case_number
                left join public.plaintiffs p on p.id = j.plaintiff_id
                where j.plaintiff_id is not null
            ),
            scored_judgments as (
                select
                    judgment_id,
                    plaintiff_id,
                    judgment_amount,
                    priority_level,
                    plaintiff_status,
                    case
                        when tier_code = 'A' then 'Tier A'
                        when tier_code = 'B' then 'Tier B'
                        when tier_code = 'C' then 'Tier C'
                        when tier_code is null or tier_code = '' then 'Unranked'
                        else tier_code
                    end as tier_label,
                    case
                        when tier_code = 'A' then 1
                        when tier_code = 'B' then 2
                        when tier_code = 'C' then 3
                        else 4
                    end as tier_order,
                    case
                        when priority_level = 'urgent' then 1
                        when priority_level = 'high' then 2
                        when priority_level = 'normal' then 3
                        when priority_level = 'low' then 4
                        when priority_level = 'on_hold' then 5
                        else 6
                    end as priority_order
                from raw_judgments
            ),
            ranked_judgments as (
                select
                    *,
                    row_number() over (
                        order by tier_order, priority_order, judgment_amount desc, judgment_id
                    )::float as tier_rank
                from scored_judgments
            ),
            pipeline as (
                select distinct on (plaintiff_id)
                    plaintiff_id,
                    tier_label as collectability_tier,
                    priority_level,
                    tier_rank,
                    plaintiff_status as pipeline_status
                from ranked_judgments
                order by plaintiff_id, tier_order, priority_order, judgment_amount desc, judgment_id
            ),
            recent_contacts as (
                select plaintiff_id,
                       max(changed_at) filter (
                           where status in ('contacted','qualified','sent_agreement','signed')
                       ) as last_contacted_at
                from public.plaintiff_status_history
                group by plaintiff_id
            ),
            open_tasks as (
                select plaintiff_id,
                       count(*) as total_open,
                       jsonb_agg(distinct kind) as open_kinds,
                       max(assignee) filter (where kind = 'call') as call_assignee
                from public.plaintiff_tasks
                where status in ('open','in_progress')
                group by plaintiff_id
            )
            select pipeline.plaintiff_id,
                   pipeline.collectability_tier,
                   pipeline.priority_level,
                   pipeline.tier_rank,
                   coalesce(pipeline.pipeline_status, p.status) as plaintiff_status,
                   recent_contacts.last_contacted_at,
                   coalesce(open_tasks.open_kinds, '[]'::jsonb) as open_kinds,
                   coalesce(open_tasks.total_open, 0) as total_open_tasks,
                   open_tasks.call_assignee
            from pipeline
            join public.plaintiffs p on p.id = pipeline.plaintiff_id
            left join recent_contacts on recent_contacts.plaintiff_id = pipeline.plaintiff_id
            left join open_tasks on open_tasks.plaintiff_id = pipeline.plaintiff_id
            order by pipeline.collectability_tier nulls last,
                     pipeline.tier_rank nulls last,
                     pipeline.plaintiff_id
            limit %s
        """
        snapshots: list[CandidateSnapshot] = []
        with self.conn.cursor() as cur:
            cur.execute(query, (int(limit),))
            for row in cur.fetchall():
                raw_kinds = row[6]
                if isinstance(raw_kinds, list):
                    kinds = frozenset(str(item) for item in raw_kinds if isinstance(item, str))
                elif isinstance(raw_kinds, str):
                    try:
                        parsed = json.loads(raw_kinds)
                    except Exception:  # pragma: no cover - defensive parsing
                        parsed = []
                    kinds = frozenset(str(item) for item in parsed if isinstance(item, str))
                else:
                    kinds = frozenset()
                snapshots.append(
                    CandidateSnapshot(
                        plaintiff_id=row[0],
                        collectability_tier=row[1],
                        priority_level=row[2],
                        tier_rank=float(row[3]) if row[3] is not None else None,
                        plaintiff_status=row[4],
                        last_contacted_at=row[5],
                        open_kinds=kinds,
                        total_open_tasks=int(row[7]),
                        call_assignee=row[8],
                    )
                )
        return snapshots

    def insert_tasks(self, tasks: Sequence[PlannedTask]) -> int:
        if not tasks:
            return 0
        inserted = 0
        with self.conn.cursor() as cur:
            for task in tasks:
                cur.execute(
                    """
                    insert into public.plaintiff_tasks (
                        plaintiff_id, kind, status, due_at, note, assignee, metadata, created_by
                    )
                    values (%s, %s, 'open', %s, %s, %s, %s, %s)
                    on conflict (plaintiff_id, kind, status) do nothing
                    returning id
                    """,
                    (
                        task.plaintiff_id,
                        task.kind,
                        task.due_at,
                        task.note,
                        task.assignee,
                        Jsonb(task.metadata),
                        task.created_by,
                    ),
                )
                if cur.fetchone():
                    inserted += 1
            self.conn.commit()
        return inserted

    def reassign_open_tasks(self, *, source: str, target: str) -> int:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                update public.plaintiff_tasks
                set assignee = %s,
                    updated_at = timezone('utc', now())
                where assignee = %s
                  and status in ('open','in_progress')
                returning id
                """,
                (target, source),
            )
            updated = len(cur.fetchall())
            if updated:
                self.conn.commit()
            return updated

    def count_stale_open_call_tasks(self, stale_days: int) -> int:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                select count(*)
                from public.plaintiff_tasks
                where kind = 'call'
                  and status in ('open','in_progress')
                  and coalesce(due_at, created_at) < timezone('utc', now()) - (%s || ' days')::interval
                """,
                (int(stale_days),),
            )
            row = cur.fetchone()
            return int(row[0]) if row else 0


# ---------------------------------------------------------------------------
# Planner logic
# ---------------------------------------------------------------------------


class TaskPlanner:
    def __init__(
        self,
        *,
        repo: TaskPlannerRepository,
        config: PlannerConfig,
        dry_run: bool,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self.repo = repo
        self.config = config
        self.dry_run = dry_run
        self.now_fn = now_fn or _utcnow

    def run(self) -> PlannerOutcome:
        now = self.now_fn()
        tier_targets = self.config.normalized_targets()
        tier_counts = {tier: 0 for tier in tier_targets}
        tier_counts.update(self.repo.fetch_open_call_counts())

        candidates = list(self.repo.fetch_candidates(self.config.max_candidates))
        planned_keys: set[tuple[str, str]] = set()
        planned_tasks: list[PlannedTask] = []

        planned_tasks.extend(
            self._plan_call_deficits(candidates, tier_targets, tier_counts, planned_keys, now)
        )
        if self._enable_followups_effective:
            planned_tasks.extend(self._plan_followups(candidates, planned_keys, now))
        planned_tasks.extend(self._plan_research(candidates, planned_keys, now))

        warnings: list[str] = []
        for tier, target in tier_targets.items():
            deficit = max(0, target - tier_counts.get(tier, 0))
            if deficit > 0:
                warnings.append(
                    f"Tier '{tier}' still needs {deficit} open call tasks (target {target})."
                )

        backlog = self.repo.count_stale_open_call_tasks(self.config.stale_task_warning_days)
        if backlog > self.config.backlog_warning_threshold:
            warnings.append(
                f"{backlog} open call tasks are older than {self.config.stale_task_warning_days} days."
            )

        inserted = 0
        if not self.dry_run and planned_tasks:
            inserted = self.repo.insert_tasks(planned_tasks)

        assignment_results = self._apply_assignment_overrides(warnings)

        return PlannerOutcome(
            planned_tasks=planned_tasks,
            inserted_tasks=inserted,
            tier_counts=tier_counts,
            warnings=warnings,
            assignment_results=assignment_results,
            backlog_count=backlog,
        )

    # ------------------------------------------------------------------
    # Planning helpers
    # ------------------------------------------------------------------

    def _plan_call_deficits(
        self,
        candidates: Sequence[CandidateSnapshot],
        tier_targets: Dict[str, int],
        tier_counts: Dict[str, int],
        planned_keys: set[tuple[str, str]],
        now: datetime,
    ) -> list[PlannedTask]:
        tasks: list[PlannedTask] = []
        if not tier_targets:
            return tasks
        for candidate in candidates:
            tier_key = normalize_tier(candidate.collectability_tier)
            if tier_key not in tier_targets:
                continue
            if tier_counts.get(tier_key, 0) >= tier_targets[tier_key]:
                continue
            if self._has_task(candidate, "call", planned_keys):
                continue
            metadata = {
                "reason": "tier_deficit",
                "tier": tier_key,
                "priority_level": candidate.priority_level,
                "tier_rank": candidate.tier_rank,
            }
            task = self._make_task(
                candidate=candidate,
                kind="call",
                note=self.config.call_note_template.format(tier=tier_key),
                reason="tier_deficit",
                tier=tier_key,
                now=now,
                assignee=candidate.call_assignee,
                extra=metadata,
            )
            planned_keys.add((candidate.plaintiff_id, "call"))
            tier_counts[tier_key] = tier_counts.get(tier_key, 0) + 1
            tasks.append(task)
        return tasks

    def _plan_followups(
        self,
        candidates: Sequence[CandidateSnapshot],
        planned_keys: set[tuple[str, str]],
        now: datetime,
    ) -> list[PlannedTask]:
        tasks: list[PlannedTask] = []
        stale_days = self.config.followup_threshold_days
        for candidate in candidates:
            if self._has_task(candidate, "follow_up", planned_keys):
                continue
            days = self._days_since(candidate.last_contacted_at, now)
            if days < stale_days:
                continue
            note = self.config.follow_up_note_template.format(days=stale_days)
            days_meta: float | None
            if math.isfinite(days):
                days_meta = days
            else:
                days_meta = None
            task = self._make_task(
                candidate=candidate,
                kind="follow_up",
                note=note,
                reason="stale_contact",
                tier=normalize_tier(candidate.collectability_tier),
                now=now,
                assignee=candidate.call_assignee,
                extra={"days_since_contact": days_meta},
            )
            planned_keys.add((candidate.plaintiff_id, "follow_up"))
            tasks.append(task)
        return tasks

    @property
    def _enable_followups_effective(self) -> bool:
        if self.config.enable_followups is not None:
            return self.config.enable_followups
        return not bool(self.config.tier_targets)

    def _plan_research(
        self,
        candidates: Sequence[CandidateSnapshot],
        planned_keys: set[tuple[str, str]],
        now: datetime,
    ) -> list[PlannedTask]:
        tasks: list[PlannedTask] = []
        required_statuses = {status.lower() for status in self.config.research_statuses}
        if not required_statuses:
            return tasks
        for candidate in candidates:
            status = (candidate.plaintiff_status or "").strip().lower()
            if status not in required_statuses:
                continue
            if self._has_task(candidate, "research", planned_keys):
                continue
            note = self.config.research_note_template.format(status=status or "unknown")
            task = self._make_task(
                candidate=candidate,
                kind="research",
                note=note,
                reason="research_status",
                tier=normalize_tier(candidate.collectability_tier),
                now=now,
                assignee=None,
                extra={"plaintiff_status": status},
            )
            planned_keys.add((candidate.plaintiff_id, "research"))
            tasks.append(task)
        return tasks

    def _has_task(
        self,
        candidate: CandidateSnapshot,
        kind: str,
        planned_keys: set[tuple[str, str]],
    ) -> bool:
        key = (candidate.plaintiff_id, kind)
        if key in planned_keys:
            return True
        return kind in candidate.open_kinds

    def _make_task(
        self,
        *,
        candidate: CandidateSnapshot,
        kind: str,
        note: str,
        reason: str,
        tier: str,
        now: datetime,
        assignee: str | None,
        extra: Dict[str, object] | None,
    ) -> PlannedTask:
        planner_meta: Dict[str, object] = {
            "reason": reason,
            "tier": tier,
            "generated_at": now.isoformat(),
        }
        metadata: Dict[str, object] = {"planner": planner_meta}
        if extra:
            planner_meta.update(extra)
        assigned_to = assignee or self.config.default_assignee
        return PlannedTask(
            plaintiff_id=candidate.plaintiff_id,
            kind=kind,
            note=note,
            due_at=now,
            assignee=assigned_to,
            metadata=metadata,
            created_by=self.config.created_by,
        )

    def _days_since(self, timestamp: datetime | None, now: datetime) -> float:
        if timestamp is None:
            return float("inf")
        delta = now - timestamp
        return delta.total_seconds() / 86400

    def _apply_assignment_overrides(self, warnings: list[str]) -> list[AssignmentResult]:
        if not self.config.assignment_overrides:
            return []
        if self.dry_run:
            warnings.append("Assignment overrides configured but skipped during dry-run.")
            return []
        results: list[AssignmentResult] = []
        for source, target in self.config.assignment_overrides.items():
            if not source or not target or source == target:
                continue
            updated = self.repo.reassign_open_tasks(source=source, target=target)
            results.append(AssignmentResult(source=source, target=target, updated=updated))
        return results


# ---------------------------------------------------------------------------
# CLI + helpers
# ---------------------------------------------------------------------------


def _parse_tier_overrides(values: Sequence[str]) -> Dict[str, int]:
    overrides: Dict[str, int] = {}
    for item in values:
        if "=" not in item:
            raise click.BadParameter(
                "Tier targets must use the form tier=value (ex: --tier-target 'tier_a=8')."
            )
        name, raw_value = item.split("=", 1)
        name_key = normalize_tier(name)
        try:
            overrides[name_key] = int(raw_value)
        except ValueError as exc:  # pragma: no cover - click handles validation
            raise click.BadParameter(f"Invalid integer for tier target '{item}'.") from exc
    return overrides


def _apply_cli_overrides(
    config: PlannerConfig,
    *,
    tier_overrides: Dict[str, int] | None,
    stale_days: int | None,
    max_candidates: int | None,
) -> PlannerConfig:
    payload: Dict[str, object] = {}
    if tier_overrides:
        payload["tier_targets"] = tier_overrides
    if stale_days is not None:
        payload["followup_threshold_days"] = stale_days
    if max_candidates is not None:
        payload["max_candidates"] = max_candidates
    if not payload:
        return config
    return merge_config(config, payload)


def _print_summary(outcome: PlannerOutcome, *, dry_run: bool, env: str) -> None:
    mode = "DRY-RUN" if dry_run else "COMMIT"
    click.echo(f"[task_planner] mode={mode} env={env}")
    click.echo(
        f"[task_planner] planned={len(outcome.planned_tasks)} inserted={outcome.inserted_tasks} backlog={outcome.backlog_count}"
    )
    if outcome.assignment_results:
        for result in outcome.assignment_results:
            click.echo(
                f"[task_planner] reassigned {result.updated} tasks from '{result.source}' to '{result.target}'"
            )
    preview_count = min(10, len(outcome.planned_tasks))
    if preview_count:
        click.echo("[task_planner] sample tasks:")
        for task in outcome.planned_tasks[:preview_count]:
            click.echo(
                f"  - {task.kind} for plaintiff {task.plaintiff_id} note='{task.note}' assignee={task.assignee}"
            )
        if len(outcome.planned_tasks) > preview_count:
            click.echo(
                f"  ... {len(outcome.planned_tasks) - preview_count} additional tasks not shown"
            )
    if outcome.warnings:
        click.echo("[task_planner] WARNINGS:")
        for warning in outcome.warnings:
            click.echo(f"  - {warning}")


@click.group()
def cli() -> None:
    """Automation helpers for plaintiff task planning."""


@cli.command("run")
@click.option(
    "--env",
    "requested_env",
    type=click.Choice(["dev", "prod", "demo"]),
    default=None,
    help="Override Supabase environment (defaults to SUPABASE_MODE).",
)
@click.option(
    "--config",
    "config_path",
    default=None,
    help="Path to YAML config (defaults to config/task_planner.yaml if present).",
)
@click.option(
    "--tier-target",
    "tier_target_overrides",
    multiple=True,
    help="Override tier targets (format tier=value, e.g., --tier-target 'tier_a=6').",
)
@click.option(
    "--stale-days",
    type=int,
    default=None,
    help="Override stale contact days before follow-ups are queued.",
)
@click.option(
    "--max-candidates",
    type=int,
    default=None,
    help="Max plaintiff candidates to scan while ranking tiers (default 200).",
)
@click.option(
    "--commit/--dry-run",
    "commit",
    default=False,
    help="Apply inserts/updates (default dry-run).",
)
def run_command(
    requested_env: str | None,
    config_path: str | None,
    tier_target_overrides: Sequence[str],
    stale_days: int | None,
    max_candidates: int | None,
    commit: bool,
) -> None:
    env = requested_env or get_supabase_env()
    config = load_config(config_path)
    tier_overrides = _parse_tier_overrides(tier_target_overrides) if tier_target_overrides else None
    config = _apply_cli_overrides(
        config,
        tier_overrides=tier_overrides,
        stale_days=stale_days,
        max_candidates=max_candidates,
    )

    dry_run = not commit
    with DatabaseTaskPlannerRepository(env) as repo:
        planner = TaskPlanner(repo=repo, config=config, dry_run=dry_run)
        outcome = planner.run()

    _print_summary(outcome, dry_run=dry_run, env=env)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s %(message)s")
    cli(obj={})


# ---------------------------------------------------------------------------
# Doctor hook helper
# ---------------------------------------------------------------------------


def measure_task_backlog(env: str, *, stale_days: int) -> int:
    with DatabaseTaskPlannerRepository(env) as repo:
        return repo.count_stale_open_call_tasks(stale_days)


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    main()
