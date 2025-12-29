"""Collector Intelligence Engine for scoring plaintiff collectability signals."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import typer

from src.supabase_client import create_supabase_client
from supabase import Client

logger = logging.getLogger(__name__)
app = typer.Typer(add_completion=False, help="Collector Intelligence scoring utilities")

STATE_CODES = (
    "AL",
    "AK",
    "AZ",
    "AR",
    "CA",
    "CO",
    "CT",
    "DE",
    "FL",
    "GA",
    "HI",
    "ID",
    "IL",
    "IN",
    "IA",
    "KS",
    "KY",
    "LA",
    "ME",
    "MD",
    "MA",
    "MI",
    "MN",
    "MS",
    "MO",
    "MT",
    "NE",
    "NV",
    "NH",
    "NJ",
    "NM",
    "NY",
    "NC",
    "ND",
    "OH",
    "OK",
    "OR",
    "PA",
    "RI",
    "SC",
    "SD",
    "TN",
    "TX",
    "UT",
    "VT",
    "VA",
    "WA",
    "WI",
    "WV",
    "WY",
)
PHONE_DIGITS_RE = re.compile(r"\d")
EMPLOYER_KEYWORDS = ("employer", "payroll", "wage", "garnish")
BANK_KEYWORDS = ("bank", "account", "levy", "lien", "freeze")
SUCCESS_KEYWORDS = ("collected", "paid", "satisfied", "remitted", "settled")
MOMENTUM_KEYWORDS = ("levy", "lien", "turnover", "garnish", "attachment")


@dataclass
class CollectorSignals:
    addresses: Sequence[str]
    phones: Sequence[str]
    employer_indicators: Sequence[str]
    bank_indicators: Sequence[str]
    enforcement_indicators: Sequence[str]


@dataclass
class CollectorScore:
    plaintiff_id: str
    case_id: Optional[str]
    case_number: Optional[str]
    address_quality: float
    phone_validity: float
    employer_signals: float
    bank_signals: float
    enforcement_success: float
    total_score: float

    def as_dict(self) -> Dict[str, Any]:
        return {
            "plaintiff_id": self.plaintiff_id,
            "case_id": self.case_id,
            "case_number": self.case_number,
            "address_quality": round(self.address_quality, 2),
            "phone_validity": round(self.phone_validity, 2),
            "employer_signals": round(self.employer_signals, 2),
            "bank_signals": round(self.bank_signals, 2),
            "enforcement_success": round(self.enforcement_success, 2),
            "collectability_score": round(self.total_score, 2),
        }


class CollectorIntelEngine:
    def __init__(self, client: Optional[Client] = None) -> None:
        self._client = client or create_supabase_client()
        self._logger = logging.getLogger(self.__class__.__name__)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def score_plaintiff(self, plaintiff_id: str) -> CollectorScore:
        context = self._gather_plaintiff_context(plaintiff_id)
        return self._build_score(
            plaintiff_id=plaintiff_id,
            case_id=None,
            case_number=context.get("representative_case_number"),
            signals=context["signals"],
        )

    def score_case(self, case_id: str, plaintiff_id: Optional[str] = None) -> CollectorScore:
        mapping = self._resolve_case_mapping(case_id, plaintiff_id)
        context = self._gather_plaintiff_context(mapping["plaintiff_id"])
        canonical_case_id = mapping.get("canonical_case_id") or mapping["case_id"]
        case_number = mapping.get("case_number") or context.get("representative_case_number")
        return self._build_score(
            plaintiff_id=mapping["plaintiff_id"],
            case_id=canonical_case_id,
            case_number=case_number,
            signals=context["signals"],
        )

    def persist_case_score(self, case_id: str, score: CollectorScore) -> None:
        if not case_id:
            raise ValueError("case_id is required to persist collectability_score")
        payload = {"collectability_score": round(score.total_score, 2)}
        updated = False
        try:
            self._client.table("cases").update(payload).eq("id", case_id).execute()
        except Exception as exc:
            self._logger.debug("public.cases update failed: %s", exc)
        else:
            updated = True

        if updated:
            return

        try:
            (
                self._client.schema("judgments")
                .table("cases")
                .update(payload)
                .eq("case_id", case_id)
                .execute()
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            self._logger.warning("judgments.cases update failed for %s: %s", case_id, exc)
            raise

    # ------------------------------------------------------------------
    # Static scoring helpers (public for tests)
    # ------------------------------------------------------------------
    @staticmethod
    def evaluate_signals(signals: CollectorSignals) -> Dict[str, float]:
        address_score = CollectorIntelEngine._score_address_quality(signals.addresses)
        phone_score = CollectorIntelEngine._score_phone_validity(signals.phones)
        employer_score = CollectorIntelEngine._score_keyword_hits(
            signals.employer_indicators, EMPLOYER_KEYWORDS, base=0.0, step=6.0
        )
        bank_score = CollectorIntelEngine._score_keyword_hits(
            signals.bank_indicators, BANK_KEYWORDS, base=5.0, step=4.0
        )
        enforcement_score = CollectorIntelEngine._score_enforcement_success(
            signals.enforcement_indicators
        )
        total = min(
            100.0,
            address_score + phone_score + employer_score + bank_score + enforcement_score,
        )
        return {
            "address_quality": address_score,
            "phone_validity": phone_score,
            "employer_signals": employer_score,
            "bank_signals": bank_score,
            "enforcement_success": enforcement_score,
            "collectability_score": total,
        }

    # ------------------------------------------------------------------
    # Signal extraction + scoring internals
    # ------------------------------------------------------------------
    def _gather_plaintiff_context(self, plaintiff_id: str) -> Dict[str, Any]:
        plaintiff = self._require_single(
            self._client.table("plaintiffs").select("*").eq("id", plaintiff_id).limit(1).execute(),
            "plaintiffs",
        )

        contacts = self._extract_rows(
            self._client.table("plaintiff_contacts")
            .select("kind,value,phone,email,address,role")
            .eq("plaintiff_id", plaintiff_id)
            .execute()
        )

        addresses, phones = self._extract_contact_channels(plaintiff, contacts)

        judgments = self._extract_rows(
            self._client.table("judgments")
            .select("id,case_number,notes,metadata,plaintiff_id")
            .eq("plaintiff_id", plaintiff_id)
            .execute()
        )
        judgment_ids = [row["id"] for row in judgments if row.get("id")]
        representative_case_number = next(
            (row.get("case_number") for row in judgments if row.get("case_number")),
            None,
        )

        enforcement_cases = []
        if judgment_ids:
            enforcement_cases = self._extract_rows(
                self._client.table("enforcement_cases")
                .select("id,judgment_id,case_number,status,current_stage,metadata")
                .in_("judgment_id", judgment_ids)
                .execute()
            )
            if representative_case_number is None:
                representative_case_number = next(
                    (row.get("case_number") for row in enforcement_cases if row.get("case_number")),
                    None,
                )

        events = []
        case_ids = [row["id"] for row in enforcement_cases if row.get("id")]
        if case_ids:
            events = self._extract_rows(
                self._client.table("enforcement_events")
                .select("case_id,event_type,notes,metadata")
                .in_("case_id", case_ids)
                .execute()
            )

        history = []
        if judgment_ids:
            history = self._extract_rows(
                self._client.table("enforcement_history")
                .select("judgment_id,stage,note,changed_by")
                .in_("judgment_id", judgment_ids)
                .execute()
            )

        employer_indicators: List[str] = []
        bank_indicators: List[str] = []
        enforcement_indicators: List[str] = []

        for row in events:
            employer_indicators.extend(self._collect_fragments(row, ("event_type", "notes")))
            bank_indicators.extend(self._collect_fragments(row, ("event_type", "notes")))
            employer_indicators.extend(self._metadata_strings(row.get("metadata")))
            bank_indicators.extend(self._metadata_strings(row.get("metadata")))

        for row in history:
            enforcement_indicators.extend(self._collect_fragments(row, ("stage", "note")))
            employer_indicators.extend(self._collect_fragments(row, ("stage", "note")))
            bank_indicators.extend(self._collect_fragments(row, ("stage", "note")))

        signals = CollectorSignals(
            addresses=addresses,
            phones=phones,
            employer_indicators=employer_indicators,
            bank_indicators=bank_indicators,
            enforcement_indicators=enforcement_indicators,
        )
        return {
            "signals": signals,
            "representative_case_number": representative_case_number,
        }

    def _resolve_case_mapping(
        self, case_id: str, plaintiff_id: Optional[str]
    ) -> Dict[str, Optional[str]]:
        mapping: Dict[str, Optional[str]] = {
            "case_id": str(case_id),
            "canonical_case_id": None,
            "case_number": None,
            "plaintiff_id": (plaintiff_id.strip() if isinstance(plaintiff_id, str) else None),
        }

        # Public cases table (if synced)
        try:
            row = self._first_row(
                self._client.table("cases")
                .select("id,case_number,plaintiff_id")
                .eq("id", case_id)
                .limit(1)
                .execute()
            )
        except Exception:
            row = None
        if row:
            mapping["canonical_case_id"] = row.get("id")
            mapping["case_number"] = row.get("case_number")
            mapping["plaintiff_id"] = mapping["plaintiff_id"] or row.get("plaintiff_id")
            return mapping

        # Enforcement cases path
        try:
            row = self._first_row(
                self._client.table("enforcement_cases")
                .select("id,judgment_id,case_number")
                .eq("id", case_id)
                .limit(1)
                .execute()
            )
        except Exception:
            row = None
        if row:
            mapping["case_number"] = row.get("case_number")
            judgment_id = row.get("judgment_id")
            if judgment_id and not mapping["plaintiff_id"]:
                mapping["plaintiff_id"] = self._lookup_plaintiff_by_judgment(judgment_id)
            mapping["canonical_case_id"] = self._lookup_case_id_by_number(mapping["case_number"])
            return mapping

        # judgments.cases fallback
        try:
            row = self._first_row(
                self._client.schema("judgments")
                .table("cases")
                .select("case_id,case_number")
                .eq("case_id", case_id)
                .limit(1)
                .execute()
            )
        except Exception:
            row = None
        if row:
            mapping["canonical_case_id"] = row.get("case_id")
            mapping["case_number"] = row.get("case_number")
            if not mapping["plaintiff_id"]:
                mapping["plaintiff_id"] = self._lookup_plaintiff_by_case_number(
                    mapping["case_number"]
                )
            return mapping

        if not mapping["plaintiff_id"]:
            raise ValueError(f"Unable to resolve collectability context for case {case_id}")

        mapping["canonical_case_id"] = mapping.get("canonical_case_id") or mapping["case_id"]
        return mapping

    def _lookup_plaintiff_by_case_number(self, case_number: Optional[str]) -> Optional[str]:
        if not case_number:
            return None
        try:
            row = self._first_row(
                self._client.table("judgments")
                .select("plaintiff_id")
                .eq("case_number", case_number)
                .limit(1)
                .execute()
            )
        except Exception:
            return None
        return row.get("plaintiff_id") if row else None

    def _lookup_plaintiff_by_judgment(self, judgment_id: str) -> Optional[str]:
        try:
            row = self._first_row(
                self._client.table("judgments")
                .select("plaintiff_id,case_number")
                .eq("id", judgment_id)
                .limit(1)
                .execute()
            )
        except Exception:
            return None
        return row.get("plaintiff_id") if row else None

    def _lookup_case_id_by_number(self, case_number: Optional[str]) -> Optional[str]:
        if not case_number:
            return None
        try:
            row = self._first_row(
                self._client.schema("judgments")
                .table("cases")
                .select("case_id")
                .eq("case_number", case_number)
                .limit(1)
                .execute()
            )
        except Exception:
            return None
        return row.get("case_id") if row else None

    def _build_score(
        self,
        *,
        plaintiff_id: str,
        case_id: Optional[str],
        case_number: Optional[str],
        signals: CollectorSignals,
    ) -> CollectorScore:
        breakdown = self.evaluate_signals(signals)
        return CollectorScore(
            plaintiff_id=plaintiff_id,
            case_id=case_id,
            case_number=case_number,
            address_quality=breakdown["address_quality"],
            phone_validity=breakdown["phone_validity"],
            employer_signals=breakdown["employer_signals"],
            bank_signals=breakdown["bank_signals"],
            enforcement_success=breakdown["enforcement_success"],
            total_score=breakdown["collectability_score"],
        )

    # ------------------------------------------------------------------
    # Utility helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _extract_rows(response: Any) -> List[Dict[str, Any]]:
        if response is None:
            return []
        data = getattr(response, "data", None)
        if data is None:
            if isinstance(response, list):
                return list(response)
            if isinstance(response, dict):
                return [response]
            return []
        return list(data)

    def _first_row(self, response: Any) -> Optional[Dict[str, Any]]:
        rows = self._extract_rows(response)
        return rows[0] if rows else None

    def _require_single(self, response: Any, relation: str) -> Dict[str, Any]:
        row = self._first_row(response)
        if not row:
            raise ValueError(f"No rows returned from {relation}")
        return row

    def _extract_contact_channels(
        self, plaintiff: Dict[str, Any], contacts: Sequence[Dict[str, Any]]
    ) -> Tuple[List[str], List[str]]:
        addresses: List[str] = []
        phones: List[str] = []

        if plaintiff.get("phone"):
            phones.append(str(plaintiff["phone"]).strip())

        for contact in contacts:
            kind = str(contact.get("kind") or contact.get("contact_type") or "").lower()
            value = contact.get("value") or contact.get("address") or contact.get("phone")
            if not value:
                continue
            text = str(value).strip()
            if not text:
                continue
            if kind in {"address", "mailing", "hq"}:
                addresses.append(text)
            elif kind in {"phone", "mobile", "office_phone"}:
                phones.append(text)
            elif kind in {"primary_phone", "exec_phone"}:
                phones.append(text)
        return addresses, phones

    @staticmethod
    def _collect_fragments(row: Dict[str, Any], keys: Iterable[str]) -> List[str]:
        fragments: List[str] = []
        for key in keys:
            value = row.get(key)
            if isinstance(value, str) and value.strip():
                fragments.append(value.strip())
        return fragments

    @staticmethod
    def _metadata_strings(value: Any) -> List[str]:
        if value is None:
            return []
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        try:
            return [json.dumps(value, sort_keys=True)]
        except Exception:
            return [str(value)] if value else []

    # ------------------------------------------------------------------
    # Scoring primitives
    # ------------------------------------------------------------------
    @staticmethod
    def _score_address_quality(addresses: Sequence[str]) -> float:
        if not addresses:
            return 0.0
        score = 4.0
        for address in addresses:
            upper = address.upper()
            has_digits = bool(re.search(r"\d", upper))
            has_state = any(f" {state} " in f" {upper} " for state in STATE_CODES)
            if has_digits and has_state:
                score += 8.0
            elif has_digits or has_state:
                score += 4.0
            else:
                score += 2.0
        if len(addresses) >= 3:
            score += 4.0
        return min(20.0, score)

    @staticmethod
    def _score_phone_validity(phones: Sequence[str]) -> float:
        if not phones:
            return 0.0
        normalized = ["".join(PHONE_DIGITS_RE.findall(phone)) for phone in phones]
        valid = sum(1 for digits in normalized if len(digits) >= 10)
        if valid == 0:
            return 5.0
        score = 10.0 + min(10.0, valid * 5.0)
        if any(d.startswith("1") and len(d) >= 11 for d in normalized):
            score += 2.0
        return min(20.0, score)

    @staticmethod
    def _score_keyword_hits(
        messages: Sequence[str], keywords: Sequence[str], *, base: float, step: float
    ) -> float:
        if not messages:
            return base
        hits = 0
        for message in messages:
            text = str(message or "").lower()
            if not text:
                continue
            if any(keyword in text for keyword in keywords):
                hits += 1
        if hits == 0:
            return base
        return min(20.0, base + hits * step)

    @staticmethod
    def _score_enforcement_success(indicators: Sequence[str]) -> float:
        if not indicators:
            return 6.0
        normalized = [str(item or "").lower() for item in indicators if item]
        if any(keyword in text for text in normalized for keyword in SUCCESS_KEYWORDS):
            return 20.0
        if any(keyword in text for text in normalized for keyword in MOMENTUM_KEYWORDS):
            return 12.0
        return 8.0


def _render(score: CollectorScore) -> None:
    typer.echo(json.dumps(score.as_dict(), indent=2, sort_keys=True))


@app.command("plaintiff")
def cli_score_plaintiff(
    plaintiff_id: str = typer.Argument(..., help="Target plaintiff UUID"),
) -> None:
    engine = CollectorIntelEngine()
    try:
        score = engine.score_plaintiff(plaintiff_id)
    except Exception as exc:  # pragma: no cover - CLI convenience
        logger.error("collector_intel plaintiff scoring failed: %s", exc)
        typer.echo(f"Error scoring plaintiff {plaintiff_id}: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    _render(score)


@app.command("case")
def cli_score_case(
    case_id: str = typer.Argument(..., help="Enforcement or judgment case UUID"),
    plaintiff_id: Optional[str] = typer.Option(
        None,
        "--plaintiff-id",
        help="Optional override when the case is not linked yet",
    ),
) -> None:
    engine = CollectorIntelEngine()
    try:
        score = engine.score_case(case_id, plaintiff_id=plaintiff_id)
    except Exception as exc:  # pragma: no cover - CLI convenience
        logger.error("collector_intel case scoring failed: %s", exc)
        typer.echo(f"Error scoring case {case_id}: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    _render(score)


if __name__ == "__main__":  # pragma: no cover - CLI hook
    app()
