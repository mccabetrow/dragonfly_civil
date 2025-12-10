from __future__ import annotations

import argparse
from datetime import datetime, timezone
from typing import Literal

from src.supabase_client import create_supabase_client, get_supabase_env

CallOutcome = Literal["completed", "cannot_contact", "do_not_pursue"]
VALID_OUTCOMES: tuple[CallOutcome, ...] = (
    "completed",
    "cannot_contact",
    "do_not_pursue",
)

CLI_OUTCOME_MAP: dict[CallOutcome, tuple[str, str]] = {
    "completed": ("reached", "hot"),
    "cannot_contact": ("no_answer", "none"),
    "do_not_pursue": ("do_not_call", "none"),
}


def complete_plaintiff_call_task(
    task_id: str,
    *,
    outcome: CallOutcome,
    notes: str | None = None,
    next_follow_up_at: str | None = None,
    env: str | None = None,
    plaintiff_id: str | None = None,
) -> None:
    """Call the Supabase RPC to record a plaintiff call task outcome."""

    supabase_env = env or get_supabase_env()
    client = create_supabase_client(supabase_env)

    resolved_plaintiff_id = plaintiff_id or _fetch_plaintiff_id(client, task_id)
    if not resolved_plaintiff_id:
        raise RuntimeError("Unable to resolve plaintiff_id for the provided task")

    mapped = CLI_OUTCOME_MAP.get(outcome, ("no_answer", "none"))
    clean_notes = notes.strip() if isinstance(notes, str) else None

    payload = {
        "_plaintiff_id": resolved_plaintiff_id,
        "_task_id": task_id,
        "_outcome": mapped[0],
        "_interest": mapped[1],
        "_notes": clean_notes or None,
        "_follow_up_at": next_follow_up_at,
    }

    response = client.rpc("log_call_outcome", payload).execute()
    error = getattr(response, "error", None)
    if error:
        raise RuntimeError(f"Supabase RPC error: {error}")


def _parse_follow_up(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:  # pragma: no cover - argument validation
        raise argparse.ArgumentTypeError(f"Invalid ISO timestamp: {value}") from exc

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m tools.plaintiff_tasks",
        description="Log plaintiff call outcomes via the Supabase RPC.",
    )
    parser.add_argument("task_id", help="Task UUID from v_plaintiff_open_tasks")
    parser.add_argument(
        "--outcome",
        choices=VALID_OUTCOMES,
        default="completed",
        help="Call outcome to record (default: completed)",
    )
    parser.add_argument(
        "--notes",
        default=None,
        help="Optional notes captured in plaintiff_status_history",
    )
    parser.add_argument(
        "--follow-up",
        dest="follow_up",
        type=_parse_follow_up,
        default=None,
        help="Optional ISO timestamp for the next follow-up task (ex: 2025-11-18T15:30:00-05:00)",
    )
    parser.add_argument(
        "--env",
        default=None,
        help="Override Supabase env (dev/prod). Defaults to SUPABASE_MODE.",
    )
    parser.add_argument(
        "--plaintiff-id",
        dest="plaintiff_id",
        default=None,
        help="Optional plaintiff UUID (saves a lookup if provided).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    complete_plaintiff_call_task(
        args.task_id,
        outcome=args.outcome,
        notes=args.notes,
        next_follow_up_at=args.follow_up,
        env=args.env,
        plaintiff_id=args.plaintiff_id,
    )

    print(
        "[plaintiff_tasks] Recorded outcome",
        {
            "task_id": args.task_id,
            "outcome": args.outcome,
            "next_follow_up_at": args.follow_up,
            "plaintiff_id": args.plaintiff_id,
            "env": args.env or get_supabase_env(),
        },
    )
    return 0


def _fetch_plaintiff_id(client, task_id: str) -> str | None:
    response = (
        client.table("plaintiff_tasks").select("plaintiff_id").eq("id", task_id).limit(1).execute()
    )
    data = getattr(response, "data", None) or []
    if isinstance(data, list) and data:
        candidate = data[0]
        if isinstance(candidate, dict):
            value = candidate.get("plaintiff_id")
            if isinstance(value, str) and value:
                return value
    return None


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    raise SystemExit(main())
