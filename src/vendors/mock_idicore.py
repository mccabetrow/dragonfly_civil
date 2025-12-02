"""Mock idiCORE vendor for development and testing.

Returns deterministic but realistic fake enrichment data.
No external HTTP calls are made.
"""

from __future__ import annotations

import hashlib
from typing import Any

from .base import HomeOwnership, IncomeBand, SkipTraceResult, SkipTraceVendor

# Realistic fake data pools
_EMPLOYERS = [
    ("Delta Air Lines", "JFK Terminal 4, Jamaica, NY 11430"),
    ("Mount Sinai Hospital", "1 Gustave L. Levy Pl, New York, NY 10029"),
    ("NYC Department of Education", "52 Chambers St, New York, NY 10007"),
    ("Goldman Sachs", "200 West St, New York, NY 10282"),
    ("Amazon Fulfillment", "55-15 Grand Ave, Maspeth, NY 11378"),
    ("Uber Technologies", "111 8th Ave, New York, NY 10011"),
    ("Target Corporation", "519 Gateway Dr, Brooklyn, NY 11239"),
    ("JPMorgan Chase", "383 Madison Ave, New York, NY 10179"),
    ("Northwell Health", "2000 Marcus Ave, New Hyde Park, NY 11042"),
    ("FedEx Ground", "301 Crossways Park Dr, Woodbury, NY 11797"),
]

_BANKS = [
    ("Chase Bank", "270 Park Ave, New York, NY 10172"),
    ("Bank of America", "225 Liberty St, New York, NY 10281"),
    ("Wells Fargo", "150 E 42nd St, New York, NY 10017"),
    ("Citibank", "388 Greenwich St, New York, NY 10013"),
    ("TD Bank", "1701 Route 70 East, Cherry Hill, NJ 08034"),
    ("Capital One", "1680 Capital One Dr, McLean, VA 22102"),
    ("PNC Bank", "300 5th Ave, Pittsburgh, PA 15222"),
    ("US Bank", "425 Walnut St, Cincinnati, OH 45202"),
]

_INCOME_BANDS: list[IncomeBand] = ["LOW", "MED", "HIGH"]
_HOME_OWNERSHIP: list[HomeOwnership] = ["owner", "renter", "unknown"]


def _deterministic_hash(seed: str) -> int:
    """Generate a deterministic hash from a string seed."""
    return int(hashlib.md5(seed.encode()).hexdigest(), 16)


class MockIdiCORE:
    """Mock idiCORE vendor for development and testing.

    Returns deterministic fake data based on the debtor name and case index.
    This allows consistent test results while simulating realistic enrichment data.

    Usage:
        vendor = MockIdiCORE()
        result = await vendor.enrich("John Smith", "NYC-2024-001234")
    """

    @property
    def provider_name(self) -> str:
        """Return the vendor name for FCRA audit logging."""
        return "mock_idicore"

    @property
    def endpoint(self) -> str:
        """Return the API endpoint for FCRA audit logging."""
        return "/mock/person/search"

    async def enrich(self, debtor_name: str, case_index: str) -> SkipTraceResult:
        """Generate deterministic fake enrichment data.

        Args:
            debtor_name: Name of the debtor to search for.
            case_index: Court case index number for reference.

        Returns:
            SkipTraceResult with fake but realistic enrichment data.
        """
        # Create deterministic seed from inputs
        seed = f"{debtor_name.lower().strip()}:{case_index.lower().strip()}"
        hash_val = _deterministic_hash(seed)

        # Select employer based on hash
        employer_idx = hash_val % len(_EMPLOYERS)
        employer_name, employer_address = _EMPLOYERS[employer_idx]

        # Select bank based on hash (offset to get different selection)
        bank_idx = (hash_val >> 8) % len(_BANKS)
        bank_name, bank_address = _BANKS[bank_idx]

        # Determine income band
        income_idx = (hash_val >> 16) % len(_INCOME_BANDS)
        income_band = _INCOME_BANDS[income_idx]

        # Determine home ownership
        ownership_idx = (hash_val >> 24) % len(_HOME_OWNERSHIP)
        home_ownership = _HOME_OWNERSHIP[ownership_idx]

        # Benefits-only account (rare, ~10% chance)
        has_benefits_only = (hash_val % 10) == 0

        # Confidence score varies from 65-95 based on hash
        confidence_score = 65 + (hash_val % 31)

        # Build raw_meta (no PII, just metadata)
        raw_meta: dict[str, Any] = {
            "mock": True,
            "provider_version": "mock_idicore_v1",
            "query_timestamp": "2025-01-01T00:00:00Z",
            "match_type": "exact" if (hash_val % 3) == 0 else "fuzzy",
            "records_searched": 1,
            "records_matched": 1,
        }

        return SkipTraceResult(
            employer_name=employer_name,
            employer_address=employer_address,
            income_band=income_band,
            bank_name=bank_name,
            bank_address=bank_address,
            home_ownership=home_ownership,
            has_benefits_only_account=has_benefits_only,
            confidence_score=confidence_score,
            raw_meta=raw_meta,
        )


# Verify MockIdiCORE implements SkipTraceVendor protocol
assert isinstance(
    MockIdiCORE(), SkipTraceVendor
), "MockIdiCORE must implement SkipTraceVendor"
