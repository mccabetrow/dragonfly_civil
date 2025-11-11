"""Pydantic models for Simplicity case imports."""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from functools import cached_property
from typing import Iterator, Literal
from uuid import UUID, uuid5

from pydantic import BaseModel, Field, ValidationError  # type: ignore[attr-defined]

try:  # pragma: no cover - compatibility shim for pydantic < 2
    from pydantic import ConfigDict, field_validator  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover - fallback to pydantic v1 APIs
    ConfigDict = dict  # type: ignore[misc, assignment]

    from pydantic import validator as _pydantic_validator  # type: ignore

    def field_validator(*fields, **kwargs):  # type: ignore[misc]
        kwargs.pop("mode", None)
        return _pydantic_validator(*fields, **kwargs)

_ENTITY_NAMESPACE = UUID("8bfa69a9-63fd-4d1f-bfd7-98ae1b85b8e9")
_COMPANY_KEYWORDS = {
    "llc",
    "inc",
    "inc.",
    "corp",
    "corp.",
    "corporation",
    "company",
    "co",
    "co.",
    "pllc",
    "pc",
    "ltd",
}

_STATUS_MAP = {
    "open": "new",
    "pending": "contacting",
    "in progress": "contacting",
    "closed": "dead",
    "completed": "collected",
}


def _normalize_whitespace(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = re.sub(r"\s+", " ", value.strip())
    return cleaned or None


class PartyRecord(BaseModel):
    """Party information for a case."""

    model_config = ConfigDict(str_strip_whitespace=True)  # type: ignore[call-arg]

    name: str
    role: Literal["plaintiff", "defendant"]
    address: str | None = None
    phone: str | None = None
    email: str | None = None

    @cached_property
    def normalized_name(self) -> str:
        return re.sub(r"\s+", " ", self.name.strip().lower())

    @cached_property
    def entity_id(self) -> UUID:
        return uuid5(_ENTITY_NAMESPACE, self.normalized_name)

    @cached_property
    def entity_type(self) -> Literal["person", "company"]:
        lowered = self.normalized_name
        if any(keyword in lowered for keyword in _COMPANY_KEYWORDS):
            return "company"
        if lowered.isupper() and " " not in lowered:
            return "company"
        return "company" if lowered.endswith(" inc") else "person"

    def entity_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "entity_id": str(self.entity_id),
            "name_raw": self.name,
            "type": self.entity_type,
        }
        return payload

    def role_payload(self, case_id: UUID) -> dict[str, object]:
        return {
            "case_id": str(case_id),
            "entity_id": str(self.entity_id),
            "role": self.role,
        }


class CaseRecord(BaseModel):
    """Single case row parsed from Simplicity exports."""

    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=True)  # type: ignore[call-arg]

    lead_id: str = Field(alias="LeadID")
    court: str = Field(alias="Court")
    index_number: str = Field(alias="IndexNumber")
    case_type: str | None = Field(default=None, alias="CaseType")
    judgment_date: date | None = Field(default=None, alias="JudgmentDate")
    judgment_amount: Decimal | None = Field(default=None, alias="JudgmentAmount")
    status_raw: str | None = Field(default=None, alias="Status")
    county: str = Field(alias="County")
    state: str = Field(alias="State")
    plaintiff_name: str | None = Field(default=None, alias="PlaintiffName")
    plaintiff_address: str | None = Field(default=None, alias="PlaintiffAddress")
    defendant_name: str | None = Field(default=None, alias="DefendantName")
    defendant_address: str | None = Field(default=None, alias="DefendantAddress")
    phone: str | None = Field(default=None, alias="Phone")
    email: str | None = Field(default=None, alias="Email")

    @field_validator("judgment_date", mode="before")
    @classmethod
    def _parse_date(cls, value: object) -> object:
        if value in (None, ""):
            return None
        if isinstance(value, date):
            return value
        for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
            try:
                return datetime.strptime(str(value), fmt).date()
            except ValueError:
                continue
        raise ValueError(f"Unsupported date format: {value}")

    @field_validator("judgment_amount", mode="before")
    @classmethod
    def _parse_amount(cls, value: object) -> object:
        if value in (None, ""):
            return None
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value))

    @field_validator(
        "plaintiff_address",
        "defendant_address",
        "plaintiff_name",
        "defendant_name",
        "phone",
        "email",
        mode="before",
    )
    @classmethod
    def _clean_string(cls, value: object) -> object:
        if value in (None, ""):
            return None
        return _normalize_whitespace(str(value))

    @property
    def mapped_status(self) -> str:
        if not self.status_raw:
            return "new"
        return _STATUS_MAP.get(self.status_raw.strip().lower(), "new")

    def case_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "index_no": self.index_number,
            "court": self.court,
            "county": self.county,
            "status": self.mapped_status,
            "principal_amt": float(self.judgment_amount or Decimal("0")),
            "source": "simplicity",
            "fingerprint_hash": self.lead_id,
        }
        if self.judgment_date:
            payload["judgment_at"] = self.judgment_date.isoformat()
        return payload

    def parties(self) -> Iterator[PartyRecord]:
        if self.plaintiff_name:
            yield PartyRecord(
                name=self.plaintiff_name,
                role="plaintiff",
                address=self.plaintiff_address,
                phone=self.phone,
                email=self.email,
            )
        if self.defendant_name:
            yield PartyRecord(
                name=self.defendant_name,
                role="defendant",
                address=self.defendant_address,
                phone=self.phone,
                email=self.email,
            )


def parse_rows(rows: Iterator[dict[str, str]]) -> tuple[list[CaseRecord], list[str]]:
    """Validate raw CSV rows into case records, collecting error messages."""

    records: list[CaseRecord] = []
    errors: list[str] = []
    for idx, row in enumerate(rows, start=1):
        try:
            validator = getattr(CaseRecord, "model_validate", None)
            if validator is not None:
                records.append(validator(row))  # type: ignore[misc]
            else:  # pragma: no cover - pydantic v1 fallback
                records.append(CaseRecord.parse_obj(row))  # type: ignore[attr-defined]
        except ValidationError as exc:  # pragma: no cover - validation path
            errors.append(f"Row {idx}: {exc}")
    return records, errors
