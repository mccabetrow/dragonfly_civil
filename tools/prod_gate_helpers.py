"""Utility helpers for tools/prod_gate.ps1 formatting.

Provides:
- mask_secret: consistent masking for DSNs/keys
- format_banner: standardized PASS/FAIL banner output

The PowerShell script shells out to this module to avoid duplicating
string-formatting logic, and the same functions are covered via pytest.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Iterable

_PLACEHOLDER = "<unset>"


def mask_secret(value: str | None) -> str:
    """Mask sensitive values, keeping only the outer 4 characters.

    Rules:
    - None/empty => <unset>
    - <= 8 characters => fully masked
    - Otherwise keep first 4 + last 4 characters
    """

    if value is None:
        return _PLACEHOLDER
    trimmed = value.strip()
    if not trimmed:
        return _PLACEHOLDER
    if len(trimmed) <= 8:
        return "*" * len(trimmed)
    middle = "*" * (len(trimmed) - 8)
    return f"{trimmed[:4]}{middle}{trimmed[-4:]}"


@dataclass(slots=True)
class Banner:
    status: str
    reasons: tuple[str, ...]

    def render(self) -> str:
        line = "=" * 60
        header = "PROD GATE :: PASS" if self.status == "pass" else "PROD GATE :: FAIL"
        body_lines: list[str]
        if self.reasons:
            body_lines = [f"[{idx}] {text}" for idx, text in enumerate(self.reasons, start=1)]
        else:
            body_lines = ["All gates passed."]
        return "\n".join([line, header, *body_lines, line])


def format_banner(status: str, reasons: Iterable[str] | None = None) -> str:
    normalized = status.lower()
    if normalized not in {"pass", "fail"}:
        raise ValueError(f"Invalid status: {status}")
    filtered = tuple(reason.strip() for reason in (reasons or ()) if reason and reason.strip())
    return Banner(status=normalized, reasons=filtered).render()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prod gate helper CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    mask_parser = sub.add_parser("mask", help="Mask a sensitive value")
    mask_parser.add_argument("--value", default="", help="Value to be masked")

    banner_parser = sub.add_parser("banner", help="Render PASS/FAIL banner")
    banner_parser.add_argument("--status", required=True, choices=("pass", "fail"))
    banner_parser.add_argument(
        "--reason",
        action="append",
        default=[],
        help="Failure reasons to display (can repeat)",
    )
    return parser


def _main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "mask":
        print(mask_secret(args.value))
        return 0

    if args.command == "banner":
        print(format_banner(args.status, args.reason))
        return 0

    parser.error(f"Unsupported command: {args.command}")
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
