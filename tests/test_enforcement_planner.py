from __future__ import annotations

from datetime import datetime, timedelta, timezone

from planner.enforcement_planner import EnforcementPlanner, TASK_DEFINITIONS


def _fixed_now() -> datetime:
    return datetime(2025, 1, 15, 14, 0, tzinfo=timezone.utc)


def test_planner_generates_all_definitions_when_no_existing_tasks() -> None:
    planner = EnforcementPlanner(now_fn=_fixed_now)
    tasks = planner.plan(existing_task_codes=None)

    assert len(tasks) == len(TASK_DEFINITIONS)
    assert tasks[0].task_code == TASK_DEFINITIONS[0].task_code
    assert tasks[0].due_at == _fixed_now()
    assert tasks[-1].due_at == _fixed_now() + timedelta(days=30)
    assert tasks[-1].metadata["rule"] == "refresh_30_days"


def test_planner_skips_existing_codes_idempotently() -> None:
    planner = EnforcementPlanner(now_fn=_fixed_now)
    existing = {"enforcement_mailer", "enforcement_wage_garnishment_prep"}

    tasks = planner.plan(existing_task_codes=existing)

    resulting_codes = {task.task_code for task in tasks}
    assert "enforcement_mailer" not in resulting_codes
    assert "enforcement_wage_garnishment_prep" not in resulting_codes
    assert len(tasks) == len(TASK_DEFINITIONS) - len(existing)
