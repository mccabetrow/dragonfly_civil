"""Base classes and protocols for skip-trace vendors.

Defines the SkipTraceResult dataclass and SkipTraceVendor protocol
that all vendor implementations must follow.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

IncomeBand = Literal["LOW", "MED", "HIGH", "UNKNOWN"]
HomeOwnership = Literal["owner", "renter", "unknown"]


@dataclass(frozen=True)
class SkipTraceResult:
    """Result of a skip-trace enrichment query.

    Contains employment, banking, and asset intelligence about a debtor.
    The raw_meta field stores provider-specific metadata (never raw PII).

    Attributes:
        employer_name: Name of the debtor's employer, if found.
        employer_address: Address of the employer, if found.
        income_band: Estimated income range (LOW, MED, HIGH, UNKNOWN).
        bank_name: Name of the debtor's bank, if found.
        bank_address: Address of the bank, if found.
        home_ownership: Whether debtor owns/rents home.
        has_benefits_only_account: True if bank account may be exempt under CPLR 5222(d).
        confidence_score: Data quality score 0-100; higher = more reliable.
        raw_meta: Provider-specific metadata (redacted, no raw PII).
    """

    employer_name: str | None = None
    employer_address: str | None = None
    income_band: IncomeBand = "UNKNOWN"
    bank_name: str | None = None
    bank_address: str | None = None
    home_ownership: HomeOwnership = "unknown"
    has_benefits_only_account: bool = False
    confidence_score: int = 0
    raw_meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for database insertion."""
        return {
            "employer_name": self.employer_name,
            "employer_address": self.employer_address,
            "income_band": self.income_band,
            "bank_name": self.bank_name,
            "bank_address": self.bank_address,
            "home_ownership": self.home_ownership,
            "has_benefits_only_account": self.has_benefits_only_account,
            "confidence_score": self.confidence_score,
        }


@runtime_checkable
class SkipTraceVendor(Protocol):
    """Protocol for skip-trace vendor implementations.

    All vendor clients must implement this interface to be usable
    by the enrichment worker.

    Example:
        class MyVendor(SkipTraceVendor):
            async def enrich(self, debtor_name: str, case_index: str) -> SkipTraceResult:
                # Call external API and return result
                ...
    """

    @property
    def provider_name(self) -> str:
        """Return the vendor/provider name for FCRA audit logging."""
        ...

    @property
    def endpoint(self) -> str:
        """Return the API endpoint name for FCRA audit logging."""
        ...

    async def enrich(self, debtor_name: str, case_index: str) -> SkipTraceResult:
        """Perform skip-trace enrichment for a debtor.

        Args:
            debtor_name: Name of the debtor to search for.
            case_index: Court case index number for reference.

        Returns:
            SkipTraceResult with enrichment data.

        Raises:
            Exception: If the enrichment call fails.
        """
        ...
