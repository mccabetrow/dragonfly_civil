"""Pydantic models used to construct enrichment payloads."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class Contact(BaseModel):
    """Contact detail produced by enrichment providers."""

    kind: Literal["phone", "email", "address"]
    value: str
    entity_id: UUID
    source: str | None = None
    score: float | None = None
    validated_bool: bool | None = None

    def to_jsonb(self) -> dict[str, object]:
        """Return a JSON-compatible payload for the contacts array."""
        data = self.model_dump(mode="json", exclude_none=True)  # type: ignore[attr-defined]
        data["entity_id"] = str(self.entity_id)
        return data


class Asset(BaseModel):
    """Asset hint gathered during enrichment."""

    asset_type: Literal[
        "real_property",
        "bank_hint",
        "employment",
        "vehicle",
        "license",
        "ucc",
        "dba",
    ]
    entity_id: UUID
    meta_json: dict[str, object] = Field(default_factory=dict)
    source: str | None = None
    confidence: float | None = None

    def to_jsonb(self) -> dict[str, object]:
        """Return a JSON-compatible payload for the assets array."""
        data = self.model_dump(mode="json", exclude_none=True)  # type: ignore[attr-defined]
        data["entity_id"] = str(self.entity_id)
        return data


class EnrichmentBundle(BaseModel):
    """Bundle of contacts and assets for a case enrichment RPC call."""

    case_id: UUID
    contacts: list[Contact] = Field(default_factory=list)
    assets: list[Asset] = Field(default_factory=list)

    def to_jsonb(self) -> dict[str, object]:
        """Return the JSON-serialisable payload expected by upsert_enrichment_bundle."""

        return {
            "case_id": str(self.case_id),
            "contacts": [contact.to_jsonb() for contact in self.contacts],
            "assets": [asset.to_jsonb() for asset in self.assets],
        }
