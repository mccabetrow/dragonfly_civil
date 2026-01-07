from __future__ import annotations

import argparse
from collections import Counter
from typing import Dict, Sequence

from src.supabase_client import get_supabase_env
from tools.task_planner import (
    DatabaseTaskPlannerRepository,
    PlannerConfig,
    PlannerOutcome,
    TaskPlanner,
    normalize_tier,
)

DEFAULT_TIER_TARGETS: dict[str, int] = {"tier_a": 10, "tier_b": 5}


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Schedule plaintiff tasks based on tier targets and follow-up rules",
    )
    parser.add_argument(
        "--env",
        choices=["dev", "prod"],
        default=None,
        help="Supabase environment to target (defaults to SUPABASE_MODE)",
    )
    parser.add_argument(
        "--tier-target",
        dest="tier_targets",
        action="append",
        default=[],
        metavar="tier=value",
        help=(
            "Desired active call tasks per tier, e.g. --tier-target tier_a=5 --tier-target tier_b=3"
        ),
    )
    parser.add_argument(
        "--enable-followups",
        dest="enable_followups",
        action="store_true",
        default=None,
        help="Enable follow-up tasks for stale contacts (uses followup_threshold_days).",
    )
    parser.add_argument(
        "--followup-threshold-days",
        type=int,
        default=None,
        help="Number of days since last contact before a follow-up is scheduled.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print diagnostic information about tier counts and candidate selection.",
    )
    return parser.parse_args(argv)


def _build_tier_targets(raw_targets: Sequence[str]) -> Dict[str, int]:
    tier_targets: Dict[str, int] = {}
    for raw in raw_targets:
        if "=" not in raw:
            raise argparse.ArgumentTypeError(
                f"Invalid --tier-target value '{raw}'. Expected format tier=value."
            )
        key, value = raw.split("=", 1)
        key = normalize_tier(key)
        if not key:
            raise argparse.ArgumentTypeError(f"Invalid tier name in --tier-target '{raw}'.")
        try:
            tier_targets[key] = int(value)
        except ValueError as exc:  # pragma: no cover - defensive parsing
            raise argparse.ArgumentTypeError(f"Invalid integer in --tier-target '{raw}'.") from exc
    return tier_targets


def main(argv: Sequence[str] | None = None) -> None:
    args = _parse_args(argv)
    env = args.env or get_supabase_env()

    tier_targets = DEFAULT_TIER_TARGETS
    if args.tier_targets:
        tier_targets = _build_tier_targets(args.tier_targets)

    config_kwargs: Dict[str, object] = {
        "tier_targets": tier_targets,
        "enable_followups": args.enable_followups,
    }
    if args.followup_threshold_days is not None:
        config_kwargs["followup_threshold_days"] = args.followup_threshold_days

    config = PlannerConfig(**config_kwargs)  # type: ignore[arg-type]

    with DatabaseTaskPlannerRepository(env) as repo:
        planner = TaskPlanner(repo=repo, config=config, dry_run=False)
        outcome = planner.run()
        if args.verbose:
            _print_debug_summary(repo, config, outcome)

    kind_counts = Counter(task.kind for task in outcome.planned_tasks)
    detail_parts = [f"{count} {kind}" for kind, count in sorted(kind_counts.items())]
    detail = ", ".join(detail_parts) if detail_parts else "no tasks"
    print(
        "Planned {total} tasks ({detail}); backlog now {backlog}.".format(
            total=len(outcome.planned_tasks),
            detail=detail,
            backlog=outcome.backlog_count,
        )
    )


def _print_debug_summary(
    repo: DatabaseTaskPlannerRepository,
    config: PlannerConfig,
    outcome: PlannerOutcome,
) -> None:
    try:
        open_counts = repo.fetch_open_call_counts()
        formatted_counts = (
            ", ".join(f"{tier}={total}" for tier, total in sorted(open_counts.items()))
            if open_counts
            else "none"
        )
        print(f"[debug] Open calls by tier: {formatted_counts}")
    except Exception as exc:  # pragma: no cover - diagnostic only
        print(f"[debug] Open call count fetch failed: {exc}")

    try:
        candidates = repo.fetch_candidates(config.max_candidates)
        print(
            "[debug] Candidates considered: {count} (limit {limit})".format(
                count=len(candidates),
                limit=config.max_candidates,
            )
        )
    except Exception as exc:  # pragma: no cover - diagnostic only
        print(f"[debug] Candidate fetch failed: {exc}")

    followups_status = (
        "enabled"
        if config.enable_followups
        else "auto" if config.enable_followups is None else "disabled"
    )
    print(f"[debug] Follow-ups configuration: {followups_status}")
    print(f"[debug] Planned tasks: {len(outcome.planned_tasks)}")


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    main()


# Sanity checklist:
# cd C:\Users\mccab\dragonfly_civil
# $env:SUPABASE_MODE='dev'
# .\.venv\Scripts\python.exe -m pytest tests/test_task_planner.py -q
# .\.venv\Scripts\python.exe -m tools.run_task_planner --env dev `
#   --tier-target tier_a=3 --tier-target tier_b=2 `
#   --enable-followups --followup-threshold-days 21
