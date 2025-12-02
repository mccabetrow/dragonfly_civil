from __future__ import annotations

import json
from typing import Any, Mapping
from uuid import UUID

import typer

from src.ai.case_copilot import (
    DEFAULT_CASE_COPILOT_MODEL,
    AIClient,
    CaseContextRepository,
    CaseCopilotResult,
    CaseCopilotService,
    run_case_copilot,
)

app = typer.Typer(help="Summarize enforcement cases with Case Copilot v2.")


def summarize_case(
    case_id: UUID | str,
    *,
    env: str | None = None,
    model: str | None = None,
    repo: CaseContextRepository | None = None,
    ai_client: AIClient | None = None,
    extra_metadata: Mapping[str, Any] | None = None,
) -> CaseCopilotResult:
    return run_case_copilot(
        case_id,
        env=env,
        model=model,
        repository=repo,
        ai_client=ai_client,
        extra_metadata=extra_metadata,
    )


@app.command("summarize")
def summarize_command(
    case_id: UUID = typer.Option(..., "--case-id", help="Enforcement case UUID"),
    env: str | None = typer.Option(
        None, "--env", help="Override Supabase env (dev/prod)."
    ),
    model: str = typer.Option(
        DEFAULT_CASE_COPILOT_MODEL,
        "--model",
        help="Override the OpenAI model (default: gpt-4.1-mini).",
    ),
    output_json: bool = typer.Option(
        False,
        "--json",
        help="Emit the raw JSON response instead of a formatted summary.",
    ),
) -> None:
    result = summarize_case(case_id, env=env, model=model)
    if output_json:
        typer.echo(
            json.dumps(
                {
                    "summary": result.summary,
                    "enforcement_suggestions": [
                        s.to_payload() for s in result.enforcement_suggestions
                    ],
                    "draft_documents": [
                        doc.to_payload() for doc in result.draft_documents
                    ],
                    "risk": result.risk.to_payload(),
                    "timeline_analysis": [
                        ti.to_payload() for ti in result.timeline_analysis
                    ],
                    "contact_strategy": [
                        cs.to_payload() for cs in result.contact_strategy
                    ],
                    "model": result.model,
                },
                indent=2,
            )
        )
        return

    _print_human_summary(result)


def _print_human_summary(result: CaseCopilotResult) -> None:
    typer.echo("[case_copilot] Summary:\n" + result.summary)
    typer.echo(
        f"\nRisk: {result.risk.value}/100 ({result.risk.label})\nDrivers: "
        + ", ".join(result.risk.drivers)
    )

    typer.echo("\nEnforcement suggestions:")
    for suggestion in result.enforcement_suggestions:
        rationale = f" — {suggestion.rationale}" if suggestion.rationale else ""
        next_step = f" [Next: {suggestion.next_step}]" if suggestion.next_step else ""
        typer.echo(f"- {suggestion.title}{rationale}{next_step}")

    typer.echo("\nDraft documents:")
    for plan in result.draft_documents:
        objective = f" ({plan.objective})" if plan.objective else ""
        typer.echo(f"- {plan.title}{objective}")
        if plan.key_points:
            for point in plan.key_points:
                typer.echo(f"    • {point}")

    if result.timeline_analysis:
        typer.echo("\nTimeline insights:")
        for insight in result.timeline_analysis:
            impact = f" impact={insight.impact}" if insight.impact else ""
            urgency = f" urgency={insight.urgency}" if insight.urgency else ""
            typer.echo(f"- {insight.observation}{impact}{urgency}")

    if result.contact_strategy:
        typer.echo("\nContact strategy:")
        for play in result.contact_strategy:
            cadence = f" cadence={play.cadence}" if play.cadence else ""
            notes = f" — {play.notes}" if play.notes else ""
            typer.echo(f"- [{play.channel}] {play.action}{cadence}{notes}")


if __name__ == "__main__":  # pragma: no cover
    app()
