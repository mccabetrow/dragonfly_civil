from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, Sequence

from tools import task_planner


class _FakeRepo(task_planner.TaskPlannerRepository):
    def __init__(self) -> None:
        self.call_counts: Dict[str, int] = {}
        self.candidates: Sequence[task_planner.CandidateSnapshot] = []
        self.inserted: list[task_planner.PlannedTask] = []
        self.reassign_calls: list[tuple[str, str]] = []
        self.reassign_result: Dict[tuple[str, str], int] = {}
        self.stale_count: int = 0
        self.last_stale_days: int | None = None

    def fetch_open_call_counts(self) -> Dict[str, int]:
        return dict(self.call_counts)

    def fetch_candidates(self, limit: int) -> Sequence[task_planner.CandidateSnapshot]:
        return list(self.candidates)[:limit]

    def insert_tasks(self, tasks: Sequence[task_planner.PlannedTask]) -> int:
        self.inserted.extend(tasks)
        return len(tasks)

    def reassign_open_tasks(self, *, source: str, target: str) -> int:
        self.reassign_calls.append((source, target))
        return self.reassign_result.get((source, target), 0)

    def count_stale_open_call_tasks(self, stale_days: int) -> int:
        self.last_stale_days = stale_days
        return self.stale_count


def _candidate(
    *,
    plaintiff_id: str,
    tier: str | None = "Tier A",
    status: str | None = "new",
    last_contact_delta: int | None = None,
    open_kinds: Sequence[str] | None = None,
    call_assignee: str | None = None,
) -> task_planner.CandidateSnapshot:
    last_contacted_at = None
    if last_contact_delta is not None:
        last_contacted_at = datetime(2025, 1, 1, tzinfo=timezone.utc) - timedelta(
            days=last_contact_delta
        )
    return task_planner.CandidateSnapshot(
        plaintiff_id=plaintiff_id,
        collectability_tier=tier,
        priority_level="high",
        tier_rank=1,
        plaintiff_status=status,
        last_contacted_at=last_contacted_at,
        open_kinds=frozenset(open_kinds or []),
        total_open_tasks=len(open_kinds or []),
        call_assignee=call_assignee,
    )


def test_planner_creates_call_tasks_for_deficit() -> None:
    repo = _FakeRepo()
    repo.candidates = [
        _candidate(plaintiff_id="p1", tier="Tier A"),
        _candidate(plaintiff_id="p2", tier="Tier A"),
    ]
    config = task_planner.PlannerConfig(tier_targets={"tier_a": 2})
    planner = task_planner.TaskPlanner(
        repo=repo,
        config=config,
        dry_run=True,
        now_fn=lambda: datetime(2025, 1, 1, tzinfo=timezone.utc),
    )

    outcome = planner.run()

    assert len(outcome.planned_tasks) == 2
    assert all(task.kind == "call" for task in outcome.planned_tasks)
    assert outcome.inserted_tasks == 0  # dry-run


def test_planner_skips_existing_call_tasks() -> None:
    repo = _FakeRepo()
    repo.call_counts = {"tier_a": 1}
    repo.candidates = [
        _candidate(plaintiff_id="p1", tier="Tier A", open_kinds=["call"]),
    ]
    config = task_planner.PlannerConfig(tier_targets={"tier_a": 1})
    planner = task_planner.TaskPlanner(
        repo=repo,
        config=config,
        dry_run=True,
        now_fn=lambda: datetime(2025, 1, 1, tzinfo=timezone.utc),
    )

    outcome = planner.run()

    assert outcome.planned_tasks == []
    assert "still needs" not in " ".join(outcome.warnings)


def test_planner_schedules_follow_up_for_stale_contact() -> None:
    repo = _FakeRepo()
    repo.candidates = [
        _candidate(plaintiff_id="p1", tier="Tier B", last_contact_delta=30),
    ]
    config = task_planner.PlannerConfig(tier_targets={})
    planner = task_planner.TaskPlanner(
        repo=repo,
        config=config,
        dry_run=True,
        now_fn=lambda: datetime(2025, 1, 1, tzinfo=timezone.utc),
    )

    outcome = planner.run()

    assert len(outcome.planned_tasks) == 1
    assert outcome.planned_tasks[0].kind == "follow_up"


def test_assignment_overrides_apply_when_committing() -> None:
    repo = _FakeRepo()
    repo.stale_count = 0
    repo.reassign_result[("mom", "ops")] = 5
    config = task_planner.PlannerConfig(tier_targets={}, assignment_overrides={"mom": "ops"})
    planner = task_planner.TaskPlanner(
        repo=repo,
        config=config,
        dry_run=False,
        now_fn=lambda: datetime(2025, 1, 1, tzinfo=timezone.utc),
    )

    outcome = planner.run()

    assert outcome.assignment_results == [
        task_planner.AssignmentResult(source="mom", target="ops", updated=5)
    ]
    assert repo.reassign_calls == [("mom", "ops")]


def test_planner_records_backlog_warning() -> None:
    repo = _FakeRepo()
    repo.stale_count = 2000
    config = task_planner.PlannerConfig(tier_targets={})
    planner = task_planner.TaskPlanner(
        repo=repo,
        config=config,
        dry_run=True,
        now_fn=lambda: datetime(2025, 1, 1, tzinfo=timezone.utc),
    )

    outcome = planner.run()

    assert outcome.backlog_count == 2000
    assert any("2000" in warning for warning in outcome.warnings)
