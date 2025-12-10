"""Vendor-to-canonical plaintiff CSV adapter.

This utility normalises vendor-specific CSV exports into the canonical schema
consumed by ``plaintiff_importer.py``. Each vendor defines a minimal mapping
between their header names and the importer's expected headers so we can
onboard new feeds without touching the importer.
"""

from __future__ import annotations

import argparse
import csv
import logging
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional, Sequence

CANONICAL_HEADERS = (
    "PlaintiffName",
    "FirmName",
    "ContactName",
    "ContactEmail",
    "ContactPhone",
    "TotalJudgmentAmount",
)

logger = logging.getLogger(__name__)


FieldResolver = Callable[[Mapping[str, Any]], Optional[str]]
VendorMapping = Mapping[str, FieldResolver]


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _resolve(*source_keys: str) -> FieldResolver:
    lowered = tuple(key.lower() for key in source_keys if key)

    def resolver(row: Mapping[str, Any]) -> Optional[str]:
        for key in lowered:
            if key in row:
                candidate = _clean(row[key])
                if candidate:
                    return candidate
        return None

    return resolver


VENDOR_MAPPINGS: dict[str, VendorMapping] = {
    "vendor_x": {
        # Placeholder configuration showing how to extend the adapter. Future
        # vendors can copy this pattern and override the field sources.
        "PlaintiffName": _resolve("plaintiffname"),
        "FirmName": _resolve("firmname"),
        "ContactName": _resolve("contactname"),
        "ContactEmail": _resolve("contactemail"),
        "ContactPhone": _resolve("contactphone"),
        "TotalJudgmentAmount": _resolve("judgmentamount"),
    },
}

SUPPORTED_VENDORS: set[str] = {"simplicity", *VENDOR_MAPPINGS}


class UnsupportedVendorError(ValueError):
    """Raised when a vendor key is not registered."""


def _normalise_row(row: Mapping[str, Any]) -> Dict[str, Any]:
    return {(key or "").strip().lower(): row[key] for key in row if key is not None}


def _first_value(row: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        candidate = _clean(row.get(key))
        if candidate:
            return candidate
    return ""


def _map_simplicity_row(row: Mapping[str, Any]) -> Optional[Dict[str, str]]:
    plaintiff_name = _first_value(
        row,
        "plaintiff_name",
        "plaintiff",
        "title",
        "case_title",
        "case_name",
        "case_number",
    )
    if not plaintiff_name:
        return None

    firm_name = _first_value(
        row, "firm_name", "law_firm", "organization", "organisation", "org_name"
    )
    contact_name = _first_value(
        row, "plaintiff_contact", "contact_name", "primary_contact", "contact"
    )
    if not contact_name:
        contact_name = plaintiff_name
    contact_email = _first_value(row, "plaintiff_email", "contact_email", "email")
    contact_phone = _first_value(row, "plaintiff_phone", "contact_phone", "phone")
    amount = _first_value(
        row,
        "judgment_amount",
        "amount_awarded",
        "total_judgment",
        "total_judgment_amount",
        "amount",
    )

    payload: Dict[str, str] = {
        "PlaintiffName": plaintiff_name,
        "FirmName": firm_name,
        "ContactName": contact_name,
        "ContactEmail": contact_email,
        "ContactPhone": contact_phone,
        "TotalJudgmentAmount": amount,
    }

    for header in CANONICAL_HEADERS:
        payload.setdefault(header, "")
    return payload


def map_vendor_row_to_plaintiff(row: Mapping[str, Any], vendor: str) -> Optional[Dict[str, str]]:
    """Transform a vendor CSV row into the canonical plaintiff representation.

    Parameters
    ----------
    row:
        A dictionary produced by ``csv.DictReader`` for the vendor export.
    vendor:
        Registered vendor key (case-insensitive).

    Returns
    -------
    Optional[Dict[str, str]]
        Canonical plaintiff fields or ``None`` when the row cannot be mapped.
    """

    vendor_key = vendor.strip().lower()
    normalised_row = _normalise_row(row)

    if vendor_key == "simplicity":
        return _map_simplicity_row(normalised_row)

    mapping = VENDOR_MAPPINGS.get(vendor_key)
    if mapping is None:
        raise UnsupportedVendorError(f"Unsupported vendor '{vendor}'")

    payload: Dict[str, str] = {}

    for field, resolver in mapping.items():
        value = resolver(normalised_row)
        if value is not None:
            payload[field] = value

    if not payload.get("PlaintiffName") or not payload.get("ContactName"):
        logger.debug("Row missing PlaintiffName or ContactName; skipping")
        return None

    # Ensure optional fields exist even when blank so downstream CSV writers
    # always produce the same column order.
    for header in CANONICAL_HEADERS:
        payload.setdefault(header, "")

    return payload


def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(message)s")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Adapt vendor CSVs into canonical plaintiff schema"
    )
    parser.add_argument("--vendor", required=True, help="Vendor key (e.g. simplicity)")
    parser.add_argument(
        "--csv", dest="csv_path", required=True, help="Path to the vendor CSV export"
    )
    parser.add_argument(
        "--out",
        dest="output_path",
        required=True,
        help="Destination for canonical CSV output",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    return parser


def _run_cli(argv: Optional[Sequence[str]]) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    _configure_logging(args.verbose)

    input_path = Path(args.csv_path)
    output_path = Path(args.output_path)

    if not input_path.exists():
        logger.error("Input CSV not found: %s", input_path)
        return 1

    vendor_key = args.vendor.strip().lower()
    if vendor_key not in SUPPORTED_VENDORS:
        logger.error("Unsupported vendor '%s'", args.vendor)
        return 1

    output_path.parent.mkdir(parents=True, exist_ok=True)

    total = 0
    mapped = 0
    skipped = 0

    try:
        with (
            input_path.open("r", encoding="utf-8-sig", newline="") as source,
            output_path.open("w", encoding="utf-8", newline="") as sink,
        ):
            reader = csv.DictReader(source)
            if reader.fieldnames is None:
                logger.error("CSV file is missing a header row")
                return 1
            writer = csv.DictWriter(sink, fieldnames=CANONICAL_HEADERS)
            writer.writeheader()

            for row in reader:
                total += 1
                result = map_vendor_row_to_plaintiff(row, vendor_key)
                if result is None:
                    skipped += 1
                    continue
                writer.writerow({header: result.get(header, "") for header in CANONICAL_HEADERS})
                mapped += 1
    except Exception as exc:
        logger.error("Adapter run failed: %s", exc)
        logger.debug("Traceback", exc_info=True)
        return 1

    if mapped == 0:
        logger.warning(
            "No valid plaintiff rows mapped for vendor %s (%d input rows)",
            vendor_key,
            total,
        )
        return 1

    logger.info("Converted %d/%d rows to canonical schema; skipped %d", mapped, total, skipped)
    logger.info("Canonical CSV written to %s", output_path)
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    return _run_cli(argv)


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
